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
    spot_btn.wait_for(timeout=60000)
    spot_btn.click()


def extract_charge_items(page) -> dict:
    """
    Lê a tabela de preços na sidebar (charge-items) e
    retorna um dicionário: { 'Ocean Freight': 1165.0, ... }.
    """
    log("Extraindo charge-items da sidebar...")
    container = page.locator(".sidebar .charge-items")
    container.wait_for(timeout=60000)

    items = container.locator(".charge-item")
    count = items.count()

    charges: dict[str, float] = {}

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


def append_charges_to_csv(
    charges: dict,
    origin: str,
    destination: str,
    status: str,
    message: str,
    csv_path: Path = OUTPUT_CSV,
    key: str | None = None,
):
    """
    Grava uma linha no CSV:
    key,origin,destination,last_attempt_at,quoted_at,status,message,
    Ocean Freight, Export Surcharges, Freight Surcharges, Import Surcharges
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    base_fields = [
        "key",
        "origin",
        "destination",
        "last_attempt_at",
        "quoted_at",
        "status",
        "message",
    ]

    fieldnames = base_fields + KNOWN_CHARGES

    file_exists = csv_path.exists()

    if key is None:
        key = f"{origin}-{destination}"

    now_iso = datetime.now().isoformat()

    row = {
        "key": key,
        "origin": origin,
        "destination": destination,
        "last_attempt_at": now_iso,
        "quoted_at": now_iso if status == "success" else "",
        "status": status,
        "message": message,
    }

    # Preenche as colunas de charge só se existirem
    for charge_name in KNOWN_CHARGES:
        row[charge_name] = charges.get(charge_name)

    # se o arquivo ainda não existir, cria com header
    mode = "a" if file_exists else "w"
    with csv_path.open(mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    log(f"Linha gravada em {csv_path} (status={status})")


# ----------------------------------------------------------------------
# PIPELINE DE UMA ÚNICA COTAÇÃO (1 linha do Excel)
# ----------------------------------------------------------------------
def run_single_quote_flow(page, origin: str, destination: str) -> tuple[dict, str, str]:
    """
    Executa o fluxo completo para uma origem/destino.
    Retorna (charges, status, message).
    """
    status = "success"
    message = ""
    charges: dict[str, float] = {}

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
# MAIN – LOOP LENDO O EXCEL
# ----------------------------------------------------------------------
def main():
    if not JOBS_XLSX.exists():
        raise FileNotFoundError(f"Arquivo de jobs não encontrado: {JOBS_XLSX}")

    df = pd.read_excel(JOBS_XLSX)

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

        for idx, row in df.iterrows():
            origin = str(row.get("ORIGEM", "")).strip()
            destination = str(row.get("PORTO DE DESTINO", "")).strip()

            if not origin or not destination or origin.lower() == "nan" or destination.lower() == "nan":
                log(f"Linha {idx}: origem/destino vazio, pulando.")
                continue

            log(f"=== Processando linha {idx}: {origin} -> {destination} ===")

            try:
                charges, status, message = run_single_quote_flow(
                    quote_page, origin, destination
                )
            except Exception as e:
                # guarda qualquer erro bruto aqui como status=error
                charges = {}
                status = "error"
                message = f"Erro não tratado no fluxo: {e!r}"

            append_charges_to_csv(
                charges=charges,
                origin=origin,
                destination=destination,
                status=status,
                message=message,
            )

        log("Processamento concluído. Fechando contexto em 10s...")
        time.sleep(10)
        context.close()


if __name__ == "__main__":
    main()
