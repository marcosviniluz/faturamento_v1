from django.shortcuts import redirect
from django.urls import reverse

class RequireContaAtivaMiddleware:
    """
    Se o usuário autenticado acessar /estoque/ sem conta ativa na sessão,
    redireciona para a tela de seleção.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Só aplica para área de relatórios
        if request.path.startswith("/estoque/") or request.path.startswith("/apontamentos/"):
            # Se não está logado, deixa o @login_required cuidar disso
            if request.user.is_authenticated:
                if not request.session.get("conta_id"):
                    return redirect(reverse("clientes:selecionar"))

        return self.get_response(request)
