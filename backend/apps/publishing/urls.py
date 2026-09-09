from django.urls import path

from apps.publishing import views

app_name = "publishing"

urlpatterns = [
    path(".well-known/acme-challenge/<str:token>", views.acme_challenge, name="acme_challenge"),
    path("sites/<slug:subdomain>/f/<slug:slug>", views.submit_form, name="submit_form"),
    path("sites/<slug:subdomain>/checkout", views.checkout, name="checkout"),
    path("sites/<slug:subdomain>/order/<str:reference>", views.order_status, name="order_status"),
    path("sites/<slug:subdomain>/", views.serve_published, {"path": ""}, name="serve"),
    path("sites/<slug:subdomain>/<path:path>", views.serve_published, name="serve_path"),
]
