from django.contrib import admin
from django.db import transaction
from django.utils.html import format_html

from .media import signed_media_url
from .models import Asset, AssetSeries, Tags
from user.audit_signals import AuditAdminMixin


@admin.register(Asset)
class AssetAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("name", "code", "version_no", "uploaded_by", "upload_datetime")
    search_fields = ("name", "code", "description")
    list_filter = ("file_type",)
    filter_horizontal = ("tags",)
    readonly_fields = ("id", "code", "version_no", "uploaded_by", "upload_datetime", "file_type", "file_size", "asset_file")
    exclude = ("url",)

    def has_add_permission(self, request):
        return False

    def get_object(self, request, object_id, from_field=None):
        obj = super().get_object(request, object_id, from_field)
        if obj and request.method == "POST":
            # Django wraps change/delete POSTs in an atomic transaction.
            AssetSeries.objects.select_for_update().filter(code=obj.code).first()
            obj = super().get_object(request, object_id, from_field)
        if obj:
            obj.media_request = request
        return obj

    @admin.display(description="File")
    def asset_file(self, obj):
        url = signed_media_url(obj, obj.media_request)["url"]
        return format_html('<a href="{}&download=1">Download file</a>', url)

    @transaction.atomic
    def delete_queryset(self, request, queryset):
        list(AssetSeries.objects.select_for_update().filter(
            code__in=queryset.values("code"),
        ).order_by("code"))
        queryset.delete()


@admin.register(Tags)
class TagAdmin(AuditAdminMixin, admin.ModelAdmin):
    search_fields = ("title",)
