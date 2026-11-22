from django.urls import path

from . import views

app_name = "coletas"

urlpatterns = [
    path("<int:pk>/coletar/", views.coletar_agora, name="coletar_agora"),
]
