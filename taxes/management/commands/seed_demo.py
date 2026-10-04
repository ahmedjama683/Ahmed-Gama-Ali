"""
Load starter data: Somaliland > Maroodi Jeex > Hargeisa, its districts,
departments, tax types and one demo account per role.

    python manage.py seed_demo                    # reference data + demo users
    python manage.py seed_demo --collections 5000 # also random test payments

District / village names and tax amounts are SAMPLES. Replace them with the
official list from the municipality in the admin site before going live.
"""

import random
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import Department, User
from locations.models import City, Country, District, Region, Village
from taxes.models import DutyShift, LocationPing, PaymentMethod, TaxCollection, TaxType

DISTRICTS = {
    "26 June": ["Jigjiga Yar", "Masalaha"],
    "Ahmed Dhagah": ["Dami", "Sha'ab"],
    "Ga'an Libah": ["Ga'an Libah", "Calaamadaha"],
    "Ibrahim Koodbuur": ["Koodbuur", "Faluuja"],
    "Mohamed Mooge": ["Mohamed Mooge", "Isha Borama"],
    "Mohamoud Haybe": ["Mohamoud Haybe", "New Hargeisa"],
}

DEPARTMENTS = [
    ("PROP", "Property Tax"),
    ("BUS", "Business Licensing"),
    ("MKT", "Markets & Trade"),
    ("TRN", "Transport & Parking"),
    ("SAN", "Sanitation"),
]

TAX_TYPES = [
    # code, name, department, default amount, currency, frequency, collector max discount %
    ("PROP-RES", "Residential property tax", "PROP", 300000, "SLSH", "ANNUAL", 10),
    ("PROP-COM", "Commercial property tax", "PROP", 120, "USD", "ANNUAL", 5),
    ("BUS-LIC", "Business licence", "BUS", 50, "USD", "ANNUAL", 5),
    ("BUS-SIGN", "Signboard fee", "BUS", 150000, "SLSH", "ANNUAL", 0),
    ("MKT-STALL", "Market stall fee", "MKT", 5000, "SLSH", "DAILY", 0),
    ("MKT-LIVE", "Livestock market fee", "MKT", 10000, "SLSH", "ONE_OFF", 0),
    ("TRN-PARK", "Parking fee", "TRN", 3000, "SLSH", "DAILY", 0),
    ("SAN-WASTE", "Waste collection fee", "SAN", 30000, "SLSH", "MONTHLY", 10),
]

DEMO_USERS = [
    # username, first, last, role, employee id, department code, district
    ("admin", "System", "Admin", User.Role.ADMIN, "HGA-ADM-001", None, None),
    ("director", "Executive", "Director", User.Role.EXECUTIVE, "HGA-EXE-001", None, None),
    ("treasury", "Treasury", "Officer", User.Role.TREASURY, "HGA-TRS-001", None, None),
    ("auditor", "Internal", "Auditor", User.Role.AUDITOR, "HGA-AUD-001", None, None),
    ("supervisor", "Property", "Supervisor", User.Role.SUPERVISOR, "HGA-SUP-001", "PROP", None),
    ("collector1", "Amina", "Warsame", User.Role.COLLECTOR, "HGA-TC-0001", "PROP", "26 June"),
    ("collector2", "Abdi", "Farah", User.Role.COLLECTOR, "HGA-TC-0002", "MKT", "Ahmed Dhagah"),
    ("collector3", "Hodan", "Jama", User.Role.COLLECTOR, "HGA-TC-0003", "PROP", "Ga'an Libah"),
    ("collector4", "Yusuf", "Ali", User.Role.COLLECTOR, "HGA-TC-0004", "PROP", "Mohamed Mooge"),
]
DEMO_PASSWORD = "ChangeMe-2026"

HARGEISA = (9.5624, 44.0770, 1334)  # lat, lon, altitude (m)


class Command(BaseCommand):
    help = "Load sample Hargeisa reference data, demo users and optional test payments."

    def add_arguments(self, parser):
        parser.add_argument("--collections", type=int, default=0,
                            help="Number of random test payments to create.")
        parser.add_argument("--no-users", action="store_true", help="Skip demo users.")
        parser.add_argument("--tracking", action="store_true",
                            help="Simulate today's shifts and walking routes for the tracker map.")

    @transaction.atomic
    def handle(self, *args, **opts):
        country, _ = Country.objects.get_or_create(name="Somaliland", defaults={"iso_code": "SL"})
        region, _ = Region.objects.get_or_create(country=country, name="Maroodi Jeex")
        city, _ = City.objects.get_or_create(region=region, name="Hargeisa")
        villages = []
        for d_name, v_names in DISTRICTS.items():
            district, _ = District.objects.get_or_create(city=city, name=d_name)
            for v_name in v_names:
                v, _ = Village.objects.get_or_create(district=district, name=v_name)
                villages.append(v)

        depts = {}
        for code, name in DEPARTMENTS:
            depts[code], _ = Department.objects.get_or_create(code=code, defaults={"name": name})

        for code, name, dept, amount, cur, freq, max_disc in TAX_TYPES:
            TaxType.objects.get_or_create(code=code, defaults=dict(
                name=name, department=depts[dept], default_amount=Decimal(amount), currency=cur,
                frequency=freq, max_collector_discount_percent=Decimal(max_disc)))
        self.stdout.write(self.style.SUCCESS(
            f"Locations: {len(villages)} villages · {len(depts)} departments · "
            f"{TaxType.objects.count()} tax types"))

        if not opts["no_users"]:
            for username, first, last, role, emp_id, dept, district in DEMO_USERS:
                user, created = User.objects.get_or_create(username=username, defaults=dict(
                    first_name=first, last_name=last, role=role, employee_id=emp_id,
                    department=depts.get(dept),
                    assigned_district=District.objects.filter(city=city, name=district).first(),
                    is_staff=role == User.Role.ADMIN, is_superuser=role == User.Role.ADMIN))
                if created:
                    user.set_password(DEMO_PASSWORD)
                    user.save()
            self.stdout.write(self.style.WARNING(
                f"Demo users: {', '.join(u[0] for u in DEMO_USERS)} · password '{DEMO_PASSWORD}'. "
                "Change or delete them before real use."))

        n = opts["collections"]
        if n:
            self._random_collections(n, villages)
        if opts["tracking"]:
            self._simulate_tracking(villages)

    def _random_collections(self, n, villages):
        collectors = list(User.objects.filter(role__in=[User.Role.COLLECTOR, User.Role.SUPERVISOR]))
        tax_types = list(TaxType.objects.all())
        if not collectors:
            self.stderr.write("No collectors exist; create users first.")
            return
        names = ["Hodan", "Mohamed", "Fadumo", "Ahmed", "Sahra", "Ismail", "Khadra", "Yusuf",
                 "Ayan", "Abdirahman", "Nimco", "Hassan"]
        now = timezone.now()
        lat0, lon0, alt0 = HARGEISA
        batch = []
        for i in range(n):
            t = random.choice(tax_types)
            collector = random.choice(collectors)
            method = random.choices(
                [PaymentMethod.ZAAD, PaymentMethod.EDAHAB, PaymentMethod.CASH, PaymentMethod.BANK],
                weights=[55, 20, 20, 5])[0]
            amount = t.default_amount
            disc_pct = Decimal(random.choice([0, 0, 0, 0, 5, 10])).min(
                t.max_collector_discount_percent)
            c = TaxCollection(
                collector=collector, department_id=t.department_id, tax_type=t,
                payer_name=f"{random.choice(names)} {random.choice(names)}",
                currency=t.currency, tax_amount=amount,
                discount_type="PERCENT" if disc_pct else "NONE", discount_value=disc_pct,
                discount_reason="Early payment" if disc_pct else "",
                payment_method=method,
                transaction_reference="" if method == PaymentMethod.CASH else f"TX{random.randint(10**8, 10**9)}",
                collected_at=now - timedelta(minutes=random.randint(0, 60 * 24 * 90)),
                village=random.choice(villages),
                latitude=Decimal(lat0 + random.uniform(-0.03, 0.03)).quantize(Decimal("0.000001")),
                longitude=Decimal(lon0 + random.uniform(-0.04, 0.04)).quantize(Decimal("0.000001")),
                altitude=Decimal(alt0 + random.uniform(-30, 30)).quantize(Decimal("0.1")),
                gps_accuracy=Decimal(random.uniform(3, 25)).quantize(Decimal("0.1")),
            )
            c.discount_amount = c.compute_discount()
            c.amount_paid = c.tax_amount - c.discount_amount
            c.receipt_number = f"TEST-{now:%y%m%d%H%M%S}-{i:07d}"
            batch.append(c)
            if len(batch) == 2000:
                TaxCollection.objects.bulk_create(batch)
                batch = []
        TaxCollection.objects.bulk_create(batch)
        self.stdout.write(self.style.SUCCESS(f"Created {n} random test payments."))

    def _simulate_tracking(self, villages):
        """Open shifts from 08:00 for most collectors, with a walking route and payments."""
        now = timezone.localtime()
        start = now.replace(hour=8, minute=0, second=0, microsecond=0)
        if now <= start:
            start = now - timedelta(hours=3)
        lat0, lon0, alt0 = HARGEISA
        collectors = list(User.objects.filter(role=User.Role.COLLECTOR).order_by("username"))
        q = Decimal("0.000001")
        for idx, collector in enumerate(collectors):
            DutyShift.objects.filter(collector=collector, ended_at__isnull=True).update(ended_at=now)
            shift = DutyShift.objects.create(collector=collector, started_at=start)
            # The last collector has closed the app an hour ago, to show a "stale" status.
            stop = now - timedelta(hours=1) if idx == len(collectors) - 1 else now
            lat = lat0 + random.uniform(-0.02, 0.02)
            lon = lon0 + random.uniform(-0.025, 0.025)
            heading_lat, heading_lon = random.uniform(-1, 1), random.uniform(-1, 1)
            t, pings = start, []
            tax_types = list(TaxType.objects.filter(department_id=collector.department_id)) \
                or list(TaxType.objects.all())
            while t <= stop:
                if random.random() < 0.15:  # change street now and then
                    heading_lat, heading_lon = random.uniform(-1, 1), random.uniform(-1, 1)
                lat += heading_lat * 0.00025
                lon += heading_lon * 0.00025
                pings.append(LocationPing(
                    collector=collector, shift=shift, recorded_at=t,
                    latitude=Decimal(lat).quantize(q), longitude=Decimal(lon).quantize(q),
                    altitude=Decimal(alt0 + random.uniform(-20, 20)).quantize(Decimal("0.1")),
                    accuracy=Decimal(random.uniform(4, 20)).quantize(Decimal("0.1"))))
                if random.random() < 0.12:
                    t_type = random.choice(tax_types)
                    c = TaxCollection(
                        collector=collector, tax_type=t_type, department_id=t_type.department_id,
                        payer_name=f"Payer {random.randint(100, 999)}", currency=t_type.currency,
                        tax_amount=t_type.default_amount, payment_method=PaymentMethod.ZAAD,
                        transaction_reference=f"ZD{random.randint(10**6, 10**7)}",
                        collected_at=t, village=random.choice(villages),
                        latitude=Decimal(lat).quantize(q), longitude=Decimal(lon).quantize(q))
                    c.save()
                t += timedelta(minutes=2)
            LocationPing.objects.bulk_create(pings)
        self.stdout.write(self.style.SUCCESS(
            f"Simulated today's routes for {len(collectors)} collectors."))
