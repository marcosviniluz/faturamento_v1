from django.db import models


class RelatorioServico(models.Model):
    cliente = models.ForeignKey("clientes.Cliente", on_delete=models.CASCADE)
    nome = models.CharField(max_length=120)
    codigo = models.SlugField(max_length=80)

    tipo = models.CharField(
        max_length=20,
        choices=[
            ("MULT", "Multiplicação"),
            ("PERCENTUAL", "Percentual"),
        ],
        default="MULT"
    )

    unidade = models.CharField(max_length=20, blank=True)
    ordem = models.IntegerField(default=0)
    ativo = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.cliente.nome} - {self.nome}"


class RelatorioTaxaConta(models.Model):
    conta = models.ForeignKey("clientes.ContaFaturamento", on_delete=models.CASCADE)
    servico = models.ForeignKey(RelatorioServico, on_delete=models.CASCADE)

    taxa = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    ativo = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.conta} - {self.servico.nome}"