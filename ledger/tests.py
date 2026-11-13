from io import StringIO
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .forms import CreditEntryForm
from .models import CreditEntry, Customer, Payment, ReminderLog, ShopProfile


class CustomerAccountFlowTests(TestCase):
    def setUp(self):
        owner = get_user_model().objects.create_user(
            username="shop-owner",
            password="test-password",
        )
        self.client.force_login(owner)
        self.customer = Customer.objects.create(
            name="Ramesh Kumar",
            phone="9876543210",
        )

    def test_duplicate_mobile_shows_review_before_creating_an_account(self):
        CreditEntry.objects.create(
            customer=self.customer,
            items_description="Existing groceries",
            amount=Decimal("45.00"),
            date_given="2026-10-01",
            due_date="2026-10-08",
        )
        response = self.client.post(
            reverse("customer_create"),
            {
                "name": "Ramesh Kumar",
                "phone": "+91 98765-43210",
                "email": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A customer with matching details may already exist")
        self.assertContains(response, self.customer.customer_code)
        self.assertContains(response, "Outstanding ₹45.00")
        self.assertContains(response, "Use Existing Customer")
        self.assertContains(response, "Create Separate Customer")
        self.assertNotContains(response, "9876543210")
        self.assertEqual(Customer.objects.count(), 1)


    def test_owner_can_confirm_shared_phone_for_a_different_person(self):
        response = self.client.post(
            reverse("customer_create"),
            {
                "name": "Ramesh Kumar's Family Member",
                "phone": "09876543210",
                "email": "",
            },
        )
        self.assertContains(
            response,
            "Create Separate Customer",
        )

        response = self.client.post(
            reverse("customer_create"),
            {
                "name": "Ramesh Kumar's Family Member",
                "phone": "09876543210",
                "email": "",
                "confirm_separate": "yes",
            },
        )
        self.assertRedirects(response, reverse("customers"))
        self.assertEqual(Customer.objects.count(), 2)
        new_customer = Customer.objects.get(name="Ramesh Kumar's Family Member")
        self.assertEqual(new_customer.phone_normalized, "9876543210")

    def test_same_name_without_matching_contact_is_not_blocked(self):
        response = self.client.post(
            reverse("customer_create"),
            {
                "name": "Ramesh Kumar",
                "phone": "9123456780",
                "email": "another@example.com",
            },
        )
        self.assertRedirects(response, reverse("customers"))
        self.assertEqual(Customer.objects.count(), 2)

    def test_registration_saves_optional_details_in_normalized_form(self):
        response = self.client.post(
            reverse("customer_create"),
            {
                "name": "New Customer",
                "phone": "+91 91234 56780",
                "email": "new@example.com",
                "pan_number": "abcde1234f",
                "gstin": "29abcde1234f1z5",
                "address": "Market Road",
            },
        )

        self.assertRedirects(response, reverse("customers"))
        customer = Customer.objects.get(name="New Customer")
        self.assertEqual(customer.customer_code, f"CUST-{customer.pk:04d}")
        self.assertEqual(customer.phone_normalized, "9123456780")
        self.assertEqual(customer.pan_number, "ABCDE1234F")
        self.assertEqual(customer.gstin, "29ABCDE1234F1Z5")
        self.assertEqual(customer.address, "Market Road")
        self.assertIsNotNone(customer.registered_date)

    def test_duplicate_pan_is_reviewed_and_never_created_as_separate_account(self):
        self.customer.pan_number = "ABCDE1234F"
        self.customer.save()

        response = self.client.post(
            reverse("customer_create"),
            {
                "name": "Different Person",
                "phone": "9123456780",
                "email": "",
                "pan_number": "abcde1234f",
                "gstin": "",
                "address": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A PAN or GSTIN is already assigned")
        self.assertContains(response, "PAN ending")
        self.assertNotContains(response, "ABCDE1234F")
        self.assertEqual(Customer.objects.count(), 1)
        self.assertEqual(Customer.objects.get().pan_number, "ABCDE1234F")

        response = self.client.post(
            reverse("customer_create"),
            {
                "name": "Different Person",
                "phone": "9123456780",
                "email": "",
                "pan_number": "abcde1234f",
                "gstin": "",
                "address": "",
                "confirm_separate": "yes",
            },
        )
        self.assertContains(response, "A PAN or GSTIN is already assigned")
        self.assertEqual(Customer.objects.count(), 1)

    def test_invalid_pan_and_gstin_are_rejected(self):
        response = self.client.post(
            reverse("customer_create"),
            {
                "name": "Invalid IDs",
                "phone": "9123456780",
                "email": "",
                "pan_number": "not-a-pan",
                "gstin": "not-a-gstin",
                "address": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter a valid 10-character PAN number.")
        self.assertContains(response, "Enter a valid 15-character GSTIN.")
        self.assertEqual(Customer.objects.count(), 1)

    def test_pan_and_gstin_uniqueness_is_enforced_by_database(self):
        Customer.objects.create(
            name="PAN Holder",
            phone="9123456780",
            pan_number="ABCDE1234F",
            gstin="29ABCDE1234F1Z5",
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            Customer.objects.create(
                name="Other PAN Holder",
                phone="9123456781",
                pan_number="ABCDE1234F",
            )

        with self.assertRaises(IntegrityError), transaction.atomic():
            Customer.objects.create(
                name="Other GST Holder",
                phone="9123456782",
                gstin="29ABCDE1234F1Z5",
            )

    def test_customer_short_id_is_stable_and_selector_includes_it(self):
        self.assertEqual(self.customer.customer_code, f"CUST-{self.customer.pk:04d}")

    def test_customer_selectors_identify_the_account_id(self):
        form = CreditEntryForm()
        customer_label = next(
            label
            for value, label in form.fields["customer"].choices
            if str(value) == str(self.customer.pk)
        )

        self.assertIn(self.customer.name, customer_label)
        self.assertIn(self.customer.phone, customer_label)
        self.assertIn(self.customer.customer_code, customer_label)

    def test_credit_form_uses_manual_amount_and_note_instead_of_item_rows(self):
        response = self.client.get(reverse("credit_create"))

        self.assertContains(response, "Bill Amount (₹)")
        self.assertContains(response, "Note")
        self.assertContains(response, "important remarks or additional information")
        self.assertNotContains(response, "Item List")
        self.assertNotContains(response, 'name="item_name"')

    def test_customer_directory_can_be_searched_by_short_id(self):
        response = self.client.get(
            reverse("customers"),
            {"search": self.customer.customer_code},
        )
        self.assertContains(response, self.customer.customer_code)
        self.assertEqual(len(response.context["customer_rows"]), 1)

    def test_duplicate_review_existing_customer_link_prefills_purchase_selector(self):
        response = self.client.get(
            reverse("credit_create"),
            {"customer_id": self.customer.pk},
        )
        self.assertEqual(
            response.context["form"]["customer"].value(),
            str(self.customer.pk),
        )

    def test_payment_selector_has_searchable_customer_short_id(self):
        response = self.client.get(reverse("record_payment"))
        self.assertContains(response, "Search existing customers by short ID")
        self.assertContains(response, self.customer.customer_code)

    def test_customer_registration_requires_authentication(self):
        self.client.logout()
        response = self.client.get(reverse("customer_create"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_multiple_manual_credit_bills_and_acknowledged_payment_use_one_account(self):
        for amount in ("500.00", "200.00", "300.00"):
            response = self.client.post(
                reverse("credit_create"),
                {
                    "customer": str(self.customer.pk),
                    "date_given": "2026-01-01",
                    "due_date": "2026-01-08",
                    "amount": amount,
                    "note": f"Transaction note {amount}",
                },
            )
            self.assertRedirects(response, reverse("credits"))

        bills = list(
            CreditEntry.objects.filter(customer_id=self.customer.pk).order_by("id")
        )
        self.assertEqual(Customer.objects.count(), 1)
        self.assertEqual(len(bills), 3)
        self.assertEqual(
            [bill.amount for bill in bills],
            [Decimal("500.00"), Decimal("200.00"), Decimal("300.00")],
        )
        self.assertEqual(len({bill.bill_number for bill in bills}), 3)
        self.assertTrue(all(bill.bill_number.startswith("CM-") for bill in bills))
        self.assertTrue(
            all(bill.customer_id == self.customer.pk for bill in bills)
        )
        self.assertTrue(
            all(
                bill.date_given.isoformat() == "2026-01-01"
                and bill.due_date.isoformat() == "2026-01-08"
                and bill.items.count() == 0
                for bill in bills
            )
        )
        self.assertEqual(
            [bill.items_description for bill in bills],
            [f"Transaction note {amount}" for amount in ("500.00", "200.00", "300.00")],
        )

        response = self.client.post(
            reverse("record_payment"),
            {
                "customer": str(self.customer.pk),
                "amount": "400.00",
                "note": "Part payment",
            },
        )
        self.assertRedirects(response, reverse("payments"))
        payment = Payment.objects.get(customer_id=self.customer.pk)
        self.assertFalse(payment.acknowledged)

        statement_url = reverse(
            "customer_statement",
            args=[self.customer.pk],
        )
        statement = self.client.get(statement_url)
        self.assertEqual(statement.context["balance_due"], Decimal("1000.00"))

        response = self.client.post(
            reverse("acknowledge_payment", args=[payment.pk])
        )
        self.assertRedirects(response, reverse("payments"))

        statement = self.client.get(statement_url)
        self.assertEqual(statement.context["total_credit"], Decimal("1000.00"))
        self.assertEqual(statement.context["total_paid"], Decimal("400.00"))
        self.assertEqual(statement.context["balance_due"], Decimal("600.00"))
        for bill in bills:
            self.assertContains(statement, bill.bill_number)
        self.assertContains(statement, "Acknowledged")

    def test_credit_form_rejects_invalid_bill_amounts(self):
        for amount in ("NaN", "10.001", "0"):
            response = self.client.post(
                reverse("credit_create"),
                {
                    "customer": str(self.customer.pk),
                    "date_given": "2026-10-01",
                    "due_date": "2026-10-08",
                    "amount": amount,
                    "note": "Test note",
                },
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(CreditEntry.objects.count(), 0)

    def test_manual_bill_amount_and_note_are_saved_and_displayed(self):
        response = self.client.post(
            reverse("credit_create"),
            {
                "customer": str(self.customer.pk),
                "date_given": "2026-10-01",
                "due_date": "2026-10-08",
                "amount": "123.45",
                "note": "Customer requested delivery next week.",
            },
        )

        self.assertRedirects(response, reverse("credits"))
        entry = CreditEntry.objects.get()
        self.assertEqual(entry.amount, Decimal("123.45"))
        self.assertEqual(
            entry.items_description,
            "Customer requested delivery next week.",
        )
        self.assertEqual(entry.items.count(), 0)
        self.assertContains(
            self.client.get(reverse("credits")),
            "Customer requested delivery next week.",
        )
        self.assertContains(
            self.client.get(
                reverse("customer_statement", args=[self.customer.pk])
            ),
            "Customer requested delivery next week.",
        )


class OwnerSignupTests(TestCase):
    def signup_data(self, **overrides):
        data = {
            "full_name": "First Shop Owner",
            "username": "first-owner",
            "email": "owner@example.com",
            "owner_phone": "+91 98765 43210",
            "alternate_phone": "",
            "shop_name": "Test Provision Store",
            "shop_phone": "9876500000",
            "shop_email": "shop@example.com",
            "shop_address": "Main Market",
            "shop_gstin": "29ABCDE1234F1Z5",
            "password1": "a-secure-owner-password-927!",
            "password2": "a-secure-owner-password-927!",
        }
        data.update(overrides)
        return data

    def test_first_owner_can_sign_up_and_is_signed_in(self):
        response = self.client.get(reverse("owner_signup"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create owner account")

        response = self.client.post(
            reverse("owner_signup"),
            self.signup_data(),
        )

        self.assertRedirects(response, reverse("dashboard"))
        owner = get_user_model().objects.get(username="first-owner")
        self.assertEqual(owner.first_name, "First")
        self.assertEqual(owner.last_name, "Shop Owner")
        self.assertEqual(owner.email, "owner@example.com")
        self.assertEqual(owner.owner_profile.phone, "+91 98765 43210")
        self.assertEqual(owner.owner_profile.alternate_phone, "")
        profile = ShopProfile.objects.get(pk=1)
        self.assertEqual(profile.shop_name, "Test Provision Store")
        self.assertEqual(profile.phone, "9876500000")
        self.assertEqual(profile.email, "shop@example.com")
        self.assertEqual(profile.address, "Main Market")
        self.assertEqual(profile.gstin, "29ABCDE1234F1Z5")
        self.assertIn("_auth_user_id", self.client.session)
        response = self.client.get(reverse("owner_signup"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create another account")

    def test_signup_is_hidden_and_closed_after_first_owner_exists(self):
        get_user_model().objects.create_user(
            username="existing-owner",
            password="a-secure-owner-password-927!",
        )

        self.assertNotContains(
            self.client.get(reverse("landing")),
            "Create Owner Account",
        )
        response = self.client.get(reverse("owner_signup"))
        self.assertRedirects(response, reverse("login"))

        response = self.client.post(
            reverse("owner_signup"),
            self.signup_data(username="second-owner"),
        )
        self.assertRedirects(response, reverse("login"))
        self.assertFalse(
            get_user_model().objects.filter(username="second-owner").exists()
        )

    def test_signup_rejects_mismatched_passwords(self):
        response = self.client.post(
            reverse("owner_signup"),
            self.signup_data(password2="different-secure-password-927!"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "password fields didn’t match")
        self.assertFalse(get_user_model().objects.exists())

    def test_signed_in_owner_can_create_additional_account_without_changing_shop(self):
        existing_owner = get_user_model().objects.create_user(
            username="existing-owner",
            password="a-secure-owner-password-927!",
        )
        ShopProfile.objects.create(
            pk=1,
            shop_name="Existing Shop",
            phone="9123456789",
            gstin="29ABCDE1234F1Z5",
        )
        self.client.force_login(existing_owner)

        response = self.client.get(reverse("owner_account_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create another account")
        self.assertContains(response, "Existing Shop")
        self.assertNotContains(response, "name=\"shop_name\"")

        response = self.client.post(
            reverse("owner_account_create"),
            self.signup_data(
                full_name="Additional Account Owner",
                username="additional-owner",
                email="additional@example.com",
                owner_phone="9876543210",
                shop_name="Do not overwrite",
                shop_gstin="invalid",
            ),
        )

        self.assertRedirects(response, reverse("dashboard"))
        additional_owner = get_user_model().objects.get(username="additional-owner")
        self.assertEqual(additional_owner.first_name, "Additional")
        self.assertEqual(additional_owner.last_name, "Account Owner")
        self.assertEqual(additional_owner.owner_profile.phone, "9876543210")
        self.assertEqual(ShopProfile.objects.get(pk=1).shop_name, "Existing Shop")
        self.assertEqual(ShopProfile.objects.get(pk=1).gstin, "29ABCDE1234F1Z5")
        self.assertEqual(int(self.client.session["_auth_user_id"]), existing_owner.pk)

    def test_signup_requires_owner_contact_and_valid_shop_gstin(self):
        for post_data, field_name, error in (
            (
                self.signup_data(owner_phone=""),
                "owner_phone",
                "This field is required.",
            ),
            (
                self.signup_data(shop_gstin="not-a-gstin"),
                "shop_gstin",
                "Enter a valid 15-character GSTIN.",
            ),
        ):
            response = self.client.post(reverse("owner_signup"), post_data)
            self.assertEqual(response.status_code, 200)
            self.assertIn(error, response.context["form"][field_name].errors)
            self.assertFalse(get_user_model().objects.exists())


class ReportsAndReminderTests(TestCase):
    def setUp(self):
        owner = get_user_model().objects.create_user(
            username="reports-owner",
            password="test-password",
        )
        self.client.force_login(owner)
        self.customer = Customer.objects.create(
            name="Report Customer",
            phone="9876500000",
            email="customer@example.com",
        )
        self.profile = ShopProfile.objects.create(
            pk=1,
            shop_name="Test Provision Store",
            enable_email_reminders=True,
            send_daily_reminders=True,
        )

    def create_credit(self, amount, due_date=None, date_given=None):
        today = timezone.localdate()
        return CreditEntry.objects.create(
            customer=self.customer,
            bill_number=f"TEST-{CreditEntry.objects.count() + 1}",
            items_description="Groceries",
            amount=Decimal(amount),
            date_given=date_given or today,
            due_date=due_date or today,
        )

    def test_reports_filter_activity_and_export_csv(self):
        self.create_credit("500.00", date_given="2026-10-01")
        self.create_credit("20.00", date_given="2026-10-01")
        Payment.objects.create(
            customer=self.customer,
            amount=Decimal("100.00"),
            payment_date="2026-10-03",
            acknowledged=True,
        )
        Payment.objects.create(
            customer=self.customer,
            amount=Decimal("25.00"),
            payment_date="2026-10-04",
            acknowledged=False,
        )

        response = self.client.get(
            reverse("reports"),
            {"start_date": "2026-10-01", "end_date": "2026-10-03"},
        )
        self.assertEqual(response.status_code, 200)
        report = response.context["report"]
        self.assertEqual(report["period_credit"], Decimal("520.00"))
        self.assertEqual(report["period_collections"], Decimal("100.00"))
        self.assertEqual(report["pending_payments"], Decimal("0.00"))
        self.assertEqual(report["total_outstanding"], Decimal("420.00"))
        self.assertEqual(len(report["daily_activity"]), 2)
        credit_day = next(
            day for day in report["daily_activity"]
            if day["date"].isoformat() == "2026-10-01"
        )
        self.assertEqual(credit_day["credit"], Decimal("520.00"))

        csv_response = self.client.get(
            reverse("reports"),
            {
                "start_date": "2026-10-01",
                "end_date": "2026-10-03",
                "export": "csv",
            },
        )
        self.assertEqual(csv_response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("TEST-1", csv_response.content.decode("utf-8-sig"))
        self.assertIn("Customer balance summary", csv_response.content.decode("utf-8-sig"))
        self.assertIn("TEST-2", csv_response.content.decode("utf-8-sig"))

    def test_reports_reject_start_date_after_end_date(self):
        response = self.client.get(
            reverse("reports"),
            {"start_date": "2026-10-10", "end_date": "2026-10-01"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["report"])
        self.assertContains(response, "The start date must be on or before the end date.")

    def test_settings_update_is_reflected_in_shared_shop_profile(self):
        response = self.client.post(
            reverse("settings"),
            {
                "shop_name": "New Store Name",
                "phone": "9876543210",
                "email": "shop@example.com",
                "address": "Market Road",
                "gstin": "29ABCDE1234F1Z5",
                "reminder_days_before_due": "3",
                "send_daily_reminders": "on",
                "enable_email_reminders": "on",
            },
        )

        self.assertRedirects(response, reverse("settings"))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.shop_name, "New Store Name")
        self.assertEqual(self.profile.reminder_days_before_due, 3)
        self.assertEqual(self.profile.gstin, "29ABCDE1234F1Z5")

        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "New Store Name")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_manual_reminder_sends_email_and_records_delivery(self):
        self.create_credit("300.00")

        response = self.client.post(
            reverse("send_reminder", args=[self.customer.pk])
        )

        self.assertRedirects(response, reverse("reminders"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["customer@example.com"])
        self.assertIn("₹300.00", mail.outbox[0].body)
        reminder_log = ReminderLog.objects.get(customer=self.customer)
        self.assertEqual(reminder_log.status, "sent")
        self.assertIsNotNone(reminder_log.sent_at)

        response = self.client.post(
            reverse("send_reminder", args=[self.customer.pk])
        )
        self.assertRedirects(response, reverse("reminders"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(ReminderLog.objects.filter(customer=self.customer).count(), 1)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_daily_reminder_command_is_idempotent_and_respects_settings(self):
        self.create_credit("450.00")
        output = StringIO()

        call_command("process_reminders", dry_run=True, stdout=output)
        self.assertIn("Would email", output.getvalue())
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(ReminderLog.objects.count(), 0)

        call_command("process_reminders", stdout=output)
        call_command("process_reminders", stdout=StringIO())

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            ReminderLog.objects.filter(customer=self.customer, status="sent").count(),
            1,
        )

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    @patch("ledger.services.send_mail", side_effect=OSError("SMTP unavailable"))
    def test_failed_email_attempt_is_logged_and_reported(self, mocked_send_mail):
        self.create_credit("275.00")

        response = self.client.post(
            reverse("send_reminder", args=[self.customer.pk])
        )

        self.assertRedirects(response, reverse("reminders"))
        failed_log = ReminderLog.objects.get(customer=self.customer)
        self.assertEqual(failed_log.status, "failed")
        self.assertIn("SMTP unavailable", failed_log.notes)
        mocked_send_mail.assert_called_once()

    def test_disabled_email_reminders_do_not_send(self):
        self.profile.enable_email_reminders = False
        self.profile.save(update_fields=["enable_email_reminders"])
        self.create_credit("125.00")

        response = self.client.post(
            reverse("send_reminder", args=[self.customer.pk])
        )

        self.assertRedirects(response, reverse("reminders"))
        self.assertEqual(ReminderLog.objects.count(), 0)
