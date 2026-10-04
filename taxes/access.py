"""Row-level access rules shared by the web pages and the API."""

from datetime import timedelta
from functools import wraps

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from .models import TaxCollection, Taxpayer


def today_range():
    """Start and end of today in local (Hargeisa) time."""
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def scoped_collections(user):
    """Collections the user is allowed to see."""
    qs = TaxCollection.objects.select_related(
        "collector", "department", "tax_type", "taxpayer",
        "village__district__city__region__country",
    )
    if user.sees_everything:
        return qs
    if user.is_supervisor and user.department_id:
        return qs.filter(department_id=user.department_id)
    # Collectors only see what they themselves did today.
    start, end = today_range()
    return qs.filter(collector=user, collected_at__gte=start, collected_at__lt=end)


def scoped_team(user):
    """Collectors whose performance the user may see."""
    User = get_user_model()
    qs = User.objects.filter(
        role__in=[User.Role.COLLECTOR, User.Role.SUPERVISOR], is_active=True
    ).select_related("department", "assigned_district")
    if user.can_view_tracker:  # executive director and admin: everyone
        return qs
    if user.is_supervisor and user.department_id:
        return qs.filter(department_id=user.department_id, role=User.Role.COLLECTOR)
    return qs.none()


def scoped_taxpayers(user):
    qs = Taxpayer.objects.select_related("village__district")
    if user.sees_everything or user.can_collect:
        return qs
    return qs.none()


def role_required(check):
    """View decorator: `check` is a User property name such as 'can_void'."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not getattr(request.user, check, False):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator
