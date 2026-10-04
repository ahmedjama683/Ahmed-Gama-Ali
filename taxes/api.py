"""
REST API at /api/. Lets a future Android app (or an offline-first PWA) record
collections and sync them. Authenticate with a token from /api/auth/token/.
"""

from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError
from django.utils import timezone
from rest_framework import mixins, permissions, serializers, status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from locations.models import Village

from .access import scoped_collections, scoped_taxpayers
from .models import AuditLog, DutyShift, LocationPing, TaxCollection, TaxType, Taxpayer


class CanCollect(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user.can_collect


class TaxTypeSerializer(serializers.ModelSerializer):
    department = serializers.StringRelatedField()

    class Meta:
        model = TaxType
        fields = ["id", "code", "name", "department", "default_amount", "currency",
                  "frequency", "max_collector_discount_percent"]


class VillageSerializer(serializers.ModelSerializer):
    district = serializers.CharField(source="district.name")
    city = serializers.CharField(source="district.city.name")
    region = serializers.CharField(source="district.city.region.name")
    country = serializers.CharField(source="district.city.region.country.name")

    class Meta:
        model = Village
        fields = ["id", "name", "district", "city", "region", "country", "latitude", "longitude"]


class TaxpayerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Taxpayer
        fields = ["id", "taxpayer_number", "kind", "name", "business_name", "national_id",
                  "phone", "village", "address", "property_number", "latitude", "longitude"]
        read_only_fields = ["taxpayer_number"]


class CollectionSerializer(serializers.ModelSerializer):
    collector_id = serializers.CharField(source="collector.employee_id", read_only=True)
    collector_name = serializers.CharField(source="collector.get_full_name", read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True)
    village_name = serializers.CharField(source="village.name", read_only=True)
    city = serializers.CharField(source="village.district.city.name", read_only=True)
    region = serializers.CharField(source="village.district.city.region.name", read_only=True)
    country = serializers.CharField(source="village.district.city.region.country.name",
                                    read_only=True)

    class Meta:
        model = TaxCollection
        fields = [
            "id", "receipt_number", "client_uuid", "status",
            "collector_id", "collector_name", "department", "department_name",
            "taxpayer", "payer_name", "payer_phone", "tax_type", "period_start", "period_end",
            "currency", "tax_amount", "discount_type", "discount_value", "discount_reason",
            "discount_amount", "amount_paid", "payment_method", "transaction_reference",
            "collected_at", "village", "village_name", "city", "region", "country",
            "latitude", "longitude", "altitude", "gps_accuracy", "notes",
            "void_reason", "voided_at", "created_at",
        ]
        read_only_fields = [
            "receipt_number", "status", "department", "discount_amount", "amount_paid",
            "void_reason", "voided_at", "created_at",
        ]
        # Uniqueness of client_uuid is handled in create() so retries are idempotent.
        extra_kwargs = {"client_uuid": {"validators": []}}

    def validate(self, attrs):
        instance = TaxCollection(**attrs, collector=self.context["request"].user)
        try:
            instance.clean()
        except Exception as exc:  # django ValidationError -> DRF ValidationError
            raise serializers.ValidationError(getattr(exc, "message_dict", str(exc)))
        return attrs


class CollectionViewSet(mixins.CreateModelMixin, mixins.ListModelMixin,
                        mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Collections can be created and read, never edited or deleted."""

    serializer_class = CollectionSerializer
    permission_classes = [permissions.IsAuthenticated, CanCollect]
    filterset_fields = ["status", "payment_method", "currency", "tax_type", "department",
                        "village", "village__district"]
    search_fields = ["receipt_number", "payer_name", "payer_phone", "transaction_reference"]
    ordering_fields = ["collected_at", "amount_paid"]

    def get_queryset(self):
        qs = scoped_collections(self.request.user)
        since = self.request.query_params.get("since")
        if since:
            qs = qs.filter(collected_at__gte=since)
        return qs

    def create(self, request, *args, **kwargs):
        client_uuid = request.data.get("client_uuid")
        if client_uuid:
            existing = TaxCollection.objects.filter(
                client_uuid=client_uuid, collector=request.user
            ).first()
            if existing:
                return Response(self.get_serializer(existing).data, status=status.HTTP_200_OK)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            collection = serializer.save(collector=request.user)
        except IntegrityError:
            return Response({"client_uuid": ["Already used by another collector."]},
                            status=status.HTTP_400_BAD_REQUEST)
        AuditLog.record(request, "collection.create", collection, via="api",
                        receipt=collection.receipt_number)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        if not request.user.can_void:
            return Response(status=status.HTTP_403_FORBIDDEN)
        collection = self.get_object()
        try:
            collection.void(request.user, request.data.get("reason", ""))
        except Exception as exc:
            return Response({"detail": " ".join(getattr(exc, "messages", [str(exc)]))},
                            status=status.HTTP_400_BAD_REQUEST)
        AuditLog.record(request, "collection.void", collection, via="api",
                        reason=collection.void_reason)
        return Response(self.get_serializer(collection).data)


class TaxpayerViewSet(mixins.CreateModelMixin, mixins.ListModelMixin,
                      mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = TaxpayerSerializer
    permission_classes = [permissions.IsAuthenticated, CanCollect]
    filterset_fields = ["kind", "village"]
    search_fields = ["taxpayer_number", "name", "business_name", "phone", "national_id",
                     "property_number"]

    def get_queryset(self):
        return scoped_taxpayers(self.request.user)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class TaxTypeViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TaxTypeSerializer
    queryset = TaxType.objects.filter(is_active=True).select_related("department")


class VillageViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = VillageSerializer
    queryset = Village.objects.select_related("district__city__region__country")
    pagination_class = None


@api_view(["GET"])
def me(request):
    u = request.user
    return Response({
        "username": u.username, "name": u.get_full_name(), "employee_id": u.employee_id,
        "role": u.role, "department": u.department.name if u.department else None,
        "assigned_district": u.assigned_district_id,
    })


# --- Collector location tracking -------------------------------------------

class PingSerializer(serializers.Serializer):
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=-90, max_value=90)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=-180,
                                         max_value=180)
    altitude = serializers.DecimalField(max_digits=7, decimal_places=1, required=False,
                                        allow_null=True)
    accuracy = serializers.DecimalField(max_digits=7, decimal_places=1, required=False,
                                        allow_null=True)
    recorded_at = serializers.DateTimeField(required=False)

    def validate_recorded_at(self, value):
        # Phones may send queued points after losing signal, but not from the future
        # or from long ago.
        now = timezone.now()
        if value > now + timedelta(minutes=5) or value < now - timedelta(hours=24):
            raise serializers.ValidationError("Time is out of range.")
        return value


def _round(value, places):
    return None if value is None else Decimal(value).quantize(Decimal(10) ** -places)


@api_view(["POST"])
def tracking_ping(request):
    """
    Save one position, or a batch queued while offline:
    {"latitude": 9.56, "longitude": 44.07, "altitude": 1334, "accuracy": 12}
    {"pings": [{...}, {...}]}
    Only accepted while the collector has an open duty shift.
    """
    if not request.user.can_collect:
        return Response(status=status.HTTP_403_FORBIDDEN)
    shift = DutyShift.open_for(request.user)
    if not shift:
        return Response({"detail": "No open shift."}, status=status.HTTP_409_CONFLICT)
    items = request.data.get("pings") if isinstance(request.data, dict) else None
    serializer = PingSerializer(data=items if items is not None else [request.data], many=True)
    serializer.is_valid(raise_exception=True)
    pings = [
        LocationPing(
            collector=request.user, shift=shift,
            recorded_at=max(p.get("recorded_at") or timezone.now(), shift.started_at),
            latitude=_round(p["latitude"], 6), longitude=_round(p["longitude"], 6),
            altitude=_round(p.get("altitude"), 1), accuracy=_round(p.get("accuracy"), 1),
        )
        for p in serializer.validated_data[:500]
    ]
    LocationPing.objects.bulk_create(pings)
    return Response({"saved": len(pings)}, status=status.HTTP_201_CREATED)


@api_view(["GET", "POST"])
def tracking_shift(request):
    """GET: current shift. POST {"action": "start"} or {"action": "end"} (for a mobile app)."""
    if not request.user.can_collect:
        return Response(status=status.HTTP_403_FORBIDDEN)
    shift = DutyShift.open_for(request.user)
    if request.method == "POST":
        action_name = request.data.get("action")
        if action_name == "start" and not shift:
            shift = DutyShift.objects.create(collector=request.user)
            AuditLog.record(request, "shift.start", shift, via="api")
        elif action_name == "end" and shift:
            shift.ended_at = timezone.now()
            shift.save(update_fields=["ended_at"])
            AuditLog.record(request, "shift.end", shift, via="api")
            shift = None
        elif action_name not in ("start", "end"):
            return Response({"action": ["Use 'start' or 'end'."]},
                            status=status.HTTP_400_BAD_REQUEST)
    return Response({"on_shift": bool(shift),
                     "started_at": shift.started_at if shift else None})
