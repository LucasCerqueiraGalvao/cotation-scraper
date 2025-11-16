# cma_instant_quote_batch.py
import os
import csv
from datetime import date, timedelta, datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PWTimeout,
)

# ----------------------------------------------------------------------
# Caminhos
# ----------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent

INPUT_JOBS = ROOT_DIR / "artifacts" / "input" / "cma_jobs.xlsx"

CSV_OUT_DIR = ROOT_DIR / "artifacts" / "output"
CSV_OUT_DIR.mkdir(parents=True, exist_ok=True)
CSV_FILE = CSV_OUT_DIR / "cma_breakdowns.csv"

# Pasta fixa de cache/perfil do Playwright
USER_DATA_DIR = ROOT_DIR / ".pw-user-data-cma"
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

# ----------------------------------------------------------------------
# Login CMA
# ----------------------------------------------------------------------
LOGIN_URL = (
    "https://auth.cma-cgm.com/as/authorization.oauth2"
    "?client_id=webapp-must"
    "&redirect_uri=https%3A%2F%2Fwww.cma-cgm.com%2Fsignin-oidc"
    "&response_type=code"
    "&scope=email%20openid%20profile%20Ecom%3Awebapp-must-apl-anl-cnc"
    "%20ans%3Afe%3Aread%20ans%3Afe%3Awrite"
    "&code_challenge=G-quk988U40u5cg0_02rRVUJskUp6y7JupTeeydjbYM"
    "&code_challenge_method=S256"
    "&state=OpenIdConnect.AuthenticationProperties%3DxnUawSvQyga4RKs359_1cVHw5I2RZF22N-Tfl-3z1nbxMZo9eZKrADXecbhTNSR2yGv-dStVRN5U_jxPzdbY6evgrMmmrEWkJvu87ErsNIsEVDYyEkpbW-_U17cWiTMMV5Zj9Ru6oumhcqAYZ8smQFHCUH7z8gtJnlTrXx28omYDVssPvvAw2zEmoIfDJNJVtiV33k4t86KGd5GFogaSh-E693VQqnttDIBtkRF9UL-WFYNdho66s1bY0zrAoEqWnKCAz7YeBMB6EEAsvvHhNzKX1giIRuMiuQ5vjj1npAbG0cxZF1qLx1f6N3OnGwsM%26Language%3Den-US%26actas%3Dfalse"
    "&response_mode=form_post"
    "&x-client-SKU=ID_NET472"
    "&x-client-ver=6.27.0.0"
)

INSTANT_URL = "https://www.cma-cgm.com/ebusiness/pricing/instant-Quoting"

SEL_EMAIL  = "input#login-email"
SEL_PASS   = "input#login-password"
SEL_SUBMIT = 'button[type="submit"]'

# ----------------------------------------------------------------------
# Selectors da tela de Instant Quoting
# ----------------------------------------------------------------------
# ORIGEM / DESTINO
SEL_ORIGIN_INPUT   = '#sortedAutocompleteWrapper-origin-field input[name="Origin"]'
SEL_ORIGIN_OPTION1 = '#sortedAutocompletePopup-origin-field li.place-suggestion:first-child'

SEL_DEST_INPUT     = '#sortedAutocompleteWrapper-destination-field input[name="Origin"]'
SEL_DEST_OPTION1   = '#sortedAutocompletePopup-destination-field li.place-suggestion:first-child'

# DATA
SEL_DEPARTURE_INPUT = "#DepartureFrom"

# CONTAINER 20' DRY STANDARD - botão "Adicionar"
SEL_ADD_20DRY = "li:has(.ico-20st) button.add-button"

# PESO POR CONTAINER
SEL_WEIGHT_INPUT = "#TxtWeight span[name='weightPerContainer'] input"

# MERCADORIA (campo visível)
SEL_COMMODITY_INPUT = "#DdlCommodity"

# BOTÃO OBTER COTAÇÃO
SEL_SEARCH_QUOTE = "#SearchQuote"

# RESULTADOS: primeiro botão "Detalhes"
SEL_DETAILS_FIRST = (
    "article.card-route-horizontal label.o-button.primary-ghost:has-text('Detalhes')"
)

# TABELA DE RATE
SEL_RATE_TABLE_ROWS = (
    "div.rate-wrapper table.el-table__body tbody tr.el-table__row"
)
SEL_RATE_TOTAL_PRICE = "div.rate-wrapper table.footer div.price.current"
SEL_RATE_TOTAL_CURRENCY = "div.rate-wrapper table.footer div.price.current span.currency"


# ----------------------------------------------------------------------
# Utilidades de CSV
# ----------------------------------------------------------------------
def load_previous_records() -> dict:
    """
    Lê o CSV existente (se houver) e devolve um dict {key: row_dict}.
    Aqui a key é ORIGEM-DESTINO (sem data), representando o 'lead'.
    """
    records = {}
    if CSV_FILE.exists():
        with CSV_FILE.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if "key" in row and row["key"]:
                    records[row["key"]] = row
    return records


def write_all_records(records: dict):
    """
    Escreve todos os records no CSV, substituindo o arquivo.
    Garante ordem: colunas fixas + dinâmicas.
    Chamado após CADA job, pra manter o CSV sempre atualizado.
    """
    if not records:
        return

    # Coleta todas as colunas usadas
    all_fields = set()
    for row in records.values():
        all_fields.update(row.keys())

    fixed_cols = [
        "key",
        "origin",
        "destination",
        "last_attempt_at",
        "quoted_at",
        "status",
        "message",
        "total_all_in",
        "total_currency",
    ]
    dynamic_cols = [c for c in all_fields if c not in fixed_cols]
    fieldnames = fixed_cols + sorted(dynamic_cols)

    with CSV_FILE.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for key in sorted(records.keys()):
            writer.writerow(records[key])


def parse_iso(dt_str: str):
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str)
    except Exception:
        return None


def build_sorted_jobs_from_excel_and_records(df: pd.DataFrame, records: dict):
    """
    Lê ORIGEM / PORTO DE DESTINO do Excel e retorna uma lista de (origin, dest)
    ordenada por prioridade:

    1) Primeiro leads que já tiveram sucesso (status=success), ordenados pelo quoted_at mais antigo.
    2) Depois leads sem sucesso, ordenados pelo last_attempt_at mais antigo.
    3) Leads sem registro ainda entram no grupo 2, com last_attempt_at "muito antigo"
       (pra serem tentados cedo entre os que nunca deram sucesso).
    """
    jobs_raw = []
    for _, row in df.iterrows():
        origin = str(row["ORIGEM"]).strip()
        dest = str(row["PORTO DE DESTINO"]).strip()
        if not origin or origin.lower() == "nan":
            continue
        if not dest or dest.lower() == "nan":
            continue
        jobs_raw.append((origin, dest))

    def priority_for_job(job):
        origin, dest = job
        key = f"{origin}-{dest}"
        rec = records.get(key)

        # Flag de sucesso prévio
        if rec and rec.get("status") == "success" and rec.get("quoted_at"):
            has_success_flag = 0  # 0 = tem sucesso, 1 = não tem
            quoted_dt = parse_iso(rec.get("quoted_at")) or datetime.min
        else:
            has_success_flag = 1
            # sem sucesso -> joga quoted_dt pro futuro pra eles virem depois dos com sucesso
            quoted_dt = datetime.max

        # Segundo critério: last_attempt_at (mais antigo primeiro)
        if rec and rec.get("last_attempt_at"):
            last_attempt_dt = parse_iso(rec.get("last_attempt_at")) or datetime.min
        else:
            # nunca tentou -> considera bem antigo, pra ter prioridade dentro do grupo
            last_attempt_dt = datetime.min

        return (has_success_flag, quoted_dt, last_attempt_dt)

    jobs_sorted = sorted(jobs_raw, key=priority_for_job)
    return jobs_sorted


# ----------------------------------------------------------------------
# Login / navegação
# ----------------------------------------------------------------------
def login_cma(page):
    """
    Faz login na CMA no próprio page e, ao final, vai para a tela de Instant Quoting.
    Se já estiver logado e o formulário não aparecer, apenas segue para a tela de cotação.
    """
    load_dotenv()
    email = os.getenv("CMA_USER")
    password = os.getenv("CMA_PASS")

    if not email or not password:
        raise RuntimeError("CMA_USER e/ou CMA_PASS não definidos no .env")

    print("[CMA] Abrindo página de login...")
    page.goto(LOGIN_URL, timeout=90_000)

    try:
        # tenta achar o formulário de login; se não achar, assume que já está logado
        page.wait_for_selector(SEL_EMAIL, timeout=15_000)
        page.fill(SEL_EMAIL, email)
        page.fill(SEL_PASS, password)
        print("[CMA] Enviando formulário de login...")
        page.click(SEL_SUBMIT)

        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(5_000)
        print("[CMA] Login efetuado. Indo para Instant Quoting...")
    except PWTimeout:
        print("[CMA] Campo de login não apareceu; possivelmente já logado. Indo direto para Instant Quoting...")

    page.goto(INSTANT_URL, timeout=90_000)
    page.wait_for_load_state("networkidle")


def ensure_instant_form(page) -> bool:
    """
    Garante que estamos na tela de Instant Quoting.
    Se não achar o campo de origem, tenta refazer login.
    Retorna True se conseguiu, False se falhou.
    """
    try:
        page.wait_for_selector(SEL_ORIGIN_INPUT, timeout=5_000)
        return True
    except PWTimeout:
        # tenta login de novo
        try:
            print("[CMA] Formulário não encontrado. Refazendo login...")
            login_cma(page)
            page.wait_for_selector(SEL_ORIGIN_INPUT, timeout=10_000)
            return True
        except Exception as e:
            print(f"[CMA] Erro ao tentar garantir formulário: {e}")
            return False


def try_open_first_details(page) -> bool:
    """
    Após clicar em 'Obter minha cotação', tenta abrir o primeiro Detalhes.
    Retorna True se conseguiu, False se não havia detalhes (sem cotação).
    Timeouts mais curtos pra não travar quando não tem rota.
    """
    try:
        # tenta esperar a lista de resultados
        page.wait_for_selector("ul.results-list", timeout=10_000)
    except PWTimeout:
        # nem lista de resultados apareceu -> provavelmente sem cotação
        return False

    details_loc = page.locator(SEL_DETAILS_FIRST)
    if details_loc.count() == 0:
        return False

    details_btn = details_loc.first
    details_btn.scroll_into_view_if_needed()
    try:
        details_btn.click(timeout=4_000)
    except PWTimeout:
        return False

    return True


def parse_rate_table(page, base_record: dict) -> dict:
    """
    Lê a tabela de rate (aba 'rate') e devolve o record atualizado com:
      - colunas de cada tipo de cobrança (Frete Marítimo, etc.)
      - total_all_in, total_currency
    """
    record = base_record.copy()

    rows = page.locator(SEL_RATE_TABLE_ROWS)
    try:
        n_rows = rows.count()
    except Exception:
        n_rows = 0

    print(f"[CMA] Linhas de cobranças encontradas: {n_rows}")

    for i in range(n_rows):
        row = rows.nth(i)
        try:
            charge_name = (
                row.locator("td:nth-child(2) span.charges-detail")
                .inner_text()
                .strip()
            )
        except Exception:
            continue

        amount_text = (
            row.locator("td:nth-child(3) span")
            .inner_text()
            .strip()
        )
        currency_text = (
            row.locator("td:nth-child(5) .el-tooltip__trigger")
            .inner_text()
            .strip()
        )

        try:
            amount_value = float(amount_text.replace(" ", "").replace(",", ""))
        except ValueError:
            amount_value = amount_text

        # nome da coluna = texto da cobrança
        record[charge_name] = amount_value
        # (se quiser moeda por cobrança, pode criar colunas extras aqui)

    # total all in
    try:
        total_text = (
            page.locator(SEL_RATE_TOTAL_PRICE)
            .inner_text()
            .strip()
        )
        total_num_str = total_text.split()[0]
        try:
            total_value = float(total_num_str.replace(" ", "").replace(",", ""))
        except ValueError:
            total_value = total_text

        record["total_all_in"] = total_value

        total_currency = (
            page.locator(SEL_RATE_TOTAL_CURRENCY)
            .inner_text()
            .strip()
        )
        record["total_currency"] = total_currency
    except Exception:
        # se não achar, deixa como está
        pass

    return record


# ----------------------------------------------------------------------
# Fluxo principal
# ----------------------------------------------------------------------
def run_batch(headless: bool = False):
    # Lê registros anteriores (pra saber prioridade e manter histórico)
    records = load_previous_records()

    # Lê jobs do Excel
    df = pd.read_excel(INPUT_JOBS)

    # Normaliza colunas esperadas
    if "ORIGEM" not in df.columns or "PORTO DE DESTINO" not in df.columns:
        raise ValueError("Excel precisa ter colunas 'ORIGEM' e 'PORTO DE DESTINO'.")

    # Ordena jobs com base no CSV de saída (prioridade)
    jobs = build_sorted_jobs_from_excel_and_records(df, records)
    print(f"[CMA] Total de jobs carregados do Excel: {len(jobs)}")

    with sync_playwright() as p:
        # Contexto persistente com user_data_dir fixo (.pw-user-data-cma)
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=headless,
        )
        page = context.new_page()

        # login inicial
        login_cma(page)

        for idx, (origin, dest) in enumerate(jobs, start=1):
            print(f"\n[CMA] ==== Job {idx}/{len(jobs)}: {origin} -> {dest} ====")

            # chave única por lead (origem-destino)
            now_iso = datetime.utcnow().isoformat()
            key = f"{origin}-{dest}"

            # Record base: se já existir, começamos dele (pra manter valores antigos em caso de erro)
            base_record = records.get(key, {}).copy()
            base_record.setdefault("key", key)
            base_record["origin"] = origin
            base_record["destination"] = dest
            base_record["last_attempt_at"] = now_iso
            # quoted_at só será atualizado em caso de sucesso
            base_record.setdefault("quoted_at", "")

            # Data-alvo: hoje + 7
            target_date = date.today() + timedelta(days=7)
            date_str = target_date.strftime("%d/%m/%Y")

            # Garante que estamos na tela de instant quoting
            if not ensure_instant_form(page):
                # erro de login / form indisponível
                base_record["status"] = "error"
                base_record["message"] = "Não foi possível carregar formulário de cotação (login falhou)."
                records[key] = base_record
                print("[CMA] Erro: formulário não disponível, seguindo para próximo job.")

                # atualiza CSV imediatamente
                write_all_records(records)
                continue

            try:
                # Limpa e preenche origem
                page.fill(SEL_ORIGIN_INPUT, "")
                page.click(SEL_ORIGIN_INPUT)
                page.fill(SEL_ORIGIN_INPUT, origin)
                page.wait_for_selector(SEL_ORIGIN_OPTION1, timeout=30_000)
                page.click(SEL_ORIGIN_OPTION1)

                # Limpa e preenche destino
                page.fill(SEL_DEST_INPUT, "")
                page.click(SEL_DEST_INPUT)
                page.fill(SEL_DEST_INPUT, dest)
                page.wait_for_selector(SEL_DEST_OPTION1, timeout=30_000)
                page.click(SEL_DEST_OPTION1)

                print(f"[CMA] Origem/Destino preenchidos: {origin} -> {dest}")

                # DATA: hoje + 7 dias
                page.wait_for_selector(SEL_DEPARTURE_INPUT, timeout=30_000)
                page.click(SEL_DEPARTURE_INPUT)
                page.fill(SEL_DEPARTURE_INPUT, date_str)
                page.keyboard.press("Tab")
                print(f"[CMA] Data de partida = {date_str}")

                # CONTAINER: 20ST Adicionar
                page.wait_for_selector(SEL_ADD_20DRY, timeout=30_000)
                page.click(SEL_ADD_20DRY)
                print("[CMA] Container 20ST adicionado.")

                # PESO: 26000
                page.wait_for_selector(SEL_WEIGHT_INPUT, timeout=30_000)
                page.fill(SEL_WEIGHT_INPUT, "26000")
                print("[CMA] Peso = 26000 KGM.")

                # MERCADORIA: FAK
                page.wait_for_selector(SEL_COMMODITY_INPUT, timeout=30_000)
                page.click(SEL_COMMODITY_INPUT)
                page.wait_for_timeout(500)
                fak_option = page.locator(
                    "div.el-select__popper[aria-hidden='false'] "
                    "li.el-select-dropdown__item",
                    has_text="FAK",
                )
                fak_option.first.wait_for(state="visible", timeout=30_000)
                fak_option.first.click()
                print("[CMA] Mercadoria FAK selecionada.")

                # Obter cotação
                page.wait_for_selector(SEL_SEARCH_QUOTE, timeout=30_000)
                page.click(SEL_SEARCH_QUOTE)
                print("[CMA] 'Obter minha cotação' clicado.")

                page.wait_for_load_state("networkidle")

                # Tentar abrir primeiros detalhes
                has_details = try_open_first_details(page)
                if not has_details:
                    # sem cotação
                    base_record["status"] = "no_quote"
                    base_record["message"] = "Nenhuma cotação SPOT encontrada (sem botão Detalhes)."
                    records[key] = base_record
                    print("[CMA] Nenhuma cotação encontrada para este par. Indo para próximo job.")

                    # volta para tela principal
                    try:
                        page.goto(INSTANT_URL, timeout=90_000)
                        page.wait_for_load_state("networkidle")
                    except Exception:
                        pass

                    # atualiza CSV imediatamente
                    write_all_records(records)
                    continue

                print("[CMA] Detalhes da rota abertos. Lendo tabela de rate...")

                # Espera tabela de rate e parseia
                page.wait_for_selector(SEL_RATE_TABLE_ROWS, timeout=60_000)
                record_ok = parse_rate_table(page, base_record)
                record_ok["status"] = "success"
                record_ok["message"] = ""
                record_ok["quoted_at"] = now_iso

                records[key] = record_ok
                print("[CMA] Cotação lida e registrada com sucesso.")

                # Volta para tela principal para próximo job
                try:
                    page.goto(INSTANT_URL, timeout=90_000)
                    page.wait_for_load_state("networkidle")
                except Exception:
                    pass

            except Exception as e:
                # qualquer erro nessa rota -> marca como error, mantendo valores antigos se houver
                base_record["status"] = "error"
                base_record["message"] = f"Erro durante cotação: {e}"
                records[key] = base_record
                print(f"[CMA] Erro durante job {origin}->{dest}: {e}")

                # tenta voltar para tela principal pra não travar próximo job
                try:
                    page.goto(INSTANT_URL, timeout=90_000)
                    page.wait_for_load_state("networkidle")
                except Exception:
                    pass

            # >>> AQUI: após CADA job, escreve o CSV atualizado <<<
            write_all_records(records)

        context.close()

    print(f"\n[CMA] Processamento concluído. CSV atualizado em: {CSV_FILE}")


if __name__ == "__main__":
    run_batch(headless=False)
