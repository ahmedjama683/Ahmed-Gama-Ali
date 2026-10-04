from django.contrib import admin

from .models import City, Country, District, Region, Village


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ["name", "iso_code"]
    search_fields = ["name"]


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ["name", "country"]
    list_filter = ["country"]
    search_fields = ["name"]


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ["name", "region"]
    list_filter = ["region"]
    search_fields = ["name"]


@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    list_display = ["name", "city"]
    list_filter = ["city"]
    search_fields = ["name"]


@admin.register(Village)
class VillageAdmin(admin.ModelAdmin):
    list_display = ["name", "district", "latitude", "longitude"]
    list_filter = ["district"]
    search_fields = ["name", "district__name"]
