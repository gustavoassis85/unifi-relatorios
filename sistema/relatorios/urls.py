from django.urls import path

from . import views

app_name = "relatorios"

urlpatterns = [
    path("marca/", views.marca, name="marca"),
]
