from django.contrib import admin
from django.db import models

from .models import Cliente, ContaFaturamento, ConfigContaFaturamento


class ConfigContaInline(admin.StackedInline):
    model = ConfigContaFaturamento
    extra = 0
    max_num = 1
    can_delete = False

    # melhora edição do JSON no inline
    formfield_overrides = {
        models.JSONField: {"widget": admin.widgets.AdminTextareaWidget(attrs={"rows": 10, "style": "width: 98%;"})},
    }

    fieldsets = (
        ("WMS / Armazenagem", {
            "fields": ("metodo_armazenagem", "wms_local_prefixes", "somente_com_estoque"),
        }),
        ("Relatório (por CNPJ)", {
            "fields": ("relatorio_config",),
            "description": "JSON que define layout/linhas/ISS/branding do relatório para este CNPJ.",
        }),
        ("Metadados", {
            "fields": ("created_at", "updated_at"),
        }),
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("nome", "slug", "ativo", "created_at")
    search_fields = ("nome", "slug")
    list_filter = ("ativo",)
    ordering = ("nome",)


@admin.register(ContaFaturamento)
class ContaFaturamentoAdmin(admin.ModelAdmin):
    list_display = ("cliente", "apelido", "slug", "cnpj", "cnpj_wms", "ativa", "created_at")
    search_fields = ("apelido", "slug", "cnpj", "cnpj_wms", "cliente__nome")
    list_filter = ("ativa", "cliente")
    ordering = ("cliente__nome", "apelido")
    inlines = [ConfigContaInline]


@admin.register(ConfigContaFaturamento)
class ConfigContaFaturamentoAdmin(admin.ModelAdmin):
    list_display = ("conta", "metodo_armazenagem", "somente_com_estoque", "created_at", "updated_at")
    search_fields = ("conta__apelido", "conta__cnpj", "conta__cnpj_wms", "conta__cliente__nome")
    list_filter = ("metodo_armazenagem", "somente_com_estoque", "conta__cliente")
    ordering = ("conta__cliente__nome", "conta__apelido")

    # melhora edição do JSON na tela dedicada também
    formfield_overrides = {
        models.JSONField: {"widget": admin.widgets.AdminTextareaWidget(attrs={"rows": 16, "style": "width: 98%;"})},
    }

    fieldsets = (
        ("Conta", {
            "fields": ("conta",),
        }),
        ("WMS / Armazenagem", {
            "fields": ("metodo_armazenagem", "wms_local_prefixes", "somente_com_estoque"),
        }),
        ("Relatório (por CNPJ)", {
            "fields": ("relatorio_config",),
            "description": "Cole aqui o JSON do layout/linhas/ISS/branding do relatório.",
        }),
        ("Metadados", {
            "fields": ("created_at", "updated_at"),
        }),
    )
    readonly_fields = ("created_at", "updated_at")