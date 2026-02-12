from django.conf import settings
from django.db import models
from django.utils.text import slugify


class Cliente(models.Model):
    nome = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, db_index=True)
    ativo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.nome)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nome


class ContaFaturamento(models.Model):
    """
    Unidade faturável (CNPJ). Ex.: Ricoh - Itapevi / Ricoh - Navegantes
    """
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name="contas")

    apelido = models.CharField(max_length=120)  # "Itapevi", "Navegantes"
    slug = models.SlugField(max_length=140)     # slug do apelido (único dentro do cliente)

    cnpj = models.CharField(max_length=14, db_index=True)       # CNPJ que você mostra
    cnpj_wms = models.CharField(max_length=14, db_index=True)   # document_number no WMS

    ativa = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("cliente", "slug")]
        indexes = [
            models.Index(fields=["cliente", "ativa"]),
            models.Index(fields=["cnpj"]),
            models.Index(fields=["cnpj_wms"]),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.apelido)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.cliente.nome} - {self.apelido}"


class ConfigContaFaturamento(models.Model):
    """
    Configurações que mudam por CNPJ (ContaFaturamento).
    Aqui é onde você resolve PP vs PK (e no futuro peso etc.) sem hardcode.
    """
    METODO_ARMAZENAGEM_CHOICES = [
        ("PALLET_UNICO", "Armazenagem por pallet único (distinct local)"),
        # futuro:
        # ("PESO_KG", "Armazenagem por peso (kg)"),
        # ("QTDE_UN", "Armazenagem por quantidade"),
        # ("VALOR", "Armazenagem por valor"),
    ]

    conta = models.OneToOneField(
        ContaFaturamento,
        on_delete=models.CASCADE,
        related_name="config",
    )

    metodo_armazenagem = models.CharField(
        max_length=30,
        choices=METODO_ARMAZENAGEM_CHOICES,
        default="PALLET_UNICO",
    )

    # Prefixos de local que entram no cálculo/export.
    # Ex Ricoh: ["PP-", "BINS", "BL"]
    # Outro CNPJ: ["PK-"]
    wms_local_prefixes = models.JSONField(default=list, blank=True)

    # se você quiser manter a regra de só contar se tiver estoque
    somente_com_estoque = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Config {self.conta}"


class UserConta(models.Model):
    """
    Opcional:
    - Se TODOS usuários podem ver TODAS empresas, você pode nem usar isso agora.
    - Eu estou mantendo porque você já criou e pode querer no futuro.
    """
    ROLE_CHOICES = [
        ("ADMIN", "Admin"),
        ("OPERADOR", "Operador"),
        ("LEITURA", "Leitura"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    conta = models.ForeignKey(ContaFaturamento, on_delete=models.CASCADE, related_name="usuarios")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default="OPERADOR")
    ativo = models.BooleanField(default=True)

    class Meta:
        unique_together = [("user", "conta")]
        indexes = [
            models.Index(fields=["user", "ativo"]),
            models.Index(fields=["conta", "ativo"]),
        ]

    def __str__(self):
        return f"{self.user} -> {self.conta} ({self.role})"
