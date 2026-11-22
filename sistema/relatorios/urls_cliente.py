from django.urls import path

from . import views_cliente as views

app_name = "relatorios_cliente"

urlpatterns = [
    path("<int:pk>/relatorios/", views.lista, name="lista"),
    path("<int:pk>/relatorios/gerar/", views.gerar, name="gerar"),
    path("<int:pk>/relatorios/<int:relatorio_pk>/", views.ver, name="ver"),
    path("<int:pk>/relatorios/<int:relatorio_pk>/pdf/", views.baixar, name="baixar"),
]
