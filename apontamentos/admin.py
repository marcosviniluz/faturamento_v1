from __future__ import annotations

from django.contrib import admin, messages
from django.contrib.admin.sites import NotRegistered
from django.db import transaction

from clientes.models import ContaFaturamento
from apontamentos.models import TabelaHoraExtra, Cargo


class TabelaHoraExtraInline(admin.TabularInline):
    """
    Aqui é onde melhora:
    - você edita HH dentro do CNPJ
    - o campo cargo é filtrado automaticamente pelo cliente da conta
    """
    model = TabelaHoraExtra
    extra = 0
    fields = ("cargo", "tipo", "valor_hh")
    ordering = ("cargo__ordem", "cargo__nome", "tipo")

    def get_formset(self, request, obj=None, **kwargs):
        # guarda a conta pai para usar no filtro de cargo
        self._parent_obj = obj
        return super().get_formset(request, obj, **kwargs)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "cargo":
            parent = getattr(self, "_parent_obj", None)
            if parent is not None:
                kwargs["queryset"] = (
                    Cargo.objects.filter(cliente=parent.cliente, ativo=True)
                    .order_by("ordem", "nome")
                )
            else:
                # Em "Add ContaFaturamento" o obj ainda não existe; melhor não mostrar tudo.
                kwargs["queryset"] = Cargo.objects.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.action(description="Clonar Tabela HH deste CNPJ para TODOS os CNPJs do mesmo cliente")
def clonar_hh_mesmo_cliente(modeladmin, request, queryset):
    if queryset.count() != 1:
        messages.error(request, "Selecione exatamente 1 CNPJ (Conta) como modelo para clonar.")
        return

    conta_origem = queryset.first()

    linhas_origem = list(
        TabelaHoraExtra.objects.filter(conta=conta_origem)
        .values("cargo_id", "tipo", "valor_hh")
    )
    if not linhas_origem:
        messages.error(request, "Este CNPJ modelo não possui Tabela HH cadastrada.")
        return

    contas_destino = list(
        ContaFaturamento.objects.filter(cliente=conta_origem.cliente)
        .exclude(id=conta_origem.id)
        .only("id")
    )
    if not contas_destino:
        messages.warning(request, "Não há outros CNPJs desse cliente para clonar.")
        return

    upserts = 0
    with transaction.atomic():
        for dest in contas_destino:
            for l in linhas_origem:
                TabelaHoraExtra.objects.update_or_create(
                    conta_id=dest.id,
                    cargo_id=l["cargo_id"],
                    tipo=l["tipo"],
                    defaults={"valor_hh": l["valor_hh"]},
                )
                upserts += 1

    messages.success(
        request,
        f"Clonagem OK: modelo {conta_origem.cnpj}. Destinos: {len(contas_destino)}. Upserts: {upserts}."
    )


class ContaFaturamentoAdmin(admin.ModelAdmin):
    list_display = ("apelido", "cnpj", "cliente", "ativa")
    list_filter = ("cliente", "ativa")
    search_fields = ("apelido", "cnpj", "cliente__nome", "cliente__slug")
    ordering = ("cliente__nome", "apelido")

    inlines = [TabelaHoraExtraInline]
    actions = [clonar_hh_mesmo_cliente]


# Evita erro se já estava registrado em outro lugar
try:
    admin.site.unregister(ContaFaturamento)
except NotRegistered:
    pass

admin.site.register(ContaFaturamento, ContaFaturamentoAdmin)