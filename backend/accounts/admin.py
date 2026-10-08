from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "get_full_name", "role", "phone", "is_active")
    list_filter = ("role", "is_active")
    fieldsets = BaseUserAdmin.fieldsets + (("SHG system", {"fields": ("role", "phone")}),)
    add_fieldsets = BaseUserAdmin.add_fieldsets + (("SHG system", {"fields": ("role", "phone")}),)

from django.contrib.auth.models import Group

# This system uses roles (ADMIN / LEADER / VIEWER), not Django permission groups.
admin.site.unregister(Group)
