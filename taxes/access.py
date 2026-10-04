"""Row-level access rules shared by the web pages and the API."""

from functools import wraps

from django.core.exceptions import PermissionDenied

from .models import TaxCollection, Taxpayer


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
    return qs.filter(collector=user)


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
