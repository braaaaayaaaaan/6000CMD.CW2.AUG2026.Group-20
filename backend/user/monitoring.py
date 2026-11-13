"""Administrator-only monitoring APIs using existing authentication and paging."""
from datetime import timedelta, timezone as dt_timezone

import django_filters
from django.db import transaction
from django.db.models import Count, Q
from django.db.models.functions import TruncDay, TruncHour
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from rest_framework import filters, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend

from .auditing import EVENTS, RULES, record_event
from .models import AuditEvent, SecurityAlert
from .permissions import IsApplicationAdmin


class AuditSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="actor.username", default="")

    class Meta:
        model = AuditEvent
        fields = ["id", "actor", "actor_reference", "username", "account_identifier", "event_type", "category", "resource_type",
                  "resource_id", "timestamp", "ip_address", "user_agent", "outcome", "severity", "metadata"]
        read_only_fields = fields


class AlertSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="affected_user.username", default="")
    resolved_by_username = serializers.CharField(source="resolved_by.username", default="")

    class Meta:
        model = SecurityAlert
        fields = ["id", "alert_type", "affected_user", "username", "account_identifier", "severity", "description",
                  "event_count", "window_seconds", "window_started_at", "first_detected_at", "last_detected_at",
                  "status", "resolved_at", "resolved_by", "resolved_by_username", "metadata"]
        read_only_fields = fields


class AuditFilter(django_filters.FilterSet):
    user = django_filters.UUIDFilter(field_name="actor_id")
    start = django_filters.IsoDateTimeFilter(field_name="timestamp", lookup_expr="gte")
    end = django_filters.IsoDateTimeFilter(field_name="timestamp", lookup_expr="lte")
    resource = django_filters.CharFilter(field_name="resource_id", lookup_expr="icontains")

    class Meta:
        model = AuditEvent
        fields = ["event_type", "category", "outcome", "severity", "resource_type"]


class AlertFilter(django_filters.FilterSet):
    user = django_filters.UUIDFilter(field_name="affected_user_id")
    start = django_filters.IsoDateTimeFilter(field_name="last_detected_at", lookup_expr="gte")
    end = django_filters.IsoDateTimeFilter(field_name="last_detected_at", lookup_expr="lte")

    class Meta:
        model = SecurityAlert
        fields = ["severity", "alert_type", "status"]


class AuditEventPagination(PageNumberPagination):
    page_size = 40
    page_size_query_param = "page_size"
    max_page_size = 100


@method_decorator(never_cache, name="dispatch")
class AuditEventViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditEvent.objects.select_related("actor").all()
    serializer_class = AuditSerializer
    pagination_class = AuditEventPagination
    permission_classes = [IsApplicationAdmin]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_class = AuditFilter
    search_fields = ["actor__username", "account_identifier", "resource_id", "event_type"]


@method_decorator(never_cache, name="dispatch")
class SecurityAlertViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SecurityAlert.objects.select_related("affected_user", "resolved_by").all()
    serializer_class = AlertSerializer
    permission_classes = [IsApplicationAdmin]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_class = AlertFilter
    search_fields = ["affected_user__username", "account_identifier"]

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        with transaction.atomic():
            alert = self.get_object()
            alert = SecurityAlert.objects.select_for_update().get(pk=alert.pk)
            if alert.status == "open":
                alert.status = "resolved"
                alert.resolved_at = timezone.now()
                alert.resolved_by = request.user
                alert.save(update_fields=["status", "resolved_at", "resolved_by"])
                record_event("alert_resolved", request.user, target=alert, request=request)
        return Response(self.get_serializer(alert).data)


@method_decorator(never_cache, name="dispatch")
class SecurityOverview(APIView):
    permission_classes = [IsApplicationAdmin]

    def get(self, request):
        hours = serializers.ChoiceField(choices=["24", "168", "720"]).run_validation(request.query_params.get("hours", "24"))
        end = timezone.now()
        start = end - timedelta(hours=int(hours))
        events = AuditEvent.objects.filter(timestamp__gte=start, timestamp__lte=end)
        counts = events.aggregate(
            failed_logins=Count("id", filter=Q(event_type="login_failed")),
            access_denials=Count("id", filter=Q(event_type="access_denied")),
            asset_downloads=Count("id", filter=Q(event_type="asset_downloaded", outcome="success")),
        )
        counts["open_alerts"] = SecurityAlert.objects.filter(status="open").count()
        trunc = TruncHour if hours == "24" else TruncDay
        activity = events.filter(event_type__in=RULES).annotate(
            period=trunc("timestamp", tzinfo=dt_timezone.utc),
        ).values("period", "event_type").annotate(count=Count("id")).order_by("period", "event_type")
        return Response({"start": start, "end": end, "hours": int(hours), "counts": counts, "activity": list(activity),
                         "event_types": list(EVENTS), "alert_types": [rule["type"] for rule in RULES.values()],
                         "rules": [{"event_type": event_type, **rule} for event_type, rule in RULES.items()]})
