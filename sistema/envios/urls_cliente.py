from django.urls import path

from . import views_cliente as views

app_name = "envios_cliente"

urlpatterns = [
    path("<int:pk>/agendamentos/novo/", views.novo, name="novo"),
    path("<int:pk>/agendamentos/<int:agendamento_pk>/editar/", views.editar, name="editar"),
    path("<int:pk>/agendamentos/<int:agendamento_pk>/pausar/", views.pausar, name="pausar"),
    path("<int:pk>/agendamentos/<int:agendamento_pk>/excluir/", views.excluir, name="excluir"),
    path("<int:pk>/relatorios/<int:relatorio_pk>/reenviar/", views.reenviar, name="reenviar"),
]
