from django.urls import path

from apps.publishing import api

app_name = "commerce_api"

urlpatterns = [
    path("stores/<slug:subdomain>/products", api.ProductListView.as_view(), name="products"),
    path("stores/<slug:subdomain>/products/<slug:slug>", api.ProductDetailView.as_view(), name="product"),
    path("stores/<slug:subdomain>/checkout", api.CheckoutView.as_view(), name="checkout"),
    path("stores/<slug:subdomain>/orders/<str:reference>", api.OrderStatusView.as_view(), name="order"),
]
