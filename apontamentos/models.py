# operacao/models.py
from __future__ import annotations

from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


# ----------------------------
# Hora extra: cadastro base
# ----------------------------

class TipoHoraExtra(models.TextChoices):
    ATE_21 = "ATE_21", "Após as 18h até 21h"
    APOS_21_OU_FDS = "APOS_21_OU_FDS", "Sáb/Dom/Feriados e após 21h"


class Cargo(models.Model):
    """
    Cargo depende do Cliente (empresa).
    Ex.: Ricoh tem 8 cargos; outro cliente pode ter outros.
    """
    cliente = models.ForeignKey("clientes.Cliente", on_delete=models.CASCADE, related_name="cargos")
    nome = models.CharField(max_length=80)
    ordem = models.PositiveIntegerField(default=0)
    ativo = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["cliente", "nome"], name="uniq_cargo_cliente_nome"),
        ]
        ordering = ["cliente_id", "ordem", "nome"]

    def __str__(self) -> str:
        return f"{self.cliente.nome} - {self.nome}"


class TabelaHoraExtra(models.Model):
    """
    Valor Homem/Hora por CNPJ (ContaFaturamento) e por Cargo (do mesmo cliente da conta).
    Cada (conta, cargo, tipo) é único.

    Importante: isso é o "cadastro" que precisa existir para permitir lançar hora extra do dia.
    """
    conta = models.ForeignKey(
        "clientes.ContaFaturamento",
        on_delete=models.CASCADE,
        related_name="tabela_hora_extra",
    )
    cargo = models.ForeignKey(Cargo, on_delete=models.PROTECT, related_name="tabelas_hh")
    tipo = models.CharField(max_length=20, choices=TipoHoraExtra.choices)
    valor_hh = models.DecimalField(max_digits=10, decimal_places=4)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["conta", "cargo", "tipo"], name="uniq_hh_conta_cargo_tipo"),
        ]
        ordering = ["conta_id", "cargo__ordem", "cargo__nome", "tipo"]

    def clean(self):
        super().clean()
        # garante integridade: cargo deve ser do mesmo cliente da conta
        if self.conta_id and self.cargo_id:
            if self.conta.cliente_id != self.cargo.cliente_id:
                raise ValidationError("Cargo não pertence ao mesmo Cliente desta Conta (CNPJ).")

    def __str__(self) -> str:
        return f"{self.conta} | {self.cargo.nome} | {self.get_tipo_display()} = {self.valor_hh}"


# ----------------------------
# Diário: tela única do dia
# ----------------------------

class Diario(models.Model):
    """
    1 por (conta, data). É o "cabeçalho" do dia para a tela de preenchimento manual.
    """
    conta = models.ForeignKey("clientes.ContaFaturamento", on_delete=models.CASCADE, related_name="diarios")
    data = models.DateField()
    observacao = models.CharField(max_length=255, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="diarios_criados"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["conta", "data"], name="uniq_diario_conta_data"),
        ]
        ordering = ["-data", "conta_id"]

    def __str__(self) -> str:
        return f"{self.conta} - {self.data}"

    @property
    def total_hora_extra(self) -> Decimal:
        return sum((l.total for l in self.hora_extra_lancamentos.all()), Decimal("0"))


# ----------------------------
# Métricas manuais (configurável por cliente)
# ----------------------------

class MetricaTipo(models.Model):
    """
    Define quais inputs manuais aparecem para um cliente.
    Ex.: Descarga por palete, Carga por NF, Crossdocking, Etiquetagem...
    """
    cliente = models.ForeignKey("clientes.Cliente", on_delete=models.CASCADE, related_name="metricas_tipos")
    nome = models.CharField(max_length=80)  # label na UI
    slug = models.SlugField(max_length=80)  # identificador estável (por cliente)
    unidade = models.CharField(max_length=20, blank=True)  # "paletes", "NF", etc
    ordem = models.PositiveIntegerField(default=0)
    ativa = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["cliente", "slug"], name="uniq_metrica_cliente_slug"),
        ]
        ordering = ["cliente_id", "ordem", "nome"]

    def __str__(self) -> str:
        return f"{self.cliente.nome} - {self.nome}"


class DiarioMetricaValor(models.Model):
    """
    Valor preenchido no Diário para cada MetricaTipo ativa do cliente.
    """
    diario = models.ForeignKey(Diario, on_delete=models.CASCADE, related_name="metricas")
    tipo = models.ForeignKey(MetricaTipo, on_delete=models.PROTECT, related_name="valores")
    valor = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["diario", "tipo"], name="uniq_diario_tipo_metrica"),
        ]
        ordering = ["tipo__ordem", "tipo__nome"]

    def clean(self):
        super().clean()
        # garante integridade: tipo deve ser do mesmo cliente do diário
        if self.diario_id and self.tipo_id:
            if self.diario.conta.cliente_id != self.tipo.cliente_id:
                raise ValidationError("Métrica não pertence ao mesmo Cliente desta Conta/Diário.")

    def __str__(self) -> str:
        return f"{self.diario} | {self.tipo.nome} = {self.valor}"


# ----------------------------
# Hora extra do dia (lançamento + itens)
# ----------------------------

class HoraExtraLancamento(models.Model):
    """
    Um lançamento de hora extra por (diario, tipo).
    Você terá 2 por dia: ATE_21 e APOS_21_OU_FDS.
    """
    diario = models.ForeignKey(Diario, on_delete=models.CASCADE, related_name="hora_extra_lancamentos")
    tipo = models.CharField(max_length=20, choices=TipoHoraExtra.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["diario", "tipo"], name="uniq_diario_tipo_he"),
        ]
        ordering = ["diario_id", "tipo"]

    @property
    def total(self) -> Decimal:
        return sum((i.subtotal for i in self.itens.all()), Decimal("0"))

    def __str__(self) -> str:
        return f"{self.diario} | {self.get_tipo_display()}"


class HoraExtraItem(models.Model):
    """
    Uma linha por cargo no lançamento de hora extra do dia.
    Guarda snapshot de valor_hh para preservar histórico.
    """
    lancamento = models.ForeignKey(HoraExtraLancamento, on_delete=models.CASCADE, related_name="itens")
    cargo = models.ForeignKey(Cargo, on_delete=models.PROTECT, related_name="hora_extra_itens")

    qtd_colaboradores = models.PositiveIntegerField(default=0)
    qtd_horas = models.DecimalField(max_digits=6, decimal_places=2, default=0)

    # snapshot do valor hh vigente para aquela conta/cargo/tipo no momento do preenchimento
    valor_hh = models.DecimalField(max_digits=10, decimal_places=4)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["lancamento", "cargo"], name="uniq_he_lancamento_cargo"),
        ]
        ordering = ["cargo__ordem", "cargo__nome"]

    def clean(self):
        super().clean()
        # integridade: cargo deve ser do mesmo cliente do diário
        if self.lancamento_id and self.cargo_id:
            diario_cliente_id = self.lancamento.diario.conta.cliente_id
            if self.cargo.cliente_id != diario_cliente_id:
                raise ValidationError("Cargo não pertence ao mesmo Cliente desta Conta/Diário.")

    @property
    def subtotal(self) -> Decimal:
        return (self.valor_hh or Decimal("0")) * Decimal(self.qtd_colaboradores or 0) * (self.qtd_horas or Decimal("0"))

    def __str__(self) -> str:
        return f"{self.lancamento} | {self.cargo.nome}"