from django.urls import path

from apps.support import views

app_name = "support"

urlpatterns = [
    # Customer-facing, under /app/ (alongside the dashboard).
    path("app/support/", views.my_tickets, name="mine"),
    path("app/support/<int:pk>/", views.ticket, name="ticket"),
    # Staff desk, under /staff/ (alongside the Control Center).
    path("staff/support/", views.desk, name="desk"),
    path("staff/support/<int:pk>/", views.desk_ticket, name="desk_ticket"),
]
