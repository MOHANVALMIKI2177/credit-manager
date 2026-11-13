
import re
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import Customer, Payment, ShopProfile, normalize_phone_number


class CustomerChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, customer):
        return f"{customer.customer_code} — {customer.name} — {customer.phone}"


class OwnerSignupForm(UserCreationForm):
    full_name = forms.CharField(
        max_length=150,
        label="Owner full name",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "autocomplete": "name",
            "placeholder": "Enter your full name",
        }),
    )
    email = forms.EmailField(
        label="Owner email",
        widget=forms.EmailInput(attrs={
            "class": "form-control",
            "autocomplete": "email",
            "placeholder": "name@example.com",
        }),
    )
    owner_phone = forms.CharField(
        max_length=20,
        label="Owner phone number",
        widget=forms.TelInput(attrs={
            "class": "form-control",
            "autocomplete": "tel",
            "placeholder": "Enter your contact number",
        }),
    )
    alternate_phone = forms.CharField(
        max_length=20,
        required=False,
        label="Alternate phone number",
        widget=forms.TelInput(attrs={
            "class": "form-control",
            "autocomplete": "tel",
            "placeholder": "Optional alternate contact number",
        }),
    )
    shop_name = forms.CharField(
        max_length=150,
        label="Shop name",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "autocomplete": "organization",
            "placeholder": "Enter your shop name",
        }),
    )
    shop_phone = forms.CharField(
        max_length=20,
        required=False,
        label="Shop phone number",
        widget=forms.TelInput(attrs={
            "class": "form-control",
            "placeholder": "Optional shop contact number",
        }),
    )
    shop_email = forms.EmailField(
        required=False,
        label="Shop email",
        widget=forms.EmailInput(attrs={
            "class": "form-control",
            "placeholder": "Optional shop email",
        }),
    )
    shop_address = forms.CharField(
        max_length=250,
        required=False,
        label="Shop address",
        widget=forms.Textarea(attrs={
            "class": "form-control",
            "autocomplete": "street-address",
            "placeholder": "Optional shop address",
            "rows": 3,
        }),
    )
    shop_gstin = forms.CharField(
        max_length=15,
        required=False,
        label="Shop GSTIN",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Optional 15-character GSTIN",
        }),
    )

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username",)

    def __init__(self, *args, include_shop_fields=True, **kwargs):
        super().__init__(*args, **kwargs)
        if not include_shop_fields:
            for name in (
                "shop_name",
                "shop_phone",
                "shop_email",
                "shop_address",
                "shop_gstin",
            ):
                self.fields.pop(name)
        self.order_fields([
            "full_name",
            "username",
            "email",
            "owner_phone",
            "alternate_phone",
            "shop_name",
            "shop_phone",
            "shop_email",
            "shop_address",
            "shop_gstin",
            "password1",
            "password2",
        ])
        for name in ("username", "password1", "password2"):
            self.fields[name].widget.attrs["class"] = "form-control"

    def clean_full_name(self):
        full_name = " ".join(self.cleaned_data["full_name"].split())
        if not full_name:
            raise forms.ValidationError("Please enter the owner's full name.")
        return full_name

    def clean_owner_phone(self):
        return self._clean_phone("owner_phone", required=True)

    def clean_alternate_phone(self):
        return self._clean_phone("alternate_phone", required=False)

    def _clean_phone(self, field_name, *, required):
        phone = (self.cleaned_data.get(field_name) or "").strip()
        if not phone and required:
            raise forms.ValidationError("Please enter the owner's phone number.")
        if phone and not 7 <= len(normalize_phone_number(phone)) <= 15:
            raise forms.ValidationError("Enter a valid phone number.")
        return phone

    def clean_shop_gstin(self):
        gstin = re.sub(r"\s+", "", self.cleaned_data.get("shop_gstin", "")).upper()
        if gstin and not re.fullmatch(
            r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]",
            gstin,
        ):
            raise forms.ValidationError("Enter a valid 15-character GSTIN.")
        return gstin

    def save(self, commit=True):
        user = super().save(commit=False)
        first_name, _, last_name = self.cleaned_data["full_name"].partition(" ")
        user.first_name = first_name
        user.last_name = last_name
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
            self.save_m2m()
        return user


class CustomerForm(forms.ModelForm):
    def _get_validation_exclusions(self):
        excluded = super()._get_validation_exclusions()
        # Duplicate identifiers need a review card before the database rejects them.
        excluded.update({"pan_number", "gstin"})
        return excluded

    class Meta:
        model = Customer
        fields = [
            "name",
            "phone",
            "email",
            "pan_number",
            "gstin",
            "address",
        ]

        labels = {
            "name": "Customer full name",
            "phone": "Mobile number",
            "email": "Email address",
            "pan_number": "PAN number",
            "gstin": "GSTIN",
            "address": "Address",
        }

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Enter customer name",
                    "autocomplete": "name",
                }
            ),
            "phone": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Enter mobile number",
                    "autocomplete": "tel",
                    "inputmode": "tel",
                }
            ),
            "email": forms.EmailInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Enter email address (optional)",
                    "autocomplete": "email",
                }
            ),
            "pan_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Enter PAN only if needed",
                    "autocomplete": "off",
                    "maxlength": "10",
                }
            ),
            "gstin": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Enter GSTIN if applicable",
                    "autocomplete": "off",
                    "maxlength": "15",
                }
            ),
            "address": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "placeholder": "Enter address (optional)",
                    "autocomplete": "street-address",
                    "rows": "3",
                }
            ),
        }

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            raise forms.ValidationError("Please enter the customer's name.")
        return name

    def clean_phone(self):
        phone = (self.cleaned_data.get("phone") or "").strip()
        if not phone:
            raise forms.ValidationError(
                "Please enter the customer's mobile number."
            )
        if len(phone) > 20:
            raise forms.ValidationError(
                "The mobile number must be 20 characters or fewer."
            )

        normalized_phone = normalize_phone_number(phone)
        if not 7 <= len(normalized_phone) <= 15:
            raise forms.ValidationError("Please enter a valid mobile number.")

        return phone

    def clean_pan_number(self):
        pan_number = re.sub(
            r"\s+",
            "",
            self.cleaned_data.get("pan_number", ""),
        ).upper()
        if pan_number and not re.fullmatch(
            r"[A-Z]{5}[0-9]{4}[A-Z]",
            pan_number,
        ):
            raise forms.ValidationError(
                "Enter a valid 10-character PAN number."
            )
        return pan_number

    def clean_gstin(self):
        gstin = re.sub(
            r"\s+",
            "",
            self.cleaned_data.get("gstin", ""),
        ).upper()
        if gstin and not re.fullmatch(
            r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]",
            gstin,
        ):
            raise forms.ValidationError(
                "Enter a valid 15-character GSTIN."
            )
        return gstin


class CreditEntryForm(forms.Form):
    customer = CustomerChoiceField(
        queryset=Customer.objects.order_by("name", "id"),
        label="Select customer",
        widget=forms.Select(
            attrs={"class": "form-control customer-select"}
        ),
    )
    date_given = forms.DateField(
        label="Purchase date",
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    due_date = forms.DateField(
        label="Due date",
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    amount = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0.01,
        label="Bill Amount (₹)",
        widget=forms.NumberInput(
            attrs={
                "class": "form-control",
                "placeholder": "Enter total bill amount",
                "min": "0.01",
                "step": "0.01",
            }
        ),
    )
    note = forms.CharField(
        required=False,
        max_length=250,
        label="Note",
        help_text=(
            "Please ensure that all customer details and payment records are "
            "entered correctly. Use this section to add any important remarks "
            "or additional information related to the transaction for future "
            "reference."
        ),
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "placeholder": "Optional transaction remarks",
                "rows": 3,
            }
        ),
    )

    def clean(self):
        cleaned_data = super().clean()
        date_given = cleaned_data.get("date_given")
        due_date = cleaned_data.get("due_date")

        if date_given and due_date and due_date < date_given:
            raise forms.ValidationError(
                "The due date must be on or after the purchase date."
            )

        return cleaned_data


class PaymentForm(forms.ModelForm):
    customer = CustomerChoiceField(
        queryset=Customer.objects.order_by("name", "id"),
        label="Select customer",
        widget=forms.Select(
            attrs={"class": "form-control customer-select"}
        ),
    )

    class Meta:
        model = Payment
        fields = ["customer", "amount", "note"]

        labels = {
            "customer": "Select customer",
            "amount": "Payment amount (₹)",
            "note": "Payment note",
        }

        widgets = {
            "customer": forms.Select(attrs={
                "class": "form-control",
            }),
            "amount": forms.NumberInput(attrs={
                "class": "form-control",
                "placeholder": "Enter amount",
                "min": "0.01",
                "step": "0.01",
            }),
            "note": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Optional payment details",
            }),
        }

    def clean_amount(self):
        amount = self.cleaned_data["amount"]

        if amount <= 0:
            raise forms.ValidationError(
                "Payment amount must be greater than zero."
            )

        return amount


class ShopProfileForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["send_daily_reminders"].help_text = (
            "Daily email delivery runs through the process_reminders command."
        )
        self.fields["enable_email_reminders"].help_text = (
            "Email delivery uses the configured Django email backend."
        )

    def clean_gstin(self):
        gstin = re.sub(r"\s+", "", self.cleaned_data.get("gstin", "")).upper()
        if gstin and not re.fullmatch(
            r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]",
            gstin,
        ):
            raise forms.ValidationError("Enter a valid 15-character GSTIN.")
        return gstin

    class Meta:
        model = ShopProfile
        fields = [
            "shop_name",
            "phone",
            "email",
            "address",
            "gstin",
            "reminder_days_before_due",
            "send_daily_reminders",
            "enable_email_reminders",
        ]

        widgets = {
            "shop_name": forms.TextInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "gstin": forms.TextInput(attrs={"class": "form-control"}),
            "reminder_days_before_due": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "send_daily_reminders": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "enable_email_reminders": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_reminder_days_before_due(self):
        days = self.cleaned_data["reminder_days_before_due"]
        if days < 1:
            raise forms.ValidationError(
                "Reminder lead time must be at least one day."
            )
        return days


class ReportFilterForm(forms.Form):
    start_date = forms.DateField(
        required=False,
        label="From",
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    end_date = forms.DateField(
        required=False,
        label="To",
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        if start_date and end_date and start_date > end_date:
            raise forms.ValidationError(
                "The start date must be on or before the end date."
            )
        return cleaned_data
