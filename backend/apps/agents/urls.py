from django.urls import path

from apps.agents.api import AgentDetailView, AgentListView

app_name = "agents"

urlpatterns = [
    path("agents/", AgentListView.as_view(), name="list"),
    path("agents/<str:key>/", AgentDetailView.as_view(), name="detail"),
]
