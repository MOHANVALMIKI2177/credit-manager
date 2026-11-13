
from django.urls import path
from . import views

urlpatterns = [
    path("", views.landing, name="landing"),
    path("signup/", views.owner_signup, name="owner_signup"),
    path("accounts/create/", views.owner_signup, name="owner_account_create"),
    path("dashboard/", views.dashboard, name="dashboard"),

    path("customers/", views.customers_page, name="customers"),
    path("customers/add/", views.customer_create, name="customer_create"),
    path(
        "customer/<int:customer_id>/statement/",
        views.customer_statement,
        name="customer_statement",
    ),

    path("credits/", views.credits_page, name="credits"),
    path("credits/add/", views.credit_create, name="credit_create"),

    path("payments/", views.payments_page, name="payments"),
    path("payments/add/", views.record_payment, name="record_payment"),
    path(
        "payments/<int:payment_id>/acknowledge/",
        views.acknowledge_payment,
        name="acknowledge_payment",
    ),

    path("reminders/", views.reminders_page, name="reminders"),
    path(
        "reminders/<int:customer_id>/send/",
        views.send_reminder,
        name="send_reminder",
    ),
    path("reports/", views.reports_page, name="reports"),
    path("settings/", views.settings_page, name="settings"),
]
