from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .models import Cliente, ContaFaturamento


@login_required
def selecionar_cliente_conta(request):
    clientes = Cliente.objects.filter(ativo=True).order_by("nome")

    cliente_slug = request.GET.get("cliente") or request.GET.get("cliente_slug")
    if cliente_slug:
        cliente_selecionado = get_object_or_404(Cliente, slug=cliente_slug, ativo=True)
    else:
        cliente_selecionado = clientes.first()

    contas = []
    if cliente_selecionado:
        contas = (
            ContaFaturamento.objects.filter(cliente=cliente_selecionado, ativa=True)
            .order_by("apelido", "cnpj_wms")
        )

    conta_ativa_id = request.session.get("conta_id")

    return render(
        request,
        "clientes/selecionar.html",
        {
            "clientes": clientes,
            "cliente_selecionado": cliente_selecionado,
            "contas": contas,
            "conta_ativa_id": conta_ativa_id,
        },
    )


@login_required
def ativar_conta(request, slug: str):
    cliente_slug = request.GET.get("cliente") or request.GET.get("cliente_slug")
    next_url = request.GET.get("next")

    if not cliente_slug:
        return HttpResponseBadRequest("Parâmetro 'cliente' é obrigatório (por causa do unique_together).")

    conta = get_object_or_404(
        ContaFaturamento,
        cliente__slug=cliente_slug,
        slug=slug,
        ativa=True,
        cliente__ativo=True,
    )

    request.session["conta_id"] = conta.id
    request.session.modified = True

    if next_url:
        return redirect(next_url)

    return redirect(reverse("relatorios:tela_estoque_valor"))
