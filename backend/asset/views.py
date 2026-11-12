from django.db import transaction
from django.db.models import Count, F, Max, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404
from rest_framework import filters, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import NotFound
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from django_filters.rest_framework import DjangoFilterBackend

from .files import AssetMultiPartParser, staged_file
from .media import MISSING_FILE_MESSAGE, signed_media_url
from .models import Asset, AssetSeries, Tags
from .permissions import AssetPermission
from .serializers import AssetSerializer, TagSerializer


class StableOrderingFilter(filters.OrderingFilter):
    def get_ordering(self, request, queryset, view):
        ordering = list(super().get_ordering(request, queryset, view) or queryset.query.order_by)
        if not any(field.lstrip("-") == "id" for field in ordering):
            ordering.append("id")
        return ordering


def latest_assets():
    latest = Asset.objects.filter(code=OuterRef("code")).order_by("-version_no")
    return Asset.objects.annotate(
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
        queryset = latest_assets() if self.action == "list" else Asset.objects.all()
        return queryset.prefetch_related("tags").order_by("-upload_datetime", "id")

    def get_throttles(self):
        throttles = super().get_throttles()
        if self.action == "create":
            self.throttle_scope = "uploads"
            throttles.append(ScopedRateThrottle())
        return throttles

    def perform_create(self, serializer):
        code = serializer.validated_data.get("code")
        with staged_file(serializer), transaction.atomic():
            if code:
                get_object_or_404(AssetSeries.objects.select_for_update(), code=code)
                number = Asset.objects.filter(code=code).aggregate(number=Max("version_no"))["number"]
                if number is None:
                    raise NotFound("This asset no longer exists.")
            else:
                from .models import UniqueCodeGenerator
                code = UniqueCodeGenerator.generate_code(prefix="A")
                AssetSeries.objects.create(code=code)
                number = 0
            serializer.save(code=code, version_no=number + 1, uploaded_by=self.request.user.get_username())

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=kwargs.pop("partial", False))
        serializer.is_valid(raise_exception=True)
        with staged_file(serializer), transaction.atomic():
            get_object_or_404(AssetSeries.objects.select_for_update(), code=instance.code)
            serializer.instance = get_object_or_404(self.get_queryset().select_for_update(), pk=instance.pk)
            serializer.save()
        return Response(serializer.data)

    def perform_destroy(self, instance):
        with transaction.atomic():
            get_object_or_404(AssetSeries.objects.select_for_update(), code=instance.code)
            get_object_or_404(Asset, pk=instance.pk).delete()

    @action(detail=True, methods=["get"], url_path="media-url")
    def media_url(self, request, pk=None):
        asset = self.get_object()
        if not asset.url or not asset.url.storage.exists(asset.url.name):
            raise NotFound(MISSING_FILE_MESSAGE)
        return Response(signed_media_url(asset, request))


class TagViewSet(viewsets.ModelViewSet):
    queryset = Tags.objects.order_by("title", "id")
    serializer_class = TagSerializer
    permission_classes = [AssetPermission]
    filter_backends = [StableOrderingFilter]
    ordering_fields = ["title"]


@api_view(["GET"])
def asset_usage_count(request):
    current_ids = latest_assets().values("pk")
    data = Tags.objects.annotate(
        usage_count=Count("assets", filter=Q(assets__pk__in=Subquery(current_ids)), distinct=True)
    ).values("id", "title", "usage_count").order_by("title", "id")
    return Response(data)


@api_view(["PATCH"])
@permission_classes([AssetPermission])
def clear_all_tags(request, asset_id):
    asset = get_object_or_404(Asset, pk=asset_id)
    with transaction.atomic():
        get_object_or_404(AssetSeries.objects.select_for_update(), code=asset.code)
        asset = get_object_or_404(Asset, pk=asset_id)
        asset.tags.clear()
    return Response([])


@api_view(["GET"])
def get_new_version_no(request, asset_code):
    number = Asset.objects.filter(code=asset_code).aggregate(number=Max("version_no"))["number"]
    if number is None:
        raise NotFound("Asset not found.")
    return Response(number + 1)


@api_view(["GET"])
def get_all_file_versions(request, asset_code):
    if not Asset.objects.filter(code=asset_code).exists():
        raise NotFound("Asset not found.")
    versions = Asset.objects.filter(code=asset_code).prefetch_related("tags").order_by("-version_no", "id")
    return Response(AssetSerializer(versions, many=True, context={"request": request}).data)


@api_view(["DELETE"])
@permission_classes([AssetPermission])
def delete_asset_by_code(request, asset_code):
    with transaction.atomic():
        series = get_object_or_404(AssetSeries.objects.select_for_update(), code=asset_code)
        assets = Asset.objects.filter(code=asset_code)
        count = assets.count()
        if not count:
            raise NotFound("Asset not found.")
        assets.delete()
        series.delete()
    return Response({"detail": "Deleted %s asset version(s)." % count})
