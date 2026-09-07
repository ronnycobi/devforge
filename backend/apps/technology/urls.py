from django.urls import path

from apps.technology.api import (
    SelectStackView,
    StackListView,
    StackProposalView,
    TechnologyListView,
)

app_name = "technology"

urlpatterns = [
    path("technologies/", TechnologyListView.as_view(), name="list"),
    path("stacks/", StackListView.as_view(), name="stacks"),
    path(
        "projects/<int:project_pk>/stack-proposal/",
        StackProposalView.as_view(),
        name="stack-proposal",
    ),
    path(
        "projects/<int:project_pk>/select-stack/",
        SelectStackView.as_view(),
        name="select-stack",
    ),
]
