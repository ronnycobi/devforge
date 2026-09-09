from django.urls import path

from apps.publishing import views

app_name = "publishing"

urlpatterns = [
    path("sites/<slug:subdomain>/", views.serve_published, {"path": ""}, name="serve"),
    path("sites/<slug:subdomain>/<path:path>", views.serve_published, name="serve_path"),
]
