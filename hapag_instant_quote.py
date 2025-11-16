# hapag_batch_quotes.py

import os
import csv
import time
from pathlib import Path
from datetime import datetime, timedelta

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
def _parse_iso_or_none(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def load_rows_cache(csv_path: Path):
    """
    Lê o CSV de saída (se existir) e monta um cache:
      rows_cache[key] = row_dict

    Se existir mais de uma linha para a mesma key (versão antiga),
    ele deduplica assim:
      - last_attempt_at/status/message = da tentativa mais recente
      - quoted_at + charges = da cotação de sucesso mais recente
    """
    rows_cache = {}

    if not csv_path.exists():
        return rows_cache

    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for raw_row in reader:
            row = dict(raw_row)

            origin = (row.get("origin") or "").strip()
            destination = (row.get("destination") or "").strip()
            key = (row.get("key") or "").strip()
            if not key:
                key = f"{origin}-{destination}"
            row["key"] = key

            # garante que todas as colunas existam
            for field in ALL_FIELDS:
                row.setdefault(field, "")

            existing = rows_cache.get(key)
            if not existing:
                rows_cache[key] = row
                continue

            # combinar com o que já temos
            curr_attempt = _parse_iso_or_none(existing.get("last_attempt_at"))
            new_attempt = _parse_iso_or_none(row.get("last_attempt_at"))
            curr_success = _parse_iso_or_none(existing.get("quoted_at"))
            new_success = _parse_iso_or_none(row.get("quoted_at"))

            merged = existing

            # tentativa mais recente -> atualiza last_attempt/status/message
            if new_attempt and (not curr_attempt or new_attempt > curr_attempt):
                merged["last_attempt_at"] = row.get("last_attempt_at") or ""
                merged["status"] = row.get("status") or ""
                merged["message"] = row.get("message") or ""

            # sucesso mais recente -> atualiza quoted_at + charges
            if new_success and (not curr_success or new_success > curr_success):
                merged["quoted_at"] = row.get("quoted_at") or ""
                for charge_name in KNOWN_CHARGES:
                    merged[charge_name] = row.get(charge_name)

            rows_cache[key] = merged

    log(f"Rows cache carregado de {csv_path} com {len(rows_cache)} keys (deduplicado).")
    return rows_cache


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


def upsert_charges_in_cache(
    rows_cache,
    charges,
    origin,
    destination,
    status,
    message,
    key=None,
):
    """
    Atualiza (ou cria) UMA linha no cache para a key:
      - last_attempt_at, status, message SEMPRE atualizados
      - quoted_at + charges SÓ atualizados se status == "success"
    """
    if key is None:
        key = f"{origin}-{destination}"

    now_iso = datetime.now().isoformat()

    row = rows_cache.get(key)
    if row is None:
        row = {field: "" for field in ALL_FIELDS}
        row["key"] = key

    row["origin"] = origin
    row["destination"] = destination
    row["last_attempt_at"] = now_iso
    row["status"] = status
    row["message"] = message

    if status == "success":
        row["quoted_at"] = now_iso
        for charge_name in KNOWN_CHARGES:
            row[charge_name] = charges.get(charge_name)
    # se NÃO for success, mantemos quoted_at + charges antigos

    rows_cache[key] = row


def flush_rows_cache_to_csv(rows_cache, csv_path: Path):
    """
    Reescreve o CSV inteiro com UMA linha por key.
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ALL_FIELDS)
        writer.writeheader()

        for key in sorted(rows_cache.keys()):
            row = rows_cache[key]
            out_row = {field: row.get(field, "") for field in ALL_FIELDS}
            writer.writerow(out_row)

    log(f"CSV atualizado em {csv_path} com {len(rows_cache)} linhas (1 por key).")


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

    # DATA – hoje + 7 dias
    log("Preenchendo data (hoje + 7)...")
    date_input = page.locator('input[data-testid="validity-input"]')
    date_input.wait_for(timeout=30000)

    date_str = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
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
    """Clica no botão Select do card Quick Quotes Spot."""
    log("Selecionando card Quick Quotes Spot...")
    spot_btn = page.locator(
        'button[data-testid="offer-card-select-button-spot"]'
    ).first
    # timeout máximo para aparecer o botão Select
    spot_btn.wait_for(timeout=15000)
    spot_btn.click()


def extract_charge_items(page):
    """
    Lê a tabela de preços na sidebar (charge-items) e
    retorna um dicionário: { 'Ocean Freight': 1165.0, ... }.
    """
    log("Extraindo charge-items da sidebar...")
    container = page.locator(".sidebar .charge-items")
    container.wait_for(timeout=15000)

    items = container.locator(".charge-item")
    count = items.count()

    charges = {}

    for i in range(count):
        row = items.nth(i)

        label = row.locator(".charge-item__title span").inner_text().strip()
        price_text = row.locator(".charge-item__price span").inner_text().strip()

        # normalizar: remove espaços especiais e vírgulas de milhar
        cleaned = (
            price_text.replace("\u202f", "")
            .replace("\xa0", "")
            .replace(",", "")
        )

        try:
            value = float(cleaned)
        except ValueError:
            value = None

        charges[label] = value

    log(f"Charges extraídos: {charges}")
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


if __name__ == "__main__":
    main()
