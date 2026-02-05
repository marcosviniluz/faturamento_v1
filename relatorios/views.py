import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from django.shortcuts import render
import mysql.connector


HOST = "vdm-analytics-wms.mysql.database.azure.com"
PORT = 3306
USER = "prod_vdm_wms_view"
PASSWORD = ""
DB = "prod_vdm_wms"

CNPJ_RICOH = "33597659001521"
DATE_FIELD = "created_at"

LIKE1, LIKE2, LIKE3 = "%PP-%", "%BINS%", "%BL%"


SQL_PICO_VALOR_UNITVALUE_JOIN = f"""
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
ORDER BY total_unit_value DESC
LIMIT 1
"""

SQL_PICO_ARMAZENAGEM_COMPLEMENT = f"""
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
  AND sc.amount > 0
  AND (
        sc.local_id LIKE %s
     OR sc.local_id LIKE %s
     OR sc.local_id LIKE %s
  )
GROUP BY DATE(s.{DATE_FIELD})
ORDER BY qtd_pico DESC
LIMIT 1
"""


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


def calcular_pico_valor_periodo_unitvalue_join(data_inicial: str, data_final: str) -> Tuple[Optional[str], Decimal]:
    start_dt, end_dt = _dt_range(data_inicial, data_final)

    conn = _conn_wms()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(SQL_PICO_VALOR_UNITVALUE_JOIN, (CNPJ_RICOH, start_dt, end_dt))
        row = cur.fetchone()
        cur.close()

        if not row:
            return None, Decimal("0")

        dia = row.get("dia")
        if hasattr(dia, "strftime"):
            dia_str = dia.strftime("%Y-%m-%d")
        else:
            dia_str = str(dia)

        total = d(row.get("total_unit_value"))
        return dia_str, total
    finally:
        conn.close()


def calcular_pico_armazenagem_complement(data_inicial: str, data_final: str) -> Tuple[Optional[str], Optional[int]]:
    start_dt, end_dt = _dt_range(data_inicial, data_final)

    conn = _conn_wms()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            SQL_PICO_ARMAZENAGEM_COMPLEMENT,
            (CNPJ_RICOH, start_dt, end_dt, LIKE1, LIKE2, LIKE3),
        )
        row = cur.fetchone()
        cur.close()

        if not row:
            return None, None

        dia = row.get("dia")
        if hasattr(dia, "strftime"):
            dia_str = dia.strftime("%Y-%m-%d")
        else:
            dia_str = str(dia)

        qtd = int(row.get("qtd_pico") or 0)
        return dia_str, qtd
    finally:
        conn.close()


def tela_estoque_valor(request):
    hoje = date.today().isoformat()

    data_inicial = _safe_ymd(request.GET.get("data_inicial") or "") or hoje
    data_final = _safe_ymd(request.GET.get("data_final") or "") or hoje

    pico_dia = None
    pico_base_valor = Decimal("0")

    arm_dia = None
    arm_qtd = None

    erros: List[str] = []

    try:
        pico_dia, pico_base_valor = calcular_pico_valor_periodo_unitvalue_join(data_inicial, data_final)
    except Exception as e:
        erros.append(f"Pico valor: {e}")

    try:
        arm_dia, arm_qtd = calcular_pico_armazenagem_complement(data_inicial, data_final)
    except Exception as e:
        erros.append(f"Pico armazenagem: {e}")

    linhas = [
        {
            "servico": "Ad-valorem (pico)",
            "taxa": d("0.0731"),
            "taxa_unit": "%",
            "qtd": pico_base_valor,
            "qtd_unit": "",
            "tipo": "PERCENTUAL",
        },
        {
            "servico": "Armazenagem (pico)",
            "taxa": d("21.25"),
            "taxa_unit": "",
            "qtd": arm_qtd,
            "qtd_unit": "plt",
            "tipo": "MULT",
        },
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
            ln["qtd_fmt"] = f" {br_money(d(qtd))}"
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

    return render(request, "relatorios/tela_ricoh.html", {
        "cnpj": mask_cnpj(CNPJ_RICOH),
        "data_inicial": data_inicial,
        "data_final": data_final,
        "periodo_txt": periodo_txt,

        "pico_dia": pico_dia,
        "pico_base_valor": pico_base_valor,
        "pico_base_valor_fmt": br_money(pico_base_valor),

        "arm_pico_dia": arm_dia,
        "arm_pico_qtd": arm_qtd,

        "linhas": linhas,

        "subtotal_fmt": f"R$ {br_money(subtotal)}",
        "iss_percent_fmt": br_num(iss_percent, 2),
        "iss_valor_fmt": f"R$ {br_money(iss_valor)}",
        "total_fmt": f"R$ {br_money(total_geral)}",

        "erro_wms": " | ".join(erros) if erros else None,
    })
