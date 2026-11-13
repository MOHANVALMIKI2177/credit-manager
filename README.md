# Credit Manager

Django application for customer accounts, manually entered credit bills and notes, payment acknowledgement, customer statements, reports, and payment reminders.

## Run locally on Windows

From the project directory in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver
```

The application uses a local SQLite database at `db.sqlite3`, which is intentionally excluded from version control because it contains customer and transaction data. On a fresh setup, the `migrate` command above creates the database.

Create the first owner account from the **Create Owner Account** link on the home page (or visit `/signup/`). Enter the owner's full name, username, email, and phone, plus the shop name. Alternate owner contact, shop phone/email/address, and GSTIN are optional. This one-time public signup closes after the first account is created.

To create an account with access to Django admin, use:

```powershell
.\.venv\Scripts\python.exe manage.py createsuperuser
```

Open the local URL printed by `runserver`, then sign in with the owner account.

Once signed in, an owner can use **Create account** to add another login for a trusted person. The additional account requires the person's full name, username, email, phone, and password; optional alternate phone is also collected. Additional accounts share the shop's customer and transaction records and do not receive Django admin or superuser privileges. Shop details remain shared and can be edited in Shop Settings. Django admin is available at `/admin/` to accounts with the appropriate staff permissions.

## Customer registration and duplicate review

Customer short IDs such as `CUST-0001` are generated from the existing unique database primary key; the owner cannot enter or reuse one. Existing account IDs are preserved. Registration date uses the existing `created_at` value.

Name and mobile number are required. Email, PAN, GSTIN, and address are optional. Bank account numbers and credentials are not collected. Mobile numbers are normalized for punctuation, an Indian `+91`/`0091` country prefix, and a leading domestic zero. A matching phone opens a review page; the owner must confirm before adding a separate family member. A matching PAN or GSTIN is blocked and protected by conditional database uniqueness constraints. Phone numbers are indexed but intentionally not unique so families can share a phone.

Purchase and payment customer selectors show the short ID, name, and phone, and include a search box. The customer directory can also be searched by short ID, name, or mobile.

Before applying migrations to an existing database, make a copy from PowerShell in the project directory:

```powershell
Copy-Item .\db.sqlite3 ".\db.sqlite3.backup-before-customer-update-$(Get-Date -Format yyyyMMdd-HHmmss).sqlite3"
.\.venv\Scripts\python.exe manage.py migrate
```

The customer migration adds optional columns, fills normalized phone values for existing rows, and does not merge/delete customer accounts or change credit bills, items, payments, or acknowledgements. Existing customer IDs remain unchanged. The migration includes no PAN/GSTIN values for old accounts, so there are no legacy PAN/GSTIN conflicts to resolve in the current database. Duplicate phone matches are handled as review warnings rather than database conflicts.

## Reports and exports

The Reports page defaults to the current month and supports a custom date range. Its CSV export includes period credit and payment records plus all-time customer account balances. Use **Print report** or **Print statement** and choose **Save as PDF** in the browser to create a PDF.

## Email reminders

Reminder emails use Django's configured email backend. For local development the default is Django's console backend: a successful send is printed in the server console and is not delivered to the customer.

Before live delivery, configure SMTP through environment variables rather than committing credentials:

```powershell
$env:DJANGO_DEBUG = "false"
$env:DJANGO_SECRET_KEY = "<unique-secret-key>"
$env:DJANGO_ALLOWED_HOSTS = "your-domain.example"
$env:EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
$env:EMAIL_HOST = "smtp.example.com"
$env:EMAIL_PORT = "587"
$env:EMAIL_HOST_USER = "<smtp-username>"
$env:EMAIL_HOST_PASSWORD = "<smtp-password>"
$env:EMAIL_USE_TLS = "true"
$env:EMAIL_USE_SSL = "false"
$env:DEFAULT_FROM_EMAIL = "Credit Manager <shop@your-domain.example>"
```

The project loads values from a `.env` file in the project root; explicitly set process environment variables take precedence. Keep `.env` out of version control and never commit real credentials. Restart the Django server after changing email settings. In **Settings**, enable email reminders; manually send due reminders from **Reminder Centre**. For automatic daily emails, also enable daily reminders and schedule this command once per day. On Windows, create a daily task in Task Scheduler with the Python executable as the program and the command arguments below; set the task's **Start in** value to the project directory:

```powershell
Program: D:\path\to\project\.venv\Scripts\python.exe
Arguments: manage.py process_reminders
Start in: D:\path\to\project
```

Run the task under the same Windows user/environment configuration as the Django app so it receives the SMTP environment variables.

Use `--dry-run` to review eligible email recipients without sending. The command skips accounts already emailed that day and accounts that no longer have an eligible due balance. Delivery is only as reliable as the configured backend; a backend acceptance is not proof that a message reached an inbox.

SMS delivery is not connected. It requires choosing and configuring an SMS provider before it can be enabled safely.

## Validation

```powershell
.\.venv\Scripts\python.exe manage.py test ledger
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```
