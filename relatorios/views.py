import os
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any, List, Optional, Tuple

import mysql.connector
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from openpyxl import Workbook

from clientes.models import ContaFaturamento


# =========================
# CONFIG WMS (use env var)
# =========================
HOST = os.getenv("WMS_HOST", "vdm-analytics-wms.mysql.database.azure.com")
PORT = int(os.getenv("WMS_PORT", "3306"))
USER = os.getenv("WMS_USER", "prod_vdm_wms_view")
PASSWORD = os.getenv("WMS_PASSWORD", "")
DB = os.getenv("WMS_DB", "prod_vdm_wms")

DATE_FIELD = "created_at"


# =========================
# QUERIES BASE
# =========================

# ✅ AD-VALOREM (PICO DO PERÍODO) — NÃO ALTERAR A REGRA
SQL_PICO_ADVALOREM_UNITVALUE_JOIN = f"""
SELECT
  dia,
  total_unit_value
FROM (
  SELECT
    DATE(aws.{DATE_FIELD}) AS dia,
    SUM(COALESCE(aws.unit_value, 0)) AS total_unit_value
  FROM api_wms_stock aws
  LEFT JOIN api_wms_stock_complement awsc
    ON awsc.stock_id = aws.id
  WHERE aws.deleted_at IS NULL
    AND aws.is_active = 1
    AND TRIM(aws.document_number) = %s
    AND aws.{DATE_FIELD} >= %s
    AND aws.{DATE_FIELD} < %s
  GROUP BY DATE(aws.{DATE_FIELD})
) x
ORDER BY total_unit_value DESC, dia DESC
LIMIT 1
"""


def _sql_pico_armazenagem(local_clause_sql: str, somente_com_estoque: bool) -> str:
    estoque_clause = "AND sc.amount > 0" if somente_com_estoque else ""
    return f"""
SELECT
  DATE(s.{DATE_FIELD}) AS dia,
  COUNT(DISTINCT sc.local_id) AS qtd_pico
FROM api_wms_stock s
JOIN api_wms_stock_complement sc ON sc.stock_id = s.id
WHERE s.deleted_at IS NULL
  AND s.is_active = 1
  AND TRIM(s.document_number) = %s
  AND s.{DATE_FIELD} >= %s
  AND s.{DATE_FIELD} < %s
  {estoque_clause}
  AND {local_clause_sql}
GROUP BY DATE(s.{DATE_FIELD})
ORDER BY qtd_pico DESC, dia DESC
LIMIT 1
"""


def _sql_export(local_clause_sql: str, somente_com_estoque: bool) -> str:
    estoque_clause = "AND sc.amount > 0" if somente_com_estoque else ""
    return f"""
SELECT
  DATE(s.{DATE_FIELD})                           AS data_ref,
  TRIM(s.document_number)                        AS cnpj,
  s.warehouse                                    AS armazem,
  COALESCE(s.sector,'SEM_SETOR')                 AS setor,
  sc.local_id                                    AS endereco,
  s.product_code                                 AS codigo_produto,
  MAX(s.description)                             AS produto,
  COALESCE(s.batch,'GERAL')                      AS lote,
  COALESCE(s.product_status,'N/D')               AS estado,
  ROUND(MAX(COALESCE(s.unit_value,0)), 6)        AS unit_value,
  SUM(COALESCE(sc.amount,0))                     AS qtde_unidades,
  SUM(COALESCE(sc.amount,0) * COALESCE(s.unit_value,0)) AS valor
FROM api_wms_stock s
JOIN api_wms_stock_complement sc ON sc.stock_id = s.id
WHERE s.deleted_at IS NULL
  AND s.is_active = 1
  AND TRIM(s.document_number) = %s
  AND s.{DATE_FIELD} >= %s
  AND s.{DATE_FIELD} < %s
  {estoque_clause}
  AND {local_clause_sql}
GROUP BY
  DATE(s.{DATE_FIELD}),
  TRIM(s.document_number),
  s.warehouse,
  COALESCE(s.sector,'SEM_SETOR'),
  sc.local_id,
  s.product_code,
  COALESCE(s.batch,'GERAL'),
  COALESCE(s.product_status,'N/D')
ORDER BY data_ref, endereco, codigo_produto, lote
"""


# =========================
# CONEXÃO / HELPERS
# =========================

def _conn_wms():
    return mysql.connector.connect(
        host=HOST,
        port=PORT,
        user=USER,
        password=PASSWORD,
        database=DB,
        use_pure=True,
        connection_timeout=30,
        read_timeout=600,
        write_timeout=600,
        charset="utf8mb4",
        ssl_disabled=False,
    )


def d(x: Any) -> Decimal:
    if x is None:
        return Decimal("0")
    if isinstance(x, Decimal):
        return x
    try:
        return Decimal(str(x))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def br_money(v: Decimal) -> str:
    s = f"{v:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def br_num(v: Decimal, dec: int = 2) -> str:
    s = f"{{:,.{dec}f}}".format(v)
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def mask_cnpj(cnpj: str) -> str:
    c = "".join(ch for ch in (cnpj or "") if ch.isdigit())
    if len(c) != 14:
        return cnpj
    return f"{c[0:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:14]}"


def _safe_ymd(s: str) -> Optional[str]:
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except Exception:
        return None


def _dt_range(data_inicial: str, data_final: str) -> Tuple[datetime, datetime]:
    di = datetime.strptime(data_inicial, "%Y-%m-%d").date()
    df = datetime.strptime(data_final, "%Y-%m-%d").date()
    start_dt = datetime.combine(di, datetime.min.time())
    end_dt = datetime.combine(df + timedelta(days=1), datetime.min.time())
    return start_dt, end_dt


def _dt_day(dia_str: str) -> Tuple[datetime, datetime]:
    d0 = datetime.strptime(dia_str, "%Y-%m-%d").date()
    start_dt = datetime.combine(d0, datetime.min.time())
    end_dt = datetime.combine(d0 + timedelta(days=1), datetime.min.time())
    return start_dt, end_dt


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        if v is None or v == "":
            return default
        return int(str(v).strip())
    except Exception:
        return default


def _like_from_prefix(prefix: str) -> str:
    p = (prefix or "").strip()
    if not p:
        return "%"
    if "%" in p:
        return p
    return f"{p}%"


def _sql_like_any(field_sql: str, prefixes: List[str]) -> Tuple[str, List[str]]:
    """
    Monta: (field LIKE %s OR field LIKE %s ...) com params.
    Se não houver prefixos, retorna "1=1" e params vazios.
    """
    likes = [_like_from_prefix(p) for p in (prefixes or []) if str(p).strip()]
    if not likes:
        return "1=1", []
    clause = "(" + " OR ".join([f"{field_sql} LIKE %s"] * len(likes)) + ")"
    return clause, likes


def _get_conta_ativa(request) -> Optional[ContaFaturamento]:
    conta_id = request.session.get("conta_id")
    if not conta_id:
        return None
    try:
        # tenta puxar config junto (reverse one-to-one)
        return (
            ContaFaturamento.objects
            .select_related("cliente", "config")
            .get(id=conta_id, ativa=True, cliente__ativo=True)
        )
    except ContaFaturamento.DoesNotExist:
        request.session.pop("conta_id", None)
        request.session.modified = True
        return None


def _get_config_prefixes_and_flags(conta: ContaFaturamento) -> Tuple[List[str], bool]:
    """
    Fonte oficial: ConfigContaFaturamento (conta.config)
    - wms_local_prefixes: lista de prefixos
    - somente_com_estoque: default True
    """
    try:
        cfg = conta.config
    except Exception:
        cfg = None

    if not cfg:
        return [], True

    prefixes = cfg.wms_local_prefixes or []
    somente = bool(getattr(cfg, "somente_com_estoque", True))
    return prefixes, somente


# =========================
# PICO AD-VALOREM / ARMAZENAGEM
# =========================

def calcular_pico_advalorem_unitvalue_join(cnpj_wms: str, data_inicial: str, data_final: str) -> Tuple[Optional[str], Decimal]:
    start_dt, end_dt = _dt_range(data_inicial, data_final)

    conn = _conn_wms()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(SQL_PICO_ADVALOREM_UNITVALUE_JOIN, (cnpj_wms, start_dt, end_dt))
        row = cur.fetchone()
        cur.close()

        if not row:
            return None, Decimal("0")

        dia = row.get("dia")
        dia_str = dia.strftime("%Y-%m-%d") if hasattr(dia, "strftime") else str(dia)
        total = d(row.get("total_unit_value"))
        return dia_str, total
    finally:
        conn.close()


def calcular_pico_armazenagem(
    cnpj_wms: str,
    data_inicial: str,
    data_final: str,
    prefixes: List[str],
    somente_com_estoque: bool,
) -> Tuple[Optional[str], Optional[int]]:
    start_dt, end_dt = _dt_range(data_inicial, data_final)

    local_clause_sql, local_params = _sql_like_any("sc.local_id", prefixes)
    sql = _sql_pico_armazenagem(local_clause_sql, somente_com_estoque)

    conn = _conn_wms()
    try:
        cur = conn.cursor(dictionary=True)
        params = [cnpj_wms, start_dt, end_dt] + local_params
        cur.execute(sql, params)
        row = cur.fetchone()
        cur.close()

        if not row:
            return None, None

        dia = row.get("dia")
        dia_str = dia.strftime("%Y-%m-%d") if hasattr(dia, "strftime") else str(dia)
        qtd = int(row.get("qtd_pico") or 0)
        return dia_str, qtd
    finally:
        conn.close()


# =========================
# EXPORT (SÓ O DIA DO PICO)
# =========================

def export_wms_xlsx(conta: ContaFaturamento, data_inicial: str, data_final: str) -> HttpResponse:
    cnpj_wms = (conta.cnpj_wms or "").strip()

    prefixes, somente_com_estoque = _get_config_prefixes_and_flags(conta)

    pico_dia, pico_qtd = calcular_pico_armazenagem(
        cnpj_wms, data_inicial, data_final, prefixes, somente_com_estoque
    )

    if not pico_dia:
        return HttpResponse(
            f"Sem dados para exportar no período {data_inicial} a {data_final}.",
            status=404,
            content_type="text/plain; charset=utf-8",
        )

    start_dt, end_dt = _dt_day(pico_dia)

    local_clause_sql, local_params = _sql_like_any("sc.local_id", prefixes)
    sql = _sql_export(local_clause_sql, somente_com_estoque)

    headers = [
        "Data", "CNPJ", "Armazém", "Setor", "Endereço",
        "Código Produto", "Produto", "Estado", "Lote",
        "Unit Value", "Qtde Unidades", "Valor"
    ]

    wb = Workbook(write_only=True)
    ws = wb.create_sheet("wms_export")
    ws.append(headers)

    conn = _conn_wms()
    try:
        cur = conn.cursor()
        params = [cnpj_wms, start_dt, end_dt] + local_params
        cur.execute(sql, params)

        while True:
            rows = cur.fetchmany(5000)
            if not rows:
                break

            for (
                data_ref, cnpj, armazem, setor, endereco, codigo_produto, produto,
                lote, estado, unit_value, qtde_unidades, valor
            ) in rows:
                ws.append([
                    data_ref, cnpj, armazem, setor, endereco,
                    codigo_produto, produto, estado, lote,
                    float(unit_value or 0),
                    float(qtde_unidades or 0),
                    float(valor or 0),
                ])

        cur.close()
    finally:
        conn.close()

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)

    # Tag do arquivo
    if not prefixes:
        prefix_tag = "ALL"
    elif len(prefixes) == 1:
        prefix_tag = str(prefixes[0]).replace("%", "").replace(" ", "")
    else:
        prefix_tag = "MULTI"

    filename = (
        f"wms_export_{prefix_tag}_{cnpj_wms}_PICO_{pico_dia}_LOC_{pico_qtd}"
        f"_({data_inicial}_a_{data_final}).xlsx"
    )

    resp = HttpResponse(
        bio.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


# =========================
# VIEW PRINCIPAL
# =========================

@login_required
def tela_estoque_valor(request):
    conta = _get_conta_ativa(request)
    if not conta:
        return redirect(reverse("clientes:selecionar"))

    hoje = date.today().isoformat()
    data_inicial = _safe_ymd(request.GET.get("data_inicial") or "") or hoje
    data_final = _safe_ymd(request.GET.get("data_final") or "") or hoje

    # manual (não-Prefixo) — por enquanto via GET
    arm_outros = _safe_int(request.GET.get("arm_outros"), default=0)

    if request.GET.get("export") == "1":
        return export_wms_xlsx(conta, data_inicial, data_final)

    erros: List[str] = []

    cnpj_wms = (conta.cnpj_wms or "").strip()
    prefixes, somente_com_estoque = _get_config_prefixes_and_flags(conta)

    # Ad-valorem (pico) - regra original
    pico_dia = None
    pico_base_valor = Decimal("0")

    # Armazenagem (pico) - com prefixes da config
    arm_dia = None
    arm_qtd = None

    try:
        pico_dia, pico_base_valor = calcular_pico_advalorem_unitvalue_join(
            cnpj_wms, data_inicial, data_final
        )
    except Exception as e:
        erros.append(f"Pico valor (ad-valorem): {e}")

    try:
        arm_dia, arm_qtd = calcular_pico_armazenagem(
            cnpj_wms, data_inicial, data_final, prefixes, somente_com_estoque
        )
    except Exception as e:
        erros.append(f"Pico armazenagem: {e}")

    # ✅ Só 1 linha: armazenagem = (pico calculado) + manual
    arm_total = None
    if arm_qtd is not None:
        arm_total = int(arm_qtd) + int(arm_outros or 0)
    elif arm_outros:
        arm_total = int(arm_outros)

    linhas = [
        {"servico": "Ad-valorem (pico)", "taxa": d("0.0731"), "taxa_unit": "%", "qtd": pico_base_valor, "qtd_unit": "", "tipo": "PERCENTUAL"},
        {"servico": "Armazenagem (pico)", "taxa": d("21.25"), "taxa_unit": "", "qtd": arm_total, "qtd_unit": "plt", "tipo": "MULT"},
        {"servico": "Descarga por palete", "taxa": d("9.00"), "taxa_unit": "", "qtd": None, "qtd_unit": "plt", "tipo": "MULT"},
        {"servico": "Carga por NF", "taxa": d("10.63"), "taxa_unit": "", "qtd": None, "qtd_unit": "nf", "tipo": "MULT"},
        {"servico": "Pedidos cancelados - entrada por palete", "taxa": d("9.00"), "taxa_unit": "", "qtd": None, "qtd_unit": "plt", "tipo": "MULT"},
        {"servico": "Pedidos cancelados - por Pedido", "taxa": d("10.63"), "taxa_unit": "", "qtd": None, "qtd_unit": "ped", "tipo": "MULT"},
        {"servico": "Crossdocking", "taxa": d("1829.50"), "taxa_unit": "", "qtd": None, "qtd_unit": "cntr", "tipo": "MULT"},
        {"servico": "Etiquetagem", "taxa": d("0.54"), "taxa_unit": "", "qtd": None, "qtd_unit": "un", "tipo": "MULT"},
        {"servico": "Hora Extra", "taxa": d("3756.57"), "taxa_unit": "R$", "qtd": None, "qtd_unit": "", "tipo": "MULT"},
    ]

    subtotal = Decimal("0")
    for ln in linhas:
        qtd = ln["qtd"]
        taxa = ln["taxa"]

        if qtd is None:
            ln["valor"] = None
            ln["taxa_fmt"] = f"{br_num(d(taxa), 4)}%" if ln["tipo"] == "PERCENTUAL" else br_num(d(taxa), 2)
            ln["qtd_fmt"] = "-"
            ln["valor_fmt"] = "-"
            continue

        if ln["tipo"] == "PERCENTUAL":
            valor = (d(qtd) * d(taxa)) / Decimal("100")
            ln["taxa_fmt"] = f"{br_num(d(taxa), 4)}%"
            ln["qtd_fmt"] = f"{br_money(d(qtd))}"
            ln["valor_fmt"] = f"R$ {br_money(valor)}"
        else:
            valor = d(qtd) * d(taxa)
            ln["taxa_fmt"] = br_num(d(taxa), 2)
            ln["qtd_fmt"] = str(qtd) if isinstance(qtd, int) else br_num(d(qtd), 2)
            ln["valor_fmt"] = f"R$ {br_money(valor)}"

        ln["valor"] = valor
        subtotal += valor

    iss_percent = d("0.98")
    iss_valor = (subtotal * iss_percent) / Decimal("100")
    total_geral = subtotal + iss_valor

    def fmt_periodo(dt_str: str) -> str:
        try:
            dt = datetime.strptime(dt_str, "%Y-%m-%d")
            return dt.strftime("%d.%m.%Y")
        except Exception:
            return dt_str

    periodo_txt = f"{fmt_periodo(data_inicial)} a {fmt_periodo(data_final)}"

    return render(
        request,
        "relatorios/tela_ricoh.html",  # pode renomear depois
        {
            "conta": conta,
            "cliente": conta.cliente,

            "cnpj": mask_cnpj(cnpj_wms),
            "prefixes": prefixes,
            "somente_com_estoque": somente_com_estoque,

            "data_inicial": data_inicial,
            "data_final": data_final,
            "periodo_txt": periodo_txt,

            "pico_dia": pico_dia,
            "pico_base_valor": pico_base_valor,
            "pico_base_valor_fmt": br_money(pico_base_valor),

            "arm_pico_dia": arm_dia,
            "arm_pico_qtd": arm_qtd,
            "arm_outros": arm_outros,

            "linhas": linhas,

            "subtotal_fmt": f"R$ {br_money(subtotal)}",
            "iss_percent_fmt": br_num(iss_percent, 2),
            "iss_valor_fmt": f"R$ {br_money(iss_valor)}",
            "total_fmt": f"R$ {br_money(total_geral)}",

            "erro_wms": " | ".join(erros) if erros else None,
        },
    )
