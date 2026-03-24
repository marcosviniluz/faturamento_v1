# apontamentos/views.py
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.forms import ModelForm, widgets
from django.forms.models import inlineformset_factory
from django.shortcuts import redirect, render
from django.urls import reverse

from clientes.models import ContaFaturamento
from .models import (
    Cargo,
    Diario,
    DiarioMetricaValor,
    HoraExtraItem,
    HoraExtraLancamento,
    MetricaTipo,
    TabelaHoraExtra,
    TipoHoraExtra,
)


# ----------------------------
# Helpers: conta ativa / redirects
# ----------------------------

def _redirect_selecionar_conta():
    try:
        return redirect(reverse("clientes:selecionar"))
    except Exception:
        return redirect("/clientes/selecionar/")


def get_conta_ativa(request) -> ContaFaturamento | None:
    conta_id = request.session.get("conta_id")
    if not conta_id:
        return None
    return (
        ContaFaturamento.objects
        .select_related("cliente")
        .filter(id=conta_id)
        .first()
    )


# ----------------------------
# Validação HH completa
# ----------------------------

@dataclass(frozen=True)
class HHIncompleta:
    faltando: list[str]

    def msg(self) -> str:
        head = self.faltando[:10]
        resto = len(self.faltando) - len(head)
        base = "Tabela de Hora Extra incompleta para este CNPJ. Faltando: " + ", ".join(head)
        if resto > 0:
            base += f" ... (+{resto})"
        base += ". Configure no admin."
        return base


def checar_hh_completa(conta: ContaFaturamento) -> HHIncompleta | None:
    cargos = list(
        Cargo.objects
        .filter(cliente=conta.cliente, ativo=True)
        .only("id", "nome")
        .order_by("ordem", "nome")
    )
    if not cargos:
        return HHIncompleta([f"Nenhum Cargo ativo para '{conta.cliente.nome}'"])

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
                faltando.append(f"{c.nome} ({t})")
    return HHIncompleta(faltando) if faltando else None


# ----------------------------
# Seed do dia
# ----------------------------

def seed_diario(conta: ContaFaturamento, data: dt.date, user=None) -> Diario:
    diario, _created = Diario.objects.get_or_create(
        conta=conta,
        data=data,
        defaults={"created_by": user} if user and getattr(user, "is_authenticated", False) else {},
    )

    # métricas do cliente
    tipos_metrica = (
        MetricaTipo.objects
        .filter(cliente=conta.cliente, ativa=True)
        .order_by("categoria", "ordem", "nome")
    )
    for mt in tipos_metrica:
        DiarioMetricaValor.objects.get_or_create(diario=diario, tipo=mt)

    # lançamentos HE
    lanc_ate21, _ = HoraExtraLancamento.objects.get_or_create(diario=diario, tipo=TipoHoraExtra.ATE_21)
    lanc_fds, _ = HoraExtraLancamento.objects.get_or_create(diario=diario, tipo=TipoHoraExtra.APOS_21_OU_FDS)

    def ensure_items_from_hh(lanc: HoraExtraLancamento):
        hh_rows = (
            TabelaHoraExtra.objects
            .filter(
                conta=conta,
                tipo=lanc.tipo,
                cargo__cliente=conta.cliente,
                cargo__ativo=True,
            )
            .select_related("cargo")
            .order_by("cargo__ordem", "cargo__nome")
        )
        for hh in hh_rows:
            HoraExtraItem.objects.get_or_create(
                lancamento=lanc,
                cargo=hh.cargo,
                defaults={"valor_hh": hh.valor_hh},
            )

    ensure_items_from_hh(lanc_ate21)
    ensure_items_from_hh(lanc_fds)

    return diario


# ----------------------------
# Forms & Formsets
# ----------------------------

class DiarioForm(ModelForm):
    class Meta:
        model = Diario
        fields = ["observacao"]
        widgets = {
            "observacao": widgets.Textarea(attrs={"rows": 1, "class": "w-full rounded-lg text-sm"})
        }


class HoraExtraItemBaseForm(ModelForm):
    class Meta:
        model = HoraExtraItem
        fields = ("qtd_colaboradores", "qtd_horas")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # classe para o JS identificar os campos
        self.fields["qtd_colaboradores"].widget.attrs.update({"class": "js-input-calc"})
        self.fields["qtd_horas"].widget.attrs.update({"class": "js-input-calc"})


DiarioMetricaFormSet = inlineformset_factory(
    parent_model=Diario,
    model=DiarioMetricaValor,
    fields=("valor",),
    extra=0,
    can_delete=False,
)

HoraExtraItemFormSet = inlineformset_factory(
    parent_model=HoraExtraLancamento,
    model=HoraExtraItem,
    form=HoraExtraItemBaseForm,
    extra=0,
    can_delete=False,
)


# ----------------------------
# Views
# ----------------------------

@login_required
def diario_hoje(request):
    hoje = dt.date.today()
    return redirect("apontamentos:diario_data", data=hoje.isoformat())


@login_required
def diario_por_data(request, data: str):
    conta = get_conta_ativa(request)
    if not conta:
        messages.warning(request, "Selecione uma conta ativa antes de prosseguir.")
        return _redirect_selecionar_conta()

    try:
        data_ref = dt.date.fromisoformat(data)
    except ValueError:
        messages.error(request, "Data inválida.")
        return redirect("apontamentos:diario_hoje")

    # HH completa?
    hh_incompleta = checar_hh_completa(conta)
    if hh_incompleta:
        messages.error(request, hh_incompleta.msg())
        return _redirect_selecionar_conta()

    # Seed
    diario = seed_diario(conta=conta, data=data_ref, user=request.user)

    # Lançamentos HE
    lanc_ate21 = HoraExtraLancamento.objects.get(diario=diario, tipo=TipoHoraExtra.ATE_21)
    lanc_fds = HoraExtraLancamento.objects.get(diario=diario, tipo=TipoHoraExtra.APOS_21_OU_FDS)

    # Querysets ordenados
    metricas_qs = (
        DiarioMetricaValor.objects
        .filter(diario=diario)
        .select_related("tipo")
        .order_by("tipo__categoria", "tipo__ordem", "tipo__nome")
    )

    he_ate21_qs = (
        HoraExtraItem.objects
        .filter(lancamento=lanc_ate21)
        .select_related("cargo")
        .order_by("cargo__ordem", "cargo__nome")
    )

    he_fds_qs = (
        HoraExtraItem.objects
        .filter(lancamento=lanc_fds)
        .select_related("cargo")
        .order_by("cargo__ordem", "cargo__nome")
    )

    if request.method == "POST":
        diario_form = DiarioForm(request.POST, instance=diario)
        metricas_fs = DiarioMetricaFormSet(request.POST, instance=diario, queryset=metricas_qs, prefix="metrics")
        he_ate21_fs = HoraExtraItemFormSet(request.POST, instance=lanc_ate21, queryset=he_ate21_qs, prefix="he_ate21")
        he_fds_fs = HoraExtraItemFormSet(request.POST, instance=lanc_fds, queryset=he_fds_qs, prefix="he_fds")

        if all([diario_form.is_valid(), metricas_fs.is_valid(), he_ate21_fs.is_valid(), he_fds_fs.is_valid()]):
            with transaction.atomic():
                diario_form.save()
                metricas_fs.save()
                he_ate21_fs.save()
                he_fds_fs.save()
            messages.success(request, f"Apontamentos de {data_ref.strftime('%d/%m/%Y')} salvos com sucesso.")
            return redirect("apontamentos:diario_data", data=data_ref.isoformat())

        messages.error(request, "Erro ao salvar. Verifique os dados inseridos.")
    else:
        diario_form = DiarioForm(instance=diario)
        metricas_fs = DiarioMetricaFormSet(instance=diario, queryset=metricas_qs, prefix="metrics")
        he_ate21_fs = HoraExtraItemFormSet(instance=lanc_ate21, queryset=he_ate21_qs, prefix="he_ate21")
        he_fds_fs = HoraExtraItemFormSet(instance=lanc_fds, queryset=he_fds_qs, prefix="he_fds")

    # ✅ ZIP dos rows (fix: converter queryset em list para manter 1:1 com forms)
    metricas_vals = list(metricas_qs)
    metricas_rows = list(zip(metricas_fs.forms, metricas_vals))

    # ✅ Agrupar por categoria para criar sub-abas no template
    metricas_grupos_map: dict[str, list[tuple]] = {}
    for form, mv in metricas_rows:
        cat = (getattr(mv.tipo, "categoria", None) or "Geral").strip() or "Geral"
        metricas_grupos_map.setdefault(cat, []).append((form, mv))

    # mantém ordem do queryset (inserção na dict em ordem)
    metricas_grupos = list(metricas_grupos_map.items())

    he_ate21_rows = list(zip(he_ate21_fs.forms, list(he_ate21_qs)))
    he_fds_rows = list(zip(he_fds_fs.forms, list(he_fds_qs)))

    data_anterior = (data_ref - dt.timedelta(days=1)).isoformat()
    data_proxima = (data_ref + dt.timedelta(days=1)).isoformat()

    return render(
        request,
        "apontamentos/diario_form.html",
        {
            "conta": conta,
            "cliente": conta.cliente,
            "data_ref": data_ref,
            "data_anterior": data_anterior,
            "data_proxima": data_proxima,
            "diario_form": diario_form,

            # mantém compatibilidade
            "metricas_formset": metricas_fs,
            "metricas_rows": metricas_rows,

            # ✅ novo: para sub-abas dinâmicas
            "metricas_grupos": metricas_grupos,

            "he_ate21_formset": he_ate21_fs,
            "he_ate21_rows": he_ate21_rows,

            "he_fds_formset": he_fds_fs,
            "he_fds_rows": he_fds_rows,
        },
    )