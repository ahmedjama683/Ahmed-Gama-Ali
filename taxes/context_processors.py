from .models import DutyShift


def duty_shift(request):
    """Expose the collector's open shift so every page can keep sharing location."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or not user.can_collect:
        return {}
    return {"open_shift": DutyShift.open_for(user)}
