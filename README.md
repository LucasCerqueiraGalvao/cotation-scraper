# Cotation Scrapers

Pipeline para coletar cotacoes de frete, comparar carriers e gerar planilha final para cliente.

## Fluxo Atual

1. `scripts/run_daily_pipeline.cmd` chama `src/orchestration/daily_pipeline_runner.py`.
2. O runner:
   - limpa a pasta `artifacts/runtime/screens`;
   - remove logs antigos em `artifacts/logs` (retencao configuravel);
   - roda em paralelo:
     - `src/scrapers/hapag_instant_quote.py`
     - `src/scrapers/maersk_instant_quote.py`
   - roda sequencial:
     - `src/processing/quote_comparison.py`
     - `src/export/upload_fretes.py`

Observacoes importantes:
- O runner diario nao executa scraper da CMA.
- As cotacoes de `cma`, `one` e `zim` entram por planilhas manuais sincronizadas (SharePoint/OneDrive).
- A comparacao final considera `hapag`, `maersk`, `cma`, `one` e `zim`.

## Fontes por Armador

- `hapag`: scraper (`src/scrapers/hapag_instant_quote.py`) + `artifacts/output/hapag_breakdowns.csv`.
- `maersk`: scraper (`src/scrapers/maersk_instant_quote.py`) + `artifacts/output/maersk_breakdowns.csv`.
- `cma`: planilha manual (`CMA_COTATIONS_FILE`).
- `one`: planilha manual (`ONE_COTATIONS_FILE`).
- `zim`: planilha manual (`ZIM_COTATIONS_FILE`).

## Entradas e Saidas Principais

Entradas:
- `artifacts/input/maersk_jobs.xlsx`
- `artifacts/input/hapag_jobs.xlsx`
- `artifacts/input/cma_jobs.xlsx`
- `artifacts/input/destination_charges.xlsx`
- `CMA_COTATIONS_FILE` (default `artifacts/input/cma_cotations.xlsx`)
- `ONE_COTATIONS_FILE` (default `one_cotations.xlsx` na mesma pasta do CMA)
- `ZIM_COTATIONS_FILE` (default `zim_cotations.xlsx` na mesma pasta do CMA)

Saidas:
- `artifacts/output/comparacao_carriers.csv` (resultado consolidado da comparacao)
- `artifacts/output/comparacao_carriers_cliente.xlsx` (planilha cliente completa)
- `artifacts/output/comparacao_carriers_cliente_special.xlsx` (planilha cliente filtrada por destinos com `SUAPE JOBS`)
- `artifacts/output/comparacao_carriers_cliente_granito.xlsx` (planilha filtrada por `GRANITO JOBS`, com acrescimo especifico por rota)

## Regras Especiais de Destino

- Coluna `USA` em `destination_charges.xlsx`:
  - Quando `1`, ativa regra de custos adicionais de importacao na comparacao.
- Coluna `SUAPE JOBS` em `destination_charges.xlsx`:
  - Identifica destinos especiais.
  - E usada para gerar automaticamente a planilha filtrada `comparacao_carriers_cliente_special.xlsx`.
- Coluna `GRANITO JOBS` em `destination_charges.xlsx`:
  - Quando marcada, a rota sai da planilha cliente padrao e entra apenas na planilha `comparacao_carriers_cliente_granito.xlsx`.
- Coluna `GRANITO MARKUP USD` em `destination_charges.xlsx`:
  - Acrescimo em USD aplicado por rota na planilha de granito.
  - Quando vazio/invalido, usa default de `200`.

## Estrutura de Pastas

- `src/orchestration`: orquestracao do pipeline.
- `src/scrapers`: scrapers dos carriers.
- `src/processing`: regras de comparacao/consolidacao.
- `src/export`: geracao de arquivo final para cliente.
- `scripts`: automacao operacional (`.cmd` e `.ps1`).
- `artifacts/input`: planilhas de entrada.
- `artifacts/output`: CSV/XLSX gerados.
- `artifacts/logs`: logs de execucao.
- `artifacts/runtime`: cache/perfis locais dos browsers + screenshots temporarios.

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
- `ONE_COTATIONS_FILE` (default: mesma pasta de `CMA_COTATIONS_FILE`, arquivo `one_cotations.xlsx`)
- `ZIM_COTATIONS_FILE` (default: mesma pasta de `CMA_COTATIONS_FILE`, arquivo `zim_cotations.xlsx`)
- `SYNC_FOLDER` (default: `artifacts/sync_out`)
- `PLANILHA_CLIENTE_SENHA` (default: `Lucas#2001`; senha de protecao da planilha final)

Publicacao (upload do XLSX final):

- `UPLOAD_MODE` (default `SYNC`; opcoes `SYNC`, `SHAREPOINT`, `BOTH`)
- `UPLOAD_ENSURE_ONEDRIVE` (default `TRUE`; usado quando `UPLOAD_MODE` inclui `SYNC`)
- `UPLOAD_SYNC_WAIT_SEC` (default `30`; usado quando `UPLOAD_MODE` inclui `SYNC`)
- `ONEDRIVE_START_TIMEOUT_SEC` (default `30`; usado quando `UPLOAD_MODE` inclui `SYNC`)
- `SHAREPOINT_GRAPH_TIMEOUT_SEC` (default `30`)

Para upload direto no SharePoint (quando `UPLOAD_MODE=SHAREPOINT` ou `BOTH`):

- `SHAREPOINT_TENANT_ID`
- `SHAREPOINT_CLIENT_ID`
- `SHAREPOINT_CLIENT_SECRET`
- `SHAREPOINT_SITE_ID` **ou** (`SHAREPOINT_HOSTNAME` + `SHAREPOINT_SITE_PATH`)
- `SHAREPOINT_DRIVE_ID` (opcional; se vazio, usa o drive padrao do site)
- `SHAREPOINT_FOLDER_PATH` (pasta destino dentro do drive, ex.: `Ceramic Customer Freight`)
- `SHAREPOINT_TRY_CREATE_LINK` (default `TRUE`; tenta gerar link de compartilhamento apos upload)
- `SHAREPOINT_LINK_SCOPE` (default `anonymous`; opcoes `anonymous`, `organization`, `users`)
- `SHAREPOINT_LINK_TYPE` (default `view`; opcoes `view`, `edit`, `embed`)

Observacao sobre link publico (`anonymous`):
- Se o tenant/site bloquear compartilhamento anonimo, o script apenas registra aviso.
- Nao existe contorno por codigo para essa restricao; a liberacao deve ser feita na politica do Microsoft 365/SharePoint.

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
- `MAERSK_BROWSER_CHANNEL` (default `chrome`; use `bundled`/`playwright` para Chromium bundled sem canal instalado)
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
- `HAPAG_USER_DATA_DIR` (default `%LOCALAPPDATA%\\CotationScrapersRuntime\\hapag\\playwright_profiles\\hapag`)
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
- `MANUAL_QUOTES_SOURCE` (uso em preflight; `FILES` default, `GRAPH` ignora validacao de existencia local de `cma/one/zim`)

## Execucao

Execucao manual completa:

```powershell
.\.venv\Scripts\python.exe src\orchestration\daily_pipeline_runner.py
```

Preflight recomendado para ambiente cloud (valida envs/caminhos antes do run):

```powershell
.\.venv\Scripts\python.exe scripts\preflight_cloud_env.py
```

Execucao cloud-like local (sem dependencia de OneDrive desktop):

```powershell
$env:UPLOAD_MODE="SHAREPOINT"
$env:UPLOAD_ENSURE_ONEDRIVE="FALSE"
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

Observacao do wrapper:
- Resolucao de Python por prioridade: `.venv\\Scripts\\python.exe` -> `py -3` -> `python`.

Exemplo para publicar direto no SharePoint (sem depender do cliente OneDrive sincronizar):

```powershell
$env:UPLOAD_MODE="SHAREPOINT"
.\.venv\Scripts\python.exe src\export\upload_fretes.py
```

## Agendamento (Windows)

Cria/atualiza tarefa no Task Scheduler:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_weekday_task.ps1 -StartTime "04:00"
```

## Docker (Predeploy Local)

Build da imagem:

```powershell
docker build -t cotation-scrapers:local .
```

Run cloud-like rapido (sem OneDrive desktop):

```powershell
$manualPath = "C:\Users\lucas\excels\Data Analisys Team - Documentos\Ceramic Customer Freight"

docker run --rm `
  --env-file .env `
  -e UPLOAD_MODE=SHAREPOINT `
  -e UPLOAD_ENSURE_ONEDRIVE=FALSE `
  -e SYNC_BEFORE_CMA_READ=0 `
  -e CMA_COTATIONS_FILE=/manual/cma_cotations.xlsx `
  -e ONE_COTATIONS_FILE=/manual/one_cotations.xlsx `
  -e ZIM_COTATIONS_FILE=/manual/zim_cotations.xlsx `
  -e MAERSK_BROWSER_CHANNEL=bundled `
  -v "${PWD}\artifacts:/app/artifacts" `
  -v "${manualPath}:/manual:ro" `
  cotation-scrapers:local
```

## Azure Bootstrap (Subplan 03)

Preparar arquivo de ambiente:

```powershell
Copy-Item .\infra\azure\dev.env.example .\infra\azure\dev.env
```

Provisionar fundacao (RG, ACR, Log Analytics, Container Apps Env, Key Vault, Storage):

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\azure\provision_foundation.ps1 -EnvFile .\infra\azure\dev.env
```

Criar job manual (apos push da imagem no ACR):

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\azure\create_job_manual.ps1 -EnvFile .\infra\azure\dev.env -ImageTag latest
```

Pre-requisito:
- Azure CLI instalado e sessao autenticada (`az login`).

## Azure Ops (Subplans 04-08)

Sincronizar segredos para Key Vault a partir do `.env` local:

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\azure\seed_keyvault_secrets_from_dotenv.ps1 -EnvFile .\infra\azure\dev.env -DotEnvFile .\.env
```

Configurar identidade do job, RBAC, registry auth e env vars/secrets:

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\azure\configure_job_identity_and_secrets.ps1 -EnvFile .\infra\azure\dev.env
```

Build/push de imagem para ACR:

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\azure\build_and_push_image.ps1 -EnvFile .\infra\azure\dev.env
```

Configurar job agendado:

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\azure\configure_job_schedule.ps1 -EnvFile .\infra\azure\dev.env -ImageTag latest -ForceRecreate
```

Executar smoke sem esperar job completo:

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\azure\start_job_smoke.ps1 -EnvFile .\infra\azure\dev.env -NoWait
```

Rollback para tag estavel:

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\azure\rollback_job_image.ps1 -EnvFile .\infra\azure\dev.env -RollbackTag <TAG> -StartAfterRollback
```

Observabilidade baseline:

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\azure\observability\create_alerts_baseline.ps1 -EnvFile .\infra\azure\dev.env -AlertEmail "<ops@company.com>"
```

Bootstrap unico (dev) para rodar quase tudo em sequencia:

```powershell
powershell -ExecutionPolicy Bypass -File .\infra\azure\bootstrap_dev_all.ps1 -EnvFile .\infra\azure\dev.env -DotEnvFile .\.env -UseAcrBuild
```

## CI/CD (GitHub Actions)

- `CI`: `.github/workflows/ci.yml`
- `CD Dev`: `.github/workflows/cd-dev.yml`
- `CD Prod`: `.github/workflows/cd-prod.yml`

Detalhes de secrets/vars e release flow:
- `docs/cicd_release_guide.md`
