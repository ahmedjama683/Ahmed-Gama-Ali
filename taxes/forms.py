from django import forms

from locations.models import Village

from .models import TaxCollection, TaxType, Taxpayer


class CollectionForm(forms.ModelForm):
    class Meta:
        model = TaxCollection
        fields = [
            "client_uuid", "taxpayer", "payer_name", "payer_phone", "tax_type",
            "period_start", "period_end", "currency", "tax_amount",
            "discount_type", "discount_value", "discount_reason",
            "payment_method", "transaction_reference", "village",
            "latitude", "longitude", "altitude", "gps_accuracy", "notes",
        ]
        widgets = {
            "client_uuid": forms.HiddenInput,
            "latitude": forms.HiddenInput,
            "longitude": forms.HiddenInput,
            "altitude": forms.HiddenInput,
            "gps_accuracy": forms.HiddenInput,
            "period_start": forms.DateInput(attrs={"type": "date"}),
            "period_end": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
            "tax_amount": forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.01"}),
            "discount_value": forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.01"}),
        }

    def __init__(self, *args, collector=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.collector = collector
        self.fields["taxpayer"].required = False
        self.fields["taxpayer"].queryset = Taxpayer.objects.filter(is_active=True)
        self.fields["taxpayer"].help_text = "Leave empty for a walk-in payer."
        tax_types = TaxType.objects.filter(is_active=True).select_related("department")
        # Collectors only see the taxes of their own department.
        if collector is not None and collector.is_collector and collector.department_id:
            tax_types = tax_types.filter(department_id=collector.department_id)
        self.fields["tax_type"].queryset = tax_types
        villages = Village.objects.select_related("district")
        # Collectors assigned to a district only record payments inside it.
        if collector is not None and collector.is_collector and collector.assigned_district_id:
            villages = villages.filter(district_id=collector.assigned_district_id)
        self.fields["village"].queryset = villages
        for name, field in self.fields.items():
            if not isinstance(field.widget, forms.HiddenInput):
                field.widget.attrs.setdefault("class", "input")

    def _post_clean(self):
        # Attach the collector before model.clean() runs its discount-limit check.
        if self.collector is not None:
            self.instance.collector = self.collector
        super()._post_clean()


class VoidForm(forms.Form):
    reason = forms.CharField(
        max_length=255, widget=forms.TextInput(attrs={"class": "input", "autofocus": True})
    )


class TaxpayerForm(forms.ModelForm):
    class Meta:
        model = Taxpayer
        fields = [
            "kind", "name", "business_name", "national_id", "phone", "village",
            "address", "property_number", "latitude", "longitude",
        ]
        widgets = {"latitude": forms.HiddenInput, "longitude": forms.HiddenInput}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["village"].queryset = Village.objects.select_related("district")
        for field in self.fields.values():
            if not isinstance(field.widget, forms.HiddenInput):
                field.widget.attrs.setdefault("class", "input")


class CollectionFilterForm(forms.Form):
    q = forms.CharField(required=False, label="Search")
    date_from = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    status = forms.ChoiceField(
        required=False, choices=[("", "Any status")] + list(TaxCollection.Status.choices)
    )
    payment_method = forms.ChoiceField(
        required=False,
        choices=[("", "Any payment")] + list(TaxCollection._meta.get_field("payment_method").choices),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "input")
