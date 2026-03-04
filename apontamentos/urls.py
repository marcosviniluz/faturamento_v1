# apontamentos/urls.py
from django.urls import path
from . import views

app_name = "apontamentos"

urlpatterns = [
    path("diario/", views.diario_hoje, name="diario_hoje"),
    path("diario/<str:data>/", views.diario_por_data, name="diario_data"),
]