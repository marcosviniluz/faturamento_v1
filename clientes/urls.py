from django.urls import path
from . import views

app_name = "clientes"

urlpatterns = [
    path("selecionar/", views.selecionar_cliente_conta, name="selecionar"),
    path("ativar/<slug:slug>/", views.ativar_conta, name="ativar_conta"),
]
