from django.contrib.auth.models import AbstractUser
from django.db import models


class Department(models.Model):
    """A revenue-collecting department of the local government."""

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=150, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class User(AbstractUser):
    """Staff account. The role decides what the person may see and do."""

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "System administrator"
        MANAGER = "MANAGER", "Revenue manager"
        SUPERVISOR = "SUPERVISOR", "Supervisor"
        COLLECTOR = "COLLECTOR", "Tax collector"
        AUDITOR = "AUDITOR", "Auditor (read-only)"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.COLLECTOR)
    employee_id = models.CharField(
        "Tax collector / employee ID", max_length=30, unique=True, null=True, blank=True
    )
    phone = models.CharField(max_length=30, blank=True)
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, null=True, blank=True, related_name="staff"
    )
    assigned_district = models.ForeignKey(
        "locations.District", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="staff",
    )

    def __str__(self):
        name = self.get_full_name() or self.username
        return f"{name} ({self.employee_id})" if self.employee_id else name

    # Role helpers used by views, the API and templates.
    @property
    def is_collector(self):
        return self.role == self.Role.COLLECTOR

    @property
    def is_supervisor(self):
        return self.role == self.Role.SUPERVISOR

    @property
    def sees_everything(self):
        return self.is_superuser or self.role in (
            self.Role.ADMIN, self.Role.MANAGER, self.Role.AUDITOR
        )

    @property
    def can_collect(self):
        return self.role in (self.Role.COLLECTOR, self.Role.SUPERVISOR)

    @property
    def can_void(self):
        return self.is_superuser or self.role in (
            self.Role.SUPERVISOR, self.Role.MANAGER, self.Role.ADMIN
        )

    @property
    def can_view_reports(self):
        return self.sees_everything or self.is_supervisor

    @property
    def can_give_unlimited_discount(self):
        return self.is_superuser or self.role in (
            self.Role.SUPERVISOR, self.Role.MANAGER, self.Role.ADMIN
        )
