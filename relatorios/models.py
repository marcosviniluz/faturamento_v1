from django.db import models

class RelatorioServico(models.Model):
    # Este é o "cérebro" do seu sistema. 
    # Cada opção aqui mapeia para uma lógica diferente no seu FaturamentoService.
    METODOS_CALCULO = [
        ("MANUAL", "Valor Manual / Fixo"),
        
        # Lógica padrão Ricoh (Usa coluna 'local')
        ("PICO_POSICAO_SNAPSHOT", "Pico de Posições (Maior contagem de locais no dia)"),
        
        # Lógica padrão Ricoh (Usa coluna 'valor_db')
        ("PICO_VALOR_SNAPSHOT", "Pico de Valor em Estoque (Maior soma de valor no dia)"),
        
        # Lógica padrão Kraton (Soma de todos os snapshots do período)
        ("SOMA_VALOR_PERIODO", "Soma de Valor no Período (Ad-valorem acumulado)"),
        
        # Lógica padrão Kraton (Soma da coluna de peso/unidades)
        ("SOMA_ESTOQUE_PERIODO", "Soma de Peso/Qtd no Período (Armazenagem por Ton/Un)"),
    ]

    cliente = models.ForeignKey("clientes.Cliente", on_delete=models.CASCADE)
    nome = models.CharField(max_length=120)
    codigo = models.SlugField(max_length=80)

    tipo = models.CharField(
        max_length=20,
        choices=[
            ("MULT", "Multiplicação (Qtd x Taxa)"),
            ("PERCENTUAL", "Percentual (Valor x % Taxa)"),
        ],
        default="MULT"
    )
    
    # Campo que define a regra de extração SQL
    metodo_calculo = models.CharField(
        max_length=30,
        choices=METODOS_CALCULO,
        default="MANUAL",
        help_text="Define qual regra de extração da tabela de Snapshot será usada."
    )

    unidade = models.CharField(max_length=20, blank=True, help_text="Ex: UN, POS, R$, TON")
    ordem = models.IntegerField(default=0, help_text="Ordem de exibição no relatório")
    ativo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Serviço de Relatório"
        verbose_name_plural = "Serviços de Relatório"
        ordering = ['ordem', 'nome']

    def __str__(self):
        return f"{self.cliente.nome} - {self.nome} ({self.get_metodo_calculo_display()})"


class RelatorioTaxaConta(models.Model):
    conta = models.ForeignKey("clientes.ContaFaturamento", on_delete=models.CASCADE)
    servico = models.ForeignKey(RelatorioServico, on_delete=models.CASCADE)

    taxa = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    ativo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Taxa por Conta"
        verbose_name_plural = "Taxas por Conta"
        unique_together = ('conta', 'servico')

    def __str__(self):
        return f"{self.conta.cliente.nome} | {self.conta.nome} - {self.servico.nome}: {self.taxa}"