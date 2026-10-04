from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Department, User


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "is_active"]
    search_fields = ["code", "name"]


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ["username", "employee_id", "first_name", "last_name", "role", "department",
                    "assigned_district", "is_active"]
    list_filter = ["role", "department", "is_active"]
    search_fields = ["username", "employee_id", "first_name", "last_name", "phone"]
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Tax system", {"fields": ("role", "employee_id", "phone", "department",
                                   "assigned_district")}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("Tax system", {"fields": ("first_name", "last_name", "role", "employee_id", "phone",
                                   "department", "assigned_district")}),
    )
