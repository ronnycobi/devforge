from django.urls import path

from apps.console import views

app_name = "console"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("orgs/", views.organizations, name="orgs"),
    path("orgs/<int:pk>/", views.organization_detail, name="org"),
    path("users/", views.users, name="users"),
    path("projects/", views.projects, name="projects"),
    path("tasks/", views.tasks, name="tasks"),
    path("economics/", views.economics, name="economics"),
    path("deployments/", views.deployments, name="deployments"),
    path("mobile/", views.mobile_releases, name="mobile"),
    path("websites/", views.websites, name="websites"),
    path("leads/", views.leads, name="leads"),
    path("audit/", views.audit, name="audit"),
]
