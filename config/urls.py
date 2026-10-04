from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.http import HttpResponse
from django.urls import include, path
from rest_framework.authtoken.views import obtain_auth_token
from rest_framework.routers import DefaultRouter

from taxes import api, views

router = DefaultRouter()
router.register("collections", api.CollectionViewSet, basename="collection")
router.register("taxpayers", api.TaxpayerViewSet, basename="taxpayer")
router.register("tax-types", api.TaxTypeViewSet, basename="taxtype")
router.register("villages", api.VillageViewSet, basename="village")

admin.site.site_header = f"{settings.CLIENT_NAME} – {settings.SYSTEM_NAME}"
admin.site.site_title = "Tax System Admin"



def robots_txt(request):
    # Staff-only system: ask search engines not to list any page.
    return HttpResponse("User-agent: *\nDisallow: /\n", content_type="text/plain")


urlpatterns = [
    path("robots.txt", robots_txt),
    path("", views.home, name="home"),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("password/", auth_views.PasswordChangeView.as_view(success_url="/"),
         name="password_change"),

    path("collector/", views.collector_home, name="collector_home"),
    path("collector/new/", views.collection_create, name="collection_create"),
    path("taxpayers/new/", views.taxpayer_create, name="taxpayer_create"),
    path("receipt/<str:receipt_number>/", views.receipt, name="receipt"),
    path("collections/", views.collection_list, name="collection_list"),
    path("collections/export.csv", views.collection_export, name="collection_export"),
    path("collections/<int:pk>/void/", views.collection_void, name="collection_void"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("collector/shift/start/", views.shift_start, name="shift_start"),
    path("collector/shift/end/", views.shift_end, name="shift_end"),
    path("team/", views.team, name="team"),
    path("tracker/", views.tracker, name="tracker"),
    path("tracker/data/", views.tracker_data, name="tracker_data"),

    path("api/auth/token/", obtain_auth_token, name="api_token"),
    path("api/me/", api.me, name="api_me"),
    path("api/tracking/ping/", api.tracking_ping, name="api_tracking_ping"),
    path("api/tracking/shift/", api.tracking_shift, name="api_tracking_shift"),
    path("api/", include(router.urls)),

    path("admin/", admin.site.urls),
]
