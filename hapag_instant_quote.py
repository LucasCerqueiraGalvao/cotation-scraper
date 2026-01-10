# hapag_batch_quotes.py

import os
import csv
import time
from pathlib import Path
from datetime import datetime, timedelta
import re

import pandas as pd
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ----------------------------------------------------------------------
# CONFIG BÁSICA
# ----------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

LOGIN_URL = (
    "https://identity.hapag-lloyd.com/hlagwebprod.onmicrosoft.com/"
    "b2c_1a_signup_signin/oauth2/v2.0/authorize"
    "?client_id=64d7a44b-1c5b-4b52-9ff9-254f7acd8fc0"
    "&scope=openid%20profile%20offline_access"
    "&redirect_uri=https%3A%2F%2Fwww.hapag-lloyd.com%2Fsolutions%2Fauth"
    "&client-request-id=019a8447-744b-7d99-85af-7bad6330baad"
    "&response_mode=fragment&response_type=code"
    "&x-client-SKU=msal.js.browser&x-client-VER=3.9.0"
    "&client_info=1"
    "&code_challenge=pCk0nSh6hx7xHTXW2vBuJW8KE0xjWCNnUKK4R3k17rg"
    "&code_challenge_method=S256"
    "&nonce=019a8447-744b-7512-9bfc-ae9439e64e96"
    "&state=eyJpZCI6IjAxOWE4NDQ3LTc0NGItN2ZhMC04NjU4LTMxZjRkZWRlYWFkZSIsIm1ldGEiOnsiaW50ZXJhY3Rpb25UeXBlIjoicmVkaXJlY3QifX0%3D"
)

NEW_QUOTE_URL = "https://www.hapag-lloyd.com/solutions/new-quote/#/simple?language=en"

JOBS_XLSX = BASE_DIR / "artifacts" / "input" / "hapag_jobs.xlsx"
OUTPUT_CSV = BASE_DIR / "artifacts" / "output" / "hapag_breakdowns.csv"

# colunas de charge que vamos manter fixas no CSV
KNOWN_CHARGES = [
    "Ocean Freight",
    "Export Surcharges",
    "Freight Surcharges",
    "Import Surcharges",
]

BASE_FIELDS = [
    "key",
    "origin",
    "destination",
    "last_attempt_at",
    "quoted_at",
    "status",
    "message",
]

ALL_FIELDS = BASE_FIELDS + KNOWN_CHARGES


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


# ----------------------------------------------------------------------
# CREDENCIAIS (.env)
# ----------------------------------------------------------------------

load_dotenv()
HL_USER = os.getenv("HL_USER")
HL_PASS = os.getenv("HL_PASS")

if not HL_USER or not HL_PASS:
    raise RuntimeError("Defina HL_USER e HL_PASS no .env")


# ----------------------------------------------------------------------
# HELPERS DE DATA / HISTÓRICO / CACHE
# ----------------------------------------------------------------------

def _all_fieldnames_from_cache(rows_cache):
    extras = set()
    for row in rows_cache.values():
        for k in row.keys():
            if k not in BASE_FIELDS:
                extras.add(k)
    return BASE_FIELDS + sorted(extras)


def load_rows_cache(csv_path: Path):
    rows_cache = {}
    if not csv_path.exists():
        return rows_cache

    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for raw_row in reader:
            row = dict(raw_row)

            origin = (row.get("origin") or "").strip()
            destination = (row.get("destination") or "").strip()
            key = (row.get("key") or "").strip() or f"{origin}-{destination}"
            row["key"] = key

            # garante base
            for field in BASE_FIELDS:
                row.setdefault(field, "")

            existing = rows_cache.get(key)
            if not existing:
                rows_cache[key] = row
                continue

            curr_attempt = _parse_iso_or_none(existing.get("last_attempt_at"))
            new_attempt = _parse_iso_or_none(row.get("last_attempt_at"))
            curr_success = _parse_iso_or_none(existing.get("quoted_at"))
            new_success = _parse_iso_or_none(row.get("quoted_at"))

            merged = existing

            if new_attempt and (not curr_attempt or new_attempt > curr_attempt):
                merged["last_attempt_at"] = row.get("last_attempt_at") or ""
                merged["status"] = row.get("status") or ""
                merged["message"] = row.get("message") or ""

            # sucesso mais recente -> copia quoted_at + TODAS as colunas extras
            if new_success and (not curr_success or new_success > curr_success):
                merged["quoted_at"] = row.get("quoted_at") or ""
                for k, v in row.items():
                    if k not in BASE_FIELDS:
                        merged[k] = v

            rows_cache[key] = merged

    log(f"Rows cache carregado de {csv_path} com {len(rows_cache)} keys (deduplicado).")
    return rows_cache


def upsert_charges_in_cache(rows_cache, charges, origin, destination, status, message, key=None):
    if key is None:
        key = f"{origin}-{destination}"

    now_iso = datetime.now().isoformat()

    row = rows_cache.get(key)
    if row is None:
        row = {field: "" for field in BASE_FIELDS}
        row["key"] = key

    row["origin"] = origin
    row["destination"] = destination
    row["last_attempt_at"] = now_iso
    row["status"] = status
    row["message"] = message

    if status == "success":
        row["quoted_at"] = now_iso
        # grava TODAS as chaves retornadas pelo breakdown
        for k, v in charges.items():
            row[k] = v

    rows_cache[key] = row


def flush_rows_cache_to_csv(rows_cache, csv_path: Path):
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = _all_fieldnames_from_cache(rows_cache)

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for key in sorted(rows_cache.keys()):
            row = rows_cache[key]
            out_row = {field: row.get(field, "") for field in fieldnames}
            writer.writerow(out_row)

    log(f"CSV atualizado em {csv_path} com {len(rows_cache)} linhas (1 por key).")


def _parse_iso_or_none(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None



def build_history_from_rows_cache(rows_cache):
    """
    Constrói histórico de tentativas/sucessos a partir do cache:
      history[key] = {
        'has_any_attempt', 'has_success',
        'last_attempt_at', 'last_success_at'
      }
    """
    history = {}
    for key, row in rows_cache.items():
        last_attempt = _parse_iso_or_none(row.get("last_attempt_at"))
        quoted_at = _parse_iso_or_none(row.get("quoted_at"))
        status = (row.get("status") or "").strip()

        history[key] = {
            "has_any_attempt": last_attempt is not None,
            "has_success": bool(quoted_at) and status == "success",
            "last_attempt_at": last_attempt,
            "last_success_at": quoted_at if quoted_at and status == "success" else None,
        }

    return history

# ----------------------------------------------------------------------
# Cloudflare: só detecta e espera você resolver na janela
# ----------------------------------------------------------------------
def wait_cloudflare_if_needed(page, max_wait_sec=120):
    """Se aparecer a tela de 'Security Check', espera você resolver."""
    try:
        page.get_by_text("Security Check", exact=False).wait_for(timeout=5000)
        print("Cloudflare Security Check detectado.")
        print(f"Resolve o 'Confirme que é humano' na janela (até {max_wait_sec}s).")
        page.wait_for_function(
            "() => !document.body.innerText.includes('Security Check')",
            timeout=max_wait_sec * 1000,
        )
        print("Security Check liberado, seguindo...")
    except PWTimeout:
        pass
    except Exception:
        pass


# ----------------------------------------------------------------------
# LOGIN
# ----------------------------------------------------------------------
def _find_login_frame(page):
    """Procura o frame que contém o input #signInName."""
    for fr in page.frames:
        try:
            fr.wait_for_selector("#signInName", timeout=2000)
            return fr
        except PWTimeout:
            continue
    raise RuntimeError("Não achei o frame com o campo #signInName.")


def login_hapag(page):
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
    wait_cloudflare_if_needed(page)

    fr = _find_login_frame(page)

    # cookies
    try:
        fr.click("#accept-recommended-btn-handler", timeout=3000)
        print("Cookies: 'Select All' clicado.")
    except Exception:
        pass

    fr.fill("#signInName", HL_USER)
    fr.fill("#password", HL_PASS)

    time.sleep(0.5)
    try:
        fr.wait_for_selector("#next", timeout=5000)
        fr.click("#next")
    except Exception:
        fr.press("#password", "Enter")

    try:
        page.wait_for_url(lambda url: "signup_signin" not in url, timeout=30000)
    except Exception:
        pass

    print("Login Hapag: tentativa concluída.")


# ----------------------------------------------------------------------
# PÁGINA DE COTAÇÃO / PREENCHIMENTO
# ----------------------------------------------------------------------
def open_quote_page(page):
    log("Abrindo página de cotação...")
    page.goto(NEW_QUOTE_URL, wait_until="networkidle", timeout=60000)
    wait_cloudflare_if_needed(page)


def _fill_location_with_dropdown(page, testid: str, code: str, label: str):
    log(f"Preenchendo {label} {code}...")
    field = page.locator(f'input[data-testid="{testid}"]')
    field.wait_for(timeout=30000)
    field.click()
    field.fill(code)

    # espera o dropdown aparecer e clica na opção com o código
    page.wait_for_timeout(1500)
    option = page.get_by_text(code, exact=False).first
    option.wait_for(timeout=10000)
    option.click()


def fill_origin_destination_and_date(page, origin_code: str, dest_code: str):
    _fill_location_with_dropdown(page, "start-input", origin_code, "origem")
    time.sleep(1)

    _fill_location_with_dropdown(page, "end-input", dest_code, "destino")
    time.sleep(1)

    # DATA – hoje + 14 dias
    log("Preenchendo data (hoje + 14)...")
    date_input = page.locator('input[data-testid="validity-input"]')
    date_input.wait_for(timeout=30000)

    date_str = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
    date_input.click()
    date_input.fill(date_str)

    try:
        date_input.evaluate("el => el.blur()")
    except Exception:
        page.click("text=Container Type", timeout=30000)

    log("Origem, destino e data preenchidos.")


def select_container_and_weight(page, weight_kg: int = 26000):
    # container
    log("Selecionando container \"20' General Purpose\"...")
    container = page.locator('[data-testid="container-input"]')
    container.wait_for(timeout=30000)
    container.click()

    option = page.get_by_text("20' General Purpose", exact=False).first
    option.wait_for(timeout=10000)
    option.click()
    time.sleep(1)

    # peso + Enter
    log(f"Preenchendo peso {weight_kg} kg e confirmando...")
    weight_input = page.locator('input[data-testid="weight-input"]')
    weight_input.wait_for(timeout=30000)
    weight_input.click()
    weight_input.fill("")
    weight_input.type(str(weight_kg))
    weight_input.press("Enter")

    log("Container e peso preenchidos; aguardando resultados...")


# ----------------------------------------------------------------------
# RESULTADOS / SIDEBAR / CSV
# ----------------------------------------------------------------------
def select_spot_offer(page):
    """
    Agora: abre o Price Breakdown do card Quick Quotes Spot (SEM clicar em Select).
    Mantém o mesmo nome pra não precisar mexer no resto do fluxo.
    """
    log("Abrindo Price Breakdown do Spot...")

    # pega o card Spot de forma bem estável
    spot_card = page.locator(
        'div.offer-card:has(button[data-testid="offer-card-select-button-spot"])'
    ).first
    spot_card.wait_for(state="visible", timeout=20000)

    # botão dentro do card (tem o texto em span.block)
    pb_btn = spot_card.locator('button:has(span.block:has-text("Price Breakdown"))').first
    pb_btn.wait_for(state="visible", timeout=20000)
    pb_btn.scroll_into_view_if_needed()

    # às vezes Quasar/overlay pode “travar” click normal; por isso force
    pb_btn.click(force=True)

    # painel com as tabelas
    page.locator(".offer-charges").first.wait_for(timeout=20000)



def open_spot_price_breakdown(page):
    """
    Em vez de clicar em Select, clica no botão "Price Breakdown"
    dentro do card Spot, e espera o painel .offer-charges aparecer.
    """
    log("Abrindo Price Breakdown do Spot...")

    spot_select_btn = page.locator('button[data-testid="offer-card-select-button-spot"]').first
    spot_select_btn.wait_for(timeout=15000)

    # Sobe pro container do card (pra não clicar no breakdown do card errado)
    spot_card = spot_select_btn.locator(
        "xpath=ancestor::div[contains(@class,'offer-card')]"
    )

    breakdown_btn = spot_card.get_by_role("button", name="Price Breakdown")
    breakdown_btn.wait_for(timeout=15000)
    breakdown_btn.click()

    # Painel que contém todas as tabelas do breakdown
    page.locator(".offer-charges").first.wait_for(timeout=20000)


def extract_charge_items(page):
    """
    Lê o Price Breakdown (div.offer-charges) e retorna um dicionário
    com MUITAS chaves (itens das tabelas, moedas, cut-offs, notes, etc.).
    Também mantém alguns "resumos" compatíveis (Ocean Freight, Export Surcharges...).
    """

    def _parse_number(text: str):
        if text is None:
            return None
        s = str(text).strip()
        if not s:
            return None

        # remove espaços “esquisitos” (ex.: 26 000)
        s = s.replace("\u202f", "").replace("\xa0", "").replace(" ", "")

        # resolve casos 1,234.56 vs 1.234,56
        if "." in s and "," in s:
            if s.rfind(".") > s.rfind(","):
                s = s.replace(",", "")          # 1,234.56 -> 1234.56
            else:
                s = s.replace(".", "").replace(",", ".")  # 1.234,56 -> 1234.56
        else:
            # só vírgula: decide se é milhar ou decimal
            if "," in s:
                # se terminar com ,dd assume decimal; senão assume milhar
                if re.search(r",\d{1,2}$", s):
                    s = s.replace(",", ".")
                else:
                    s = s.replace(",", "")
            # só ponto: se for milhar tipo 1.837 (3 dígitos) remove
            if "." in s and re.search(r"\.\d{3}$", s):
                s = s.replace(".", "")

        try:
            return float(s)
        except Exception:
            return None

    def _main_label_from_first_cell(td):
        # Preferir o primeiro <div><div> (ignora subtítulo "To be paid prepaid")
        main = td.locator("div > div").first
        if main.count():
            return main.inner_text().strip()
        return td.inner_text().strip()

    log("Extraindo tabelas do Price Breakdown (.offer-charges)...")

    root = page.locator(".offer-charges").first
    root.wait_for(timeout=20000)

    charges = {}

    # Notes (texto livre)
    try:
        note = root.locator('p[data-testid="note"]').first
        if note.count():
            charges["Notes"] = note.inner_text().strip()
    except Exception:
        pass

    # Exchange rate as of <date>
    try:
        ex = root.locator('p:has-text("Exchange rate as of") span.text-button-s').first
        if ex.count():
            charges["Exchange rate as of"] = ex.inner_text().strip()
    except Exception:
        pass

    # Para manter compatibilidade, vamos somar por tabela (quando fizer sentido)
    sums = {}  # (group, size) -> {"curr": <CUR>, "sum": <float>, "multi_curr": bool}

    tables = root.locator("table.q-table")
    tcount = tables.count()

    for t in range(tcount):
        table = tables.nth(t)

        headers_loc = table.locator("thead th span")
        hcount = headers_loc.count()
        if hcount == 0:
            continue

        headers = [headers_loc.nth(i).inner_text().strip() for i in range(hcount)]
        group = headers[0]  # ex.: Freight Charges, Import Surcharges, Cut-offs...
        rows = table.locator("tbody tr")
        rcount = rows.count()

        for r in range(rcount):
            tr = rows.nth(r)
            tds = tr.locator("td")
            tdcount = tds.count()
            if tdcount < 2:
                continue

            item_name = _main_label_from_first_cell(tds.nth(0))

            # Caso especial: Cut-offs (Date/Time)
            if group.lower() == "cut-offs":
                # headers: ["Cut-offs", "Date", "Time"]
                date_val = tds.nth(1).inner_text().strip() if tdcount >= 2 else ""
                time_val = tds.nth(2).inner_text().strip() if tdcount >= 3 else ""
                charges[f"Cut-offs | {item_name} | Date"] = date_val
                charges[f"Cut-offs | {item_name} | Time"] = time_val
                continue

            # Tabelas padrão: [Group, Curr., 20STD, ...]
            curr = ""
            if tdcount >= 2:
                curr = tds.nth(1).inner_text().strip()

            # Colunas de valor começam no índice 2
            for col_idx in range(2, min(tdcount, len(headers))):
                size = headers[col_idx]  # ex.: 20STD
                raw_val = tds.nth(col_idx).inner_text().strip()
                val = _parse_number(raw_val)

                # 1) coluna numérica
                key = f"{group} | {item_name} | {size}"
                charges[key] = val

                # 2) coluna da moeda (pra você não “perder” curr.)
                charges[f"{group} | {item_name} | {size} | Curr"] = curr

                # Soma por group/size (se moeda for consistente)
                if val is not None:
                    sk = (group, size)
                    if sk not in sums:
                        sums[sk] = {"curr": curr, "sum": 0.0, "multi_curr": False}
                    else:
                        if sums[sk]["curr"] and curr and sums[sk]["curr"] != curr:
                            sums[sk]["multi_curr"] = True
                    sums[sk]["sum"] += float(val)

                # Compat: Ocean Freight antigo (vem em Freight Charges)
                if group == "Freight Charges" and item_name == "Ocean Freight" and size == "20STD":
                    charges["Ocean Freight"] = val
                    charges["Ocean Freight Curr"] = curr

    # Compat: Export/Freight/Import Surcharges como “total da tabela” (quando moeda única)
    for (group, size), info in sums.items():
        if size != "20STD":
            continue
        if group in ("Export Surcharges", "Freight Surcharges", "Import Surcharges"):
            charges[group] = info["sum"] if not info["multi_curr"] else None
            charges[f"{group} Curr"] = info["curr"] if not info["multi_curr"] else "MULTI"

    log(f"Total de campos extraídos do breakdown: {len(charges)}")
    return charges


# ----------------------------------------------------------------------
# PIPELINE DE UMA ÚNICA COTAÇÃO (1 linha do Excel)
# ----------------------------------------------------------------------
def run_single_quote_flow(page, origin: str, destination: str):
    """
    Executa o fluxo completo para uma origem/destino.
    Retorna (charges, status, message).
    """
    status = "success"
    message = ""
    charges = {}

    try:
        open_quote_page(page)
        fill_origin_destination_and_date(page, origin, destination)
        select_container_and_weight(page, weight_kg=26000)

        # tenta achar o Spot; se não tiver, considera "no_quote" e sai
        try:
            select_spot_offer(page)
        except Exception as e:
            status = "no_quote"
            message = f"Spot offer não encontrado ou rota sem cotação: {e}"
            return {}, status, message

        # se conseguiu selecionar o Spot, extrai charges
        charges = extract_charge_items(page)

    except Exception as e:
        status = "error"
        message = f"Erro inesperado durante cotação: {e!r}"

    return charges, status, message


# ----------------------------------------------------------------------
# MAIN – LOOP LENDO O EXCEL, COM PRIORIDADE E UPSERT NO CSV
# ----------------------------------------------------------------------
def main():
    if not JOBS_XLSX.exists():
        raise FileNotFoundError(f"Arquivo de jobs não encontrado: {JOBS_XLSX}")

    df = pd.read_excel(JOBS_XLSX)

    # carrega cache de linhas e histórico para definir prioridades
    rows_cache = load_rows_cache(OUTPUT_CSV)
    history = build_history_from_rows_cache(rows_cache)

    # monta lista de jobs com prioridade
    jobs = []

    for idx, row in df.iterrows():
        origin = str(row.get("ORIGEM", "")).strip()
        destination = str(row.get("PORTO DE DESTINO", "")).strip()

        if (
            not origin
            or not destination
            or origin.lower() == "nan"
            or destination.lower() == "nan"
        ):
            log(f"Linha {idx}: origem/destino vazio, pulando.")
            continue

        key = f"{origin}-{destination}"
        info = history.get(key)

        # GRUPO DE PRIORIDADE:
        # 0 = nunca tentou (nem tentativa nem cotação)
        # 1 = já teve pelo menos uma cotação success (mais antiga -> mais prioridade)
        # 2 = já teve tentativa mas nunca sucesso (mais antiga -> mais prioridade)
        if info is None or not info.get("has_any_attempt", False):
            priority_group = 0
            priority_ts = datetime.min
        elif info.get("has_success", False):
            priority_group = 1
            priority_ts = (
                info.get("last_success_at")
                or info.get("last_attempt_at")
                or datetime.min
            )
        else:
            priority_group = 2
            priority_ts = info.get("last_attempt_at") or datetime.min

        jobs.append(
            {
                "idx": idx,
                "origin": origin,
                "destination": destination,
                "key": key,
                "priority_group": priority_group,
                "priority_ts": priority_ts,
            }
        )

    # ordena os jobs conforme a regra de prioridade
    jobs.sort(
        key=lambda j: (
            j["priority_group"],
            j["priority_ts"],
            j["idx"],  # desempate: ordem original no Excel
        )
    )

    log(
        "Ordem de execução (grupo, data, origem->destino): "
        + ", ".join(
            f"[g{j['priority_group']} {j['priority_ts']} {j['origin']}->{j['destination']}]"
            for j in jobs
        )
    )

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=".pw-user-data-hapag",
            channel="chrome",
            headless=False,
            viewport={"width": 1366, "height": 768},
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
            ],
        )
        context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )

        # LOGIN (apenas 1 vez)
        login_page = context.new_page()
        login_page.set_default_timeout(30000)
        login_hapag(login_page)

        time.sleep(7)

        # Página reutilizada para todas as cotações
        quote_page = context.new_page()
        quote_page.set_default_timeout(30000)

        for j in jobs:
            origin = j["origin"]
            destination = j["destination"]
            key = j["key"]

            log(
                f"=== Processando {origin} -> {destination} "
                f"(grupo={j['priority_group']}, ref={j['priority_ts']}) ==="
            )

            try:
                charges, status, message = run_single_quote_flow(
                    quote_page, origin, destination
                )
            except Exception as e:
                charges = {}
                status = "error"
                message = f"Erro não tratado no fluxo: {e!r}"

            upsert_charges_in_cache(
                rows_cache=rows_cache,
                charges=charges,
                origin=origin,
                destination=destination,
                status=status,
                message=message,
                key=key,
            )

        # grava o CSV final com 1 linha por key
        flush_rows_cache_to_csv(rows_cache, OUTPUT_CSV)

        log("Processamento concluído. Fechando contexto em 10s...")
        time.sleep(10)
        context.close()

        # grava o CSV final com 1 linha por key
    flush_rows_cache_to_csv(rows_cache, OUTPUT_CSV)

    # CONVERTE TUDO PRA USD (sobrescreve o CSV)
    convert_currency_columns_in_csv_to_usd(
        csv_path=OUTPUT_CSV,
        out_path=OUTPUT_CSV,        # ou troque pra um novo caminho pra não sobrescrever
        round_decimals=2,
        keep_original=False,        # True se quiser manter colunas "* | Orig"
        timeout=20,
    )


# ----------------------------------------------------------------------
# FUÇÕES PARA CONVERSÃO DE MOEDAS
# ----------------------------------------------------------------------

import json
from typing import Dict, Optional, Tuple
from urllib.request import urlopen, Request

import pandas as pd


def _http_get_json(url: str, timeout: int = 20) -> dict:
    """
    Faz GET e devolve JSON.
    - Tenta usar 'requests' se estiver instalado.
    - Se não tiver, usa urllib (sem dependências extras).
    """
    try:
        import requests  # type: ignore

        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except ModuleNotFoundError:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        # se requests falhar por algum motivo, tenta urllib como fallback
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))


def fetch_fx_rates_usd_base(timeout: int = 20) -> Dict[str, float]:
    """
    Retorna um dicionário no formato:
      rates["EUR"] = 0.92  -> significa: 1 USD = 0.92 EUR
      rates["BRL"] = 4.95  -> significa: 1 USD = 4.95 BRL

    (Base USD. Isso é importante pra fórmula de conversão.)
    Tenta múltiplas fontes, pra ficar mais robusto.
    """
    providers = [
        # 1) ER-API (geralmente bem estável e sem key)
        ("https://open.er-api.com/v6/latest/USD", "erapi"),
        # 2) exchangerate.host (pode variar disponibilidade)
        ("https://api.exchangerate.host/latest?base=USD", "exchangerate_host"),
        # 3) fawazahmed currency-api (JSON diário em CDN)
        ("https://cdn.jsdelivr.net/gh/fawazahmed0/currency-api@1/latest/currencies/usd.json", "fawazahmed"),
    ]

    last_err = None

    for url, kind in providers:
        try:
            data = _http_get_json(url, timeout=timeout)

            if kind == "erapi":
                rates = data.get("rates") or {}
            elif kind == "exchangerate_host":
                rates = data.get("rates") or {}
            else:  # fawazahmed
                # formato: {"date":"2026-01-02","usd":{"eur":0.92,"brl":4.95,...}}
                usd_map = data.get("usd") or {}
                # normaliza chaves pra "EUR", "BRL"...
                rates = {k.upper(): float(v) for k, v in usd_map.items()}

            # normaliza e valida
            norm = {}
            for k, v in (rates or {}).items():
                try:
                    kk = str(k).upper().strip()
                    vv = float(v)
                    if kk and vv > 0:
                        norm[kk] = vv
                except Exception:
                    pass

            norm["USD"] = 1.0  # garante USD

            if len(norm) >= 10:  # sanity check básico
                return norm

        except Exception as e:
            last_err = e
            continue

    raise RuntimeError(f"Não consegui obter câmbio USD->CUR em nenhum provider. Último erro: {last_err!r}")


def _clean_currency_code(x) -> str:
    """
    Extrai um código de moeda tipo 'EUR', 'GBP', 'USD' de strings variadas.
    Ex.: 'EUR', 'EUR ' , 'EUR/...' -> 'EUR'
    """
    if x is None:
        return ""
    s = str(x).strip().upper()
    if not s:
        return ""
    # pega o primeiro bloco de 3 letras
    import re
    m = re.search(r"([A-Z]{3})", s)
    return m.group(1) if m else ""


def convert_currency_columns_to_usd_in_df(
    df: pd.DataFrame,
    rates_usd_base: Dict[str, float],
    round_decimals: Optional[int] = 2,
    keep_original: bool = False,
) -> Tuple[pd.DataFrame, int]:
    """
    Converte todas as colunas numéricas que têm uma coluna de moeda correspondente para USD.

    Padrões que ele reconhece:
      1) "<alguma coisa> | Curr"  -> valor em "<alguma coisa>"
      2) "<alguma coisa> Curr"    -> valor em "<alguma coisa>"  (ex.: "Ocean Freight Curr")

    Estratégia (base USD):
      - rates_usd_base["EUR"] = 0.92 significa 1 USD = 0.92 EUR
      - Para converter 60 EUR -> USD: 60 / 0.92 = 65.217...

    Regras:
      - Se Curr for USD/vazio/MULTI -> não converte
      - Se não existir rate pra moeda -> não converte
      - Se keep_original=True -> cria colunas "* | Orig" antes de sobrescrever

    Retorna: (df_convertido, quantidade_de_células_convertidas)
    """
    rates = {k.upper(): float(v) for k, v in rates_usd_base.items()}
    rates["USD"] = 1.0

    converted_cells = 0

    for curr_col in df.columns:
        value_col = None

        if curr_col.endswith(" | Curr"):
            value_col = curr_col[:-7]  # remove " | Curr"
        elif curr_col.endswith(" Curr"):
            value_col = curr_col[:-5]  # remove " Curr"
        else:
            continue

        if not value_col or value_col not in df.columns:
            continue

        # prepara séries
        vals = pd.to_numeric(df[value_col], errors="coerce")
        currs = df[curr_col].map(_clean_currency_code)

        # máscara inicial (tem valor, tem moeda, moeda != USD e != MULTI)
        mask = (
            vals.notna()
            & currs.notna()
            & (currs != "")
            & (currs != "USD")
            & (currs != "MULTI")
        )
        if not mask.any():
            continue

        # mapeia rate (USD -> CUR)
        rate_series = currs.map(rates)
        mask2 = mask & rate_series.notna() & (rate_series != 0)

        if not mask2.any():
            continue

        if keep_original:
            # salva originais uma vez (não sobrescreve se já existir)
            orig_val_col = f"{value_col} | Orig"
            orig_cur_col = f"{curr_col} | Orig"
            if orig_val_col not in df.columns:
                df[orig_val_col] = df[value_col]
            if orig_cur_col not in df.columns:
                df[orig_cur_col] = df[curr_col]

        # conversão: amount_in_CUR / (CUR_per_USD) = amount_in_USD
        converted = vals[mask2] / rate_series[mask2]
        if round_decimals is not None:
            converted = converted.round(round_decimals)

        df.loc[mask2, value_col] = converted
        df.loc[mask2, curr_col] = "USD"

        converted_cells += int(mask2.sum())

    return df, converted_cells


def convert_currency_columns_in_csv_to_usd(
    csv_path,
    out_path=None,
    round_decimals: Optional[int] = 2,
    keep_original: bool = False,
    timeout: int = 20,
) -> None:
    """
    Lê um CSV (o seu output final), converte todas as colunas com Curr para USD e grava de volta.
    - out_path=None -> sobrescreve o próprio csv_path
    """
    csv_path = str(csv_path)
    out_path = str(out_path) if out_path is not None else csv_path

    rates = fetch_fx_rates_usd_base(timeout=timeout)

    df = pd.read_csv(csv_path, low_memory=False)

    df2, n = convert_currency_columns_to_usd_in_df(
        df,
        rates_usd_base=rates,
        round_decimals=round_decimals,
        keep_original=keep_original,
    )

    df2.to_csv(out_path, index=False, encoding="utf-8")

    try:
        log(f"Conversão para USD concluída. Células convertidas: {n}. Arquivo: {out_path}")
    except Exception:
        print(f"[FX] Conversão para USD concluída. Células convertidas: {n}. Arquivo: {out_path}")


if __name__ == "__main__":
    main()
