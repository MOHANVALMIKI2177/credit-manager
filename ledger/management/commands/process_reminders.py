from django.core.management.base import BaseCommand
from django.utils import timezone

from ledger.models import ReminderLog, ShopProfile
from ledger.services import get_reminder_candidates, send_customer_email_reminder


class Command(BaseCommand):
    help = (
        "Send due-customer email reminders when daily reminders are enabled. "
        "Schedule this command to run once per day for automatic delivery."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List eligible reminder recipients without sending emails.",
        )

    def handle(self, **options):
        profile = ShopProfile.objects.first()
        if not profile or not profile.send_daily_reminders:
            self.stdout.write(
                self.style.WARNING(
                    "Daily reminders are disabled in Shop Settings; nothing was sent."
                )
            )
            return
        if not profile.enable_email_reminders:
            self.stdout.write(
                self.style.WARNING(
                    "Email reminders are disabled in Shop Settings; nothing was sent."
                )
            )
            return

        today = timezone.localdate()
        candidates = get_reminder_candidates(profile=profile, today=today)
        sent_count = 0
        skipped_count = 0
        failed_count = 0

        for row in candidates:
            customer = row["customer"]
            if not customer.email:
                self.stdout.write(
                    f"Skipped account #{customer.pk} ({customer.name}): no email address."
                )
                skipped_count += 1
                continue

            already_sent = ReminderLog.objects.filter(
                customer=customer,
                reminder_type="email",
                scheduled_for=today,
                status="sent",
            ).exists()
            if already_sent:
                self.stdout.write(
                    f"Skipped account #{customer.pk} ({customer.name}): already sent today."
                )
                skipped_count += 1
                continue

            if options["dry_run"]:
                self.stdout.write(
                    f"Would email {customer.name} <{customer.email}> "
                    f"(balance ₹{row['balance']:.2f})."
                )
                continue

            if send_customer_email_reminder(
                customer,
                profile,
                row["balance"],
                today=today,
            ):
                sent_count += 1
                self.stdout.write(f"Sent reminder to account #{customer.pk}.")
            else:
                failed_count += 1
                self.stderr.write(
                    f"Failed to send reminder to account #{customer.pk}; see reminder history."
                )

        if options["dry_run"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Dry run complete: {len(candidates)} eligible account(s)."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Reminder run complete: {sent_count} sent, "
                    f"{skipped_count} skipped, {failed_count} failed."
                )
            )
