import logging
from decimal import Decimal
from smtplib import SMTPException
from datetime import timedelta

from django.core.mail import send_mail
from django.db.models import Sum
from django.utils import timezone

from .models import CreditEntry, Customer, Payment, ReminderLog, ShopProfile


logger = logging.getLogger(__name__)


def get_customer_balances():
    credit_totals = {
        row["customer_id"]: row["total"] or Decimal("0.00")
        for row in CreditEntry.objects.values("customer_id").annotate(
            total=Sum("amount")
        )
    }
    payment_totals = {
        row["customer_id"]: row["total"] or Decimal("0.00")
        for row in Payment.objects.filter(acknowledged=True)
        .values("customer_id")
        .annotate(total=Sum("amount"))
    }

    balances = []
    for customer in Customer.objects.order_by("name", "id"):
        credit = credit_totals.get(customer.id, Decimal("0.00"))
        paid = payment_totals.get(customer.id, Decimal("0.00"))
        balances.append({
            "customer": customer,
            "credit": credit,
            "paid": paid,
            "balance": credit - paid,
        })
    return balances


def get_reminder_candidates(profile=None, today=None):
    profile = profile or ShopProfile.objects.first()
    today = today or timezone.localdate()
    lead_days = profile.reminder_days_before_due if profile else 2
    due_through = today + timedelta(days=lead_days)
    due_customer_ids = set(
        CreditEntry.objects.filter(due_date__lte=due_through)
        .values_list("customer_id", flat=True)
        .distinct()
    )

    candidates = [
        row for row in get_customer_balances()
        if row["balance"] > 0 and row["customer"].id in due_customer_ids
    ]
    due_dates = {}
    due_date_rows = (
        CreditEntry.objects.filter(
            customer_id__in=[row["customer"].id for row in candidates],
            due_date__lte=due_through,
        )
        .values("customer_id", "due_date")
        .order_by("due_date")
    )
    for row in due_date_rows:
        due_dates.setdefault(row["customer_id"], row["due_date"])
    for row in candidates:
        row["next_due_date"] = due_dates.get(row["customer"].id)
        row["is_overdue"] = bool(
            row["next_due_date"] and row["next_due_date"] < today
        )
    return candidates


def send_customer_email_reminder(customer, profile, balance, today=None):
    today = today or timezone.localdate()
    shop_name = profile.shop_name if profile else "Your local shop"
    subject = f"Payment reminder from {shop_name}"
    body = (
        f"Dear {customer.name},\n\n"
        f"This is a friendly reminder that your outstanding balance "
        f"with {shop_name} is ₹{balance:.2f}.\n"
        "Please contact the shop if you have already made this payment "
        "or would like to discuss your account.\n\n"
        "Thank you."
    )

    try:
        sent_count = send_mail(
            subject,
            body,
            None,
            [customer.email],
            fail_silently=False,
        )
        if sent_count != 1:
            raise OSError("Email backend did not confirm delivery.")
    except (SMTPException, OSError) as error:
        ReminderLog.objects.create(
            customer=customer,
            reminder_type="email",
            scheduled_for=today,
            status="failed",
            notes=str(error)[:2000],
        )
        logger.exception("Email reminder failed for customer %s", customer.pk)
        return False

    ReminderLog.objects.create(
        customer=customer,
        reminder_type="email",
        scheduled_for=today,
        sent_at=timezone.now(),
        status="sent",
        notes="Email accepted by the configured backend; inbox delivery is not confirmed.",
    )
    return True
