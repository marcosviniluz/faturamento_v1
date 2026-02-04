from django.urls import path
from .views import tela_estoque_valor

urlpatterns = [
    path("ricoh/", tela_estoque_valor, name="tela_estoque_valor"),
]
