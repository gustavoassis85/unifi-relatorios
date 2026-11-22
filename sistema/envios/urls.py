from django.urls import path

from . import views

app_name = "envios"

urlpatterns = [
    path("smtp/", views.smtp, name="smtp"),
    path("smtp/testar/", views.testar, name="testar"),
    path("smtp/teste/", views.situacao_teste, name="situacao_teste"),
]
