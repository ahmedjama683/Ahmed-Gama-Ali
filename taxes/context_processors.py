from .models import DutyShift


def duty_shift(request):
    """Expose the collector's open shift so every page can keep sharing location."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or not user.can_collect:
        return {}
    return {"open_shift": DutyShift.open_for(user)}


def branding(request):
    from django.conf import settings

    return {
        "SYSTEM_NAME": settings.SYSTEM_NAME,
        "CLIENT_NAME": settings.CLIENT_NAME,
        "OPERATOR_NAME": settings.OPERATOR_NAME,
        "MAP_CENTER": settings.MAP_CENTER,
    }
