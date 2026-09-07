from django.urls import path

from apps.technology.api import StackListView, TechnologyListView

app_name = "technology"

urlpatterns = [
    path("technologies/", TechnologyListView.as_view(), name="list"),
    path("stacks/", StackListView.as_view(), name="stacks"),
]
