from django.contrib import admin
from .models import RelatorioServico, RelatorioTaxaConta


@admin.register(RelatorioServico)
class RelatorioServicoAdmin(admin.ModelAdmin):
    list_display = ("cliente", "nome", "codigo", "tipo", "unidade", "ativo")


@admin.register(RelatorioTaxaConta)
class RelatorioTaxaContaAdmin(admin.ModelAdmin):
    list_display = ("conta", "servico", "taxa", "ativo")