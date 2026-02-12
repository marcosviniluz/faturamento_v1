from clientes.models import ContaFaturamento

def conta_ativa(request):
    conta_id = request.session.get("conta_id")
    conta = None

    if conta_id:
        conta = (
            ContaFaturamento.objects
            .select_related("cliente")
            .filter(id=conta_id, ativa=True, cliente__ativo=True)
            .first()
        )

    return {"conta_ativa_global": conta}
