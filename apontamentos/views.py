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
    # Ajustado para buscar 'conta_id' conforme sua sessão
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
# Validação HH completa (Mantido seu original)
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
    cargos = list(Cargo.objects.filter(cliente=conta.cliente, ativo=True).only("id", "nome"))
    if not cargos:
        return HHIncompleta([f"Nenhum Cargo ativo para '{conta.cliente.nome}'"])

    tipos = [TipoHoraExtra.ATE_21, TipoHoraExtra.APOS_21_OU_FDS]
    existentes = set(TabelaHoraExtra.objects.filter(conta=conta).values_list("cargo_id", "tipo"))

    faltando = []
    for c in cargos:
        for t in tipos:
            if (c.id, t) not in existentes:
                faltando.append(f"{c.nome} ({t})")
    return HHIncompleta(faltando) if faltando else None

# ----------------------------
# Seed do dia (Mantido seu original)
# ----------------------------

def seed_diario(conta: ContaFaturamento, data: dt.date, user=None) -> Diario:
    diario, created = Diario.objects.get_or_create(
        conta=conta,
        data=data,
        defaults={"created_by": user} if user and getattr(user, "is_authenticated", False) else {},
    )

    tipos_metrica = MetricaTipo.objects.filter(cliente=conta.cliente, ativa=True)
    for mt in tipos_metrica:
        DiarioMetricaValor.objects.get_or_create(diario=diario, tipo=mt)

    lanc_ate21, _ = HoraExtraLancamento.objects.get_or_create(diario=diario, tipo=TipoHoraExtra.ATE_21)
    lanc_fds, _ = HoraExtraLancamento.objects.get_or_create(diario=diario, tipo=TipoHoraExtra.APOS_21_OU_FDS)

    def ensure_items_from_hh(lanc: HoraExtraLancamento):
        hh_rows = TabelaHoraExtra.objects.filter(conta=conta, tipo=lanc.tipo, cargo__ativo=True)
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
            'observacao': widgets.Textarea(attrs={'rows': 1, 'class': 'w-full rounded-lg text-sm'})
        }

class HoraExtraItemBaseForm(ModelForm):
    class Meta:
        model = HoraExtraItem
        fields = ("qtd_colaboradores", "qtd_horas")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Classe para o JavaScript identificar os campos de cálculo
        self.fields['qtd_colaboradores'].widget.attrs.update({'class': 'js-input-calc'})
        self.fields['qtd_horas'].widget.attrs.update({'class': 'js-input-calc'})

# Configuração dos Formsets
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
        return redirect("apontamentos:diario_hoje")

    # Verifica se a tabela de preços está completa
    hh_incompleta = checar_hh_completa(conta)
    if hh_incompleta:
        messages.error(request, hh_incompleta.msg())
        return _redirect_selecionar_conta()

    # Garante a existência dos registros (Seed)
    diario = seed_diario(conta=conta, data=data_ref, user=request.user)

    # Lançamentos de HE
    lanc_ate21 = HoraExtraLancamento.objects.get(diario=diario, tipo=TipoHoraExtra.ATE_21)
    lanc_fds = HoraExtraLancamento.objects.get(diario=diario, tipo=TipoHoraExtra.APOS_21_OU_FDS)

    # Querysets ordenados para o ZIP
    metricas_qs = DiarioMetricaValor.objects.filter(diario=diario).select_related("tipo").order_by("tipo__ordem")
    he_ate21_qs = HoraExtraItem.objects.filter(lancamento=lanc_ate21).select_related("cargo").order_by("cargo__ordem")
    he_fds_qs = HoraExtraItem.objects.filter(lancamento=lanc_fds).select_related("cargo").order_by("cargo__ordem")

    if request.method == "POST":
        diario_form = DiarioForm(request.POST, instance=diario)
        metricas_fs = DiarioMetricaFormSet(request.POST, instance=diario, queryset=metricas_qs, prefix="metrics")
        # Nota: Usamos prefixos diferentes para as duas tabelas de HE
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
        else:
            messages.error(request, "Erro ao salvar. Verifique os dados inseridos.")
    else:
        diario_form = DiarioForm(instance=diario)
        metricas_fs = DiarioMetricaFormSet(instance=diario, queryset=metricas_qs, prefix="metrics")
        he_ate21_fs = HoraExtraItemFormSet(instance=lanc_ate21, queryset=he_ate21_qs, prefix="he_ate21")
        he_fds_fs = HoraExtraItemFormSet(instance=lanc_fds, queryset=he_fds_qs, prefix="he_fds")

    # Datas para navegação no template
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
            # Passamos o formset E a lista pareada (zip)
            "metricas_formset": metricas_fs,
            "metricas_rows": zip(metricas_fs.forms, metricas_qs),
            
            "he_ate21_formset": he_ate21_fs,
            "he_ate21_rows": zip(he_ate21_fs.forms, he_ate21_qs),
            
            "he_fds_formset": he_fds_fs,
            "he_fds_rows": zip(he_fds_fs.forms, he_fds_qs),
        },
    )