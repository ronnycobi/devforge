from django.urls import path

from apps.credits.api import CreditBalanceView, UsageListView

app_name = "credits"

urlpatterns = [
    path("orgs/<int:org_pk>/credits/", CreditBalanceView.as_view(), name="balance"),
    path("orgs/<int:org_pk>/usage/", UsageListView.as_view(), name="usage"),
]
