import csv
import uuid
from datetime import date, datetime, time, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Count, Max, Min, Q, Sum
from django.db.models.functions import TruncDate
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.models import Department

from .access import role_required, scoped_collections, scoped_team, today_range
from .forms import CollectionFilterForm, CollectionForm, TaxpayerForm, VoidForm
from .models import AuditLog, DutyShift, LocationPing, TaxCollection

COMPLETED = TaxCollection.Status.COMPLETED
VOIDED = TaxCollection.Status.VOIDED


def _totals_by_currency(qs):
    return list(
        qs.filter(status=COMPLETED)
        .values("currency")
        .annotate(total=Sum("amount_paid"), discount=Sum("discount_amount"), count=Count("id"))
        .order_by("currency")
    )


@login_required
def home(request):
    user = request.user
    if user.can_view_tracker:
        return redirect("tracker")
    if user.can_view_financials:
        return redirect("dashboard")
    if user.can_view_team:
        return redirect("team")
    return redirect("collector_home")


# --- Collector pages -------------------------------------------------------

@login_required
def collector_home(request):
    user = request.user
    start, end = today_range()
    today = TaxCollection.objects.filter(
        collector=user, collected_at__gte=start, collected_at__lt=end
    )
    return render(request, "taxes/collector_home.html", {
        "today_totals": _totals_by_currency(today),
        "today_count": today.filter(status=COMPLETED).count(),
        "today_list": today.select_related("tax_type", "village"),
        "shift": DutyShift.open_for(user),
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
            if collection.latitude is not None:
                # Every payment with GPS is also a point on the collector's track.
                LocationPing.objects.create(
                    collector=user, shift=DutyShift.open_for(user),
                    recorded_at=collection.collected_at, latitude=collection.latitude,
                    longitude=collection.longitude, altitude=collection.altitude,
                    accuracy=collection.gps_accuracy, source=LocationPing.Source.PAYMENT,
                )
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
@role_required("can_view_financials")
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
@role_required("can_view_financials")
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


# --- Duty shifts (collector) -----------------------------------------------

@login_required
@role_required("can_collect")
def shift_start(request):
    if request.method == "POST" and not DutyShift.open_for(request.user):
        try:
            shift = DutyShift.objects.create(collector=request.user)
        except IntegrityError:  # double tap: a shift was opened a moment ago
            pass
        else:
            AuditLog.record(request, "shift.start", shift)
            messages.success(request, "Shift started. Keep this app open while you work "
                                      "so your location is shared.")
    return redirect("collector_home")


@login_required
@role_required("can_collect")
def shift_end(request):
    shift = DutyShift.open_for(request.user)
    if request.method == "POST" and shift:
        shift.ended_at = timezone.now()
        shift.save(update_fields=["ended_at"])
        AuditLog.record(request, "shift.end", shift)
        messages.success(request, "Shift ended. Location sharing has stopped.")
    return redirect("collector_home")


# --- Supervisor: collector performance -------------------------------------

PERIODS = {"today": "Today", "7": "Last 7 days", "30": "Last 30 days", "90": "Last 90 days"}


@login_required
@role_required("can_view_team")
def team(request):
    period = request.GET.get("period", "today")
    if period not in PERIODS:
        period = "today"
    start, end = today_range()
    if period != "today":
        start = end - timedelta(days=int(period))
    collectors = list(scoped_team(request.user))
    department = request.GET.get("department")
    if department and request.user.can_view_tracker:
        collectors = [c for c in collectors if str(c.department_id) == department]

    base = TaxCollection.objects.filter(
        collector__in=collectors, collected_at__gte=start, collected_at__lt=end
    )
    done = Q(status=COMPLETED)
    stats = {
        row["collector"]: row
        for row in base.values("collector").annotate(
            payments=Count("id", filter=done),
            slsh=Sum("amount_paid", filter=done & Q(currency="SLSH")),
            usd=Sum("amount_paid", filter=done & Q(currency="USD")),
            discount_slsh=Sum("discount_amount", filter=done & Q(currency="SLSH")),
            discount_usd=Sum("discount_amount", filter=done & Q(currency="USD")),
            discounted=Count("id", filter=done & Q(discount_amount__gt=0)),
            voided=Count("id", filter=Q(status=VOIDED)),
            first=Min("collected_at", filter=done),
            last=Max("collected_at", filter=done),
            active_days=Count(TruncDate("collected_at"), filter=done, distinct=True),
        )
    }
    on_shift = set(
        DutyShift.objects.filter(collector__in=collectors, ended_at__isnull=True)
        .values_list("collector_id", flat=True)
    )
    rows = []
    for c in collectors:
        s = stats.get(c.pk, {})
        payments = s.get("payments") or 0
        days = s.get("active_days") or 0
        rows.append({
            "user": c,
            "payments": payments,
            "slsh": s.get("slsh") or 0,
            "usd": s.get("usd") or 0,
            "discount_slsh": s.get("discount_slsh") or 0,
            "discount_usd": s.get("discount_usd") or 0,
            "discounted": s.get("discounted") or 0,
            "discount_rate": round(100 * (s.get("discounted") or 0) / payments) if payments else 0,
            "voided": s.get("voided") or 0,
            "first": s.get("first"),
            "last": s.get("last"),
            "active_days": days,
            "per_day": round(payments / days, 1) if days else 0,
            "on_shift": c.pk in on_shift,
        })
    rows.sort(key=lambda r: (r["slsh"], r["usd"], r["payments"]), reverse=True)
    totals = {k: sum(r[k] for r in rows) for k in ("payments", "slsh", "usd", "voided", "discounted")}
    totals["on_shift"] = len(on_shift)
    return render(request, "taxes/team.html", {
        "rows": rows, "totals": totals, "period": period, "periods": PERIODS,
        "period_label": PERIODS[period], "chart_height": max(160, min(600, 30 * len(rows) + 40)),
        "departments": Department.objects.all() if request.user.can_view_tracker else None,
        "department": department or "",
        "chart": [{"label": r["user"].employee_id or r["user"].username,
                   "slsh": float(r["slsh"]), "usd": float(r["usd"])} for r in rows],
    })


# --- Executive director / admin: live collector tracker ---------------------

@login_required
@role_required("can_view_tracker")
def tracker(request):
    return render(request, "taxes/tracker.html", {
        "departments": Department.objects.all(),
        "today": timezone.localdate().isoformat(),
    })


ONLINE_MINUTES = 10
MAX_TRAIL_POINTS = 720  # 12 hours at one point a minute


@login_required
@role_required("can_view_tracker")
def tracker_data(request):
    try:
        day = date.fromisoformat(request.GET.get("date", ""))
    except ValueError:
        day = timezone.localdate()
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day, time.min), tz)
    end = start + timedelta(days=1)

    collectors = scoped_team(request.user)
    if request.GET.get("department"):
        collectors = collectors.filter(department_id=request.GET["department"])
    collectors = list(collectors)
    ids = [c.pk for c in collectors]

    trails = {}
    pings = (
        LocationPing.objects.filter(collector_id__in=ids, recorded_at__gte=start,
                                    recorded_at__lt=end)
        .order_by("recorded_at")
        .values_list("collector_id", "recorded_at", "latitude", "longitude", "accuracy", "source")
    )
    for cid, at, lat, lon, acc, source in pings.iterator(chunk_size=5000):
        trails.setdefault(cid, []).append([
            float(lat), float(lon), timezone.localtime(at).strftime("%H:%M"),
            float(acc) if acc is not None else None, source, at,
        ])

    payments = TaxCollection.objects.filter(
        collector_id__in=ids, collected_at__gte=start, collected_at__lt=end
    )
    money = {
        row["collector"]: row for row in payments.values("collector").annotate(
            count=Count("id", filter=Q(status=COMPLETED)),
            slsh=Sum("amount_paid", filter=Q(status=COMPLETED, currency="SLSH")),
            usd=Sum("amount_paid", filter=Q(status=COMPLETED, currency="USD")),
        )
    }
    open_shifts = {
        s.collector_id: s for s in DutyShift.objects.filter(collector_id__in=ids,
                                                            ended_at__isnull=True)
    }
    now = timezone.now()
    out = []
    for c in collectors:
        trail = trails.get(c.pk, [])
        last = trail[-1] if trail else None
        shift = open_shifts.get(c.pk)
        minutes_ago = int((now - last[5]).total_seconds() // 60) if last else None
        if shift and last and minutes_ago <= ONLINE_MINUTES:
            state = "online"
        elif shift:
            state = "stale"   # on shift but the phone has not reported recently
        else:
            state = "off"
        m = money.get(c.pk, {})
        out.append({
            "id": c.pk,
            "employee_id": c.employee_id or c.username,
            "name": c.get_full_name() or c.username,
            "department": c.department.name if c.department else "",
            "district": c.assigned_district.name if c.assigned_district else "",
            "state": state,
            "shift_started": timezone.localtime(shift.started_at).strftime("%H:%M") if shift else None,
            "last": {"lat": last[0], "lon": last[1], "time": last[2], "accuracy": last[3],
                     "minutes_ago": minutes_ago} if last else None,
            "trail": [p[:5] for p in trail[-MAX_TRAIL_POINTS:]],
            "payments": m.get("count") or 0,
            "slsh": float(m.get("slsh") or 0),
            "usd": float(m.get("usd") or 0),
        })
    points = [
        {**p, "latitude": float(p["latitude"]), "longitude": float(p["longitude"]),
         "amount_paid": float(p["amount_paid"]),
         "collected_at": timezone.localtime(p["collected_at"]).strftime("%H:%M")}
        for p in payments.exclude(latitude__isnull=True).values(
            "receipt_number", "latitude", "longitude", "amount_paid", "currency",
            "payer_name", "status", "collected_at", "collector_id")[:5000]
    ]
    return JsonResponse({"date": day.isoformat(), "is_today": day == timezone.localdate(),
                         "collectors": out, "payments": points})
