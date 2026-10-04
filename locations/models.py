"""
Administrative geography: Country > Region (State) > City > District > Village.

Collections point at a Village; the city, region and country are reached
through the chain, so a place name is stored once and reports can roll up
at any level.
"""

from django.db import models


class Country(models.Model):
    name = models.CharField(max_length=100, unique=True)
    iso_code = models.CharField(max_length=3, blank=True)

    class Meta:
        verbose_name_plural = "countries"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Region(models.Model):
    """State / Region, e.g. Maroodi Jeex."""

    country = models.ForeignKey(Country, on_delete=models.PROTECT, related_name="regions")
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["name"]
        unique_together = [("country", "name")]

    def __str__(self):
        return self.name


class City(models.Model):
    region = models.ForeignKey(Region, on_delete=models.PROTECT, related_name="cities")
    name = models.CharField(max_length=100)

    class Meta:
        verbose_name_plural = "cities"
        ordering = ["name"]
        unique_together = [("region", "name")]

    def __str__(self):
        return self.name


class District(models.Model):
    """Administrative district of a city (Hargeisa is divided into districts)."""

    city = models.ForeignKey(City, on_delete=models.PROTECT, related_name="districts")
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["name"]
        unique_together = [("city", "name")]

    def __str__(self):
        return f"{self.name} ({self.city})"


class Village(models.Model):
    """Village / neighbourhood (xaafad) inside a district."""

    district = models.ForeignKey(District, on_delete=models.PROTECT, related_name="villages")
    name = models.CharField(max_length=100)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("district", "name")]

    def __str__(self):
        return f"{self.name}, {self.district.name}"

    @property
    def city(self):
        return self.district.city

    @property
    def region(self):
        return self.district.city.region

    @property
    def country(self):
        return self.district.city.region.country
