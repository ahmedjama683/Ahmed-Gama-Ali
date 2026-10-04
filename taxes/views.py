import csv
import uuid
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .access import role_required, scoped_collections
from .forms import CollectionFilterForm, CollectionForm, TaxpayerForm, VoidForm
from .models import AuditLog, TaxCollection

COMPLETED = TaxCollection.Status.COMPLETED


def _today_range():
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def _totals_by_currency(qs):
    return list(
        qs.filter(status=COMPLETED)
        .values("currency")
        .annotate(total=Sum("amount_paid"), discount=Sum("discount_amount"), count=Count("id"))
        .order_by("currency")
    )


@login_required
def home(request):
    if request.user.can_collect and not request.user.can_view_reports:
        return redirect("collector_home")
    if request.user.can_view_reports:
        return redirect("dashboard")
    return redirect("collector_home")


# --- Collector pages -------------------------------------------------------

@login_required
def collector_home(request):
    user = request.user
    start, end = _today_range()
    mine = TaxCollection.objects.filter(collector=user)
    today = mine.filter(collected_at__gte=start, collected_at__lt=end)
    return render(request, "taxes/collector_home.html", {
        "today_totals": _totals_by_currency(today),
        "today_count": today.filter(status=COMPLETED).count(),
        "recent": mine.select_related("tax_type", "village")[:15],
    })


@login_required
@role_required("can_collect")
def collection_create(request):
    user = request.user
    if request.method == "POST":
        # A retried submit (bad network, double tap) must not create a second payment.
        client_uuid = request.POST.get("client_uuid")
        existing = (
            TaxCollection.objects.filter(client_uuid=client_uuid, collector=user).first()
            if _is_uuid(client_uuid) else None
        )
        if existing:
            return redirect("receipt", receipt_number=existing.receipt_number)
        form = CollectionForm(request.POST, collector=user)
        if form.is_valid():
            collection = form.save(commit=False)
            collection.collector = user
            collection.save()
            AuditLog.record(request, "collection.create", collection,
                            receipt=collection.receipt_number,
                            amount=str(collection.amount_paid), currency=collection.currency)
            messages.success(request, f"Payment saved. Receipt {collection.receipt_number}.")
            return redirect("receipt", receipt_number=collection.receipt_number)
    else:
        form = CollectionForm(collector=user, initial={"client_uuid": uuid.uuid4()})
    tax_types = {
        str(t.pk): {"amount": str(t.default_amount), "currency": t.currency,
                    "max_discount": str(t.max_collector_discount_percent)}
        for t in form.fields["tax_type"].queryset
    }
    return render(request, "taxes/collection_form.html", {"form": form, "tax_types": tax_types})


def _is_uuid(value):
    try:
        uuid.UUID(str(value))
        return True
    except (TypeError, ValueError):
        return False


@login_required
def receipt(request, receipt_number):
    collection = get_object_or_404(scoped_collections(request.user), receipt_number=receipt_number)
    return render(request, "taxes/receipt.html", {"c": collection})


@login_required
def taxpayer_create(request):
    if not (request.user.can_collect or request.user.sees_everything):
        raise PermissionDenied
    form = TaxpayerForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        taxpayer = form.save(commit=False)
        taxpayer.created_by = request.user
        taxpayer.save()
        AuditLog.record(request, "taxpayer.create", taxpayer)
        messages.success(request, f"Taxpayer registered: {taxpayer}.")
        return redirect("collection_create")
    return render(request, "taxes/taxpayer_form.html", {"form": form})


# --- Lists, reports, export -----------------------------------------------

def _filtered(request):
    qs = scoped_collections(request.user)
    form = CollectionFilterForm(request.GET or None)
    if form.is_valid():
        d = form.cleaned_data
        if d["q"]:
            qs = qs.filter(
                Q(receipt_number__icontains=d["q"]) | Q(payer_name__icontains=d["q"])
                | Q(payer_phone__icontains=d["q"]) | Q(transaction_reference__icontains=d["q"])
                | Q(collector__employee_id__iexact=d["q"])
                | Q(taxpayer__taxpayer_number__iexact=d["q"])
            )
        if d["date_from"]:
            qs = qs.filter(collected_at__date__gte=d["date_from"])
        if d["date_to"]:
            qs = qs.filter(collected_at__date__lte=d["date_to"])
        if d["status"]:
            qs = qs.filter(status=d["status"])
        if d["payment_method"]:
            qs = qs.filter(payment_method=d["payment_method"])
    return qs, form


@login_required
def collection_list(request):
    qs, form = _filtered(request)
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "taxes/collection_list.html", {
        "page": page, "form": form, "totals": _totals_by_currency(qs),
        "querystring": params.urlencode(),
    })


class _Echo:
    def write(self, value):
        return value


@login_required
@role_required("can_view_reports")
def collection_export(request):
    """Stream a CSV so very large exports do not exhaust server memory."""
    qs, _ = _filtered(request)
    AuditLog.record(request, "collection.export", rows=qs.count())
    writer = csv.writer(_Echo())
    header = [
        "Receipt", "Status", "Collected at", "Collector ID", "Collector name", "Department",
        "Tax type", "Payer", "Taxpayer no.", "Currency", "Tax amount", "Discount",
        "Discount reason", "Amount paid", "Payment method", "Transaction ref", "Village",
        "District", "City", "Region", "Country", "Latitude", "Longitude", "Altitude (m)",
        "GPS accuracy (m)",
    ]

    def rows():
        yield writer.writerow(header)
        for c in qs.iterator(chunk_size=2000):
            v = c.village
            yield writer.writerow([
                c.receipt_number, c.status, timezone.localtime(c.collected_at).isoformat(),
                c.collector.employee_id or "", c.collector.get_full_name() or c.collector.username,
                c.department.name, c.tax_type.name, c.payer_name,
                c.taxpayer.taxpayer_number if c.taxpayer else "", c.currency, c.tax_amount,
                c.discount_amount, c.discount_reason, c.amount_paid,
                c.get_payment_method_display(), c.transaction_reference, v.name,
                v.district.name, v.district.city.name, v.district.city.region.name,
                v.district.city.region.country.name, c.latitude, c.longitude, c.altitude,
                c.gps_accuracy,
            ])

    response = StreamingHttpResponse(rows(), content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="collections-{timezone.localdate():%Y%m%d}.csv"'
    )
    return response


@login_required
@role_required("can_view_reports")
def dashboard(request):
    try:
        days = max(1, min(int(request.GET.get("days", 30)), 366))
    except ValueError:
        days = 30
    since = timezone.now() - timedelta(days=days)
    qs = scoped_collections(request.user).filter(collected_at__gte=since, status=COMPLETED)

    def breakdown(*fields):
        return list(
            qs.values(*fields, "currency")
            .annotate(total=Sum("amount_paid"), count=Count("id"))
            .order_by("-total")[:15]
        )

    daily = list(
        qs.annotate(day=TruncDate("collected_at"))
        .values("day", "currency")
        .annotate(total=Sum("amount_paid"))
        .order_by("day")
    )
    return render(request, "taxes/dashboard.html", {
        "days": days,
        "totals": _totals_by_currency(qs),
        "by_department": breakdown("department__name"),
        "by_tax_type": breakdown("tax_type__name"),
        "by_method": breakdown("payment_method"),
        "by_collector": breakdown("collector__employee_id", "collector__first_name",
                                  "collector__last_name"),
        "by_district": breakdown("village__district__name"),
        "daily": [{"day": d["day"].isoformat(), "currency": d["currency"],
                   "total": float(d["total"])} for d in daily],
        "voided": scoped_collections(request.user).filter(
            collected_at__gte=since, status=TaxCollection.Status.VOIDED).count(),
        "method_labels": dict(TaxCollection._meta.get_field("payment_method").choices),
    })


@login_required
@role_required("can_view_reports")
def collection_map(request):
    return render(request, "taxes/map.html")


@login_required
@role_required("can_view_reports")
def collection_map_data(request):
    qs, _ = _filtered(request)
    qs = qs.exclude(latitude__isnull=True).values(
        "receipt_number", "latitude", "longitude", "amount_paid", "currency",
        "payer_name", "status", "collected_at", "collector__employee_id",
    )[:5000]
    return JsonResponse({"points": [
        {**p, "latitude": float(p["latitude"]), "longitude": float(p["longitude"]),
         "amount_paid": float(p["amount_paid"]),
         "collected_at": timezone.localtime(p["collected_at"]).strftime("%Y-%m-%d %H:%M")}
        for p in qs
    ]})


@login_required
@role_required("can_void")
def collection_void(request, pk):
    collection = get_object_or_404(scoped_collections(request.user), pk=pk)
    form = VoidForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            collection.void(request.user, form.cleaned_data["reason"])
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
        else:
            AuditLog.record(request, "collection.void", collection,
                            reason=collection.void_reason)
            messages.success(request, f"Receipt {collection.receipt_number} voided.")
        return redirect("receipt", receipt_number=collection.receipt_number)
    return render(request, "taxes/void_form.html", {"form": form, "c": collection})
