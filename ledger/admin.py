
from django.contrib import admin
from .models import (
    CreditEntry,
    CreditItem,
    Customer,
    OwnerProfile,
    Payment,
    ReminderLog,
    ShopProfile,
)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "phone", "created_at")
    search_fields = ("name", "phone")


@admin.register(CreditEntry)
class CreditEntryAdmin(admin.ModelAdmin):
    list_display = (
        "id", "bill_number", "customer", "amount", "date_given", "due_date"
    )
    search_fields = ("bill_number", "customer__name", "customer__phone", "items_description")
    list_filter = ("due_date", "date_given")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "customer",
        "amount",
        "payment_date",
        "acknowledged",
        "acknowledged_at",
    )
    search_fields = ("customer__name", "customer__phone", "note")
    list_filter = ("payment_date", "acknowledged")


@admin.register(CreditItem)
class CreditItemAdmin(admin.ModelAdmin):
    list_display = ("id", "credit_entry", "item_name", "quantity", "unit", "unit_price")
    search_fields = ("credit_entry__bill_number", "credit_entry__customer__name", "item_name")


@admin.register(ShopProfile)
class ShopProfileAdmin(admin.ModelAdmin):
    list_display = ("shop_name", "phone", "email", "gstin", "updated_at")


@admin.register(OwnerProfile)
class OwnerProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "phone", "alternate_phone")
    search_fields = ("user__username", "user__first_name", "user__last_name", "phone")


@admin.register(ReminderLog)
class ReminderLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "customer",
        "reminder_type",
        "scheduled_for",
        "status",
        "sent_at",
    )
    search_fields = ("customer__name", "customer__phone", "notes")
    list_filter = ("reminder_type", "scheduled_for", "status")
