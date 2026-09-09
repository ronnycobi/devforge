from django.urls import path

from apps.publishing import views

app_name = "publishing"

urlpatterns = [
    path("sites/<slug:subdomain>/f/<slug:slug>", views.submit_form, name="submit_form"),
    path("sites/<slug:subdomain>/", views.serve_published, {"path": ""}, name="serve"),
    path("sites/<slug:subdomain>/<path:path>", views.serve_published, name="serve_path"),
]
