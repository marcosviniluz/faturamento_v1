# operacao/services.py
from .models import Cargo, TabelaHoraExtra, TipoHoraExtra

def faltando_hh_por_conta(conta):
    cargos = list(Cargo.objects.all())
    tipos = [TipoHoraExtra.ATE_21, TipoHoraExtra.APOS_21_OU_FDS]

    existentes = set(
        TabelaHoraExtra.objects
        .filter(conta=conta)
        .values_list("cargo_id", "tipo")
    )

    faltando = []
    for c in cargos:
        for t in tipos:
            if (c.id, t) not in existentes:
                faltando.append((c.nome, t))
    return faltando