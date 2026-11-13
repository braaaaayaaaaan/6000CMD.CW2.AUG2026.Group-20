from django.db import transaction
from django.core.exceptions import SuspiciousFileOperation
from django.db.models import Count, F, Max, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404
from rest_framework import filters, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import NotFound
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from django_filters.rest_framework import DjangoFilterBackend
from types import SimpleNamespace

from .files import AssetMultiPartParser, staged_file
from .media import MISSING_FILE_MESSAGE, signed_media_url
from .models import Asset, AssetSeries, Tags
from .permissions import AssetPermission
from .serializers import AssetSerializer, TagSerializer
from user.security import event


class StableOrderingFilter(filters.OrderingFilter):
    def get_ordering(self, request, queryset, view):
        ordering = list(
            super().get_ordering(request, queryset, view) or queryset.query.order_by
        )
        if not any(field.lstrip("-") == "id" for field in ordering):
            ordering.append("id")
        return ordering


def can_manage_uploads(request):
    # Reuse the existing write permission without changing role/authentication rules.
    return AssetPermission().has_permission(
        SimpleNamespace(user=request.user, method="POST"), None
    )


def visible_assets(request):
    queryset = Asset.objects.all()
    if not can_manage_uploads(request):
        queryset = Asset.published()
    return queryset


def latest_assets(queryset=None):
    if queryset is None:
        queryset = Asset.published()
    latest = queryset.filter(code=OuterRef("code")).order_by("-version_no")
    return queryset.annotate(
        latest_version_no=Subquery(latest.values("version_no")[:1])
    ).filter(version_no=F("latest_version_no"))


class AssetViewSet(viewsets.ModelViewSet):
    queryset = Asset.objects.all()
    serializer_class = AssetSerializer
    parser_classes = [JSONParser, AssetMultiPartParser]
    permission_classes = [AssetPermission]
    filter_backends = [StableOrderingFilter, filters.SearchFilter, DjangoFilterBackend]
    ordering_fields = ["name", "upload_datetime"]
    filterset_fields = ["tags"]
    search_fields = ["name", "description", "file_type"]

    def get_queryset(self):
        if self.action == "list":
            queryset = latest_assets(
                (
                    visible_assets(self.request)
                    if self.request.query_params.get("uploads") == "1"
                    else None
                ),
            )
        else:
            queryset = visible_assets(self.request)
        return queryset.prefetch_related("tags").order_by("-upload_datetime", "id")

    def get_throttles(self):
        throttles = super().get_throttles()
        if self.action in {"create", "update", "partial_update"}:
            self.throttle_scope = "uploads"
            throttles.append(ScopedRateThrottle())
        return throttles

    def perform_create(self, serializer):
        code = serializer.validated_data.get("code")
        with staged_file(serializer), transaction.atomic():
            if code:
                get_object_or_404(AssetSeries.objects.select_for_update(), code=code)
                number = Asset.objects.filter(code=code).aggregate(
                    number=Max("version_no")
                )["number"]
                if number is None:
                    raise NotFound("This asset no longer exists.")
            else:
                from .models import UniqueCodeGenerator

                code = UniqueCodeGenerator.generate_code(prefix="A")
                AssetSeries.objects.create(code=code)
                number = 0
            asset = serializer.save(
                code=code,
                version_no=number + 1,
                uploaded_by=self.request.user.get_username(),
            )
            event("asset_uploaded", self.request.user, target=asset,
                  metadata={"version_no": asset.version_no})

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(
            instance, data=request.data, partial=kwargs.pop("partial", False)
        )
        serializer.is_valid(raise_exception=True)
        with staged_file(serializer), transaction.atomic():
            get_object_or_404(
                AssetSeries.objects.select_for_update(), code=instance.code
            )
            serializer.instance = get_object_or_404(
                self.get_queryset().select_for_update(), pk=instance.pk
            )
            if "url" in serializer.validated_data:
                # A file update creates a new immutable version, including PUT/PATCH.
                previous = serializer.instance
                number = Asset.objects.filter(code=previous.code).aggregate(
                    number=Max("version_no")
                )["number"]
                tags = list(serializer.validated_data.pop("tags", previous.tags.all()))
                values = {
                    "name": previous.name,
                    "description": previous.description,
                    **serializer.validated_data,
                }
                replacement = Asset.objects.create(
                    **values,
                    code=previous.code,
                    version_no=number + 1,
                    uploaded_by=request.user.get_username(),
                )
                replacement.tags.set(tags)
                serializer.instance = replacement
            else:
                serializer.save()
            event("asset_replaced" if "url" in serializer.validated_data else "asset_updated",
                  request.user, target=serializer.instance,
                  metadata={"version_no": serializer.instance.version_no})
        return Response(serializer.data)

    def perform_destroy(self, instance):
        with transaction.atomic():
            get_object_or_404(
                AssetSeries.objects.select_for_update(), code=instance.code
            )
            event("asset_deleted", self.request.user, target=instance)
            get_object_or_404(Asset, pk=instance.pk).delete()

    @action(detail=True, methods=["get"], url_path="media-url")
    def media_url(self, request, pk=None):
        asset = self.get_object()
        if not asset.is_published:
            raise NotFound("This file is not approved for previews or downloads.")
        try:
            exists = asset.url and asset.url.storage.exists(asset.url.name)
        except (OSError, ValueError, SuspiciousFileOperation):
            exists = False
        if not exists:
            raise NotFound(MISSING_FILE_MESSAGE)
        return Response(signed_media_url(asset, request))


class TagViewSet(viewsets.ModelViewSet):
    queryset = Tags.objects.order_by("title", "id")
    serializer_class = TagSerializer
    permission_classes = [AssetPermission]
    filter_backends = [StableOrderingFilter]
    ordering_fields = ["title"]

    def perform_create(self, serializer):
        with transaction.atomic():
            event("tag_created", self.request.user, target=serializer.save())

    def perform_update(self, serializer):
        with transaction.atomic():
            event("tag_updated", self.request.user, target=serializer.save())

    def perform_destroy(self, instance):
        with transaction.atomic():
            event("tag_deleted", self.request.user, target=instance)
            instance.delete()


@api_view(["GET"])
def asset_usage_count(request):
    current_ids = latest_assets().values("pk")
    data = (
        Tags.objects.annotate(
            usage_count=Count(
                "assets", filter=Q(assets__pk__in=Subquery(current_ids)), distinct=True
            )
        )
        .values("id", "title", "usage_count")
        .order_by("title", "id")
    )
    return Response(data)


@api_view(["PATCH"])
@permission_classes([AssetPermission])
def clear_all_tags(request, asset_id):
    asset = get_object_or_404(Asset, pk=asset_id)
    with transaction.atomic():
        get_object_or_404(AssetSeries.objects.select_for_update(), code=asset.code)
        asset = get_object_or_404(Asset, pk=asset_id)
        asset.tags.clear()
        event("asset_updated", request.user, target=asset)
    return Response([])


@api_view(["GET"])
def get_new_version_no(request, asset_code):
    number = Asset.objects.filter(code=asset_code).aggregate(number=Max("version_no"))[
        "number"
    ]
    if number is None:
        raise NotFound("Asset not found.")
    return Response(number + 1)


@api_view(["GET"])
def get_all_file_versions(request, asset_code):
    versions = visible_assets(request).filter(code=asset_code)
    if not versions.exists():
        raise NotFound("Asset not found.")
    versions = versions.prefetch_related("tags").order_by("-version_no", "id")
    return Response(
        AssetSerializer(versions, many=True, context={"request": request}).data
    )


@api_view(["DELETE"])
@permission_classes([AssetPermission])
def delete_asset_by_code(request, asset_code):
    with transaction.atomic():
        series = get_object_or_404(
            AssetSeries.objects.select_for_update(), code=asset_code
        )
        assets = Asset.objects.filter(code=asset_code)
        count = assets.count()
        if not count:
            raise NotFound("Asset not found.")
        assets.delete()
        series.delete()
        event("asset_deleted", request.user, resource_id=asset_code, metadata={"version_count": count})
    return Response({"detail": "Deleted %s asset version(s)." % count})
