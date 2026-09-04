from django.urls import path

from apps.model_router.api import ModelListView, RouteView

app_name = "model_router"

urlpatterns = [
    path("ai/models/", ModelListView.as_view(), name="model-list"),
    path("ai/route/", RouteView.as_view(), name="route"),
]
