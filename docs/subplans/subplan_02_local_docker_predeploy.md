# Subplan 02 - Local Docker Predeploy

## Status Atual (feito e pendente)

- Ultima atualizacao: 2026-03-31
- Status do subplan: `done`

### Done in this cycle

- Controle global de execucao definido em `docs/execution_status.md`.
- Gate de entrada atendido: Subplan 01 concluido.
- Base de containerizacao criada:
  - `Dockerfile`
  - `.dockerignore`
- Dependencias de runtime revisadas em `requirements.txt`:
  - `pandas`, `openpyxl`, `requests` adicionados para compatibilidade de container.
- Scraper Maersk preparado para ambiente container sem canal Chrome instalado:
  - nova env `MAERSK_BROWSER_CHANNEL` (`bundled`/`playwright` para usar Chromium bundled).
- Build local da imagem executado com sucesso:
  - comando: `docker build -t cotation-scrapers:local .`
  - resultado: imagem `cotation-scrapers:local` criada.
- Sanidade de execucao no container validada sem scraping pesado:
  - comando: `docker run --rm cotation-scrapers:local python src/orchestration/daily_pipeline_runner.py --dry-run`
  - resultado: exit code `0` e pipeline dry-run concluido.
  - evidencia: `artifacts/logs/20260331_122001_docker_dryrun.log`
- Validacao cloud-like com geracao real de artefatos no container concluida:
  - comando: `docker run` (sem scrapers) para `quote_comparison.py` + `upload_fretes.py`
  - envs: `UPLOAD_MODE=SHAREPOINT`, `UPLOAD_ENSURE_ONEDRIVE=FALSE`, `SYNC_BEFORE_CMA_READ=0`
  - mounts:
    - `${PWD}\\artifacts:/app/artifacts`
    - `C:\\Users\\lucas\\excels\\Data Analisys Team - Documentos\\Ceramic Customer Freight:/manual:ro`
  - evidencia: `artifacts/logs/20260331_121852_docker_cloudlike_fast_validation.log`
  - outputs gerados/publicados:
    - `comparacao_carriers_cliente.xlsx` (`linhas=253`)
    - `comparacao_carriers_cliente_special.xlsx` (`linhas=87`)
    - `comparacao_carriers_cliente_granito.xlsx` (`linhas=13`)

### Still pending

- [ ] (Opcional) Rodar pipeline completo com scrapers dentro do container para benchmark de duracao/anti-bot.

## Objetivo

Empacotar a rotina em Docker e validar localmente de ponta a ponta antes de subir para Azure.

## Gate de entrada

- Subplan 01 concluido.

## Tarefas

1. Criar `Dockerfile` com base Python e dependencias do projeto.
2. Criar `.dockerignore` para reduzir tamanho da imagem e evitar vazamento de arquivos locais.
3. Definir estrategia de volume para `artifacts` durante testes locais.
4. Instalar dependencias de browser no container (Playwright e libs de sistema).
5. Garantir execucao do entrypoint de producao:
   - `python src/orchestration/daily_pipeline_runner.py`
6. Validar env vars injetadas por `--env-file`/`-e` (sem copiar `.env` para imagem).
7. Rodar pipeline completo no container.
8. Confirmar outputs finais e logs.
9. Taggear imagem com versao reprodutivel.

## Comandos base (modelo)

```powershell
docker build -t cotation-scrapers:local .
```

```powershell
docker run --rm `
  --env-file .env `
  -e UPLOAD_MODE=SHAREPOINT `
  -e UPLOAD_ENSURE_ONEDRIVE=FALSE `
  -v "${PWD}\artifacts:/app/artifacts" `
  cotation-scrapers:local
```

## Verificacoes obrigatorias

1. Container conclui com exit code `0`.
2. Arquivos gerados:
   - `artifacts/output/comparacao_carriers_cliente.xlsx`
   - `artifacts/output/comparacao_carriers_cliente_special.xlsx`
   - `artifacts/output/comparacao_carriers_cliente_granito.xlsx`
3. Nao ha segredo embedado em camada da imagem.

## Riscos

1. Dependencia de browser/channel no container.
2. Comportamento anti-bot diferente do host local.
3. Permissao de escrita em mounts de artifacts.

## Mitigacao

1. Validar browser com teste curto antes do full run.
2. Persistir logs/screenshots para comparacao.
3. Ajustar timeout/retry somente apos medir falha real.

## Definition of Done (DoD)

- Build local reproduzivel.
- Run completo dentro do container sem dependencia do host fora de envs e volume.
- Evidencia de artefatos finais e logs.
