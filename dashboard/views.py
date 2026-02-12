from django.contrib.auth.decorators import login_required
from django.shortcuts import render

@login_required
def dashboard_home(request):
    return render(request, "dashboard/home.html")
