from django.contrib.auth import views as auth_views
from django.urls import path

from apps.dashboard import views

app_name = "dashboard"

urlpatterns = [
    path("", views.overview, name="home"),
    path("projects/", views.projects, name="projects"),
    path("projects/<int:pk>/", views.project, name="project"),
    path("projects/<int:pk>/release/", views.release_center, name="release_center"),
    path("projects/<int:pk>/preview/", views.preview, name="preview"),
    path("projects/<int:pk>/live/", views.preview_live, {"path": ""}, name="preview_live"),
    path("projects/<int:pk>/live/<path:path>", views.preview_live, name="preview_live_path"),
    path("changes/<int:pk>/", views.change_detail, name="change"),
    path("import/", views.import_software, name="import"),
    path("security/", views.security, name="security"),
    path("people/", views.people, name="people"),
    path("invite/<str:token>/", views.accept_invite, name="accept_invite"),
    path("agents/", views.agents, name="agents"),
    path("tasks/", views.tasks, name="tasks"),
    path("deployments/", views.deployments, name="deployments"),
    path("usage/", views.usage, name="usage"),
    path("section/<slug:slug>/", views.section, name="section"),
    path("repository/", views.repository, name="repository"),
    path("templates/", views.templates_page, name="templates"),
    path("settings/", views.settings_page, name="settings"),
    path("ops/<slug:area>/", views.operations, name="ops"),
    path("soon/<slug:slug>/", views.soon, name="soon"),
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="dashboard/login.html", redirect_authenticated_user=True
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
]
