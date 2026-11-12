from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class AccountAdmin(UserAdmin):
    readonly_fields = (*UserAdmin.readonly_fields, "token_version", "email_verified")
    fieldsets = (*UserAdmin.fieldsets, ("Account security", {"fields": ("email_verified", "token_version")}))
    # Secret fields are never included in admin forms or list displays.

# Register your models here.
