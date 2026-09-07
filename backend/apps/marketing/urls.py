from django.urls import path

from apps.marketing import views

app_name = "marketing"

urlpatterns = [
    path("", views.home, name="home"),
    path("platform/", views.platform, name="platform"),
    path("how-it-works/", views.how_it_works, name="how_it_works"),
    path("agents/", views.agents, name="agents"),
    path("pricing/", views.pricing, name="pricing"),
    path("about/", views.about, name="about"),
    path("contact/", views.contact, name="contact"),
    path("signup/", views.signup, name="signup"),
]
