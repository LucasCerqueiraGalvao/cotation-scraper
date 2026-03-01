# hapag_batch_quotes.py

import os
import csv
import time
from pathlib import Path
from datetime import datetime, timedelta
import re
import unicodedata

import pandas as pd
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ----------------------------------------------------------------------
# CONFIG BÁSICA
# ----------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

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

JOBS_XLSX = PROJECT_ROOT / "artifacts" / "input" / "hapag_jobs.xlsx"
OUTPUT_CSV = PROJECT_ROOT / "artifacts" / "output" / "hapag_breakdowns.csv"

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


_ROUTE_HEADER_RE = re.compile(r"^=== Processando \((\d+)/(\d+)\)\s+(.+?)\s+->\s+(.+?)\s*===$")
_LOG_CTX = {
    "job_idx": 0,
    "job_total": 0,
    "last_stage_status": None,
    "last_stage": "ETAPA",
}


def _normalize_for_match(text: str) -> str:
    if not text:
        return ""
    s = unicodedata.normalize("NFKD", str(text))
    s = s.encode("ascii", errors="ignore").decode("ascii")
    s = s.lower()
    return re.sub(r"\s+", " ", s).strip()


def _counter_label() -> str:
    idx = int(_LOG_CTX.get("job_idx") or 0)
    total = int(_LOG_CTX.get("job_total") or 0)
    if total > 0:
        return f"({idx}/{total})"
    return f"({idx}/?)"


def _infer_stage(msg_text: str, current_stage: str = "ETAPA") -> str:
    msg = _normalize_for_match(msg_text)
    if "login" in msg or "security check" in msg or "cookies" in msg:
        return "LOGIN"
    if "csv atualizado" in msg or "processamento concluido" in msg or "job finalizado" in msg:
        return "RESUMO"
    if "jobs" in msg or "ordem de execucao" in msg:
        return "CARGA_JOBS"
    if "abrindo pagina de cotacao" in msg or "quote page" in msg:
        return "NAVEGACAO"
    if "origem" in msg or "start-input" in msg:
        return "ORIGEM"
    if "destino" in msg or "end-input" in msg:
        return "DESTINO"
    if "data" in msg or "validity-input" in msg:
        return "DATA"
    if "container" in msg:
        return "CONTAINER"
    if "peso" in msg or "weight" in msg:
        return "PESO"
    if "search" in msg or "offer-card" in msg or "spot offer" in msg:
        return "OFERTAS"
    if "price breakdown" in msg:
        return "PRICE_DETAILS"
    if "breakdown" in msg or "offer-charges" in msg or "extraindo tabelas" in msg:
        return "BREAKDOWN"
    return current_stage or "ETAPA"


def _infer_status(msg_text: str) -> str:
    msg = _normalize_for_match(msg_text)
    error_markers = [
        "erro",
        "falha",
        "falhou",
        "nao achei",
        "nao encontrado",
        "nao encontrada",
        "no quote",
        "indisponivel",
        "erro nao tratado",
        "spot offer nao encontrado",
        "sem cotacao",
        "job finalizado com erro",
    ]
    warning_markers = [
        "timeout",
        "retry",
        "nao atingido rapidamente",
        "tentando",
        "continuando",
        "security check detectado",
    ]
    ok_markers = [
        "ok",
        "sucesso",
        "concluido",
        "concluida",
        "preenchido",
        "preenchida",
        "selecionado",
        "selecionada",
        "aberto",
        "aberta",
        "atualizado",
        "liberado",
        "job finalizado com sucesso",
    ]
    progress_markers = [
        "iniciando",
        "abrindo",
        "processando",
        "preenchendo",
        "aguardando",
    ]

    if any(m in msg for m in error_markers):
        return "ERRO"
    if any(m in msg for m in ok_markers):
        return "OK"
    if any(m in msg for m in warning_markers):
        return "ATENCAO"
    if any(m in msg for m in progress_markers):
        return "EM_ANDAMENTO"
    return "INFO"


def _to_structured_terminal_line(msg: str) -> str | None:
    raw = "" if msg is None else str(msg).strip()
    if not raw:
        return None

    m = _ROUTE_HEADER_RE.match(raw)
    if m:
        _LOG_CTX["job_idx"] = int(m.group(1))
        _LOG_CTX["job_total"] = int(m.group(2))
        _LOG_CTX["last_stage_status"] = None
        _LOG_CTX["last_stage"] = "INICIO_ROTA"
        origin = m.group(3).strip()
        destination = m.group(4).strip()
        return f"{_counter_label()} {origin} -> {destination}"

    raw_lower = raw.lower()
    if "ordem de execucao (grupo, data, origem->destino):" in raw_lower:
        return None
    if "detalhe no_quote" in raw_lower:
        return None

    stage = _infer_stage(raw, current_stage=_LOG_CTX.get("last_stage", "ETAPA"))
    _LOG_CTX["last_stage"] = stage
    status = _infer_status(raw)

    if status == "INFO":
        if stage in {"ORIGEM", "DESTINO", "DATA", "CONTAINER", "PESO", "PRICE_DETAILS", "BREAKDOWN"}:
            status = "OK"
        elif stage in {"LOGIN", "NAVEGACAO", "OFERTAS", "CARGA_JOBS", "RESUMO"}:
            status = "EM_ANDAMENTO"
        else:
            return None

    event_key = (_LOG_CTX["job_idx"], stage, status)
    if event_key == _LOG_CTX["last_stage_status"]:
        return None
    _LOG_CTX["last_stage_status"] = event_key

    return f"{_counter_label()} | {stage} | {status}"


def log(msg: str) -> None:
    structured = _to_structured_terminal_line(msg)
    if structured is None:
        return
    print(structured)


def parse_env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "f", "no", "n", "off"}:
        return False
    return default


# ----------------------------------------------------------------------
# CREDENCIAIS (.env)
# ----------------------------------------------------------------------

load_dotenv(PROJECT_ROOT / ".env", override=False)
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


def _datetime_to_sort_int(dt: datetime) -> int:
    """
    Converte datetime em inteiro monotônico para ordenação estável.
    Não depende de timestamp/epoch para evitar edge-cases com datas muito antigas.
    """
    if not isinstance(dt, datetime):
        return 0
    return (
        dt.toordinal() * 86_400_000_000_000
        + dt.hour * 3_600_000_000_000
        + dt.minute * 60_000_000_000
        + dt.second * 1_000_000_000
        + dt.microsecond * 1_000
    )



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
        log("Cloudflare Security Check detectado.")
        log(f"Resolve o 'Confirme que é humano' na janela (até {max_wait_sec}s).")
        page.wait_for_function(
            "() => !document.body.innerText.includes('Security Check')",
            timeout=max_wait_sec * 1000,
        )
        log("Security Check liberado, seguindo...")
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
        log("Cookies: 'Select All' clicado.")
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

    log("Login Hapag: tentativa concluida.")


# ----------------------------------------------------------------------
# PÁGINA DE COTAÇÃO / PREENCHIMENTO
# ----------------------------------------------------------------------
def open_quote_page(page):
    log("Abrindo página de cotação...")
    nav_timeout_ms = int(os.getenv("HAPAG_NAV_TIMEOUT_MS", "60000"))
    wait_until = os.getenv("HAPAG_QUOTE_WAIT_UNTIL", "domcontentloaded").strip() or "domcontentloaded"
    if wait_until not in {"load", "domcontentloaded", "networkidle", "commit"}:
        wait_until = "domcontentloaded"

    page.goto(NEW_QUOTE_URL, wait_until=wait_until, timeout=nav_timeout_ms)
    quote_idle_wait_ms = int(os.getenv("HAPAG_QUOTE_IDLE_WAIT_MS", "2500"))
    if quote_idle_wait_ms > 0:
        try:
            page.wait_for_load_state("networkidle", timeout=quote_idle_wait_ms)
        except Exception:
            log("Quote page: networkidle não atingido rapidamente; seguindo.")
    wait_cloudflare_if_needed(page)


def _fill_location_with_dropdown(page, testid: str, code: str, label: str):
    log(f"Preenchendo {label} {code}...")
    action_timeout_ms = int(os.getenv("HAPAG_ACTION_TIMEOUT_MS", "30000"))
    dropdown_wait_ms = int(os.getenv("HAPAG_DROPDOWN_WAIT_MS", "8000"))
    poll_ms = int(os.getenv("HAPAG_DROPDOWN_POLL_MS", "250"))

    field = page.locator(f'input[data-testid="{testid}"]')
    field.wait_for(timeout=action_timeout_ms)
    field.click()
    field.fill(code)

    # Espera o dropdown aparecer e clica na opção com o código.
    option = page.get_by_text(code, exact=False).first
    deadline = time.time() + (dropdown_wait_ms / 1000.0)
    while time.time() < deadline:
        try:
            if option.count() > 0 and option.is_visible():
                option.click()
                log(f"{label.capitalize()} preenchida.")
                return
        except Exception:
            pass
        page.wait_for_timeout(poll_ms)

    # fallback: mantém comportamento antigo para não quebrar.
    option.wait_for(timeout=action_timeout_ms)
    option.click()
    log(f"{label.capitalize()} preenchida.")


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

    log("Data preenchida.")


def select_container_and_weight(page, weight_kg: int = 26000):
    action_timeout_ms = int(os.getenv("HAPAG_ACTION_TIMEOUT_MS", "30000"))

    # container
    log("Selecionando container \"20' General Purpose\"...")
    container = page.locator('[data-testid="container-input"]')
    container.wait_for(timeout=action_timeout_ms)
    container.click()

    option = page.get_by_text("20' General Purpose", exact=False).first
    option.wait_for(timeout=action_timeout_ms)
    option.click()
    log("Container selecionado.")
    time.sleep(1)

    # peso + Enter
    log(f"Preenchendo peso {weight_kg} kg e confirmando...")
    weight_input = page.locator('input[data-testid="weight-input"]')
    weight_input.wait_for(timeout=action_timeout_ms)
    weight_input.click()
    weight_input.fill("")
    weight_input.type(str(weight_kg))
    weight_input.press("Enter")
    log("Peso preenchido.")

    # Em headless o Enter nem sempre dispara a busca; clicar em Search torna o fluxo consistente.
    try:
        search_btn = page.get_by_role("button", name=re.compile(r"^\s*Search\s*$", re.I)).first
        if search_btn.count() > 0:
            search_btn.click(timeout=min(5000, action_timeout_ms))
            log("Botao Search clicado.")
    except Exception:
        pass

    log("Aguardando resultados de ofertas...")


def wait_offers_ready(page, timeout_ms: int = 45000) -> bool:
    """
    Aguarda os cards de oferta ficarem visiveis apos a busca.
    Retorna True quando os cards aparecem.
    """
    deadline = time.time() + (timeout_ms / 1000.0)
    while time.time() < deadline:
        try:
            if page.locator("div.offer-card:visible").count() > 0:
                log("Ofertas prontas.")
                return True
            if page.locator(".offer-card").count() > 0:
                log("Ofertas prontas.")
                return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def wait_price_breakdown_ready(page, timeout_ms: int = 45000, poll_ms: int = 300) -> bool:
    """
    Espera inteligente do Price Breakdown:
    - painel visível
    - tabelas do breakdown presentes
    - sem indicadores de loading/skeleton por alguns ciclos
    """
    deadline = time.time() + (timeout_ms / 1000.0)
    panel = page.locator(".offer-charges").first
    stable_hits = 0

    while time.time() < deadline:
        panel_visible = False
        table_count = 0
        row_count = 0
        loading_count = 0

        try:
            panel_visible = panel.count() > 0 and panel.is_visible()
        except Exception:
            panel_visible = False

        if panel_visible:
            try:
                table_count = panel.locator("table.q-table").count()
            except Exception:
                table_count = 0
            try:
                row_count = panel.locator("table.q-table tbody tr").count()
            except Exception:
                row_count = 0

        try:
            loading_count += page.locator(".q-inner-loading:visible").count()
        except Exception:
            pass
        try:
            loading_count += page.locator(".q-spinner:visible").count()
        except Exception:
            pass
        try:
            loading_count += page.locator(".q-skeleton:visible").count()
        except Exception:
            pass
        try:
            loading_count += page.locator("[aria-busy='true']:visible").count()
        except Exception:
            pass

        ready_by_table = panel_visible and (table_count > 0 or row_count > 0)

        if ready_by_table and loading_count == 0:
            stable_hits += 1
            if stable_hits >= 3:
                return True
        elif panel_visible and loading_count == 0:
            # fallback para casos onde o painel abre sem tabela imediatamente,
            # mas já parou de carregar.
            stable_hits += 1
            if stable_hits >= 6:
                return True
        else:
            stable_hits = 0

        page.wait_for_timeout(poll_ms)

    return False


# ----------------------------------------------------------------------
# RESULTADOS / SIDEBAR / CSV
# ----------------------------------------------------------------------
def select_spot_offer(page):
    """
    Abre o Price Breakdown priorizando o card Quick Quotes Spot.
    Se o Spot estiver indisponivel/desabilitado, usa o card Quick Quotes.
    """
    log("Abrindo Price Breakdown...")

    card_visible_timeout_ms = int(os.getenv("HAPAG_CARD_VISIBLE_TIMEOUT_MS", "20000"))
    breakdown_button_timeout_ms = int(os.getenv("HAPAG_BREAKDOWN_BUTTON_TIMEOUT_MS", "7000"))
    breakdown_click_timeout_ms = int(os.getenv("HAPAG_BREAKDOWN_CLICK_TIMEOUT_MS", "5000"))
    breakdown_ready_timeout_ms = int(os.getenv("HAPAG_BREAKDOWN_READY_TIMEOUT_MS", "45000"))
    breakdown_ready_poll_ms = int(os.getenv("HAPAG_BREAKDOWN_READY_POLL_MS", "300"))

    page.locator("div.offer-card").first.wait_for(state="visible", timeout=card_visible_timeout_ms)

    def _click_breakdown_from_card(card, card_name: str):
        # evita clicar em botoes desabilitados (ex.: Spot com "We cannot fulfill your request")
        btn = card.locator(
            'button:has(span.block:has-text("Price Breakdown")):not([disabled]):not(.disabled)'
        ).first
        if btn.count() == 0:
            raise RuntimeError(f"Price Breakdown habilitado nao encontrado no card {card_name}.")

        btn.wait_for(state="visible", timeout=breakdown_button_timeout_ms)
        btn.scroll_into_view_if_needed()
        btn.click(force=True, timeout=breakdown_click_timeout_ms)
        if not wait_price_breakdown_ready(
            page,
            timeout_ms=breakdown_ready_timeout_ms,
            poll_ms=breakdown_ready_poll_ms,
        ):
            raise RuntimeError(f"Price Breakdown nao ficou pronto no card {card_name}.")
        log(f"Price Breakdown aberto via card {card_name}.")

    candidates = [
        # 1) prioriza Spot
        (
            "Quick Quotes Spot",
            page.locator('div.offer-card:has(h1:has-text("Quick Quotes Spot"))').first,
        ),
        # 2) fallback para Quick Quotes normal (QQ)
        (
            "Quick Quotes",
            page.locator('div.offer-card:has(button[data-testid="offer-card-select-button-qq"])').first,
        ),
    ]

    errors = []
    for card_name, card in candidates:
        if card.count() == 0:
            errors.append(f"{card_name}: card nao encontrado")
            continue

        try:
            _click_breakdown_from_card(card, card_name)
            return
        except Exception as e:
            errors.append(f"{card_name}: {e!r}")
            log(f"{card_name}: Price Breakdown indisponivel. Tentando proximo card...")

    try:
        # fallback final: qualquer card nao desabilitado com botao habilitado
        global_btn = page.locator(
            'div.offer-card:not(.offer-card--disabled) '
            'button:has(span.block:has-text("Price Breakdown")):not([disabled]):not(.disabled)'
        ).first
        if global_btn.count() == 0:
            raise RuntimeError("Nenhum Price Breakdown habilitado encontrado no fallback global.")

        global_btn.wait_for(state="visible", timeout=breakdown_button_timeout_ms)
        global_btn.scroll_into_view_if_needed()
        global_btn.click(force=True, timeout=breakdown_click_timeout_ms)
        if not wait_price_breakdown_ready(
            page,
            timeout_ms=breakdown_ready_timeout_ms,
            poll_ms=breakdown_ready_poll_ms,
        ):
            raise RuntimeError("Price Breakdown nao ficou pronto no fallback global.")
        log("Price Breakdown aberto via fallback global.")
        return
    except Exception as e:
        errors.append(f"fallback_global: {e!r}")

    raise RuntimeError("Falha ao abrir Price Breakdown. " + " | ".join(errors))

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
    if not wait_price_breakdown_ready(page, timeout_ms=45000, poll_ms=300):
        raise RuntimeError("Price Breakdown do Spot nao ficou pronto.")


def extract_estimated_transportation_days(page):
    """
    Lê "Estimated Transportation Days" no card de rota já aberto.
    Retorna int quando possível; senão retorna string; None se não achar.
    """
    try:
        content = page.locator(
            'div.offer-information__route-days:has(div.hal-data-item__label:has-text("Estimated Transportation Days")) '
            'div.hal-data-item__content'
        ).first

        if content.count() == 0:
            content = page.locator(
                'div.hal-data-item:has(div.hal-data-item__label:has-text("Estimated Transportation Days")) '
                'div.hal-data-item__content'
            ).first

        if content.count() == 0:
            return None

        txt = (content.inner_text() or "").strip()
        if not txt:
            return None

        m = re.search(r"\d+", txt)
        if m:
            return int(m.group(0))
        return txt
    except Exception:
        return None


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

    # Campo do card (fora das tabelas do breakdown): Estimated Transportation Days
    etd = extract_estimated_transportation_days(page)
    if etd is not None:
        charges["Estimated Transportation Days"] = etd

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
        offers_timeout_ms = int(os.getenv("HAPAG_OFFERS_READY_TIMEOUT_MS", "45000"))
        if not wait_offers_ready(page, timeout_ms=offers_timeout_ms):
            status = "no_quote"
            message = "Spot offer nao encontrado ou rota sem cotacao."
            return {}, status, message

        # tenta achar o Spot; se nao tiver, considera no_quote e sai
        try:
            select_spot_offer(page)
        except Exception as e:
            status = "no_quote"
            message = "Spot offer nao encontrado ou rota sem cotacao."
            log("Falha ao abrir Spot offer.")
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

        # GRUPO DE PRIORIDADE (alinhado com Maersk):
        # 0 = nunca tentou (nem tentativa nem cotação)
        # 1 = já teve sucesso (mais recente -> mais prioridade)
        # 2 = já teve tentativa mas nunca sucesso (mais antiga -> mais prioridade)
        if info is None or not info.get("has_any_attempt", False):
            priority_group = 0
            priority_ts = datetime.min
            priority_ts_sort = 0
        elif info.get("has_success", False):
            priority_group = 1
            priority_ts = (
                info.get("last_success_at")
                or info.get("last_attempt_at")
                or datetime.min
            )
            priority_ts_sort = -_datetime_to_sort_int(priority_ts)
        else:
            priority_group = 2
            priority_ts = info.get("last_attempt_at") or datetime.min
            priority_ts_sort = _datetime_to_sort_int(priority_ts)

        jobs.append(
            {
                "idx": idx,
                "origin": origin,
                "destination": destination,
                "key": key,
                "priority_group": priority_group,
                "priority_ts": priority_ts,
                "priority_ts_sort": priority_ts_sort,
            }
        )

    # ordena os jobs conforme a regra de prioridade
    jobs.sort(
        key=lambda j: (
            j["priority_group"],
            j["priority_ts_sort"],
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

    hapag_headless = parse_env_bool("HAPAG_HEADLESS", default=False)
    action_timeout_ms = int(os.getenv("HAPAG_ACTION_TIMEOUT_MS", "30000"))
    login_timeout_ms = int(os.getenv("HAPAG_LOGIN_TIMEOUT_MS", "60000"))
    nav_timeout_ms = int(os.getenv("HAPAG_NAV_TIMEOUT_MS", "60000"))
    viewport_width = int(os.getenv("HAPAG_VIEWPORT_WIDTH", "1366"))
    viewport_height = int(os.getenv("HAPAG_VIEWPORT_HEIGHT", "768"))
    locale = os.getenv("HAPAG_LOCALE", "pt-BR")
    timezone = os.getenv("HAPAG_TIMEZONE", "America/Sao_Paulo")
    accept_language = os.getenv("HAPAG_ACCEPT_LANGUAGE", "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7")
    after_login_sleep_sec = float(os.getenv("HAPAG_AFTER_LOGIN_SLEEP_SEC", "2"))
    keep_open_secs = float(os.getenv("HAPAG_KEEP_OPEN_SECS", "3"))
    user_data_dir = os.getenv("HAPAG_USER_DATA_DIR", str(PROJECT_ROOT / ".pw-user-data-hapag"))
    use_stealth = parse_env_bool("HAPAG_STEALTH", default=True)
    ignore_enable_automation = parse_env_bool("HAPAG_IGNORE_ENABLE_AUTOMATION", default=True)

    log(
        f"[cfg] headless={hapag_headless} action_timeout_ms={action_timeout_ms} "
        f"login_timeout_ms={login_timeout_ms} nav_timeout_ms={nav_timeout_ms} "
        f"viewport={viewport_width}x{viewport_height}"
    )

    with sync_playwright() as p:
        context_kwargs = {
            "user_data_dir": user_data_dir,
            "channel": "chrome",
            "headless": hapag_headless,
            "viewport": {"width": viewport_width, "height": viewport_height},
            "locale": locale,
            "timezone_id": timezone,
            "extra_http_headers": {"Accept-Language": accept_language},
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--disable-dev-shm-usage",
                "--no-first-run",
                "--no-default-browser-check",
                f"--window-size={viewport_width},{viewport_height}",
            ],
        }
        if ignore_enable_automation:
            context_kwargs["ignore_default_args"] = ["--enable-automation"]

        context = p.chromium.launch_persistent_context(**context_kwargs)
        if use_stealth:
            context.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            )

        # LOGIN (apenas 1 vez)
        login_page = context.new_page()
        login_page.set_default_timeout(action_timeout_ms)
        login_page.set_default_navigation_timeout(login_timeout_ms)
        login_hapag(login_page)

        time.sleep(max(0.0, after_login_sleep_sec))

        # Página reutilizada para todas as cotações
        quote_page = context.new_page()
        quote_page.set_default_timeout(action_timeout_ms)
        quote_page.set_default_navigation_timeout(nav_timeout_ms)

        total_jobs = len(jobs)
        for idx, j in enumerate(jobs, start=1):
            origin = j["origin"]
            destination = j["destination"]
            key = j["key"]

            log(f"=== Processando ({idx}/{total_jobs}) {origin} -> {destination} ===")

            try:
                charges, status, message = run_single_quote_flow(
                    quote_page, origin, destination
                )
            except Exception as e:
                charges = {}
                status = "error"
                message = f"Erro não tratado no fluxo: {e!r}"

            if status == "success":
                log("Job finalizado com sucesso.")
            elif status == "no_quote":
                log("Job finalizado sem cotacao.")
            else:
                log("Job finalizado com erro.")

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

        log(f"Processamento concluído. Fechando contexto em {keep_open_secs}s...")
        time.sleep(max(0.0, keep_open_secs))
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


