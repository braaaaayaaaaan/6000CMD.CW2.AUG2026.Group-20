from django.contrib import admin
from django.contrib.auth.admin import UserAdmin, GroupAdmin
from django.contrib.auth.models import Group

from .models import User
from .audit_signals import AuditAdminMixin


@admin.register(User)
class AccountAdmin(AuditAdminMixin, UserAdmin):
    readonly_fields = (*UserAdmin.readonly_fields, "token_version", "email_verified")
    fieldsets = (*UserAdmin.fieldsets, ("Account security", {"fields": ("email_verified", "token_version")}))
    # Secret fields are never included in admin forms or list displays.

# Register your models here.

admin.site.unregister(Group)


@admin.register(Group)
class AuditedGroupAdmin(AuditAdminMixin, GroupAdmin):
    pass
