import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from django.shortcuts import render
import mysql.connector


HOST = ""
PORT = 3306
USER = ""
PASSWORD = ""  # coloque sua senha aqui
DB = ""

CNPJ_RICOH = "33597659001521"
DATE_FIELD = "created_at"  # se um dia quiser trocar para updated_at, altere aqui

# Locais permitidos (equivalente ao LIKE do complement):
# PP / BINS / BL
def local_permitido(local: str) -> bool:
    if not local:
        return False
    u = local.upper()
    return u.startswith("PP-") or ("BINS" in u) or ("BL" in u)

# Regex para extrair do texto s.endereco:
# Identificação do endereço: PP-20-021-2-01
# Quantidade disponível: 10
# Quantidade total: 12
RE_ENDERECO_FULL = re.compile(
    r"Identificação do endereço:\s*([A-Z]{2}-\d{2}-\d{3}-\d-\d{2})\s*"
    r"(?:\r?\n)+Quantidade disponível:\s*([0-9]+(?:[.,][0-9]+)?)\s*"
    r"(?:\r?\n)+Quantidade total:\s*([0-9]+(?:[.,][0-9]+)?)",
    re.IGNORECASE,
)

SQL_STOCK_PERIODO = f"""
SELECT
  s.id AS stock_id,
  DATE(s.{DATE_FIELD}) AS dia,
  COALESCE(s.unit_value, 0) AS unit_value,
  COALESCE(s.amount_total, 0) AS amount_total,
  s.endereco AS endereco_raw
FROM api_wms_stock s
WHERE s.deleted_at IS NULL
  AND s.is_active = 1
  AND DATE(s.{DATE_FIELD}) BETWEEN %s AND %s
  AND TRIM(s.document_number) = %s
ORDER BY s.id
"""


def _conn_wms():
    return mysql.connector.connect(
        host=HOST,
        port=PORT,
        user=USER,
        password=PASSWORD,
        database=DB,
        use_pure=True,            # importante no seu Python 3.14
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


def to_decimal_locale(x: Any) -> Decimal:
    """
    Converte valores tipo '1.234,56' ou '1234,56' para Decimal.
    """
    if x is None:
        return Decimal("0")
    if isinstance(x, (int, float, Decimal)):
        return Decimal(str(x))
    s = str(x).strip()
    if not s:
        return Decimal("0")
    # remove separador de milhar e troca vírgula por ponto
    s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except Exception:
        return Decimal("0")


def parse_endereco(endereco: Optional[str]) -> List[Dict[str, Any]]:
    if not endereco:
        return []
    out = []
    for local, qtd_disp, qtd_total in RE_ENDERECO_FULL.findall(endereco):
        out.append(
            {
                "local": (local or "").upper().strip(),
                "qtd_total": to_decimal_locale(qtd_total),
                "qtd_disponivel": to_decimal_locale(qtd_disp),
            }
        )
    return out


def br_money(v: Decimal) -> str:
    # 12.345.678,90
    s = f"{v:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def br_num(v: Decimal, dec: int = 2) -> str:
    s = f"{{:,.{dec}f}}".format(v)
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def mask_cnpj(cnpj: str) -> str:
    c = "".join(ch for ch in (cnpj or "") if ch.isdigit())
    if len(c) != 14:
        return cnpj
    return f"{c[0:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:14]}"


def calcular_pico_valor_periodo(data_inicial: str, data_final: str) -> tuple[Optional[str], Decimal]:
    """
    Retorna (pico_dia, pico_valor):
    - pico_dia = dia do período com MAIOR valor total de estoque
    - pico_valor = soma(quantidade * unit_value) nesse dia

    Calcula usando APENAS api_wms_stock:
    - extrai quantidade total do texto do endereco (por local)
    - filtra locais PP/BINS/BL
    - fallback: se não parsear, usa amount_total apenas se o texto contiver PP/BINS/BL
    """
    totals_por_dia: Dict[str, Decimal] = {}

    conn = _conn_wms()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(SQL_STOCK_PERIODO, (data_inicial, data_final, CNPJ_RICOH))

        batch_size = 5000
        while True:
            rows = cur.fetchmany(batch_size)
            if not rows:
                break

            for r in rows:
                dia = r.get("dia")
                if dia is None:
                    continue

                # dia pode vir como date ou string dependendo do connector
                if hasattr(dia, "strftime"):
                    dia_key = dia.strftime("%Y-%m-%d")
                else:
                    dia_key = str(dia)

                unit_value = d(r.get("unit_value"))
                end_raw = r.get("endereco_raw") or ""
                amount_total = d(r.get("amount_total"))

                locais = parse_endereco(end_raw)

                valor_add = Decimal("0")
                if locais:
                    # soma apenas locais permitidos
                    for loc in locais:
                        if local_permitido(loc["local"]):
                            valor_add += (d(loc["qtd_total"]) * unit_value)
                else:
                    # fallback só se o texto indicar PP/BINS/BL
                    u = end_raw.upper()
                    if ("PP-" in u) or ("BINS" in u) or ("BL" in u):
                        valor_add += (amount_total * unit_value)

                if valor_add != 0:
                    totals_por_dia[dia_key] = totals_por_dia.get(dia_key, Decimal("0")) + valor_add

        cur.close()
    finally:
        conn.close()

    if not totals_por_dia:
        return None, Decimal("0")

    pico_dia = max(totals_por_dia, key=lambda k: totals_por_dia[k])
    pico_valor = totals_por_dia[pico_dia]
    return pico_dia, pico_valor


def tela_estoque_valor(request):
    hoje = date.today().isoformat()
    data_inicial = request.GET.get("data_inicial") or hoje
    data_final = request.GET.get("data_final") or hoje

    pico_dia = None
    pico_base_valor = Decimal("0")
    erro_wms = None

    try:
        pico_dia, pico_base_valor = calcular_pico_valor_periodo(data_inicial, data_final)
    except Exception as e:
        erro_wms = str(e)

    # LINHAS DA FATURA (manual por enquanto, só o ad-valorem usa a base do WMS)
    linhas = [
        {
            "servico": "Ad-valorem (pico)",
            "taxa": d("0.0731"),      # % (ex.: 0,0731%)
            "taxa_unit": "%",
            "qtd": pico_base_valor,   # BASE em R$ (pico no período)
            "qtd_unit": "R$",
            "tipo": "PERCENTUAL",     # valor = base * taxa/100
        },
        {"servico": "Armazenagem (pico)", "taxa": d("21.25"), "taxa_unit": "", "qtd": None, "qtd_unit": "plt", "tipo": "MULT"},
        {"servico": "Descarga por palete", "taxa": d("9.00"), "taxa_unit": "", "qtd": None, "qtd_unit": "plt", "tipo": "MULT"},
        {"servico": "Carga por NF", "taxa": d("10.63"), "taxa_unit": "", "qtd": None, "qtd_unit": "nf", "tipo": "MULT"},
        {"servico": "Pedidos cancelados - entrada por palete", "taxa": d("9.00"), "taxa_unit": "", "qtd": None, "qtd_unit": "plt", "tipo": "MULT"},
        {"servico": "Pedidos cancelados - por Pedido", "taxa": d("10.63"), "taxa_unit": "", "qtd": None, "qtd_unit": "ped", "tipo": "MULT"},
        {"servico": "Crossdocking", "taxa": d("1829.50"), "taxa_unit": "", "qtd": None, "qtd_unit": "cntr", "tipo": "MULT"},
        {"servico": "Etiquetagem", "taxa": d("0.54"), "taxa_unit": "", "qtd": None, "qtd_unit": "un", "tipo": "MULT"},
        {"servico": "Hora Extra", "taxa": d("3756.57"), "taxa_unit": "R$", "qtd": None, "qtd_unit": "", "tipo": "MULT"},
    ]

    # calcula valores e subtotal
    subtotal = Decimal("0")
    for ln in linhas:
        qtd = ln["qtd"]
        taxa = ln["taxa"]

        if qtd is None:
            ln["valor"] = None
            continue

        if ln["tipo"] == "PERCENTUAL":
            valor = (d(qtd) * d(taxa)) / Decimal("100")
        else:
            valor = d(qtd) * d(taxa)

        ln["valor"] = valor
        subtotal += valor

    # ISS (exemplo fixo)
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
        "pico_base_valor_fmt": br_money(pico_base_valor),

        "linhas": linhas,

        "subtotal_fmt": br_money(subtotal),
        "iss_percent_fmt": br_num(iss_percent, 2),
        "iss_valor_fmt": br_money(iss_valor),
        "total_fmt": br_money(total_geral),

        "erro_wms": erro_wms,
    })
