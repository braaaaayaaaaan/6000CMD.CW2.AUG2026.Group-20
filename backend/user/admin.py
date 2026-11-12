from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class AccountAdmin(UserAdmin):
    readonly_fields = (*UserAdmin.readonly_fields, "token_version")

# Register your models here.
