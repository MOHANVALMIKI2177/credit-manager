
import csv
import re
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Sum, Q
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from .forms import (
    CreditEntryForm,
    CustomerForm,
    OwnerSignupForm,
    PaymentForm,
    ReportFilterForm,
    ShopProfileForm,
)
from .models import (
    CreditEntry,
    Customer,
    Payment,
    OwnerProfile,
    ReminderLog,
    ShopProfile,
    normalize_phone_number,
)
from .services import (
    get_customer_balances,
    get_reminder_candidates,
    send_customer_email_reminder,
)


# --------------------------------------------------
# PUBLIC LANDING PAGE
# --------------------------------------------------

def landing(request):
    """Display the public landing page."""
    if request.user.is_authenticated:
        return redirect("dashboard")

    return render(
        request,
        "ledger/landing.html",
        {"owner_signup_available": not get_user_model().objects.exists()},
    )


def owner_signup(request):
    """Create the first owner or let a signed-in owner add another login."""
    is_additional_account = request.user.is_authenticated
    user_model = get_user_model()
    if not is_additional_account and user_model.objects.exists():
        messages.info(request, "An owner account already exists. Please sign in.")
        return redirect("login")

    form = OwnerSignupForm(
        request.POST or None,
        include_shop_fields=not is_additional_account,
    )
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            if not is_additional_account and user_model.objects.exists():
                messages.info(
                    request,
                    "An owner account was just created. Please sign in.",
                )
                return redirect("login")
            user = form.save()
            OwnerProfile.objects.create(
                user=user,
                phone=form.cleaned_data["owner_phone"],
                alternate_phone=form.cleaned_data["alternate_phone"],
            )
            if not is_additional_account:
                ShopProfile.objects.update_or_create(
                    pk=1,
                    defaults={
                        "shop_name": form.cleaned_data["shop_name"],
                        "phone": form.cleaned_data["shop_phone"],
                        "email": form.cleaned_data["shop_email"],
                        "address": form.cleaned_data["shop_address"],
                        "gstin": form.cleaned_data["shop_gstin"],
                    },
                )

        if is_additional_account:
            messages.success(
                request,
                f"Account '{user.get_username()}' created successfully.",
            )
        else:
            login(request, user)
            messages.success(request, "Owner account created. Welcome!")
        return redirect("dashboard")

    return render(
        request,
        "registration/signup.html",
        {
            "form": form,
            "is_additional_account": is_additional_account,
            "shop_profile": ShopProfile.objects.first() if is_additional_account else None,
        },
    )


def generate_bill_number():
    """Generate a unique bill number for a new credit record."""
    today = timezone.localdate().strftime("%Y%m%d")
    prefix = f"SJ-{today}-"
    recent = CreditEntry.objects.filter(bill_number__startswith=prefix).count() + 1
    return f"{prefix}{recent:04d}"


# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------

@login_required
def dashboard(request):
    """Display the shop owner's summary dashboard."""

    total_credit = (
        CreditEntry.objects.aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )

    total_payments = (
        Payment.objects.filter(acknowledged=True)
        .aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )

    today = timezone.localdate()
    customer_balances = get_customer_balances()
    customer_count = len(customer_balances)
    positive_balance_ids = {
        row["customer"].id
        for row in customer_balances
        if row["balance"] > 0
    }
    overdue_customer_ids = set(
        CreditEntry.objects.filter(due_date__lt=today)
        .values_list("customer_id", flat=True)
        .distinct()
    )
    overdue_count = len(positive_balance_ids & overdue_customer_ids)

    recent_entries = (
        CreditEntry.objects.select_related("customer")
        .order_by("-created_at", "-id")[:5]
    )

    recent_payments = (
        Payment.objects.select_related("customer")
        .order_by("-payment_date", "-id")[:5]
    )

    context = {
        "total_credit": total_credit,
        "total_payments": total_payments,
        "total_outstanding": total_credit - total_payments,
        "customer_count": customer_count,
        "overdue_count": overdue_count,
        "recent_entries": recent_entries,
        "recent_payments": recent_payments,
    }

    return render(request, "ledger/dashboard.html", context)


# --------------------------------------------------
# ADD CUSTOMER
# --------------------------------------------------

def _mask_identifier(value, *, visible_start=0, visible_end=4):
    if not value:
        return ""
    value = str(value)
    visible = min(visible_start + visible_end, len(value))
    hidden_length = max(len(value) - visible, 0)
    return (
        value[:visible_start]
        + "•" * hidden_length
        + (value[-visible_end:] if visible_end else "")
    )


def _find_customer_matches(cleaned_data):
    phone_normalized = normalize_phone_number(cleaned_data.get("phone", ""))
    pan_number = cleaned_data.get("pan_number", "")
    gstin = cleaned_data.get("gstin", "")
    name = cleaned_data.get("name", "").strip()
    email = cleaned_data.get("email", "").strip()

    query = Q()
    if phone_normalized:
        query |= Q(phone_normalized=phone_normalized)
    if pan_number:
        query |= Q(pan_number=pan_number)
    if gstin:
        query |= Q(gstin=gstin)
    if name and email:
        query |= Q(name__iexact=name, email__iexact=email)
    if not query:
        return []

    customers = Customer.objects.filter(query).order_by("name", "id")
    balances = {
        row["customer"].id: row["balance"]
        for row in get_customer_balances()
    }
    matches = []
    for customer in customers:
        identifiers = []
        if phone_normalized and customer.phone_normalized == phone_normalized:
            identifiers.append("Mobile number")
        if pan_number and customer.pan_number == pan_number:
            identifiers.append(f"PAN ending {_mask_identifier(pan_number, visible_end=2)}")
        if gstin and customer.gstin == gstin:
            identifiers.append(f"GSTIN ending {_mask_identifier(gstin, visible_start=2)}")
        if (
            name
            and email
            and customer.name.casefold() == name.casefold()
            and customer.email.casefold() == email.casefold()
        ):
            identifiers.append("Name and email")
        matches.append({
            "customer": customer,
            "identifiers": identifiers,
            "has_unique_identifier_match": any(
                identifier.startswith(("PAN ", "GSTIN "))
                for identifier in identifiers
            ),
            "masked_phone": _mask_identifier(
                customer.phone,
                visible_end=4,
            ),
            "masked_pan": _mask_identifier(
                customer.pan_number,
                visible_start=2,
                visible_end=2,
            ),
            "masked_gstin": _mask_identifier(
                customer.gstin,
                visible_start=2,
                visible_end=4,
            ),
            "balance": balances.get(customer.id, Decimal("0.00")),
        })
    return matches


def _customer_form_context(form, *, matches=None, submitted_details=None):
    return {
        "form": form,
        "page_title": "Add Customer",
        "duplicate_matches": matches or [],
        "submitted_details": submitted_details or {},
        "block_separate_customer": any(
            match["has_unique_identifier_match"] for match in (matches or [])
        ),
    }


def _submitted_customer_details(cleaned_data):
    return {
        "name": cleaned_data.get("name", ""),
        "phone": _mask_identifier(cleaned_data.get("phone", ""), visible_end=4),
        "email": cleaned_data.get("email", ""),
        "pan_number": _mask_identifier(
            cleaned_data.get("pan_number", ""),
            visible_start=2,
            visible_end=2,
        ),
        "gstin": _mask_identifier(
            cleaned_data.get("gstin", ""),
            visible_start=2,
            visible_end=4,
        ),
    }


@login_required
def customer_create(request):
    """Add a new customer."""

    if request.method == "POST":
        form = CustomerForm(request.POST)

        if form.is_valid():
            matches = _find_customer_matches(form.cleaned_data)
            blocked_by_unique_identifier = any(
                match["has_unique_identifier_match"] for match in matches
            )
            confirmed_separate = (
                request.POST.get("confirm_separate") == "yes"
            )

            if matches and (
                not confirmed_separate or blocked_by_unique_identifier
            ):
                return render(
                    request,
                    "ledger/customer_form.html",
                    _customer_form_context(
                        form,
                        matches=matches,
                        submitted_details=_submitted_customer_details(
                            form.cleaned_data
                        ),
                    ),
                )

            try:
                with transaction.atomic():
                    customer = form.save()
            except IntegrityError:
                form.add_error(
                    None,
                    "A customer with this PAN or GSTIN may have been "
                    "registered at the same time. Review existing accounts "
                    "before trying again.",
                )
                matches = _find_customer_matches(form.cleaned_data)
                return render(
                    request,
                    "ledger/customer_form.html",
                    _customer_form_context(
                        form,
                        matches=matches,
                        submitted_details=_submitted_customer_details(
                            form.cleaned_data
                        ),
                    ),
                )

            messages.success(
                request,
                f"Customer {customer.customer_code} — {customer.name} was added successfully."
            )
            return redirect("customers")
    else:
        form = CustomerForm()

    return render(
        request,
        "ledger/customer_form.html",
        _customer_form_context(form),
    )


# --------------------------------------------------
# CUSTOMER DIRECTORY
# --------------------------------------------------

@login_required
def customers_page(request):
    """Display customers with their individual balances."""

    search_query = request.GET.get("search", "").strip()

    customers = Customer.objects.all().order_by("name")

    if search_query:
        filters = (
            Q(name__icontains=search_query)
            | Q(phone__icontains=search_query)
        )
        normalized_search = normalize_phone_number(search_query)
        if normalized_search:
            filters |= Q(phone_normalized__icontains=normalized_search)
        customer_code_match = re.fullmatch(
            r"CUST-(\d+)",
            search_query,
            flags=re.IGNORECASE,
        )
        if customer_code_match:
            filters |= Q(pk=int(customer_code_match.group(1)))
        customers = customers.filter(filters)

    customer_rows = get_customer_balances()
    if search_query:
        matching_customer_ids = set(customers.values_list("id", flat=True))
        customer_rows = [
            row for row in customer_rows
            if row["customer"].id in matching_customer_ids
        ]

    return render(
        request,
        "ledger/customers.html",
        {
            "customer_rows": customer_rows,
            "search_query": search_query,
        },
    )


# --------------------------------------------------
# ADD CREDIT / NEW PURCHASE
# --------------------------------------------------

@login_required
def credit_create(request):
    """Create a new credit bill with its amount and optional note."""

    if request.method == "POST":
        form = CreditEntryForm(request.POST)

        if form.is_valid():
            with transaction.atomic():
                bill_number = generate_bill_number()
                CreditEntry.objects.create(
                    customer=form.cleaned_data["customer"],
                    bill_number=bill_number,
                    items_description=form.cleaned_data["note"],
                    amount=form.cleaned_data["amount"],
                    date_given=form.cleaned_data["date_given"],
                    due_date=form.cleaned_data["due_date"],
                )

            messages.success(request, f"Bill {bill_number} saved successfully.")
            return redirect("credits")
    else:
        today = timezone.localdate()
        initial = {
            "date_given": today,
            "due_date": today + timedelta(days=7),
        }
        customer_id = request.GET.get("customer_id", "").strip()
        if customer_id.isdigit() and Customer.objects.filter(pk=customer_id).exists():
            initial["customer"] = customer_id
        form = CreditEntryForm(
            initial=initial
        )

    return render(
        request,
        "ledger/credit_form.html",
        {
            "form": form,
            "page_title": "Add Credit / New Purchase",
        },
    )


# --------------------------------------------------
# CREDIT HISTORY
# --------------------------------------------------

@login_required
def credits_page(request):
    """Display all credit entries."""

    entries = (
        CreditEntry.objects.select_related("customer")
        .order_by("-created_at", "-id")
    )

    return render(
        request,
        "ledger/credits.html",
        {"entries": entries},
    )


# --------------------------------------------------
# PAYMENTS PAGE
# --------------------------------------------------

@login_required
def payments_page(request):
    """Display pending and acknowledged payments."""

    payments = (
        Payment.objects.select_related("customer")
        .order_by("-payment_date", "-id")
    )

    pending_payments = payments.filter(acknowledged=False)
    confirmed_payments = payments.filter(acknowledged=True)

    return render(
        request,
        "ledger/payments.html",
        {
            "payments": payments,
            "pending_payments": pending_payments,
            "confirmed_payments": confirmed_payments,
        },
    )


# --------------------------------------------------
# RECORD PAYMENT
# --------------------------------------------------

@login_required
def record_payment(request):
    """Record a payment pending the shop owner's acknowledgement."""

    if request.method == "POST":
        form = PaymentForm(request.POST)

        if form.is_valid():
            payment = form.save(commit=False)

            # A newly recorded payment is not counted as received yet.
            payment.acknowledged = False
            payment.acknowledged_at = None
            payment.save()

            messages.success(
                request,
                "Payment recorded. Please acknowledge receipt "
                "to include it in the customer's paid total."
            )

            return redirect("payments")
    else:
        form = PaymentForm()

    return render(
        request,
        "ledger/payment_form.html",
        {
            "form": form,
            "page_title": "Record Payment",
        },
    )


# --------------------------------------------------
# ACKNOWLEDGE PAYMENT
# --------------------------------------------------

@login_required
def acknowledge_payment(request, payment_id):
    """Acknowledge a payment after verifying receipt."""

    if request.method != "POST":
        return redirect("payments")

    payment = get_object_or_404(Payment, pk=payment_id)

    if not payment.acknowledged:
        payment.acknowledged = True
        payment.acknowledged_at = timezone.now()

        payment.save(
            update_fields=[
                "acknowledged",
                "acknowledged_at",
            ]
        )

        messages.success(
            request,
            f"Payment of ₹{payment.amount} acknowledged successfully."
        )
    else:
        messages.info(
            request,
            "This payment has already been acknowledged."
        )

    return redirect("payments")


# --------------------------------------------------
# CUSTOMER STATEMENT
# --------------------------------------------------

@login_required
def customer_statement(request, customer_id):
    """Display the selected customer's credit and payment history."""

    customer = get_object_or_404(Customer, pk=customer_id)

    # Only this customer's credit records.
    credit_entries = (
        CreditEntry.objects.filter(customer=customer)
        .prefetch_related("items")
        .order_by("-created_at", "-id")
    )

    # Only this customer's payment records.
    payments = (
        Payment.objects.filter(customer=customer)
        .order_by("-payment_date", "-id")
    )

    total_credit = (
        credit_entries.aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )

    # Pending payments are excluded.
    total_paid = (
        payments.filter(acknowledged=True)
        .aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )

    balance_due = total_credit - total_paid

    context = {
        "customer": customer,
        "credit_entries": credit_entries,
        "credits": credit_entries,
        "payments": payments,
        "total_credit": total_credit,
        "total_paid": total_paid,
        "balance_due": balance_due,
    }

    return render(
        request,
        "ledger/customer_statement.html",
        context,
    )


# --------------------------------------------------
# REMINDER CENTRE
# --------------------------------------------------

@login_required
def reminders_page(request):
    """Show balances due soon and the reminder delivery history."""
    profile, _ = ShopProfile.objects.get_or_create(pk=1)
    today = timezone.localdate()
    candidates = get_reminder_candidates(profile=profile, today=today)
    logs = (
        ReminderLog.objects.select_related("customer")
        .order_by("-created_at", "-id")[:50]
    )

    return render(
        request,
        "ledger/reminders.html",
        {
            "profile": profile,
            "today": today,
            "candidates": candidates,
            "reminder_logs": logs,
            "console_email_backend": settings.EMAIL_BACKEND
            == "django.core.mail.backends.console.EmailBackend",
        },
    )


@login_required
def send_reminder(request, customer_id):
    """Send one manually requested reminder to a customer by email."""
    if request.method != "POST":
        return redirect("reminders")

    profile, _ = ShopProfile.objects.get_or_create(pk=1)
    customer = get_object_or_404(Customer, pk=customer_id)

    if not profile.enable_email_reminders:
        messages.error(
            request,
            "Email reminders are disabled. Enable them in Shop Settings first.",
        )
        return redirect("reminders")
    if not customer.email:
        messages.error(
            request,
            f"{customer.name} does not have an email address on their account.",
        )
        return redirect("reminders")

    today = timezone.localdate()
    if ReminderLog.objects.filter(
        customer=customer,
        reminder_type="email",
        scheduled_for=today,
        status="sent",
    ).exists():
        messages.info(
            request,
            "An email reminder for this customer has already been accepted today.",
        )
        return redirect("reminders")

    candidate = next(
        (
            row for row in get_reminder_candidates(profile=profile)
            if row["customer"].id == customer.id
        ),
        None,
    )
    if candidate is None:
        messages.error(
            request,
            "This customer has no outstanding balance with a due or overdue bill.",
        )
        return redirect("reminders")

    sent = send_customer_email_reminder(
        customer,
        profile,
        candidate["balance"],
        today=today,
    )
    if sent:
        messages.success(
            request,
            f"Reminder email was accepted by the configured email backend for {customer.email}.",
        )
    else:
        messages.error(
            request,
            "The reminder email could not be sent. Check the email backend and review reminder history.",
        )
    return redirect("reminders")


# --------------------------------------------------
# REPORTS
# --------------------------------------------------

def _get_report_data(start_date, end_date):
    credit_entries = (
        CreditEntry.objects.filter(
            date_given__gte=start_date,
            date_given__lte=end_date,
        )
        .select_related("customer")
        .prefetch_related("items")
        .order_by("date_given", "id")
    )
    payments = (
        Payment.objects.filter(
            payment_date__gte=start_date,
            payment_date__lte=end_date,
        )
        .select_related("customer")
        .order_by("payment_date", "id")
    )
    credit_summary = credit_entries.aggregate(total=Sum("amount"))
    payment_summary = payments.filter(acknowledged=True).aggregate(
        total=Sum("amount")
    )
    pending_summary = payments.filter(acknowledged=False).aggregate(
        total=Sum("amount")
    )
    daily_activity = {}
    for row in credit_entries.order_by().values("date_given").annotate(
        total=Sum("amount")
    ):
        daily_activity[row["date_given"]] = {
            "date": row["date_given"],
            "credit": row["total"] or Decimal("0.00"),
            "collections": Decimal("0.00"),
        }
    for row in payments.filter(acknowledged=True).order_by().values(
        "payment_date"
    ).annotate(total=Sum("amount")):
        activity = daily_activity.setdefault(
            row["payment_date"],
            {
                "date": row["payment_date"],
                "credit": Decimal("0.00"),
                "collections": Decimal("0.00"),
            },
        )
        activity["collections"] = row["total"] or Decimal("0.00")
    for activity in daily_activity.values():
        activity["net"] = activity["credit"] - activity["collections"]

    customer_rows = get_customer_balances()
    overdue_customer_ids = set(
        CreditEntry.objects.filter(due_date__lt=timezone.localdate())
        .values_list("customer_id", flat=True)
        .distinct()
    )
    for row in customer_rows:
        row["has_overdue_bill"] = (
            row["balance"] > 0 and row["customer"].id in overdue_customer_ids
        )
    customer_rows.sort(key=lambda row: (-row["balance"], row["customer"].name.lower()))

    return {
        "credit_entries": credit_entries,
        "payments": payments,
        "daily_activity": sorted(
            daily_activity.values(),
            key=lambda row: row["date"],
            reverse=True,
        ),
        "period_credit": credit_summary["total"] or Decimal("0.00"),
        "period_collections": payment_summary["total"] or Decimal("0.00"),
        "pending_payments": pending_summary["total"] or Decimal("0.00"),
        "customer_rows": customer_rows,
        "total_outstanding": sum(
            (row["balance"] for row in customer_rows),
            Decimal("0.00"),
        ),
        "overdue_accounts": sum(
            1 for row in customer_rows if row["has_overdue_bill"]
        ),
    }


def _build_report_csv(report_data, start_date, end_date):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="credit-report-{start_date:%Y%m%d}-{end_date:%Y%m%d}.csv"'
    )
    response.write("\ufeff")
    writer = csv.writer(response)
    def write_row(values):
        writer.writerow([
            f"'{value}" if isinstance(value, str) and value.lstrip()[:1] in "=+-@\t\r"
            else value
            for value in values
        ])

    write_row([
        "Record type",
        "Date",
        "Reference",
        "Customer ID",
        "Customer",
        "Details",
        "Status",
        "Amount (INR)",
    ])
    for entry in report_data["credit_entries"]:
        write_row([
            "Credit",
            entry.date_given.isoformat(),
            entry.bill_number,
            entry.customer_id,
            entry.customer.name,
            entry.items_description,
            "Recorded",
            entry.amount,
        ])
    for payment in report_data["payments"]:
        write_row([
            "Payment",
            payment.payment_date.isoformat(),
            f"PAY-{payment.pk}",
            payment.customer_id,
            payment.customer.name,
            payment.note,
            "Acknowledged" if payment.acknowledged else "Pending acknowledgement",
            payment.amount,
        ])

    writer.writerow([])
    write_row(["Customer balance summary (all dates)"])
    write_row(["Customer ID", "Customer", "Mobile", "Total credit", "Acknowledged payments", "Outstanding"])
    for row in report_data["customer_rows"]:
        write_row([
            row["customer"].id,
            row["customer"].name,
            row["customer"].phone,
            row["credit"],
            row["paid"],
            row["balance"],
        ])
    return response


@login_required
def reports_page(request):
    """Display date-filtered credit, collection, and balance reports."""
    today = timezone.localdate()
    first_of_month = today.replace(day=1)
    filters = ReportFilterForm(
        request.GET if request.GET else None,
        initial={"start_date": first_of_month, "end_date": today},
    )

    if request.GET and not filters.is_valid():
        report_data = None
        start_date = None
        end_date = None
    else:
        cleaned_data = filters.cleaned_data if request.GET else {}
        start_date = cleaned_data.get("start_date") or first_of_month
        end_date = cleaned_data.get("end_date") or today
        report_data = _get_report_data(start_date, end_date)
        if request.GET.get("export") == "csv":
            return _build_report_csv(report_data, start_date, end_date)

    return render(
        request,
        "ledger/reports.html",
        {
            "filters": filters,
            "start_date": start_date,
            "end_date": end_date,
            "report": report_data,
        },
    )


# --------------------------------------------------
# SHOP SETTINGS
# --------------------------------------------------

@login_required
def settings_page(request):
    """Manage shop preferences and reminder settings."""

    profile, _ = ShopProfile.objects.get_or_create(pk=1)

    if request.method == "POST":
        form = ShopProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Shop settings updated successfully.")
            return redirect("settings")
    else:
        form = ShopProfileForm(instance=profile)

    return render(
        request,
        "ledger/settings.html",
        {
            "form": form,
            "page_title": "Shop Settings",
        },
    )
