from django.contrib import admin
from .models import Cliente, ContaFaturamento, ConfigContaFaturamento


class ConfigContaInline(admin.StackedInline):
    model = ConfigContaFaturamento
    extra = 0


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("nome", "slug", "ativo", "created_at")
    search_fields = ("nome", "slug")
    list_filter = ("ativo",)


@admin.register(ContaFaturamento)
class ContaFaturamentoAdmin(admin.ModelAdmin):
    list_display = ("cliente", "apelido", "slug", "cnpj", "cnpj_wms", "ativa", "created_at")
    search_fields = ("apelido", "slug", "cnpj", "cnpj_wms", "cliente__nome")
    list_filter = ("ativa", "cliente")
    inlines = [ConfigContaInline]


@admin.register(ConfigContaFaturamento)
class ConfigContaFaturamentoAdmin(admin.ModelAdmin):
    list_display = ("conta", "metodo_armazenagem", "somente_com_estoque", "created_at")
    search_fields = ("conta__apelido", "conta__cnpj_wms", "conta__cliente__nome")
