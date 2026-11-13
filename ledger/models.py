
from decimal import Decimal, ROUND_HALF_UP
import re

from django.conf import settings
from django.db import models
from django.utils import timezone


def normalize_phone_number(phone):
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("91") and len(digits) == 12:
        return digits[2:]
    if digits.startswith("0") and len(digits) == 11:
        return digits[1:]
    return digits


class Customer(models.Model):
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)
    phone_normalized = models.CharField(
        max_length=20,
        blank=True,
        default="",
        db_index=True,
    )
    email = models.EmailField(blank=True, default="")
    pan_number = models.CharField(max_length=10, blank=True, default="")
    gstin = models.CharField(max_length=15, blank=True, default="")
    address = models.CharField(max_length=250, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["pan_number"],
                condition=~models.Q(pan_number=""),
                name="unique_customer_pan_when_provided",
            ),
            models.UniqueConstraint(
                fields=["gstin"],
                condition=~models.Q(gstin=""),
                name="unique_customer_gstin_when_provided",
            ),
        ]

    @property
    def customer_code(self):
        return f"CUST-{self.pk:04d}" if self.pk else ""

    @property
    def registered_date(self):
        if not self.created_at:
            return None
        return timezone.localtime(self.created_at).date()

    def save(self, *args, **kwargs):
        self.phone_normalized = normalize_phone_number(self.phone)
        self.pan_number = re.sub(r"\s+", "", self.pan_number or "").upper()
        self.gstin = re.sub(r"\s+", "", self.gstin or "").upper()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            update_fields = set(update_fields)
            if "phone" in update_fields:
                update_fields.add("phone_normalized")
            kwargs["update_fields"] = update_fields
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.customer_code} — {self.name}" if self.pk else self.name


class CreditEntry(models.Model):
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="credit_entries",
    )
    bill_number = models.CharField(max_length=30, unique=True, blank=True, db_index=True)
    items_description = models.CharField(max_length=250)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date_given = models.DateField(default=timezone.now)
    due_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        bill_prefix = self.bill_number or "Credit bill"
        return f"{self.customer.name} - {bill_prefix} - ₹{self.amount}"


class Payment(models.Model):
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="payments",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_date = models.DateField(default=timezone.now)
    note = models.CharField(max_length=250, blank=True)

    # Payment acknowledgement by the shop owner
    acknowledged = models.BooleanField(default=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        status = "Acknowledged" if self.acknowledged else "Pending acknowledgement"
        return f"{self.customer.name} - ₹{self.amount} ({status})"


class CreditItem(models.Model):
    credit_entry = models.ForeignKey(
        CreditEntry,
        on_delete=models.CASCADE,
        related_name="items",
    )
    item_name = models.CharField(max_length=150)
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=3,
    )
    unit = models.CharField(max_length=20, default="pcs")
    unit_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    @property
    def line_total(self):
        return (self.quantity * self.unit_price).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

    def __str__(self):
        return self.item_name


class ShopProfile(models.Model):
    shop_name = models.CharField(max_length=150, default="SRI JAGADEESHWARI PROVISION STORES")
    phone = models.CharField(max_length=20, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    address = models.CharField(max_length=250, blank=True, default="")
    gstin = models.CharField(max_length=15, blank=True, default="")
    reminder_days_before_due = models.PositiveIntegerField(default=2)
    send_daily_reminders = models.BooleanField(default=False)
    enable_email_reminders = models.BooleanField(default=False)
    enable_sms_reminders = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.shop_name


class OwnerProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="owner_profile",
    )
    phone = models.CharField(max_length=20)
    alternate_phone = models.CharField(max_length=20, blank=True, default="")

    def __str__(self):
        return f"Owner contact for {self.user.get_username()}"


class ReminderLog(models.Model):
    STATUS_CHOICES = [
        ("queued", "Queued"),
        ("sent", "Sent"),
        ("failed", "Failed"),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="reminder_logs")
    reminder_type = models.CharField(max_length=20, choices=[("email", "Email"), ("sms", "SMS")], default="email")
    scheduled_for = models.DateField()
    sent_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="queued")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.customer.name} - {self.reminder_type} ({self.status})"
