# maersk_book_fill_fast.py
import os, re, time, calendar, json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

import requests
from functools import lru_cache

# ----------------------------------------------------------------------
# Configs e caminhos
# ----------------------------------------------------------------------

HUB_URL   = "https://www.maersk.com/hub/"
BOOK_URL  = "https://www.maersk.com/book/"
LOGIN_URL = "https://accounts.maersk.com/ocean-maeu/auth/login?nonce=l57ZO6eIFuhBPTfq0nmI&scope=openid%20profile%20email&client_id=portaluser&redirect_uri=https%3A%2F%2Fwww.maersk.com%2Fportaluser%2Foidc%2Fcallback&response_type=code&code_challenge=LAAwusgt4i5sfIYW1m2ZQQYxZlWq60yvWPld0KbjclI"

# Selectors

SEL_ALLOW_ALL          = '[data-test="coi-allow-all-button"]'
SEL_ORIGIN             = "#mc-input-origin"
SEL_DESTINATION        = "#mc-input-destination"
SEL_WEIGHT             = 'input[placeholder="Enter cargo weight"]:visible, input[name="weight"]:visible'
SEL_DATE               = '#mc-input-earliestDepartureDatePicker:visible, input[name="earliestDepartureDatePicker"]:visible'
SEL_CONTAINER_VISIBLE  = 'input[placeholder="Select container type and size"]:visible'

# Commodity â€” preferir o acessÃ­vel; manter XPath como fallback
COMMODITY_XPATH        = '/html/body/div[2]/main/section/div/div[2]/div[2]/form/mc-card[2]/fieldset/span/mc-c-commodity//div/div/div/div/div/div/div/div/div/slot/input'

# I/O
ARTIFACTS        = Path("artifacts")
INPUT_XLSX       = ARTIFACTS / "input" / "maersk_jobs.xlsx"
OUT_DIR          = ARTIFACTS / "output"
OUT_CSV          = OUT_DIR / "maersk_breakdowns.csv"   # formato "wide"
RUN_LOG_CSV      = OUT_DIR / "maersk_run_log.csv"

# âœ… ALTERADO: SCREENS agora Ã© o caminho absoluto que vocÃª pediu
SCREENS = Path(r"C:\Users\lucas\Documents\Projects\professional\Cotation Scrapers\screens")

for p in [ARTIFACTS, ARTIFACTS/"input", OUT_DIR, SCREENS]:
    p.mkdir(parents=True, exist_ok=True)

# Timeout maior para esperar os cards de resultado (ajustÃ¡vel via .env)
RESULTS_TIMEOUT_SEC = int(os.getenv("MAERSK_RESULTS_TIMEOUT_SEC", "45"))

# Taxa aproximada COP â†’ USD (ajuste conforme quiser)
COP_TO_USD_APPROX = 0.00025   # COP 1 = 0.00025 USD  (exemplo realista)

# ----------------------------------------------------------------------
# âœ… NOVO: Screenshot helpers (sempre com origem/destino/horÃ¡rio)
# ----------------------------------------------------------------------
_WIN_BAD_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1F]+')

def _safe_part(s: str, max_len: int = 60) -> str:
    s = "" if s is None else str(s).strip()
    s = _WIN_BAD_CHARS_RE.sub("_", s)
    s = re.sub(r"\s+", "_", s)
    s = s.strip("._-")
    if not s:
        s = "NA"
    return s[:max_len]

def save_quote_screenshot(page, job: dict, stage: str) -> Path | None:
    """
    Salva print SEMPRE com:
      - origem
      - destino
      - horÃ¡rio (timestamp)
    e um stage pra diferenciar (offers/no_results/no_price_details/etc).
    """
    try:
        origin = _safe_part(job.get("origin", "NA"), 60)
        dest   = _safe_part(job.get("destination", "NA"), 60)
        ts     = datetime.now().strftime("%Y%m%d_%H%M%S")

        stage  = _safe_part(stage, 40)

        # Nome final (evita ficar gigante)
        fname = f"maersk__{stage}__{ts}__{origin}__{dest}.png"
        out   = SCREENS / fname

        # garantia de diretÃ³rio
        SCREENS.mkdir(parents=True, exist_ok=True)

        # tenta garantir que a Ã¡rea de ofertas esteja na viewport
        try:
            page.locator(".product-offer-card").first.scroll_into_view_if_needed(timeout=1200)
        except Exception:
            pass

        page.screenshot(path=str(out), full_page=True)
        log(f"ðŸ“¸ Screenshot salvo: {out}")
        return out
    except Exception as e:
        log(f"âš ï¸ Screenshot falhou ({type(e).__name__}: {e})")
        return None

# ----------------------------------------------------------------------
# Utils gerais
# ----------------------------------------------------------------------
def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    try:
        print(line)
    except UnicodeEncodeError:
        # Evita travar execução por caracteres não representáveis no codepage do terminal.
        safe_line = line.encode(sys.stdout.encoding or "cp1252", errors="replace").decode(
            sys.stdout.encoding or "cp1252",
            errors="replace",
        )
        print(safe_line)

def dd_mmm_yyyy_en(dt: datetime) -> str:
    return f"{dt.day:02d} {calendar.month_abbr[dt.month]} {dt.year}"

def is_blank(x) -> bool:
    s = "" if x is None else str(x).strip()
    return s == "" or s.lower() in {"nan", "none", "null"}

def _clear(loc) -> None:
    try:
        loc.fill("")
    except Exception:
        try:
            loc.press("Control+A")
            loc.press("Delete")
        except Exception:
            pass

def clamp_date_to_min_max(page, loc, target_dt: datetime) -> datetime:
    def parse_bound(s):
        try:
            head = " ".join(s.split()[:4])  # "Sat Nov 01 2025"
            return datetime.strptime(head, "%a %b %d %Y")
        except Exception:
            return None

    try:
        min_raw = loc.get_attribute("min")
        max_raw = loc.get_attribute("max")
    except Exception:
        min_raw = max_raw = None

    min_dt = parse_bound(min_raw) if min_raw else None
    max_dt = parse_bound(max_raw) if max_raw else None
    dt = target_dt
    if min_dt and dt < min_dt:
        dt = min_dt
    if max_dt and dt > max_dt:
        dt = max_dt
    return dt

def accept_cookies_quick(page) -> None:
    # botÃ£o direto
    try:
        page.locator(SEL_ALLOW_ALL).click(timeout=800)
        log("Cookies: Allow all clicado.")
        return
    except Exception:
        pass
    # JS do CookieInformation
    try:
        if page.evaluate("() => window.CookieInformation?.submitAllCategories?.() || false"):
            log("Cookies: submitAllCategories() via JS (pÃ¡gina).")
            return
    except Exception:
        pass
    # iframes
    for fr in page.frames:
        if fr == page.main_frame:
            continue
        try:
            fr.locator(SEL_ALLOW_ALL).click(timeout=600)
            log(f"Cookies: Allow all (iframe {fr.url}).")
            return
        except Exception:
            pass
        try:
            if fr.evaluate("() => window.CookieInformation?.submitAllCategories?.() || false"):
                log(f"Cookies: submitAllCategories() via JS (iframe {fr.url}).")
                return
        except Exception:
            pass
    log("Cookies: banner ausente (ok).")

def wait_input_valid(loc, timeout_ms=4000) -> bool:
    """Espera o input deixar de estar 'invalid' (aria-invalid!='true' e sem atributo 'invalid')."""
    deadline = time.time() + timeout_ms/1000.0
    while time.time() < deadline:
        try:
            inv = (loc.get_attribute("aria-invalid") or "").strip().lower()
            has_invalid_attr = loc.get_attribute("invalid") is not None
            if inv != "true" and not has_invalid_attr:
                return True
        except Exception:
            pass
        time.sleep(0.12)
    return False

def close_unexpected_modal(page, context: str = "") -> bool:
    """
    Fecha modais/cards inesperados que podem aparecer sozinhos e bloquear o fluxo.
    Retorna True se tentou fechar algo.
    """

    def _handle_previous_booking_modal() -> bool:
        """
        Modal "Select a recently confirmed booking..." (reutilizacao de booking).
        """
        modal = page.locator(
            ".previous-booking-table-desktop:visible, "
            'mc-c-table[data-test="previous-booking-table"]:visible'
        ).first

        try:
            if modal.count() == 0 or not modal.is_visible():
                return False
        except Exception:
            return False

        attempted_local = False

        # 1) Preferir botoes de descarte/fechamento para nao reutilizar dados
        negative_patterns = [
            r"(dont|don't|do not|no thanks|skip|cancel|close|dismiss|not now|ignore)",
            r"(nao|não|fechar|cancelar|pular|dispensar|agora nao|agora não)",
            r"(nao reutilizar|não reutilizar|sem reutilizar|novo booking|nova cotacao|nova cotação)",
        ]
        for patt in negative_patterns:
            try:
                btn = modal.get_by_role("button", name=re.compile(patt, re.I)).first
                if btn.count() > 0 and btn.is_visible():
                    attempted_local = True
                    try:
                        btn.click(timeout=1500)
                    except Exception:
                        btn.click(timeout=1500, force=True)
                    time.sleep(0.2)
                    return True
            except Exception:
                pass

        # 2) Tenta Escape
        try:
            page.keyboard.press("Escape")
            attempted_local = True
            time.sleep(0.2)
            try:
                if modal.count() == 0 or not modal.is_visible():
                    return True
            except Exception:
                return True
        except Exception:
            pass

        # 3) Fallback: botao de continuar/reutilizar (desbloqueia fluxo)
        positive_patterns = [
            r"(continue|reuse|re-use|use booking|select booking)",
            r"(continuar|reutilizar|usar booking|selecionar booking)",
        ]
        for patt in positive_patterns:
            try:
                btn = modal.get_by_role("button", name=re.compile(patt, re.I)).first
                if btn.count() > 0 and btn.is_visible():
                    attempted_local = True
                    try:
                        btn.click(timeout=1500)
                    except Exception:
                        btn.click(timeout=1500, force=True)
                    time.sleep(0.2)
                    return True
            except Exception:
                pass

        # 4) Ultimo recurso: primeiro botao visivel do modal
        try:
            any_btn = modal.locator("button:visible").first
            if any_btn.count() > 0 and any_btn.is_visible():
                attempted_local = True
                try:
                    any_btn.click(timeout=1500)
                except Exception:
                    any_btn.click(timeout=1500, force=True)
                time.sleep(0.2)
                return True
        except Exception:
            pass

        return attempted_local

    def _has_blocking_modal() -> bool:
        try:
            if page.locator(
                ".previous-booking-table-desktop:visible, "
                'mc-c-table[data-test="previous-booking-table"]:visible'
            ).count() > 0:
                return True
        except Exception:
            pass

        try:
            if page.locator('[data-test="offer-modal-close-icon"]:visible, mc-button.close-icon:visible').count() > 0:
                return True
        except Exception:
            pass

        try:
            if page.locator("[role='dialog']:visible, mc-modal:visible, mc-dialog:visible").count() > 0:
                return True
        except Exception:
            pass

        try:
            if page.locator(
                ".body-wrapper:visible button[aria-label*='close' i], "
                ".body-wrapper:visible button[aria-label*='fechar' i], "
                ".body-wrapper:visible button[aria-label*='times-circle' i]"
            ).count() > 0:
                return True
        except Exception:
            pass

        return False

    if not _has_blocking_modal():
        return False

    msg_ctx = f" ({context})" if context else ""
    log(f"Modal inesperado detectado{msg_ctx}. Tentando fechar...")

    close_selectors = [
        '[data-test="offer-modal-close-icon"] >>> button[part="button"]',
        '[data-test="offer-modal-close-icon"]',
        'mc-button.close-icon >>> button[part="button"]',
        'mc-button.close-icon',
        "[role='dialog'] button[aria-label*='close' i]",
        "[role='dialog'] button[aria-label*='fechar' i]",
        "[role='dialog'] button[aria-label*='times-circle' i]",
        ".body-wrapper button[aria-label*='close' i]",
        ".body-wrapper button[aria-label*='fechar' i]",
        ".body-wrapper button[aria-label*='times-circle' i]",
    ]

    attempted = False
    for _ in range(3):
        # Trata explicitamente o modal de "re-use booking details"
        try:
            if _handle_previous_booking_modal():
                attempted = True
        except Exception:
            pass

        for sel in close_selectors:
            try:
                btn = page.locator(sel).first
                if btn.count() > 0 and btn.is_visible():
                    attempted = True
                    try:
                        btn.click(timeout=1200)
                    except Exception:
                        btn.click(timeout=1200, force=True)
                    time.sleep(0.2)
            except Exception:
                pass

        try:
            page.keyboard.press("Escape")
            attempted = True
        except Exception:
            pass

        time.sleep(0.25)
        if not _has_blocking_modal():
            log(f"Modal inesperado fechado{msg_ctx}.")
            return attempted

    if _has_blocking_modal():
        log(f"Modal inesperado permaneceu aberto{msg_ctx}.")

    return attempted

# ----------------------------------------------------------------------
# Login Maersk
# ----------------------------------------------------------------------
def login_maersk(page, username: str, password: str, timeout_ms: int = 30000) -> bool:
    """
    Faz login na Maersk usando a tela de login padrÃ£o.
    Usa os web-components mc-input/mc-button atravessando o Shadow DOM.
    """
    log("Iniciando login na Maersk...")

    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    try:
        accept_cookies_quick(page)
    except Exception:
        pass

    # Username
    try:
        user_input = page.locator(
            "mc-input[data-test='username-input'] >>> input[data-id='input']"
        ).first
        user_input.wait_for(state="visible", timeout=8000)
    except Exception:
        # fallback por label
        user_input = page.get_by_label(re.compile(r"username", re.I)).first

    user_input.click()
    user_input.fill(username)

    # Password
    try:
        pass_input = page.locator(
            "mc-input[data-test='password-input'] >>> input[data-id='input']"
        ).first
        pass_input.wait_for(state="visible", timeout=8000)
    except Exception:
        pass_input = page.get_by_label(re.compile(r"password", re.I)).first

    pass_input.click()
    pass_input.fill(password)

    # BotÃ£o "Log in"
    clicked = False
    try:
        btn = page.get_by_role("button", name=re.compile(r"^\s*Log\s*in\s*$", re.I)).first
        btn.wait_for(state="visible", timeout=8000)
        btn.click()
        clicked = True
    except Exception:
        try:
            btn = page.locator(
                "mc-button[data-test='submit-button'] >> button[part='button']"
            ).first
            btn.wait_for(state="visible", timeout=8000)
            btn.click()
            clicked = True
        except Exception:
            clicked = False

    if not clicked:
        log("âš ï¸ Login: nÃ£o consegui clicar no botÃ£o 'Log in'.")
        return False

    # Espera sair da tela /auth/login
    try:
        page.wait_for_function(
            "() => !window.location.href.includes('/auth/login')",
            timeout=timeout_ms
        )
        log(f"Login: sucesso, URL atual: {page.url}")
        return True
    except Exception:
        log(f"âš ï¸ Login: aparentemente nÃ£o saiu da tela de login (URL: {page.url}).")
        return False

# ----------------------------------------------------------------------
# AÃ§Ãµes de preenchimento
# ----------------------------------------------------------------------
def fill_autocomplete(
    page,
    selector,
    text,
    label,
    wait_before_enter=0.6,
    arrow_down=True,
    wait_opts_ms=1000,
) -> bool:
    """
    Autocomplete genÃ©rico (Origem/Destino) mais parecido com set_commodity:
    - digita o texto
    - espera o dropdown de opÃ§Ãµes
    - tenta clicar numa option que contenha o texto
    - fallback: ArrowDown+Enter + retries
    """
    close_unexpected_modal(page, f"antes de preencher {label}")

    loc = page.locator(selector).first
    loc.wait_for(state="visible", timeout=8000)

    # garante que estÃ¡ na viewport
    try:
        loc.scroll_into_view_if_needed(timeout=800)
    except Exception:
        pass

    loc.click()
    _clear(loc)
    loc.fill(text)

    # pequena espera inicial para API comeÃ§ar a responder
    time.sleep(wait_before_enter)

    # tenta descobrir o listbox vinculado via aria-controls (mais preciso)
    try:
        listbox_id = loc.get_attribute("aria-controls")
    except Exception:
        listbox_id = None

    if listbox_id:
        opts = page.locator(f'#{listbox_id} [role="option"]')
    else:
        # fallback mais genÃ©rico (como em set_commodity)
        opts = page.locator('[role="option"]')

    # espera as options aparecerem
    appeared = False
    t0 = time.time()
    while time.time() - t0 < (wait_opts_ms / 1000.0):
        try:
            if opts.count() > 0 and opts.first.is_visible():
                appeared = True
                break
        except Exception:
            pass
        # dÃ¡ um nudge pra abrir o dropdown se ainda nÃ£o abriu
        try:
            loc.press("ArrowDown")
        except Exception:
            pass
        time.sleep(0.15)

    if appeared:
        # tenta achar uma option que contenha o texto digitado (cÃ³digo UNLOCODE, cidade, etc.)
        try:
            match_opt = opts.filter(has_text=re.compile(re.escape(text), re.I)).first
            if match_opt.count() > 0 and match_opt.is_visible():
                match_opt.click()
                if wait_input_valid(loc, 4000):
                    log(f"{label}: option que casa '{text}' selecionada.")
                    return True
            # se nÃ£o achar match especÃ­fico, clica na primeira visÃ­vel
            first_opt = opts.first
            if first_opt.count() > 0 and first_opt.is_visible():
                first_opt.click()
                if wait_input_valid(loc, 4000):
                    log(f"{label}: primeira option selecionada para '{text}'.")
                    return True
        except Exception:
            pass

    # se nÃ£o conseguiu usar dropdown, cai pro comportamento antigo
    try:
        loc.click()
    except Exception:
        pass

    if arrow_down:
        try:
            loc.press("ArrowDown")
            time.sleep(0.12)
        except Exception:
            pass

    try:
        loc.press("Enter")
    except Exception:
        pass

    if wait_input_valid(loc, 4000):
        log(f"{label}: '{text}' confirmado via teclado (fallback).")
        return True

    # retries leves
    for _ in range(2):
        try:
            loc.click()
            if arrow_down:
                loc.press("ArrowDown")
                time.sleep(0.12)
            loc.press("Enter")
            if wait_input_valid(loc, 2500):
                log(f"{label}: '{text}' confirmado apÃ³s retry.")
                return True
        except Exception:
            pass

    log(f"âš ï¸ {label}: nÃ£o confirmou '{text}' (campo permaneceu invÃ¡lido).")
    return False

import re, time  # redundante mas inofensivo

def set_commodity(page, text: str, wait_opts_ms: int = 5000) -> bool:
    """
    Preenche o campo Commodity (combobox dentro de <mc-c-commodity>) e seleciona uma opÃ§Ã£o.
    Retorna True se conseguiu selecionar, False caso contrÃ¡rio.
    """
    # 1) Tenta por acessibilidade (combobox 'Commodity' ou 'Mercadoria')
    loc = None
    try:
        loc = page.get_by_role("combobox", name=re.compile(r"(Commodity|Commodities|Mercadoria)", re.I)).first
        loc.wait_for(state="visible", timeout=4000)
    except Exception:
        pass

    # 2) Fallback: perfura Shadow DOM do <mc-c-commodity>
    if loc is None or loc.count() == 0:
        loc = page.locator(
            "mc-c-commodity >>> input[role='combobox'], mc-c-commodity >>> input[data-id='input']"
        ).first
        loc.wait_for(state="visible", timeout=6000)

    # Garante que estÃ¡ na viewport
    try:
        loc.scroll_into_view_if_needed(timeout=800)
    except Exception:
        pass

    # 3) Digita (tipo humano) para armar a lista
    try:
        loc.click()
    except Exception:
        pass

    # Limpa e digita
    try:
        loc.fill("")  # limpa
    except Exception:
        try:
            loc.press("Control+A")
            loc.press("Delete")
        except Exception:
            pass

    loc.fill(text)

    # 4) Aguarda aparecer options no listbox (perfurando shadow)
    opts = page.locator("[role='option']")  # Playwright costuma atravessar shadow por role
    appeared = False
    t0 = time.time()
    while time.time() - t0 < (wait_opts_ms / 1000.0):
        try:
            if opts.count() > 0 and opts.first.is_visible():
                appeared = True
                break
        except Exception:
            pass
        # pequeno nudge para disparar dropdown se necessÃ¡rio
        try:
            loc.press("ArrowDown")
        except Exception:
            pass
        time.sleep(0.15)

    # 5) Seleciona a melhor option (preferindo match pelo texto digitado)
    if appeared:
        # tenta clicar numa option que contenha o texto
        try:
            match_opt = page.get_by_role("option", name=re.compile(re.escape(text), re.I)).first
            if match_opt.count() > 0 and match_opt.is_visible():
                match_opt.click()
                log(f"Commodity: selecionado option que casa '{text}'.")
                return True
        except Exception:
            pass
        # fallback: primeira option
        try:
            opts.first.click()
            log("Commodity: selecionada primeira opÃ§Ã£o do listbox.")
            return True
        except Exception:
            pass

    # 6) Ãšltimos recursos: ArrowDown+Enter ou Enter direto
    try:
        loc.press("ArrowDown")
        time.sleep(0.15)
        loc.press("Enter")
        log("Commodity: confirmado via ArrowDown+Enter (fallback).")
        return True
    except Exception:
        pass

    try:
        loc.press("Enter")
        log("Commodity: Enter sem dropdown (fallback final).")
        return True
    except Exception:
        log("âš ï¸ Commodity: nÃ£o consegui confirmar.")
        return False

def set_container(page, text="20 Dry"):
    loc = page.locator(SEL_CONTAINER_VISIBLE).first
    if loc.count() == 0:
        loc = page.get_by_label(re.compile(r"Container type and size", re.I)).first
    loc.wait_for(state="visible", timeout=8000)

    loc.click()
    _clear(loc)
    loc.fill(text)
    time.sleep(0.2)  # dÃ¡ tempo do listbox montar

    # tenta clicar na option correta
    try:
        page.wait_for_selector('[role="option"]', timeout=1000)
        page.get_by_role("option", name=re.compile(r"^\s*20\s*Dry\s*$", re.I)).click()
        log(f"Container: '{text}' selecionado via option.")
    except Exception:
        # fallback por teclado
        try:
            loc.click()
            loc.press("ArrowDown")
            time.sleep(0.15)
            loc.press("Enter")
            log(f"Container: '{text}' confirmado via ArrowDown+Enter (fallback).")
        except Exception as e2:
            log(f"âš ï¸ Container: nÃ£o foi possÃ­vel selecionar ({type(e2).__name__}).")

def fill_weight(page, selector, kg, label="Peso (kg)") -> bool:
    loc = page.locator(selector).first
    try:
        loc.wait_for(state="visible", timeout=8000)
    except Exception:
        log(f"âš ï¸ {label}: campo nÃ£o visÃ­vel.")
        return False

    try:
        minv = int(float(loc.get_attribute("min") or "0"))
    except Exception:
        minv = 0
    try:
        maxv = int(float(loc.get_attribute("max") or "999999"))
    except Exception:
        maxv = 999999

    v = int(kg)
    if v < minv:
        log(f"âš ï¸ {label}: {v} < min ({minv}). Usando {minv}.")
        v = minv
    if v > maxv:
        log(f"âš ï¸ {label}: {v} > max ({maxv}). Usando {maxv}.")
        v = maxv

    loc.click()
    _clear(loc)
    val = str(v)
    loc.fill(val)
    # dispara eventos (alguns web-components exigem)
    try:
        handle = loc.element_handle()
        page.evaluate(
            """(el, val) => {
                if (el.value != val) el.value = val;
                el.dispatchEvent(new Event('input',  { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }""",
            handle,
            val,
        )
    except Exception:
        pass

    try:
        loc.press("Tab")
    except Exception:
        try:
            loc.blur()
        except Exception:
            pass

    log(f"{label}: '{v}' definido.")
    return True

def set_price_owner(page, owner="I am the price owner", label_for_log="Price owner"):
    # caminho preferido: role=radio (atravessa shadow DOM)
    try:
        radio = page.get_by_role("radio", name=re.compile(rf"^{re.escape(owner)}$", re.I)).first
        radio.wait_for(state="visible", timeout=3000)
        try:
            radio.check(timeout=1200)
        except Exception:
            radio.click(timeout=1200, force=True)
        log(f"{label_for_log}: marcado â†’ '{owner}'.")
        return
    except Exception:
        pass
    # fallback: host do mc-radio
    try:
        host = page.locator(f"mc-radio:has-text('{owner}')").first
        host.wait_for(state="visible", timeout=3000)
        try:
            host.click(timeout=1000)
            log(f"{label_for_log}: host clicado â†’ '{owner}'.")
            return
        except Exception:
            ck = host.locator('[part="checkmark"]').first
            ck.click(timeout=1000, force=True)
            log(f"{label_for_log}: checkmark clicado â†’ '{owner}'.")
            return
    except Exception:
        pass
    # Ãºltimo recurso: forÃ§a via JS
    try:
        value_map = {"i am the price owner": "PO", "select a price owner": "select"}
        val = value_map.get(owner.lower(), "PO")
        page.evaluate(
            """
            (value) => {
              const all = document.querySelectorAll('input[type="radio"][name="priceOwner"]');
              for (const el of all) {
                el.checked = (el.value === value);
                el.dispatchEvent(new Event('input',  {bubbles:true}));
                el.dispatchEvent(new Event('change', {bubbles:true}));
              }
            }
        """,
            val,
        )
        log(f"{label_for_log}: setado via JS â†’ '{owner}'.")
    except Exception as e:
        log(f"âš ï¸ {label_for_log}: falha ({type(e).__name__}).")

def set_date_plus(page, days=14, label_for_log="Data (Earliest departure)") -> datetime:
    """
    âœ… ALTERADO: agora retorna target_dt (datetime) para ser usado na seleÃ§Ã£o do offer-card.
    """
    loc = page.locator(SEL_DATE).first
    if loc.count() == 0:
        loc = page.get_by_label(re.compile(r"Earliest departure", re.I)).first
    loc.wait_for(state="visible", timeout=8000)

    target = datetime.now() + timedelta(days=days)
    try:
        target = clamp_date_to_min_max(page, loc, target)
    except Exception:
        pass

    date_str = dd_mmm_yyyy_en(target)
    loc.click()
    _clear(loc)
    loc.fill(date_str)

    # eventos + confirmar
    try:
        handle = loc.element_handle()
        page.evaluate(
            "(el)=>{el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true}));}",
            handle,
        )
    except Exception:
        pass

    time.sleep(0.1)
    try:
        loc.press("Enter")
    except Exception:
        try:
            loc.press("Tab")
        except Exception:
            pass

    log(f"{label_for_log}: '{date_str}' definido.")
    return target

# ----------------------------------------------------------------------
# Resultados: esperar cards, Retry etc.
# ----------------------------------------------------------------------
def wait_for_results_cards(page, timeout_sec: int = RESULTS_TIMEOUT_SEC) -> bool:
    """
    Aguarda aparecerem resultados: offer-cards, product-offer-card ou um botÃ£o 'Price details'.
    Retorna True se encontrar; False se estourar o timeout.
    """
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            if page.locator('[data-test="offer-cards"]:visible').count() > 0:
                return True
            if page.locator(".product-offer-card:visible").count() > 0:
                return True
            if (
                page.get_by_role(
                    "button",
                    name=re.compile(r"(Price\s+details|Detalhes\s+do\s+pre[cÃ§]o)", re.I),
                ).count()
                > 0
            ):
                return True
        except Exception:
            pass
        time.sleep(0.25)
    return False

SEL_RETRY_HOST  = "mc-button[data-test='pricing-search-again']"
SEL_RETRY_INNER = SEL_RETRY_HOST + " >>> button[part='button']"

def _safe_count(loc) -> int:
    try:
        return loc.count()
    except Exception:
        return -1

def _safe_visible(loc) -> bool:
    try:
        return loc.count() > 0 and loc.first.is_visible()
    except Exception:
        return False

def _results_visible(page) -> bool:
    try:
        if page.locator('[data-test="offer-cards"]:visible').count() > 0:
            return True
        if page.locator(".product-offer-card:visible").count() > 0:
            return True
        if page.get_by_role("button", name=re.compile(r"(Price\s+details|Detalhes\s+do\s+pre[cÃ§]o)", re.I)).count() > 0:
            return True
    except Exception:
        pass
    return False

DEBUG_RETRY = True  # <-- liga/desliga os logs extras
DEBUG_RETRY_SCREENSHOT = False  # salva prints em /screens

def debug_retry_state(page, tag: str = "") -> None:
    if not DEBUG_RETRY:
        return

    try:
        role = page.get_by_role("button", name=re.compile(r"^\s*Retry\s*$", re.I))
        host = page.locator(SEL_RETRY_HOST)
        inner = page.locator(SEL_RETRY_INNER)

        log(
            "RETRY-DEBUG"
            f" tag='{tag}'"
            f" url='{page.url}'"
            f" | role(count={_safe_count(role)}, visible={_safe_visible(role)})"
            f" | host(count={_safe_count(host)}, visible={_safe_visible(host)})"
            f" | inner(count={_safe_count(inner)}, visible={_safe_visible(inner)})"
        )

        probe = page.evaluate(
            """
            (sel) => {
              const host = document.querySelector(sel);
              if (!host) return {host:false};
              const root = host.shadowRoot;
              const btn  = root ? root.querySelector("button[part='button']") : null;
              return {
                host: true,
                hasShadow: !!root,
                btn: !!btn,
                btnText: btn ? (btn.innerText || btn.textContent || "").trim() : null,
                ariaLabel: btn ? btn.getAttribute("aria-label") : null,
                disabled: btn ? (btn.disabled || btn.getAttribute("disabled") !== null) : null
              };
            }
            """,
            SEL_RETRY_HOST,
        )
        log(f"RETRY-DEBUG probe={probe}")

        if DEBUG_RETRY_SCREENSHOT:
            ts = int(time.time() * 1000)
            out = SCREENS / f"retry_debug_{tag}_{ts}.png"
            page.screenshot(path=str(out), full_page=True)
            log(f"RETRY-DEBUG screenshot={out}")

    except Exception as e:
        log(f"RETRY-DEBUG erro ao inspecionar estado ({type(e).__name__}: {e})")

def _click_retry(page) -> bool:
    """
    Clique no Retry com logs detalhados.
    Retorna True se acredita que clicou, False se falhou.
    """
    debug_retry_state(page, "before_click")

    # 1) Inner (shadow) - o mais confiÃ¡vel aqui
    btn = page.locator(SEL_RETRY_INNER).first
    if _safe_visible(btn):
        try:
            btn.scroll_into_view_if_needed(timeout=800)
        except Exception:
            pass

        try:
            btn.click(timeout=1500, trial=True)
            log("RETRY-DEBUG inner trial=OK")
        except Exception as e:
            log(f"RETRY-DEBUG inner trial=FAIL ({type(e).__name__}: {e})")

        try:
            btn.click(timeout=1500)
            log("RETRY-DEBUG click=OK via inner")
            debug_retry_state(page, "after_click_inner_ok")
            return True
        except Exception as e:
            log(f"RETRY-DEBUG click=FAIL via inner ({type(e).__name__}: {e})")
            try:
                btn.click(timeout=1500, force=True)
                log("RETRY-DEBUG click=OK via inner force=True")
                debug_retry_state(page, "after_click_inner_force_ok")
                return True
            except Exception as e2:
                log(f"RETRY-DEBUG click=FAIL via inner force ({type(e2).__name__}: {e2})")

    # 2) Role fallback
    role_btn = page.get_by_role("button", name=re.compile(r"^\s*Retry\s*$", re.I)).first
    if _safe_visible(role_btn):
        try:
            role_btn.scroll_into_view_if_needed(timeout=800)
        except Exception:
            pass

        try:
            role_btn.click(timeout=1500, trial=True)
            log("RETRY-DEBUG role trial=OK")
        except Exception as e:
            log(f"RETRY-DEBUG role trial=FAIL ({type(e).__name__}: {e})")

        try:
            role_btn.click(timeout=1500)
            log("RETRY-DEBUG click=OK via role")
            debug_retry_state(page, "after_click_role_ok")
            return True
        except Exception as e:
            log(f"RETRY-DEBUG click=FAIL via role ({type(e).__name__}: {e})")
            try:
                role_btn.click(timeout=1500, force=True)
                log("RETRY-DEBUG click=OK via role force=True")
                debug_retry_state(page, "after_click_role_force_ok")
                return True
            except Exception as e2:
                log(f"RETRY-DEBUG click=FAIL via role force ({type(e2).__name__}: {e2})")

    # 3) JS fallback
    try:
        ok = page.evaluate(
            """
            (sel) => {
              const host = document.querySelector(sel);
              if (!host) return false;
              const root = host.shadowRoot || host;
              const b = root.querySelector("button[part='button']");
              if (b) { b.click(); return true; }
              return false;
            }
            """,
            SEL_RETRY_HOST,
        )
        log(f"RETRY-DEBUG click via JS => {ok}")
        debug_retry_state(page, "after_click_js")
        return bool(ok)
    except Exception as e:
        log(f"RETRY-DEBUG JS click=FAIL ({type(e).__name__}: {e})")

    debug_retry_state(page, "after_click_all_failed")
    return False

def wait_for_results_or_retry(
    page,
    timeout_sec: int,
    max_retry_clicks: int = 10,
    poll_sec: float = 0.25,
) -> tuple[bool, int]:

    start = time.time()
    retry_clicks = 0
    last_debug = 0.0

    while time.time() - start < timeout_sec:
        close_unexpected_modal(page, "aguardando resultados")

        if DEBUG_RETRY and (time.time() - last_debug) > 2.0:
            debug_retry_state(page, "loop")
            last_debug = time.time()

        if _results_visible(page):
            log(f"Resultados visÃ­veis. Retry clicado {retry_clicks}x.")
            return True, retry_clicks

        retry_inner = page.locator(SEL_RETRY_INNER).first
        retry_role  = page.get_by_role("button", name=re.compile(r"^\s*Retry\s*$", re.I)).first
        retry_host  = page.locator(SEL_RETRY_HOST).first

        retry_is_visible = _safe_visible(retry_inner) or _safe_visible(retry_role) or _safe_visible(retry_host)

        if retry_is_visible:
            retry_clicks += 1
            log(f"Retry apareceu! tentativa #{retry_clicks}/{max_retry_clicks}")

            ok_click = _click_retry(page)
            log(f"Retry click result: {'OK' if ok_click else 'FAIL'}")

            if retry_clicks >= max_retry_clicks:
                log("âš ï¸ atingiu limite de retries sem resultado.")
                return False, retry_clicks

            time.sleep(min(2.0, 0.6 * (1.5 ** (retry_clicks - 1))))
            try:
                page.wait_for_load_state("networkidle", timeout=2500)
            except Exception:
                pass
            continue

        time.sleep(poll_sec)

    log("âš ï¸ Timeout esperando resultados/Retry.")
    return False, retry_clicks

# ----------------------------------------------------------------------
# âœ… escolher offer-card pela data e clicar em Price details / Detalhes do preÃ§o
# ----------------------------------------------------------------------
PRICE_DETAILS_RE = re.compile(r"(Price\s*details|Detalhes\s*do\s*pre[cÃ§]o)", re.I)

MONTH_MAP = {
    # EN
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
    # PT
    "FEV": 2, "ABR": 4, "MAI": 5, "AGO": 8, "SET": 9, "OUT": 10, "DEZ": 12,
}

def _parse_offer_dt(card, target_dt: datetime) -> datetime | None:
    """
    LÃª dia/mÃªs do offer-card (ex.: 19 / JAN) e monta um datetime no mesmo ano do target_dt.
    Faz um ajuste simples de ano se ficar muito distante (virada de ano).
    """
    try:
        day_txt = (card.locator(".offer-cards-day").first.inner_text() or "").strip()
        mon_txt = (card.locator(".offer-cards-month").first.inner_text() or "").strip()
    except Exception:
        return None

    mday = re.search(r"\d{1,2}", day_txt)
    if not mday:
        return None
    day = int(mday.group(0))

    mon = re.sub(r"[^A-Za-z\u00C0-\u00FF]", "", mon_txt).upper()[:3]
    month = MONTH_MAP.get(mon)
    if not month:
        return None

    try:
        dt = datetime(target_dt.year, month, day)
    except Exception:
        return None

    # Ajuste simples se a diferenÃ§a for absurda (caso vire o ano)
    if (dt - target_dt).days > 180:
        dt = datetime(target_dt.year - 1, month, day)
    elif (target_dt - dt).days > 180:
        dt = datetime(target_dt.year + 1, month, day)

    return dt

def _pagination_info(page) -> tuple[int | None, int | None]:
    pag = page.locator("mc-pagination[data-test='pricing-pagination']").first
    if pag.count() == 0:
        return None, None
    try:
        cur = int((pag.get_attribute("currentpage") or "0").strip())
    except Exception:
        cur = None
    try:
        total = int((pag.get_attribute("totalpages") or "0").strip())
    except Exception:
        total = None
    return cur, total

def _goto_next_offers_page(page) -> bool:
    """
    Clica em 'Seguinte/Next' na paginaÃ§Ã£o de offers. Retorna True se avanÃ§ou.
    """
    cur, total = _pagination_info(page)
    if cur is None:
        return False
    if total is not None and cur >= total:
        return False

    next_btn = page.locator(
        "mc-pagination[data-test='pricing-pagination'] mc-button[data-cy='next'] >>> button[part='button']"
    ).first

    if next_btn.count() == 0:
        next_btn = page.get_by_role("button", name=re.compile(r"(Seguinte|Next)", re.I)).first

    try:
        if next_btn.get_attribute("disabled") is not None:
            return False
    except Exception:
        pass

    try:
        next_btn.click(timeout=2500)
    except Exception:
        try:
            next_btn.click(timeout=2500, force=True)
        except Exception:
            return False

    try:
        page.wait_for_function(
            """(cur) => {
                 const el = document.querySelector("mc-pagination[data-test='pricing-pagination']");
                 if (!el) return false;
                 const v = Number(el.getAttribute("currentpage") || "0");
                 return v > cur;
               }""",
            cur,
            timeout=6000
        )
    except Exception:
        try:
            page.wait_for_load_state("networkidle", timeout=4000)
        except Exception:
            pass

    return True

def _goto_page(page, target_page: int) -> bool:
    """
    Navega na paginaÃ§Ã£o atÃ© target_page (clicando Next/Prev).
    """
    if target_page <= 0:
        return False
    for _ in range(15):
        cur, total = _pagination_info(page)
        if cur is None:
            return False
        if cur == target_page:
            return True
        if cur < target_page:
            if not _goto_next_offers_page(page):
                return False
        else:
            prev_btn = page.locator(
                "mc-pagination[data-test='pricing-pagination'] mc-button[data-cy='prev'] >>> button[part='button']"
            ).first
            if prev_btn.count() == 0:
                prev_btn = page.get_by_role("button", name=re.compile(r"(Anterior|Previous|Prev)", re.I)).first
            try:
                if prev_btn.get_attribute("disabled") is not None:
                    return False
            except Exception:
                pass
            try:
                prev_btn.click(timeout=2500)
            except Exception:
                try:
                    prev_btn.click(timeout=2500, force=True)
                except Exception:
                    return False
            try:
                page.wait_for_load_state("networkidle", timeout=4000)
            except Exception:
                pass
    return False

def open_price_details_closest_to_target(
    page,
    target_dt: datetime,
    job: dict,  # âœ… NOVO: pra screenshot com origem/destino
    timeout_ms: int = 45000,
) -> bool:
    """
    - Seleciona offer-card mais prÃ³ximo da data alvo e abre Price details.
    - Se falhar (sem ofertas / sem botÃ£o / etc), salva screenshot COM origem/destino/horÃ¡rio.
    """
    # Espera resultados aparecerem
    if not wait_for_results_cards(page, timeout_sec=max(5, int(timeout_ms/1000))):
        log("âš ï¸ Resultados: nÃ£o apareceram offer-cards/product-offer-card no tempo.")
        save_quote_screenshot(page, job, "no_results_cards")
        return False

    try:
        page.locator(".product-offer-card").first.scroll_into_view_if_needed(timeout=1200)
    except Exception:
        pass

    try:
        n_prod = page.locator(".product-offer-card").count()
        n_off  = page.locator(".product-offer-card mc-card.offer-cards, .product-offer-card [data-test='offer-cards']").count()
        n_btn  = page.locator(".product-offer-card div[data-test='offer-button']").count()
        log(f"DEBUG offers: product-offer-card={n_prod} | offer-cards={n_off} | offer-button-area={n_btn}")
    except Exception:
        pass

    best_below = None  # (page_num, idx_clickable, offer_dt)

    for _ in range(15):
        cur_page, total_pages = _pagination_info(page)
        cur_page = cur_page or 1

        cards = page.locator(".product-offer-card mc-card.offer-cards, .product-offer-card [data-test='offer-cards']")
        if cards.count() == 0:
            log("âš ï¸ Resultados: nenhum offer-card encontrado no DOM.")
            save_quote_screenshot(page, job, "no_offer_cards_dom")
            break

        clickable_idxs = []
        clickable_dts  = []

        for i in range(cards.count()):
            card = cards.nth(i)

            has_btn = False
            try:
                if card.locator("div[data-test='offer-button'] mc-button").count() > 0:
                    has_btn = True
            except Exception:
                has_btn = False

            if not has_btn:
                continue

            offer_dt = _parse_offer_dt(card, target_dt)
            if offer_dt is None:
                continue

            clickable_idxs.append(i)
            clickable_dts.append(offer_dt)

            if offer_dt >= target_dt:
                log(f"âœ… Offer escolhido (>= alvo): {offer_dt.strftime('%d %b %Y')} | alvo={target_dt.strftime('%d %b %Y')}")

                btn_inner = card.locator("div[data-test='offer-button'] mc-button >>> button[part='button']").first
                btn_role  = card.get_by_role("button", name=PRICE_DETAILS_RE).first
                btn_host  = card.locator("div[data-test='offer-button'] mc-button").first

                try:
                    card.scroll_into_view_if_needed(timeout=1200)
                except Exception:
                    pass

                clicked = False
                for cand in (btn_inner, btn_role, btn_host):
                    try:
                        if cand.count() > 0:
                            cand.wait_for(state="visible", timeout=2500)
                            cand.click(timeout=2500)
                            clicked = True
                            break
                    except Exception:
                        try:
                            cand.click(timeout=2500, force=True)
                            clicked = True
                            break
                        except Exception:
                            pass

                if not clicked:
                    log("âš ï¸ NÃ£o consegui clicar no botÃ£o de Price details neste offer-card.")
                    save_quote_screenshot(page, job, "price_details_click_failed")
                    return False

                try:
                    page.get_by_role("tab", name=re.compile(r"Breakdown", re.I)).wait_for(state="visible", timeout=15000)
                    return True
                except Exception:
                    pass
                try:
                    page.wait_for_selector('mc-c-table[data-test="priceBreakdown"]', timeout=15000)
                    return True
                except Exception:
                    log("âš ï¸ Cliquei no offer, mas nÃ£o abriu painel no tempo esperado.")
                    save_quote_screenshot(page, job, "price_details_panel_timeout")
                    return False

            if offer_dt < target_dt:
                best_below = (cur_page, len(clickable_idxs) - 1, offer_dt)

        if _goto_next_offers_page(page):
            continue
        else:
            break

    if best_below:
        best_page, idx_clickable, best_dt = best_below
        log(f"âœ… Nenhum offer >= alvo. Usando o mais prÃ³ximo abaixo: {best_dt.strftime('%d %b %Y')} (pÃ¡gina {best_page})")

        _goto_page(page, best_page)

        cards = page.locator(".product-offer-card mc-card.offer-cards, .product-offer-card [data-test='offer-cards']")
        clickables = []
        for i in range(cards.count()):
            card = cards.nth(i)
            try:
                if card.locator("div[data-test='offer-button'] mc-button").count() > 0:
                    odt = _parse_offer_dt(card, target_dt)
                    if odt is not None:
                        clickables.append((card, odt))
            except Exception:
                pass

        if not clickables:
            log("âš ï¸ NÃ£o encontrei offer-cards clicÃ¡veis ao voltar para a pÃ¡gina do best_below.")
            save_quote_screenshot(page, job, "no_clickable_offers_best_below")
            return False

        if idx_clickable < 0 or idx_clickable >= len(clickables):
            idx_clickable = len(clickables) - 1

        card, _ = clickables[idx_clickable]

        btn_inner = card.locator("div[data-test='offer-button'] mc-button >>> button[part='button']").first
        btn_role  = card.get_by_role("button", name=PRICE_DETAILS_RE).first
        btn_host  = card.locator("div[data-test='offer-button'] mc-button").first

        try:
            card.scroll_into_view_if_needed(timeout=1200)
        except Exception:
            pass

        clicked = False
        for cand in (btn_inner, btn_role, btn_host):
            try:
                if cand.count() > 0:
                    cand.wait_for(state="visible", timeout=2500)
                    cand.click(timeout=2500)
                    clicked = True
                    break
            except Exception:
                try:
                    cand.click(timeout=2500, force=True)
                    clicked = True
                    break
                except Exception:
                    pass

        if not clicked:
            log("âš ï¸ Falha ao clicar em Price details no best_below.")
            save_quote_screenshot(page, job, "price_details_click_failed_best_below")
            return False

        try:
            page.get_by_role("tab", name=re.compile(r"Breakdown", re.I)).wait_for(state="visible", timeout=15000)
            return True
        except Exception:
            pass
        try:
            page.wait_for_selector('mc-c-table[data-test="priceBreakdown"]', timeout=15000)
            return True
        except Exception:
            save_quote_screenshot(page, job, "price_details_panel_timeout_best_below")
            return False

    # âœ… Falhou total: screenshot com origem/destino
    save_quote_screenshot(page, job, "no_price_details_any_offer")
    log("Resultados: nÃ£o encontrei nenhum offer-card com botÃ£o 'Price details/Detalhes do preÃ§o'.")
    return False

def ensure_breakdown_tab(page, timeout_ms=12000) -> bool:
    try:
        tab = page.get_by_role(
            "tab", name=re.compile(r"^\s*Breakdown\s*$", re.I)
        ).first
        tab.wait_for(state="visible", timeout=timeout_ms)
        try:
            tab.click(timeout=1500)
        except Exception:
            pass
        page.wait_for_selector(
            'mc-c-table[data-test="priceBreakdown"]', timeout=timeout_ms
        )
        return True
    except Exception:
        return False

# ----------------------------------------------------------------------
# ExtraÃ§Ã£o do Breakdown (tabela dentro do Shadow DOM)
# ----------------------------------------------------------------------
_money_re = re.compile(r"([A-Z]{3})?\s*([\-â€“]?\s*[\d\.\,]+)")
_money_re = re.compile(r"([A-Z]{3})?\s*([\-â€“âˆ’]?\s*[\d\.,]+)")

def _parse_number_any_locale(num_txt: str) -> float | None:
    if num_txt is None:
        return None

    s = str(num_txt).strip()
    s = s.replace("\u00a0", " ")  # NBSP
    s = s.replace(" ", "")
    s = s.replace("â€“", "-").replace("âˆ’", "-")  # dashes

    if not s:
        return None

    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        if re.search(r",\d{1,2}$", s):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "." in s:
        if re.search(r"\.\d{1,2}$", s):
            s = s.replace(",", "")
        else:
            s = s.replace(".", "")

    try:
        return float(s)
    except Exception:
        return None

def normalize_money(s: str):
    if s is None:
        return None, None

    txt = " ".join(str(s).split())
    m = _money_re.search(txt)
    if not m:
        parts = txt.split()
        if len(parts) >= 2 and parts[-1].isalpha() and len(parts[-1]) == 3:
            cur = parts[-1]
            num = " ".join(parts[:-1])
        else:
            return None, None
    else:
        cur = m.group(1)
        num = m.group(2)

    val = _parse_number_any_locale(num)
    return (cur.strip().upper() if cur else None), val

def extract_offer_modal_header(page, timeout_ms: int = 8000) -> dict:
    """
    Extrai dados do card aberto por "Price details":
    - data de partida
    - data de chegada
    - tempo de viagem (texto e horas, quando disponÃ­vel)
    """
    out = {
        "departure_date": None,
        "arrival_date": None,
        "transit_time": None,
        "transit_time_hours": None,
    }

    header = page.locator(".offer-modal-header").first
    try:
        header.wait_for(state="visible", timeout=timeout_ms)
    except Exception:
        return out

    data = page.evaluate(
        """
        (sel) => {
          const normalize = (txt) => {
            const s = (txt || "").replace(/\\s+/g, " ").trim();
            return s || null;
          };

          const all = [...document.querySelectorAll(sel)];
          const host =
            all.find((el) => {
              const cs = window.getComputedStyle(el);
              return cs && cs.display !== "none" && cs.visibility !== "hidden";
            }) || all[0];
          if (!host) return null;

          const readSiblingText = (testId) => {
            const label = host.querySelector(`[data-test="${testId}"]`);
            if (!label) return null;
            let sib = label.nextElementSibling;
            while (sib) {
              const txt = normalize(sib.innerText || sib.textContent || "");
              if (txt) return txt;
              sib = sib.nextElementSibling;
            }
            return null;
          };

          const dep = readSiblingText("header-label-departure");
          const arr = readSiblingText("header-label-arrival");

          let transitText = null;
          let transitHours = null;
          const transitLabel = host.querySelector('[data-test="header-label-transit"]');
          if (transitLabel) {
            const parent = transitLabel.parentElement || host;
            const dur = parent.querySelector("mc-c-duration-display");
            if (dur) {
              transitText = normalize(dur.innerText || dur.textContent || "");
              const hoursRaw = Number(dur.getAttribute("durationinhours"));
              transitHours = Number.isFinite(hoursRaw) ? hoursRaw : null;
            } else {
              transitText = readSiblingText("header-label-transit");
            }
          }

          return {
            departureDate: dep,
            arrivalDate: arr,
            transitTime: transitText,
            transitTimeHours: transitHours,
          };
        }
        """,
        ".offer-modal-header",
    )

    if isinstance(data, dict):
        out["departure_date"] = data.get("departureDate")
        out["arrival_date"] = data.get("arrivalDate")
        out["transit_time"] = data.get("transitTime")
        out["transit_time_hours"] = data.get("transitTimeHours")

    return out

def extract_breakdown_table(page) -> dict:
    table_host = page.locator(
        'mc-c-table[data-test="priceBreakdown"]'
    ).first
    table_host.wait_for(state="visible", timeout=8000)

    rows = page.evaluate(
        """
        (hostSel) => {
          const host = document.querySelector(hostSel);
          if (!host) return null;
          const root = host.shadowRoot || host;
          const tbody = root.querySelector("table > tbody");
          const tfoot = root.querySelector("table > tfoot");
          const out = { body: [], footer_raw: null };
          if (tbody) {
            for (const tr of tbody.querySelectorAll("tr")) {
              const tds = [...tr.querySelectorAll("td")].map(td => td.innerText.trim());
              const firstTd = tds[0] || "";
              const hasSection = firstTd.toLowerCase().includes("charges") && tr.querySelector(".dark-subheader--chargesHeading");
              out.body.push({ tds, isSection: !!hasSection });
            }
          }
          if (tfoot) {
            out.footer_raw = tfoot.innerText.trim();
          }
          return out;
        }
    """,
        'mc-c-table[data-test="priceBreakdown"]',
    )

    if not rows:
        return {"__error": "Tabela Breakdown nÃ£o disponÃ­vel."}

    charges = []
    for r in rows["body"]:
        if r["isSection"]:
            continue
        tds = r["tds"]
        if len(tds) < 6:
            continue
        charge_name = tds[0].strip()
        basis = tds[1].strip()
        quantity = tds[2].strip()

        try:
            if "," in quantity and "." not in quantity:
                quantity_num = float(
                    quantity.replace(".", "").replace(",", ".")
                )
            else:
                quantity_num = float(quantity)
            if quantity_num.is_integer():
                quantity_num = int(quantity_num)
        except Exception:
            quantity_num = None

        cur_u, up = normalize_money(tds[4])
        cur_t, tp = normalize_money(tds[5])

        currency = cur_t or cur_u
        if not currency:
            currency = (tds[3] or "").strip() or None

        unit_price = up
        total_price = tp

        charges.append(
            {
                "charge_name": charge_name,
                "basis": basis,
                "quantity": quantity_num,
                "currency": currency,
                "unit_price": unit_price,
                "total_price": total_price,
            }
        )

    totals_by_currency = {}
    for c in charges:
        cur = c["currency"]
        val = c["total_price"]
        if cur and (val is not None):
            totals_by_currency[cur] = totals_by_currency.get(cur, 0.0) + float(val)

    footer_raw = rows.get("footer_raw")
    fcur, fval = normalize_money(footer_raw or "")
    footer = {"raw": footer_raw, "currency": fcur, "value": fval}

    return {
        "charges": charges,
        "totals_by_currency": totals_by_currency,
        "footer_grand_total": footer,
        "meta": {
            "tab": "Breakdown",
            "source": "mc-c-table[data-test=priceBreakdown]",
            "extracted_at": datetime.now().isoformat(timespec="seconds"),
        },
    }

# ----------------------------------------------------------------------
# ConversÃ£o de moedas para USD (via API Frankfurter)
# ----------------------------------------------------------------------
FX_API_BASE = os.getenv("FX_API_BASE", "https://api.frankfurter.dev/v1/latest")

@lru_cache(maxsize=64)
def fx_rate_to_usd(from_currency: str | None) -> float | None:
    code = (from_currency or "").strip().upper()
    if not code:
        return None
    if code == "USD":
        return 1.0

    try:
        resp = requests.get(
            FX_API_BASE,
            params={"base": code, "symbols": "USD"},
            timeout=5,
        )
        resp.raise_for_status()

        data = resp.json()
        rate = (data.get("rates") or {}).get("USD")

        if rate is not None:
            return float(rate)

        log(f"âš ï¸ FX: resposta sem rate para {code}->USD. payload={data}")

    except Exception as e:
        log(f"âš ï¸ FX: erro ao buscar {code}->USD ({type(e).__name__}: {e})")

    if code == "COP":
        log("âš ï¸ FX: usando taxa aproximada para COP -> USD.")
        return COP_TO_USD_APPROX

    return None

def amount_to_usd(amount: float | None, from_currency: str | None) -> float | None:
    if amount is None:
        return None
    rate = fx_rate_to_usd(from_currency)
    if rate is None:
        return None
    return float(amount) * rate

# ----------------------------------------------------------------------
# CSV WIDE (dinÃ¢mico por charge_name, prefixado por moeda)
# ----------------------------------------------------------------------
def canonical_key(job: dict) -> str:
    return f"{job['origin'].strip()}|{job['destination'].strip()}"

def ensure_wide_columns(df: pd.DataFrame, charges: list[dict]) -> pd.DataFrame:
    cols_needed = []
    for c in charges:
        cur = c.get("currency") or "UNK"
        name = c.get("charge_name") or "Unknown"
        col = f"{cur} {name}"
        cols_needed.append(col)
    for col in cols_needed:
        if col not in df.columns:
            df[col] = pd.NA
    return df

def write_wide_row(df: pd.DataFrame, job: dict, breakdown: dict | None) -> pd.DataFrame:
    THC_DEST_NAME_RE = re.compile(
        r"^\s*Terminal\s+Handling\s+Service\s*-\s*Destination\s*$", re.I
    )

    key = canonical_key(job)
    row_idx = df.index[df["key"] == key].tolist()
    if row_idx:
        i = row_idx[0]
    else:
        i = len(df)
        df.loc[i, "key"] = key
        df.loc[i, "origin"] = job["origin"]
        df.loc[i, "destination"] = job["destination"]

    df.loc[i, "last_attempt_at"] = job.get("_started_at") or datetime.now().isoformat(
        timespec="seconds"
    )

    if breakdown is None:
        df.loc[i, "status"] = job.get("status", "error")
        df.loc[i, "message"] = job.get("message", "Falha")
        return df

    df.loc[i, "status"] = "ok"
    df.loc[i, "message"] = ""
    df.loc[i, "quoted_at"] = datetime.now().isoformat(timespec="seconds")

    offer_header = breakdown.get("offer_header") or {}
    df.loc[i, "offer_departure_date"] = offer_header.get("departure_date")
    df.loc[i, "offer_arrival_date"] = offer_header.get("arrival_date")
    df.loc[i, "offer_transit_time"] = offer_header.get("transit_time")
    df.loc[i, "offer_transit_time_hours"] = offer_header.get("transit_time_hours")

    charges = breakdown.get("charges", [])

    charges_for_csv: list[dict] = []
    for c in charges:
        name = (c.get("charge_name") or "").strip()
        cur_original = c.get("currency")
        total_val = c.get("total_price")

        if THC_DEST_NAME_RE.match(name):
            charges_for_csv.append(c)
            continue

        usd_val = amount_to_usd(total_val, cur_original)
        if usd_val is not None:
            c2 = dict(c)
            c2["currency"] = "USD"
            c2["total_price"] = usd_val
            charges_for_csv.append(c2)
        else:
            log(
                f"âš ï¸ FX: nÃ£o foi possÃ­vel converter {cur_original} -> USD; mantendo valor original no CSV."
            )
            charges_for_csv.append(c)

    df = ensure_wide_columns(df, charges_for_csv)

    for col in df.columns:
        if col not in {
            "key",
            "origin",
            "destination",
            "last_attempt_at",
            "quoted_at",
            "status",
            "message",
            "offer_departure_date",
            "offer_arrival_date",
            "offer_transit_time",
            "offer_transit_time_hours",
        }:
            df.loc[i, col] = pd.NA

    for c in charges_for_csv:
        cur = c.get("currency") or "UNK"
        name = c.get("charge_name") or "Unknown"
        col = f"{cur} {name}"
        val = c.get("total_price")
        df.loc[i, col] = val

    return df

def load_wide_csv(path: Path) -> pd.DataFrame:
    if path.exists():
        try:
            df = pd.read_csv(path)
        except Exception:
            df = pd.DataFrame()
    else:
        df = pd.DataFrame()

    for base_col in [
        "key",
        "origin",
        "destination",
        "last_attempt_at",
        "quoted_at",
        "status",
        "message",
        "offer_departure_date",
        "offer_arrival_date",
        "offer_transit_time",
        "offer_transit_time_hours",
    ]:
        if base_col not in df.columns:
            df[base_col] = pd.Series(dtype="string")
    return df

def save_wide_csv(df: pd.DataFrame, path: Path):
    df.to_csv(path, index=False, encoding="utf-8-sig")

def append_run_log(status: str, job: dict, message: str = ""):
    rec = {
        "when": datetime.now().isoformat(timespec="seconds"),
        "origin": job.get("origin"),
        "destination": job.get("destination"),
        "status": status,
        "message": message,
    }
    if RUN_LOG_CSV.exists():
        try:
            old = pd.read_csv(RUN_LOG_CSV)
        except Exception:
            old = pd.DataFrame()
        new = pd.concat([old, pd.DataFrame([rec])], ignore_index=True)
    else:
        new = pd.DataFrame([rec])
    new.to_csv(RUN_LOG_CSV, index=False, encoding="utf-8-sig")

# ----------------------------------------------------------------------
# Prioridade dos jobs com base em tentativas e cotaÃ§Ãµes anteriores
# ----------------------------------------------------------------------
def _build_status_map(wide_df: pd.DataFrame) -> dict:
    status_map: dict[str, dict] = {}
    if wide_df.empty:
        return status_map

    for _, row in wide_df.iterrows():
        key = row.get("key")
        if pd.isna(key):
            continue

        last_attempt_raw = row.get("last_attempt_at")
        quoted_raw = row.get("quoted_at")

        last_attempt_dt = pd.to_datetime(last_attempt_raw, errors="coerce")
        quoted_dt = pd.to_datetime(quoted_raw, errors="coerce")

        status_map[str(key)] = {
            "quoted_at": quoted_dt,
            "last_attempt_at": last_attempt_dt,
        }
    return status_map

def _job_sort_key(job: dict, original_idx: int, status_map: dict) -> tuple:
    key = canonical_key(job)
    info = status_map.get(key)

    group = 0
    ts = datetime.min

    if info is not None:
        qdt = info.get("quoted_at")
        adt = info.get("last_attempt_at")

        if pd.notna(qdt):
            group = 1
            ts = qdt.to_pydatetime()
        elif pd.notna(adt):
            group = 2
            ts = adt.to_pydatetime()
        else:
            group = 0
            ts = datetime.min

    return (group, ts, original_idx)

def prioritize_jobs(jobs: list[dict], wide_df: pd.DataFrame) -> list[dict]:
    status_map = _build_status_map(wide_df)

    indexed = list(enumerate(jobs))
    ordered = sorted(
        indexed,
        key=lambda t: _job_sort_key(t[1], t[0], status_map),
    )
    return [job for _, job in ordered]

# ----------------------------------------------------------------------
# Batch: ler XLSX de jobs
# ----------------------------------------------------------------------
def read_jobs_xlsx(xlsx_path: Path) -> list[dict]:
    if not xlsx_path.exists():
        raise FileNotFoundError(f"Arquivo de entrada nÃ£o encontrado: {xlsx_path}")
    df = pd.read_excel(xlsx_path, engine="openpyxl")
    possible_orig = [
        c for c in df.columns if str(c).strip().lower() in {"origem", "origin"}
    ]
    possible_dest = [
        c
        for c in df.columns
        if str(c).strip().lower() in {"porto de destino", "destino", "destination"}
    ]
    if not possible_orig or not possible_dest:
        raise ValueError(
            "NÃ£o encontrei colunas 'ORIGEM' e 'PORTO DE DESTINO' (ou equivalentes)."
        )

    col_o = possible_orig[0]
    col_d = possible_dest[0]

    jobs = []
    for _, row in df.iterrows():
        origin = "" if pd.isna(row[col_o]) else str(row[col_o]).strip()
        dest = "" if pd.isna(row[col_d]) else str(row[col_d]).strip()
        jobs.append({"origin": origin, "destination": dest})
    return jobs

# ----------------------------------------------------------------------
# Orquestra um job (uma linha do Excel) com tolerÃ¢ncia a erro
# ----------------------------------------------------------------------
def run_one_job(page, job: dict) -> dict | None:
    """
    Executa o fluxo para 1 job. Retorna o breakdown (dict) em sucesso,
    ou {"__error": "..."} em falha (para logar motivo especÃ­fico).
    """
    try:
        page.goto(HUB_URL, wait_until="domcontentloaded")
        page.goto(BOOK_URL, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=7000)
        except Exception:
            pass

        close_unexpected_modal(page, "inicio do job")
        ok = fill_autocomplete(page, SEL_ORIGIN, job["origin"], "Origem")
        if not ok:
            save_quote_screenshot(page, job, "invalid_origin")
            return {"__error": f"Origem invÃ¡lida ou nÃ£o reconhecida: {job['origin']}"}

        close_unexpected_modal(page, "apos origem")
        ok = fill_autocomplete(page, SEL_DESTINATION, job["destination"], "Destino")
        if not ok:
            save_quote_screenshot(page, job, "invalid_destination")
            return {"__error": f"Destino invÃ¡lida ou nÃ£o reconhecida: {job['destination']}"}

        close_unexpected_modal(page, "apos destino")
        ok_com = set_commodity(page, text=job["commodity"])
        if not ok_com:
            save_quote_screenshot(page, job, "commodity_not_selected")
            return {"__error": f"Commodity nÃ£o pÃ´de ser selecionado: '{job['commodity']}'"}

        close_unexpected_modal(page, "apos commodity")
        set_container(page, text=job["container"])

        ok_w = fill_weight(page, SEL_WEIGHT, job["weight_kg"], "Peso (kg)")
        if not ok_w:
            save_quote_screenshot(page, job, "weight_not_accepted")
            return {"__error": "Campo de peso nÃ£o visÃ­vel/aceito."}

        close_unexpected_modal(page, "apos peso")
        set_price_owner(page, owner=job["price_owner"])

        target_dt = set_date_plus(
            page,
            days=job["date_plus_days"],
            label_for_log="Data (Earliest departure)",
        )

        close_unexpected_modal(page, "apos data")
        ok, retry_clicks = wait_for_results_or_retry(
            page,
            timeout_sec=RESULTS_TIMEOUT_SEC,
            max_retry_clicks=10,
            poll_sec=0.25,
        )

        if not ok:
            # âœ… Se nÃ£o achou nada (ou timeout/retry), tira print da tela "sem ter achado nada"
            save_quote_screenshot(page, job, f"no_results_timeout_retry_{retry_clicks}x")
            return {
                "__error": f"Resultados nÃ£o apareceram em {RESULTS_TIMEOUT_SEC}s "
                           f"(Retry clicado {retry_clicks}x)."
            }

        # âœ… Se achou resultados, tira print do â€œcard/tela com todos os nÃºmerosâ€
        save_quote_screenshot(page, job, "offers_visible")

        log("âœ… Resultados visÃ­veis â€” escolhendo o offer-card pela data e clicando em Price details...")

        close_unexpected_modal(page, "antes de escolher offer")
        if not open_price_details_closest_to_target(
            page, target_dt=target_dt, job=job, timeout_ms=RESULTS_TIMEOUT_SEC * 1000
        ):
            # open_price_details jÃ¡ salva screenshot, mas deixo esse aqui como redundÃ¢ncia segura
            save_quote_screenshot(page, job, "no_price_details")
            return {"__error": "NÃ£o encontrei/abri 'Price details' no offer-card mais prÃ³ximo da data alvo."}

        offer_header = extract_offer_modal_header(page, timeout_ms=10000)
        log(f"Card details: partida={offer_header.get('departure_date')} | chegada={offer_header.get('arrival_date')} | tempo={offer_header.get('transit_time')} (horas={offer_header.get('transit_time_hours')})")

        if not ensure_breakdown_tab(page):
            save_quote_screenshot(page, job, "breakdown_tab_missing")
            return {"__error": "Aba 'Breakdown' indisponÃ­vel."}

        bd = extract_breakdown_table(page)
        if isinstance(bd, dict) and "__error" not in bd:
            bd["offer_header"] = offer_header

        # se der erro na extraÃ§Ã£o, salva print tambÃ©m
        if bd and isinstance(bd, dict) and "__error" in bd:
            save_quote_screenshot(page, job, "breakdown_extract_error")
        else:
            # âœ… opcional: print depois de abrir a tabela (caso vocÃª queira evidÃªncia do breakdown tambÃ©m)
            save_quote_screenshot(page, job, "breakdown_visible")

        return bd

    except Exception as e:
        save_quote_screenshot(page, job, "unexpected_exception")
        return {"__error": f"{type(e).__name__}: {e}"}

# ----------------------------------------------------------------------
# MAIN (batch)
# ----------------------------------------------------------------------
def main():
    load_dotenv()

    maersk_user = os.getenv("MAERSK_USER")
    maersk_pass = os.getenv("MAERSK_PASS")
    if not maersk_user or not maersk_pass:
        raise RuntimeError("MAERSK_USER e/ou MAERSK_PASS nÃ£o configurados no .env")

    default_commodity   = os.getenv("MAERSK_COMMODITY",   "Ceramics, stoneware")
    default_container   = os.getenv("MAERSK_CONTAINER",   "20 Dry")
    default_weight_kg   = int(os.getenv("MAERSK_WEIGHT_KG", "26000"))
    default_price_owner = os.getenv("MAERSK_PRICE_OWNER", "I am the price owner")
    default_date_plus   = int(os.getenv("MAERSK_DATE_PLUS_DAYS", "14"))
    keep_open           = int(os.getenv("KEEP_OPEN_SECS", "30"))

    jobs = read_jobs_xlsx(INPUT_XLSX)
    if not jobs:
        log("Nenhum job no XLSX de entrada.")
        return

    wide_df = load_wide_csv(OUT_CSV)

    jobs = prioritize_jobs(jobs, wide_df)
    log(f"Total de jobs carregados: {len(jobs)} (ordenados por prioridade).")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=".pw-user-data-maersk",
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
        page = context.new_page()
        page.set_default_timeout(7000)

        ok_login = login_maersk(page, maersk_user, maersk_pass)
        if not ok_login:
            log("âš ï¸ Login falhou; encerrando execuÃ§Ã£o.")
            return

        for idx, job in enumerate(jobs, start=1):
            job.setdefault("commodity", default_commodity)
            job.setdefault("container", default_container)
            job.setdefault("weight_kg", default_weight_kg)
            job.setdefault("price_owner", default_price_owner)
            job.setdefault("date_plus_days", default_date_plus)
            job["_started_at"] = datetime.now().isoformat(timespec="seconds")

            log(f"--- ({idx}/{len(jobs)}) {job['origin']} â†’ {job['destination']} ---")

            if is_blank(job["origin"]) or is_blank(job["destination"]):
                # aqui nÃ£o tem tela Ãºtil, mas se quiser:
                # save_quote_screenshot(page, job, "blank_origin_or_destination")
                job["status"] = "error"
                job["message"] = "Origem/Destino vazios no Excel."
                wide_df = write_wide_row(wide_df, job, breakdown=None)
                append_run_log("error", job, job["message"])
                save_wide_csv(wide_df, OUT_CSV)
                continue

            bd = run_one_job(page, job)

            if not bd or ("__error" in bd):
                job["status"] = "error"
                job["message"] = (bd or {}).get("__error", "Falha no fluxo/Breakdown indisponÃ­vel")
                wide_df = write_wide_row(wide_df, job, breakdown=None)
                append_run_log("error", job, job["message"])
                log(f"âŒ JOB ERRO: {job['origin']} â†’ {job['destination']} | {job['message']}")
            else:
                job["status"] = "ok"
                job["message"] = ""
                wide_df = write_wide_row(wide_df, job, breakdown=bd)
                append_run_log("ok", job, "")

            save_wide_csv(wide_df, OUT_CSV)
            time.sleep(1.0)

        log(f"âœ… Batch concluÃ­do. Mantendo aberto por {keep_open}sâ€¦")
        time.sleep(keep_open)

if __name__ == "__main__":
    main()
