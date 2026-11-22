from django.urls import path

from . import views

app_name = "conexoes"

urlpatterns = [
    path("<int:pk>/chave/", views.salvar, name="chave"),
    path("<int:pk>/chave/apagar/", views.apagar, name="chave_apagar"),
    path("<int:pk>/testar/", views.testar, name="testar"),
    path("<int:pk>/consoles/<int:console_pk>/acompanhar/", views.acompanhar, name="acompanhar"),
]
