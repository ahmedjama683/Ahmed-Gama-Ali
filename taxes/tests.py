import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import User
from locations.models import Village

from .models import AuditLog, TaxCollection, TaxType


class BaseCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0, stdout=open("/dev/null", "w"))
        cls.collector = User.objects.get(username="collector1")  # PROP department
        cls.collector2 = User.objects.get(username="collector2")  # MKT department
        cls.supervisor = User.objects.get(username="supervisor")  # PROP department
        cls.manager = User.objects.get(username="manager")
        cls.auditor = User.objects.get(username="auditor")
        cls.village = Village.objects.first()
        cls.prop = TaxType.objects.get(code="PROP-RES")  # 10% collector limit
        cls.stall = TaxType.objects.get(code="MKT-STALL")

    def make(self, collector=None, tax_type=None, **kw):
        tax_type = tax_type or self.prop
        data = dict(collector=collector or self.collector, tax_type=tax_type,
                    payer_name="Hodan Ali", tax_amount=Decimal("300000"),
                    currency=tax_type.currency, village=self.village)
        data.update(kw)
        c = TaxCollection(**data)
        c.full_clean(exclude=["receipt_number", "department"])
        c.save()
        return c

    def form_data(self, **kw):
        data = dict(client_uuid=str(uuid.uuid4()), payer_name="Hodan Ali", tax_type=self.prop.pk,
                    currency="SLSH", tax_amount="300000", discount_type="NONE",
                    discount_value="0", payment_method="CASH", village=self.village.pk,
                    latitude="9.562400", longitude="44.077000", altitude="1334.0",
                    gps_accuracy="8.0")
        data.update(kw)
        return data


class ModelTests(BaseCase):
    def test_amounts_receipt_and_department(self):
        c = self.make(discount_type="PERCENT", discount_value=Decimal("10"),
                      discount_reason="Early payment")
        self.assertEqual(c.discount_amount, Decimal("30000.00"))
        self.assertEqual(c.amount_paid, Decimal("270000.00"))
        self.assertRegex(c.receipt_number, r"^HGA-\d{4}-\d{8}$")
        self.assertEqual(c.department, self.prop.department)
        self.assertEqual(c.village.country.name, "Somaliland")

    def test_collector_discount_limit(self):
        with self.assertRaises(ValidationError):
            self.make(discount_type="PERCENT", discount_value=Decimal("25"), discount_reason="x")

    def test_supervisor_may_exceed_limit(self):
        c = self.make(collector=self.supervisor, discount_type="PERCENT",
                      discount_value=Decimal("25"), discount_reason="Hardship")
        self.assertEqual(c.amount_paid, Decimal("225000.00"))

    def test_discount_needs_reason_and_cannot_exceed_amount(self):
        with self.assertRaises(ValidationError):
            self.make(collector=self.supervisor, discount_type="FIXED", discount_value=Decimal("10"))
        with self.assertRaises(ValidationError):
            self.make(collector=self.supervisor, discount_type="FIXED",
                      discount_value=Decimal("400000"), discount_reason="x")

    def test_mobile_money_needs_reference(self):
        with self.assertRaises(ValidationError):
            self.make(payment_method="ZAAD")
        self.make(payment_method="ZAAD", transaction_reference="ZD123")

    def test_void(self):
        c = self.make()
        c.void(self.supervisor, "Wrong amount")
        c.refresh_from_db()
        self.assertEqual(c.status, TaxCollection.Status.VOIDED)
        with self.assertRaises(ValidationError):
            c.void(self.supervisor, "again")


class WebTests(BaseCase):
    def test_login_required(self):
        r = self.client.get(reverse("collector_home"))
        self.assertEqual(r.status_code, 302)

    def test_collector_records_payment_once(self):
        self.client.force_login(self.collector)
        data = self.form_data()
        r = self.client.post(reverse("collection_create"), data)
        self.assertEqual(r.status_code, 302, getattr(r, "context", {}) and r.context["form"].errors)
        # The same submit again (phone retried) must not duplicate.
        r2 = self.client.post(reverse("collection_create"), data)
        self.assertEqual(r2["Location"], r["Location"])
        self.assertEqual(TaxCollection.objects.count(), 1)
        c = TaxCollection.objects.get()
        self.assertEqual(c.altitude, Decimal("1334.0"))
        self.assertTrue(AuditLog.objects.filter(action="collection.create").exists())
        self.assertEqual(self.client.get(r["Location"]).status_code, 200)

    def test_collector_cannot_use_other_department_tax(self):
        self.client.force_login(self.collector)
        r = self.client.post(reverse("collection_create"), self.form_data(tax_type=self.stall.pk))
        self.assertEqual(r.status_code, 200)
        self.assertIn("tax_type", r.context["form"].errors)

    def test_row_level_visibility(self):
        mine = self.make()
        other = self.make(collector=self.collector2, tax_type=self.stall,
                          tax_amount=Decimal("5000"))
        self.client.force_login(self.collector)
        self.assertEqual(self.client.get(reverse("receipt", args=[other.receipt_number])).status_code, 404)
        self.assertEqual(self.client.get(reverse("receipt", args=[mine.receipt_number])).status_code, 200)
        # Supervisor of PROP sees PROP payments only.
        self.client.force_login(self.supervisor)
        self.assertEqual(self.client.get(reverse("receipt", args=[mine.receipt_number])).status_code, 200)
        self.assertEqual(self.client.get(reverse("receipt", args=[other.receipt_number])).status_code, 404)
        # Manager sees everything.
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("receipt", args=[other.receipt_number])).status_code, 200)

    def test_role_restricted_pages(self):
        c = self.make()
        self.client.force_login(self.collector)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 403)
        self.assertEqual(self.client.get(reverse("collection_export")).status_code, 403)
        self.assertEqual(self.client.get(reverse("collection_void", args=[c.pk])).status_code, 403)
        self.client.force_login(self.auditor)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("collection_create")).status_code, 403)
        self.assertEqual(self.client.get(reverse("collection_void", args=[c.pk])).status_code, 403)

    def test_supervisor_voids(self):
        c = self.make()
        self.client.force_login(self.supervisor)
        self.client.post(reverse("collection_void", args=[c.pk]), {"reason": "Duplicate"})
        c.refresh_from_db()
        self.assertEqual(c.status, "VOIDED")
        self.assertEqual(c.voided_by, self.supervisor)

    def test_reports_render(self):
        self.make()
        self.client.force_login(self.manager)
        for name in ["dashboard", "collection_list", "collection_map", "collection_map_data"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        r = self.client.get(reverse("collection_export"))
        body = b"".join(r.streaming_content).decode()
        self.assertIn("Altitude (m)", body)
        self.assertIn("Somaliland", body)


class ApiTests(BaseCase):
    def setUp(self):
        self.api = APIClient()
        token = Token.objects.create(user=self.collector)
        self.api.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def payload(self, **kw):
        data = dict(client_uuid=str(uuid.uuid4()), payer_name="Ayan", tax_type=self.prop.pk,
                    currency="SLSH", tax_amount="300000", payment_method="ZAAD",
                    transaction_reference="ZD99", village=self.village.pk,
                    latitude="9.5624", longitude="44.077", altitude="1330")
        data.update(kw)
        return data

    def test_create_is_idempotent(self):
        p = self.payload()
        r = self.api.post("/api/collections/", p, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["country"], "Somaliland")
        r2 = self.api.post("/api/collections/", p, format="json")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.data["receipt_number"], r.data["receipt_number"])

    def test_validation_and_no_edit(self):
        r = self.api.post("/api/collections/", self.payload(transaction_reference=""), format="json")
        self.assertEqual(r.status_code, 400)
        r = self.api.post("/api/collections/", self.payload(), format="json")
        pk = r.data["id"]
        self.assertEqual(self.api.patch(f"/api/collections/{pk}/", {"tax_amount": "1"}).status_code, 405)
        self.assertEqual(self.api.delete(f"/api/collections/{pk}/").status_code, 405)
        self.assertEqual(self.api.post(f"/api/collections/{pk}/void/", {"reason": "x"}).status_code, 403)

    def test_token_and_me(self):
        r = APIClient().post("/api/auth/token/", {"username": "collector1",
                                                  "password": "ChangeMe-2026"})
        self.assertEqual(r.status_code, 200)
        me = self.api.get("/api/me/")
        self.assertEqual(me.data["employee_id"], "HGA-TC-0001")
        self.assertEqual(self.api.get("/api/villages/").status_code, 200)
