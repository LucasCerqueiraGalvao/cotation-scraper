# maersk_book_fill_fast.py
import os, re, time, calendar, json
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

# Commodity — preferir o acessível; manter XPath como fallback
COMMODITY_XPATH        = '/html/body/div[2]/main/section/div/div[2]/div[2]/form/mc-card[2]/fieldset/span/mc-c-commodity//div/div/div/div/div/div/div/div/div/slot/input'

# I/O
ARTIFACTS        = Path("artifacts")
INPUT_XLSX       = ARTIFACTS / "input" / "maersk_jobs_teste.xlsx"
OUT_DIR          = ARTIFACTS / "output"
OUT_CSV          = OUT_DIR / "maersk_breakdowns.csv"   # formato "wide"
RUN_LOG_CSV      = OUT_DIR / "maersk_run_log.csv"

SCREENS          = Path("screens")

for p in [ARTIFACTS, ARTIFACTS/"input", OUT_DIR, SCREENS]:
    p.mkdir(parents=True, exist_ok=True)

# Timeout maior para esperar os cards de resultado (ajustável via .env)
RESULTS_TIMEOUT_SEC = int(os.getenv("MAERSK_RESULTS_TIMEOUT_SEC", "45"))

# Taxa aproximada COP → USD (ajuste conforme quiser)
COP_TO_USD_APPROX = 0.00025   # COP 1 = 0.00025 USD  (exemplo realista)

# ----------------------------------------------------------------------
# Utils gerais
# ----------------------------------------------------------------------
def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

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
    # botão direto
    try:
        page.locator(SEL_ALLOW_ALL).click(timeout=800)
        log("Cookies: Allow all clicado.")
        return
    except Exception:
        pass
    # JS do CookieInformation
    try:
        if page.evaluate("() => window.CookieInformation?.submitAllCategories?.() || false"):
            log("Cookies: submitAllCategories() via JS (página).")
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

# ----------------------------------------------------------------------
# Login Maersk
# ----------------------------------------------------------------------
def login_maersk(page, username: str, password: str, timeout_ms: int = 30000) -> bool:
    """
    Faz login na Maersk usando a tela de login padrão.
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

    # Botão "Log in"
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
        log("⚠️ Login: não consegui clicar no botão 'Log in'.")
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
        log(f"⚠️ Login: aparentemente não saiu da tela de login (URL: {page.url}).")
        return False

# ----------------------------------------------------------------------
# Ações de preenchimento
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
    Autocomplete genérico (Origem/Destino) mais parecido com set_commodity:
    - digita o texto
    - espera o dropdown de opções
    - tenta clicar numa option que contenha o texto
    - fallback: ArrowDown+Enter + retries
    """
    loc = page.locator(selector).first
    loc.wait_for(state="visible", timeout=8000)

    # garante que está na viewport
    try:
        loc.scroll_into_view_if_needed(timeout=800)
    except Exception:
        pass

    loc.click()
    _clear(loc)
    loc.fill(text)

    # pequena espera inicial para API começar a responder
    time.sleep(wait_before_enter)

    # tenta descobrir o listbox vinculado via aria-controls (mais preciso)
    try:
        listbox_id = loc.get_attribute("aria-controls")
    except Exception:
        listbox_id = None

    if listbox_id:
        opts = page.locator(f'#{listbox_id} [role="option"]')
    else:
        # fallback mais genérico (como em set_commodity)
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
        # dá um nudge pra abrir o dropdown se ainda não abriu
        try:
            loc.press("ArrowDown")
        except Exception:
            pass
        time.sleep(0.15)

    if appeared:
        # tenta achar uma option que contenha o texto digitado (código UNLOCODE, cidade, etc.)
        try:
            match_opt = opts.filter(has_text=re.compile(re.escape(text), re.I)).first
            if match_opt.count() > 0 and match_opt.is_visible():
                match_opt.click()
                if wait_input_valid(loc, 4000):
                    log(f"{label}: option que casa '{text}' selecionada.")
                    return True
            # se não achar match específico, clica na primeira visível
            first_opt = opts.first
            if first_opt.count() > 0 and first_opt.is_visible():
                first_opt.click()
                if wait_input_valid(loc, 4000):
                    log(f"{label}: primeira option selecionada para '{text}'.")
                    return True
        except Exception:
            pass

    # se não conseguiu usar dropdown, cai pro comportamento antigo
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
                log(f"{label}: '{text}' confirmado após retry.")
                return True
        except Exception:
            pass

    log(f"⚠️ {label}: não confirmou '{text}' (campo permaneceu inválido).")
    return False

import re, time  # redundante mas inofensivo

def set_commodity(page, text: str, wait_opts_ms: int = 5000) -> bool:
    """
    Preenche o campo Commodity (combobox dentro de <mc-c-commodity>) e seleciona uma opção.
    Retorna True se conseguiu selecionar, False caso contrário.
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

    # Garante que está na viewport
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
    while time.time() - t0 < (wait_opts_ms / 3000.0):
        try:
            if opts.count() > 0 and opts.first.is_visible():
                appeared = True
                break
        except Exception:
            pass
        # pequeno nudge para disparar dropdown se necessário
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
            log("Commodity: selecionada primeira opção do listbox.")
            return True
        except Exception:
            pass

    # 6) Últimos recursos: ArrowDown+Enter ou Enter direto
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
        log("⚠️ Commodity: não consegui confirmar.")
        return False


def set_container(page, text="20 Dry"):
    loc = page.locator(SEL_CONTAINER_VISIBLE).first
    if loc.count() == 0:
        loc = page.get_by_label(re.compile(r"Container type and size", re.I)).first
    loc.wait_for(state="visible", timeout=8000)

    loc.click()
    _clear(loc)
    loc.fill(text)
    time.sleep(0.2)  # dá tempo do listbox montar

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
            log(f"⚠️ Container: não foi possível selecionar ({type(e2).__name__}).")


def fill_weight(page, selector, kg, label="Peso (kg)") -> bool:
    loc = page.locator(selector).first
    try:
        loc.wait_for(state="visible", timeout=8000)
    except Exception:
        log(f"⚠️ {label}: campo não visível.")
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
        log(f"⚠️ {label}: {v} < min ({minv}). Usando {minv}.")
        v = minv
    if v > maxv:
        log(f"⚠️ {label}: {v} > max ({maxv}). Usando {maxv}.")
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
        log(f"{label_for_log}: marcado → '{owner}'.")
        return
    except Exception:
        pass
    # fallback: host do mc-radio
    try:
        host = page.locator(f"mc-radio:has-text('{owner}')").first
        host.wait_for(state="visible", timeout=3000)
        try:
            host.click(timeout=1000)
            log(f"{label_for_log}: host clicado → '{owner}'.")
            return
        except Exception:
            ck = host.locator('[part="checkmark"]').first
            ck.click(timeout=1000, force=True)
            log(f"{label_for_log}: checkmark clicado → '{owner}'.")
            return
    except Exception:
        pass
    # último recurso: força via JS
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
        log(f"{label_for_log}: setado via JS → '{owner}'.")
    except Exception as e:
        log(f"⚠️ {label_for_log}: falha ({type(e).__name__}).")


def set_date_plus(page, days=7, label_for_log="Data (Earliest departure)"):
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

# ----------------------------------------------------------------------
# Resultados: esperar cards, abrir "Price details" e garantir Breakdown
# ----------------------------------------------------------------------
def wait_for_results_cards(page, timeout_sec: int = RESULTS_TIMEOUT_SEC) -> bool:
    """
    Aguarda aparecerem resultados: offer-cards, product-offer-card ou um botão 'Price details'.
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
                    name=re.compile(r"^\s*Price\s+details\s*$", re.I),
                ).count()
                > 0
            ):
                return True
        except Exception:
            pass
        time.sleep(0.25)
    return False

SEL_RETRY_HOST  = "mc-button[data-test='pricing-search-again']"
SEL_RETRY_INNER = SEL_RETRY_HOST + " >> button[part='button']"

def _is_visible(loc) -> bool:
    try:
        return loc is not None and loc.count() > 0 and loc.first.is_visible()
    except Exception:
        return False

def _results_visible(page) -> bool:
    try:
        if page.locator('[data-test="offer-cards"]:visible').count() > 0:
            return True
        if page.locator(".product-offer-card:visible").count() > 0:
            return True
        if page.get_by_role("button", name=re.compile(r"^\s*Price\s+details\s*$", re.I)).count() > 0:
            return True
    except Exception:
        pass
    return False

DEBUG_RETRY = True  # <-- liga/desliga os logs extras
DEBUG_RETRY_SCREENSHOT = False  # salva prints em /screens

SEL_RETRY_HOST  = "mc-button[data-test='pricing-search-again']"
SEL_RETRY_INNER = SEL_RETRY_HOST + " >> button[part='button']"

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

        # Probe via JS (confirma se existe shadowRoot e se encontra o button)
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
            page.screenshot(path=f"screens/retry_debug_{tag}_{ts}.png", full_page=True)
            log(f"RETRY-DEBUG screenshot=screens/retry_debug_{tag}_{ts}.png")

    except Exception as e:
        log(f"RETRY-DEBUG erro ao inspecionar estado ({type(e).__name__}: {e})")

def _click_retry(page) -> bool:
    """
    Clique no Retry com logs detalhados.
    Retorna True se acredita que clicou, False se falhou.
    """
    debug_retry_state(page, "before_click")

    # 1) Inner (shadow) - o mais confiável aqui
    btn = page.locator(SEL_RETRY_INNER).first
    if _safe_visible(btn):
        try:
            btn.scroll_into_view_if_needed(timeout=800)
        except Exception:
            pass

        # Trial click (ver se é clicável)
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
        # loga estado a cada ~2s pra não spammar infinito
        if DEBUG_RETRY and (time.time() - last_debug) > 2.0:
            debug_retry_state(page, "loop")
            last_debug = time.time()

        # 1) resultados
        if _results_visible(page):
            log(f"Resultados visíveis. Retry clicado {retry_clicks}x.")
            return True, retry_clicks

        # 2) retry aparece?
        retry_inner = page.locator(SEL_RETRY_INNER).first
        retry_role  = page.get_by_role("button", name=re.compile(r"^\s*Retry\s*$", re.I)).first
        retry_host  = page.locator(SEL_RETRY_HOST).first

        retry_is_visible = _safe_visible(retry_inner) or _safe_visible(retry_role) or _safe_visible(retry_host)

        if retry_is_visible:
            retry_clicks += 1
            log(f"Retry apareceu! tentativa #{retry_clicks}/{max_retry_clicks}")

            ok_click = _click_retry(page)  # essa função já tenta inner -> role -> JS
            log(f"Retry click result: {'OK' if ok_click else 'FAIL'}")

            if retry_clicks >= max_retry_clicks:
                log("⚠️ atingiu limite de retries sem resultado.")
                return False, retry_clicks

            time.sleep(min(2.0, 0.6 * (1.5 ** (retry_clicks - 1))))
            try:
                page.wait_for_load_state("networkidle", timeout=2500)
            except Exception:
                pass
            continue

        # 3) não apareceu ainda — espera e tenta de novo
        time.sleep(poll_sec)

    log("⚠️ Timeout esperando resultados/Retry.")
    return False, retry_clicks

def open_first_price_details(page, idx_card_prefer=0, timeout_ms=10000) -> bool:
    """
    Abre o primeiro 'Price details' disponível.
    - Percorre .product-offer-card (não o host <mc-card>).
    - Procura o botão dentro do Shadow DOM: mc-button >> button[part="button"].
    - Pula cards sem botão (ex.: 'Deadline has passed').
    """
    t0 = time.time()

    # Espera até existir pelo menos 1 botão "Price details" visível em qualquer card
    while time.time() - t0 < timeout_ms / 5000.0:
        try:
            any_btn = (
                page.locator(
                    ".product-offer-card >> mc-button:has-text('Price details') >> button[part='button']"
                ).filter(has_text=re.compile(r"Price\s*details", re.I))
            )
            if any_btn.count() > 0:
                break
        except Exception:
            pass
        time.sleep(0.25)

    # Recoleta os cards (container certo)
    cards = page.locator(".product-offer-card").filter(
        has=page.locator("div[data-test='offer-button']")
    )
    if cards.count() == 0:
        log("Resultados: nenhum '.product-offer-card' com área de botão.")
        return False

    # Tenta priorizar o idx_card_prefer, mas cai para o primeiro que tiver botão
    order = list(range(cards.count()))
    if 0 <= idx_card_prefer < len(order):
        order = [idx_card_prefer] + [i for i in order if i != idx_card_prefer]

    for i in order:
        card = cards.nth(i)

        # Localizadores dentro do card
        btn_inner = card.locator(
            "mc-button:has-text('Price details') >> button[part='button']"
        ).first
        btn_role = card.get_by_role(
            "button", name=re.compile(r"^\s*Price\s+details\s*$", re.I)
        ).first
        btn_host = card.locator("mc-button:has-text('Price details')").first

        # Se não tem botão, pula
        if btn_inner.count() == 0 and btn_role.count() == 0 and btn_host.count() == 0:
            continue

        # Garante visibilidade
        try:
            card.scroll_into_view_if_needed(timeout=1200)
        except Exception:
            pass

        # Tenta cliques em ordem: inner -> role -> host -> bounding box -> JS
        clicked = False
        for attempt in range(1, 5):
            try:
                if btn_inner.count() > 0:
                    btn_inner.wait_for(state="visible", timeout=2000)
                    btn_inner.click(timeout=2000)
                    clicked = True
                elif btn_role.count() > 0:
                    btn_role.wait_for(state="visible", timeout=2000)
                    btn_role.click(timeout=2000)
                    clicked = True
                elif btn_host.count() > 0:
                    # Alguns web-components aceitam clique no host
                    btn_host.wait_for(state="visible", timeout=2000)
                    btn_host.click(timeout=2000)
                    clicked = True
                else:
                    # bounding box do melhor candidato
                    target = (
                        btn_inner
                        if btn_inner.count() > 0
                        else (btn_role if btn_role.count() > 0 else btn_host)
                    )
                    el = target.element_handle() if target.count() > 0 else None
                    box = el.bounding_box() if el else None
                    if box:
                        page.mouse.click(
                            box["x"] + box["width"] / 2,
                            box["y"] + box["height"] / 2,
                        )
                        clicked = True
                if clicked:
                    log(f"Card {i}: 'Price details' clicado (tentativa {attempt}).")
                    break
            except Exception:
                # tente forçar no próximo loop
                time.sleep(0.25)

        if not clicked:
            # último recurso: JS dentro do shadow
            try:
                ok = page.evaluate(
                    """
                    (root) => {
                      const host = root.querySelector("mc-button:has(slot[label]), mc-button[ label ]") 
                                   || root.querySelector("mc-button");
                      if (!host) return false;
                      const sr = host.shadowRoot || host;
                      const b  = sr.querySelector('button[part="button"]');
                      if (b) { b.click(); return true; }
                      return false;
                    }
                """,
                    card.evaluate_handle("n => n"),
                )
                if ok:
                    log(
                        f"Card {i}: 'Price details' clicado via JS no shadow."
                    )
                    clicked = True
            except Exception:
                pass

        if not clicked:
            log(
                f"Card {i}: falha ao clicar em 'Price details'. Tentando próximo card…"
            )
            continue

        # Espera o painel/tabela aparecer
        try:
            page.get_by_role(
                "tab", name=re.compile(r"Breakdown", re.I)
            ).wait_for(state="visible", timeout=15000)
            return True
        except Exception:
            pass
        try:
            page.wait_for_selector(
                'mc-c-table[data-test="priceBreakdown"]', timeout=15000
            )
            return True
        except Exception:
            # Se não abriu, tenta outro card
            log(
                f"Card {i}: clique não abriu o painel no tempo esperado. Tentando próximo…"
            )
            continue

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
# Extração do Breakdown (tabela dentro do Shadow DOM)
# ----------------------------------------------------------------------
_money_re = re.compile(r"([A-Z]{3})?\s*([\-–]?\s*[\d\.\,]+)")


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

    num = num.replace(" ", "").replace(".", "").replace(",", ".")
    try:
        val = float(num)
    except Exception:
        val = None
    return cur, val


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
        return {"__error": "Tabela Breakdown não disponível."}

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

        # Moeda: tenta pegar dos campos de preço; se não vier, usa a coluna "Currency" (tds[3])
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
# Conversão de moedas para USD (via API Frankfurter)
# ----------------------------------------------------------------------
FX_API_BASE = os.getenv("FX_API_BASE", "https://api.frankfurter.dev/v1/latest")


@lru_cache(maxsize=64)
def fx_rate_to_usd(from_currency: str | None) -> float | None:
    """
    Converte 1 <from_currency> -> USD.
    Regras:
      - Se for USD → 1.0
      - Se for COP e API falhar → usa taxa aproximada
      - Se não for COP e API falhar → retorna None
    """
    code = (from_currency or "").strip().upper()
    if not code:
        return None
    if code == "USD":
        return 1.0

    # 1. Tentativa normal via API
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

        # Se vier resposta sem USD → erro tratado abaixo
        log(f"⚠️ FX: resposta sem rate para {code}->USD. payload={data}")

    except Exception as e:
        log(f"⚠️ FX: erro ao buscar {code}->USD ({type(e).__name__}: {e})")

    # 2. Fallback EXCLUSIVO para COP
    if code == "COP":
        log("⚠️ FX: usando taxa aproximada para COP -> USD.")
        return COP_TO_USD_APPROX

    # 3. Para qualquer outra moeda → não tentar converter!
    return None

def amount_to_usd(amount: float | None, from_currency: str | None) -> float | None:
    if amount is None:
        return None
    rate = fx_rate_to_usd(from_currency)
    if rate is None:
        return None
    return float(amount) * rate

# ----------------------------------------------------------------------
# CSV WIDE (dinâmico por charge_name, prefixado por moeda)
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
    """
    Escreve/atualiza UMA linha (1 key = origem|destino) no CSV wide.

    Como funciona:
      - Cada charge vira uma coluna dinâmica no formato: "<CUR> <charge_name>"
        Ex.: "USD Ocean Freight", "EUR Documentation fee - Destination", etc.
      - O valor escrito é o total_price daquela charge.

    Regra de FX (já existia):
      - Tenta converter todos os totais para USD quando possível (amount_to_usd)
      - Se não conseguir converter, mantém a moeda original.

    REGRA NOVA (o que você pediu):
      - NÃO converter a charge de THC Import:
            "Terminal Handling Service - Destination"
        => Ou seja: ela deve SEMPRE permanecer na moeda original.
        Resultado: você vai ter variantes por moeda no wide, por exemplo:
            "USD Terminal Handling Service - Destination"
            "EUR Terminal Handling Service - Destination"
            "COP Terminal Handling Service - Destination"
        (em vez de tudo virar "USD ...").
    """
    # Regex robusto para pegar exatamente a THC de destino (variações de espaços/hífen)
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

    # Sempre marca a tentativa
    df.loc[i, "last_attempt_at"] = job.get("_started_at") or datetime.now().isoformat(
        timespec="seconds"
    )

    # Se não tem breakdown (falha), só registra status/mensagem
    if breakdown is None:
        df.loc[i, "status"] = job.get("status", "error")
        df.loc[i, "message"] = job.get("message", "Falha")
        return df

    # Sucesso
    df.loc[i, "status"] = "ok"
    df.loc[i, "message"] = ""
    df.loc[i, "quoted_at"] = datetime.now().isoformat(timespec="seconds")

    charges = breakdown.get("charges", [])

    # ------------------------------------------------------------------
    # FX / Normalização para CSV:
    # - Converte para USD sempre que possível (como já era)
    # - EXCETO para THC Dest (Terminal Handling Service - Destination),
    #   que deve ficar na moeda original SEMPRE.
    # ------------------------------------------------------------------
    charges_for_csv: list[dict] = []
    for c in charges:
        name = (c.get("charge_name") or "").strip()
        cur_original = c.get("currency")
        total_val = c.get("total_price")

        # ✅ REGRA NOVA: NÃO CONVERTER THC DEST
        if THC_DEST_NAME_RE.match(name):
            # Mantém exatamente como veio: moeda original + valor original
            charges_for_csv.append(c)
            continue

        # 🔁 Regra antiga: tentar converter para USD
        usd_val = amount_to_usd(total_val, cur_original)
        if usd_val is not None:
            c2 = dict(c)
            c2["currency"] = "USD"
            c2["total_price"] = usd_val
            charges_for_csv.append(c2)
        else:
            # Se não conseguir converter, mantém a moeda original no CSV
            log(
                f"⚠️ FX: não foi possível converter {cur_original} -> USD; mantendo valor original no CSV."
            )
            charges_for_csv.append(c)

    # Garante que existam colunas para todas as charges que vamos escrever
    df = ensure_wide_columns(df, charges_for_csv)

    # Zera todas as colunas dinâmicas (charges) desta linha antes de reescrever
    for col in df.columns:
        if col not in {
            "key",
            "origin",
            "destination",
            "last_attempt_at",
            "quoted_at",
            "status",
            "message",
        }:
            df.loc[i, col] = pd.NA

    # Escreve os valores no formato "<CUR> <charge_name>"
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
# Prioridade dos jobs com base em tentativas e cotações anteriores
# ----------------------------------------------------------------------
def _build_status_map(wide_df: pd.DataFrame) -> dict:
    """
    Cria um dicionário key -> {quoted_at: datetime|NaT, last_attempt_at: datetime|NaT}
    a partir do CSV wide.
    """
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
    """
    Regras de prioridade (menor tuple vem primeiro):

    grupo 0 -> nunca teve tentativa nem cotação    (novos)
    grupo 1 -> já teve cotação pelo menos 1 vez    (ordenar pela data de cotação mais antiga)
    grupo 2 -> só teve tentativa (erro), sem cotação (ordenar pela tentativa mais antiga)
    """
    key = canonical_key(job)
    info = status_map.get(key)

    # default: nunca rodou
    group = 0
    ts = datetime.min

    if info is not None:
        qdt = info.get("quoted_at")
        adt = info.get("last_attempt_at")

        if pd.notna(qdt):
            # já teve pelo menos uma cotação bem-sucedida
            group = 1
            # quanto mais antigo o quoted_at, mais prioridade => ordena por data crescente
            ts = qdt.to_pydatetime()
        elif pd.notna(adt):
            # só tentativas (erros), nenhuma cotação ainda
            group = 2
            ts = adt.to_pydatetime()
        else:
            group = 0
            ts = datetime.min

    # original_idx garante estabilidade dentro do grupo
    return (group, ts, original_idx)


def prioritize_jobs(jobs: list[dict], wide_df: pd.DataFrame) -> list[dict]:
    """
    Aplica a prioridade desejada:

    1) Primeiro: jobs sem tentativa nem cotação (não aparecem no CSV).
    2) Depois: jobs que já tiveram pelo menos uma cotação (ordenados pela cotação mais antiga).
    3) Depois: jobs que só tiveram tentativas (erro), ordenados pela tentativa mais antiga.
    """
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
    """
    Lê artifacts/input/maersk_jobs_teste.xlsx
    Espera colunas: 'ORIGEM' e 'PORTO DE DESTINO'
    """
    if not xlsx_path.exists():
        raise FileNotFoundError(f"Arquivo de entrada não encontrado: {xlsx_path}")
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
            "Não encontrei colunas 'ORIGEM' e 'PORTO DE DESTINO' (ou equivalentes)."
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
# Função para lidar com botão Retry
# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
# Orquestra um job (uma linha do Excel) com tolerância a erro
# ----------------------------------------------------------------------
def run_one_job(page, job: dict) -> dict | None:
    """
    Executa o fluxo para 1 job. Retorna o breakdown (dict) em sucesso,
    ou {"__error": "..."} em falha (para logar motivo específico).
    """
    try:
        # acorda sessão // **chamadas de cookies comentadas a pedido**
        page.goto(HUB_URL, wait_until="domcontentloaded")
        # accept_cookies_quick(page)

        page.goto(BOOK_URL, wait_until="domcontentloaded")
        # accept_cookies_quick(page)
        try:
            page.wait_for_load_state("networkidle", timeout=7000)
        except Exception:
            pass

        # origem
        ok = fill_autocomplete(page, SEL_ORIGIN, job["origin"], "Origem")
        if not ok:
            return {
                "__error": f"Origem inválida ou não reconhecida: {job['origin']}"
            }

        # destino
        ok = fill_autocomplete(
            page, SEL_DESTINATION, job["destination"], "Destino"
        )
        if not ok:
            return {
                "__error": f"Destino inválido ou não reconhecido: {job['destination']}"
            }

        ok_com = set_commodity(page, text=job["commodity"])
        if not ok_com:
            return {
                "__error": f"Commodity não pôde ser selecionado: '{job['commodity']}'"
            }

        set_container(page, text=job["container"])

        ok_w = fill_weight(
            page, SEL_WEIGHT, job["weight_kg"], "Peso (kg)"
        )
        if not ok_w:
            return {"__error": "Campo de peso não visível/aceito."}

        set_price_owner(page, owner=job["price_owner"])
        set_date_plus(
            page,
            days=job["date_plus_days"],
            label_for_log="Data (Earliest departure)",
        )

        ok, retry_clicks = wait_for_results_or_retry(
            page,
            timeout_sec=RESULTS_TIMEOUT_SEC,
            max_retry_clicks=10,
            poll_sec=0.25,
        )

        if not ok:
            return {
                "__error": f"Resultados não apareceram em {RESULTS_TIMEOUT_SEC}s "
                        f"(Retry clicado {retry_clicks}x)."
            }


        if not open_first_price_details(
            page, timeout_ms=RESULTS_TIMEOUT_SEC * 1000
        ):
            return {
                "__error": "Não consegui abrir 'Price details' do primeiro card."
            }

        if not ensure_breakdown_tab(page):
            return {"__error": "Aba 'Breakdown' indisponível."}

        bd = extract_breakdown_table(page)
        return bd

    except Exception as e:
        return {"__error": f"{type(e).__name__}: {e}"}

# ----------------------------------------------------------------------
# MAIN (batch)
# ----------------------------------------------------------------------
def main():
    load_dotenv()

    maersk_user = os.getenv("MAERSK_USER")
    maersk_pass = os.getenv("MAERSK_PASS")
    if not maersk_user or not maersk_pass:
        raise RuntimeError("MAERSK_USER e/ou MAERSK_PASS não configurados no .env")

    # Defaults do .env (podem ser sobrescritos por job no futuro)
    default_commodity   = os.getenv("MAERSK_COMMODITY",   "Ceramics, stoneware")
    default_container   = os.getenv("MAERSK_CONTAINER",   "20 Dry")
    default_weight_kg   = int(os.getenv("MAERSK_WEIGHT_KG", "26000"))
    default_price_owner = os.getenv("MAERSK_PRICE_OWNER", "I am the price owner")
    default_date_plus   = int(os.getenv("MAERSK_DATE_PLUS_DAYS", "7"))
    keep_open           = int(os.getenv("KEEP_OPEN_SECS", "30"))

    # Lê jobs do XLSX
    jobs = read_jobs_xlsx(INPUT_XLSX)
    if not jobs:
        log("Nenhum job no XLSX de entrada.")
        return

    # carrega CSV wide (para sobrescrever/atualizar por chave)
    wide_df = load_wide_csv(OUT_CSV)

    # 🔁 NOVO: reordena jobs de acordo com a prioridade desejada
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

        # 🔐 Login antes da primeira cotação
        ok_login = login_maersk(page, maersk_user, maersk_pass)
        if not ok_login:
            log("⚠️ Login falhou; encerrando execução.")
            return

        for idx, job in enumerate(jobs, start=1):
            # defaults por job
            job.setdefault("commodity", default_commodity)
            job.setdefault("container", default_container)
            job.setdefault("weight_kg", default_weight_kg)
            job.setdefault("price_owner", default_price_owner)
            job.setdefault("date_plus_days", default_date_plus)
            job["_started_at"] = datetime.now().isoformat(timespec="seconds")

            log(
                f"--- ({idx}/{len(jobs)}) {job['origin']} → {job['destination']} ---"
            )

            # valida rápido origem/destino vazios
            if is_blank(job["origin"]) or is_blank(job["destination"]):
                job["status"] = "error"
                job["message"] = "Origem/Destino vazios no Excel."
                wide_df = write_wide_row(
                    wide_df, job, breakdown=None
                )
                append_run_log("error", job, job["message"])
                save_wide_csv(wide_df, OUT_CSV)
                continue

            bd = run_one_job(page, job)

            if not bd or ("__error" in bd):
                job["status"] = "error"
                job["message"] = (bd or {}).get(
                    "__error", "Falha no fluxo/Breakdown indisponível"
                )
                wide_df = write_wide_row(
                    wide_df, job, breakdown=None
                )
                append_run_log("error", job, job["message"])
            else:
                job["status"] = "ok"
                job["message"] = ""
                wide_df = write_wide_row(
                    wide_df, job, breakdown=bd
                )
                append_run_log("ok", job, "")

            save_wide_csv(wide_df, OUT_CSV)
            time.sleep(1.0)  # respiro leve entre jobs

        log(f"✅ Batch concluído. Mantendo aberto por {keep_open}s…")
        time.sleep(keep_open)


if __name__ == "__main__":
    main()
