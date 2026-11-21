from django.urls import path

from . import views

app_name = "usuarios"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("novo/", views.novo, name="novo"),
    path("<int:usuario_id>/", views.editar, name="editar"),
]
