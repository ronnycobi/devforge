from django.contrib.auth import views as auth_views
from django.urls import path

from apps.dashboard import views

app_name = "dashboard"

urlpatterns = [
    path("", views.dashboard, name="home"),
    path("projects/<int:pk>/", views.project, name="project"),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="dashboard/login.html"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
]
