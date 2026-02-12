from django.urls import path
from . import views

app_name = "relatorios"

urlpatterns = [
    path("", views.tela_estoque_valor, name="tela_estoque_valor"),
]
