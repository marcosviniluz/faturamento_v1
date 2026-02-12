from django.contrib import admin
from django.urls import include, path, reverse
from django.shortcuts import redirect

def home(request):
    if request.user.is_authenticated:
        return redirect(reverse("dashboard:home"))
    return redirect(reverse("login"))

urlpatterns = [
    path("", home, name="home"),
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),

    path("dashboard/", include("dashboard.urls")),
    path("clientes/", include("clientes.urls")),
    path("estoque/", include("relatorios.urls")),
]
