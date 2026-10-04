from django.apps import AppConfig


class TaxesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "taxes"
    verbose_name = "Tax collection"

    def ready(self):
        from django.contrib.auth.signals import user_logged_in, user_login_failed

        from .models import AuditLog

        def on_login(sender, request, user, **kwargs):
            AuditLog.record(request, "auth.login")

        def on_login_failed(sender, credentials, request=None, **kwargs):
            AuditLog.record(request, "auth.login_failed", username=credentials.get("username", ""))

        user_logged_in.connect(on_login, dispatch_uid="taxes_audit_login")
        user_login_failed.connect(on_login_failed, dispatch_uid="taxes_audit_login_failed")
