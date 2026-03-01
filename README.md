# Cotation Scrapers

Pipeline para coletar cotacoes de frete, comparar carriers e gerar planilha final para cliente.

## Fluxo Atual

1. `scripts/run_daily_pipeline.cmd` chama `src/orchestration/daily_pipeline_runner.py`.
2. O runner:
   - limpa a pasta `screens`;
   - remove logs antigos em `artifacts/logs` (retencao configuravel);
   - roda em paralelo:
     - `src/scrapers/hapag_instant_quote.py`
     - `src/scrapers/maersk_instant_quote.py`
   - roda sequencial:
     - `src/processing/quote_comparison.py`
     - `src/export/upload_fretes.py`

## Estrutura de Pastas

- `src/orchestration`: orquestracao do pipeline.
- `src/scrapers`: scrapers dos carriers.
- `src/processing`: regras de comparacao/consolidacao.
- `src/export`: geracao de arquivo final para cliente.
- `scripts`: automacao operacional (`.cmd` e `.ps1`).
- `artifacts/input`: planilhas de entrada.
- `artifacts/output`: CSV/XLSX gerados.
- `artifacts/logs`: logs de execucao.
- `screens`: screenshots de debug (limpa no inicio de cada execucao).

## Requisitos

- Python 3.10+
- Dependencias em `requirements.txt`
- Chrome instalado (Playwright usa `channel="chrome"` em partes do fluxo)

## Instalacao

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

## Variaveis de Ambiente (`.env`)

Obrigatorias (credenciais):

- `HL_USER`
- `HL_PASS`
- `MAERSK_USER`
- `MAERSK_PASS`
- `CMA_USER`
- `CMA_PASS`

Opcional para caminhos (aceita relativo ao root do projeto):

- `CMA_COTATIONS_FILE` (default: `artifacts/input/cma_cotations.xlsx`)
- `SYNC_FOLDER` (default: `artifacts/sync_out`)

Opcionais Maersk:

- `MAERSK_HEADLESS` (default `FALSE`; aceita `TRUE/FALSE`, `1/0`, `yes/no`)
- `MAERSK_LOGIN_TIMEOUT_MS` (default `60000`)
- `MAERSK_NAV_TIMEOUT_MS` (default `60000`; usado no `goto` de `HUB_URL` e `BOOK_URL`)
- `MAERSK_BOOK_IDLE_TIMEOUT_MS` (default `2500`; espera curta de `networkidle` apos abrir `/book`)
- `MAERSK_VISIT_HUB_FIRST` (default `FALSE`; se `TRUE`, navega em `HUB_URL` antes de `BOOK_URL`)
- `MAERSK_FORM_READY_TIMEOUT_MS` (default `30000`; espera o campo de origem ficar visivel)
- `MAERSK_ACTION_TIMEOUT_MS` (default `15000`; timeout padrao de interacoes)
- `MAERSK_VIEWPORT_WIDTH` (default `1366`)
- `MAERSK_VIEWPORT_HEIGHT` (default `768`)
- `MAERSK_LOCALE` (default `en-US`)
- `MAERSK_TIMEZONE` (default `America/Sao_Paulo`)
- `MAERSK_ACCEPT_LANGUAGE` (default `en-US,en;q=0.9,pt-BR;q=0.8`)
- `MAERSK_USER_AGENT` (default Chrome desktop Windows)
- `MAERSK_STEALTH` (default `TRUE`; injeta patches de fingerprint no contexto)
- `MAERSK_IGNORE_ENABLE_AUTOMATION` (default `TRUE`)
- `MAERSK_DEBUG_RETRY` (default `FALSE`; logs detalhados do botao Retry)
- `MAERSK_RESULTS_TIMEOUT_SEC` (default `45`)
- `MAERSK_OFFER_CLICK_TIMEOUT_MS` (default `1800`; timeout por tentativa de clique no CTA do offer)
- `MAERSK_OFFER_PANEL_TIMEOUT_MS` (default `4500`; espera o painel de detalhes abrir apos clique)
- `MAERSK_OFFER_CANDIDATES_PER_LOCATOR` (default `4`; limita candidatos por seletor de botao)
- `MAERSK_MAX_OFFER_PAGES_SCAN` (default `10`; paginas maximas na busca do offer ideal)
- `MAERSK_MAX_OFFER_FALLBACK_OPENS` (default `6`; tentativas maximas de fallback quando nao acha offer ideal)
- `MAERSK_COMMODITY` (default `Ceramics, stoneware`)
- `MAERSK_CONTAINER` (default `20 Dry`)
- `MAERSK_WEIGHT_KG` (default `26000`)
- `MAERSK_PRICE_OWNER` (default `I am the price owner`)
- `MAERSK_DATE_PLUS_DAYS` (default `14`)

Opcionais Hapag:

- `HAPAG_HEADLESS` (default `FALSE`; aceita `TRUE/FALSE`, `1/0`, `yes/no`)
- `HAPAG_LOGIN_TIMEOUT_MS` (default `60000`)
- `HAPAG_NAV_TIMEOUT_MS` (default `60000`)
- `HAPAG_ACTION_TIMEOUT_MS` (default `30000`)
- `HAPAG_QUOTE_WAIT_UNTIL` (default `domcontentloaded`; opcoes `load/domcontentloaded/networkidle/commit`)
- `HAPAG_QUOTE_IDLE_WAIT_MS` (default `2500`; espera curta apos abrir New Quote)
- `HAPAG_DROPDOWN_WAIT_MS` (default `8000`; tempo total para opcao de origem/destino aparecer)
- `HAPAG_DROPDOWN_POLL_MS` (default `250`; intervalo de polling no dropdown)
- `HAPAG_OFFERS_READY_TIMEOUT_MS` (default `45000`; espera pelos cards de oferta apos Search)
- `HAPAG_CARD_VISIBLE_TIMEOUT_MS` (default `20000`)
- `HAPAG_BREAKDOWN_BUTTON_TIMEOUT_MS` (default `7000`)
- `HAPAG_BREAKDOWN_PANEL_TIMEOUT_MS` (default `12000`)
- `HAPAG_BREAKDOWN_CLICK_TIMEOUT_MS` (default `5000`)
- `HAPAG_VIEWPORT_WIDTH` (default `1366`)
- `HAPAG_VIEWPORT_HEIGHT` (default `768`)
- `HAPAG_LOCALE` (default `pt-BR`)
- `HAPAG_TIMEZONE` (default `America/Sao_Paulo`)
- `HAPAG_ACCEPT_LANGUAGE` (default `pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7`)
- `HAPAG_STEALTH` (default `TRUE`)
- `HAPAG_IGNORE_ENABLE_AUTOMATION` (default `TRUE`)
- `HAPAG_AFTER_LOGIN_SLEEP_SEC` (default `2`)
- `HAPAG_KEEP_OPEN_SECS` (default `3`)
- `HAPAG_USER_DATA_DIR` (default `.pw-user-data-hapag`)
- `HAPAG_TEST_ORIGIN` (default `BRSSZ`; usado no script de teste)
- `HAPAG_TEST_DESTINATION` (default `PTLIS`; usado no script de teste)

Opcionais gerais:

- `KEEP_OPEN_SECS` (default `30`)
- `FX_API_BASE` (default `https://api.frankfurter.dev/v1/latest`)
- `SYNC_BEFORE_CMA_READ` (default `1`)
- `SYNC_WAIT_TIMEOUT_SEC` (default `60`)
- `SYNC_START_TIMEOUT_SEC` (default `20`)
- `LOG_RETENTION_DAYS` (default `14`; `0` ou negativo desativa retencao)
- `LOG_ASCII_ONLY` (default `1`; limpa terminal para ASCII e evita caracteres quebrados)

## Execucao

Execucao manual completa:

```powershell
.\.venv\Scripts\python.exe src\orchestration\daily_pipeline_runner.py
```

Simulacao sem rodar scrapers (`dry-run`):

```powershell
.\.venv\Scripts\python.exe src\orchestration\daily_pipeline_runner.py --dry-run
```

Teste dedicado da Maersk usando `MAERSK_HEADLESS`:

```powershell
.\.venv\Scripts\python.exe src\scrapers\maersk_instant_quote_headless_teste.py
```

Para forcar rota unica no teste headless:

- `MAERSK_TEST_ORIGIN` (default `Santos (Sao Paulo), Brazil`)
- `MAERSK_TEST_DESTINATION` (default `Lisbon, Portugal`)

Teste dedicado da Hapag (headless controlado por `HAPAG_HEADLESS`):

```powershell
.\.venv\Scripts\python.exe src\scrapers\hapag_instant_quote_headless_teste.py
```

Teste Hapag com headless sempre `FALSE` (baseline visual):

```powershell
.\.venv\Scripts\python.exe src\scrapers\hapag_instant_quote_headless_semprefalse_teste.py
```

Comparador de paridade headless x headed (Hapag):

```powershell
.\.venv\Scripts\python.exe src\scrapers\hapag_headless_parity_compare.py
```

Via wrapper `.cmd`:

```powershell
.\scripts\run_daily_pipeline.cmd
```

## Agendamento (Windows)

Cria/atualiza tarefa no Task Scheduler:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_weekday_task.ps1 -StartTime "04:20"
```
