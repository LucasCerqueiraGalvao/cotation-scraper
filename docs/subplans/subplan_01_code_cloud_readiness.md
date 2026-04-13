# Subplan 01 - Code Cloud Readiness

## Status Atual (feito e pendente)

- Ultima atualizacao: 2026-03-31
- Status do subplan: `done`

### Done in this cycle

- Controle global de execucao definido em `docs/execution_status.md`.
- Estrutura de acompanhamento local padronizada para os subplans.
- Diagnostico inicial de dependencias cloud/local executado:
  - pontos de sync/OneDrive mapeados em `quote_comparison.py` e `upload_fretes.py`
  - variaveis criticas de cloud ja identificadas (`UPLOAD_MODE`, `UPLOAD_ENSURE_ONEDRIVE`, `CMA/ONE/ZIM`)
- Script de preflight cloud adicionado:
  - `scripts/preflight_cloud_env.py`
- README atualizado com:
  - comando de preflight
  - exemplo de execucao cloud-like (`UPLOAD_MODE=SHAREPOINT`)
- Dry-run cloud-like executado com sucesso:
  - comando: `daily_pipeline_runner.py --dry-run`
  - evidencia: `artifacts/logs/20260331_112844_pipeline.log`
- Preflight cloud-like em modo SharePoint executado com sucesso:
  - comando: `UPLOAD_MODE=SHAREPOINT`, `UPLOAD_ENSURE_ONEDRIVE=FALSE` + `scripts/preflight_cloud_env.py`
  - resultado: `failures=0`, `warnings=0`
- Validacao cloud-like rapida (sem scraping completo, por decisao operacional de tempo) concluida:
  - comando: `quote_comparison.py` + `upload_fretes.py`
  - envs: `UPLOAD_MODE=SHAREPOINT`, `UPLOAD_ENSURE_ONEDRIVE=FALSE`, `SYNC_BEFORE_CMA_READ=0`
  - evidencia: `artifacts/logs/20260331_120743_cloudlike_fast_validation.log`
  - outputs gerados e publicados:
    - `comparacao_carriers_cliente.xlsx` (`linhas=253`)
    - `comparacao_carriers_cliente_special.xlsx` (`linhas=87`)
    - `comparacao_carriers_cliente_granito.xlsx` (`linhas=13`)
- Script legado ajustado para reduzir dependencia de Python local fixo:
  - arquivo: `scripts/run_daily_pipeline.cmd`
  - nova ordem de resolucao: `.venv` -> `py -3` -> `python`

### Still pending

- [ ] (Opcional) Rodar orquestrador completo em janela off-peak apenas para benchmark de duracao.

## Checklist tecnico executavel (Subplan 01)

- [x] Criar preflight cloud para validar envs/caminhos (`scripts/preflight_cloud_env.py`).
- [x] Validar preflight no ambiente atual (`failures=0`).
- [x] Atualizar README com secao de preflight + execucao cloud-like.
- [x] Executar `daily_pipeline_runner.py --dry-run` em modo cloud-like e registrar saida.
- [x] Executar ciclo cloud-like de validacao com `UPLOAD_MODE=SHAREPOINT`.
- [x] Registrar evidencias de saida dos 3 arquivos finais.
- [x] Revisar script legado `scripts/run_daily_pipeline.cmd` para reduzir dependencia de Python local.

## Objetivo

Garantir que o codigo rode em ambiente cloud sem depender de caminhos locais do Windows/OneDrive desktop.

## Gate de entrada

- Subplan 00 concluido.

## Escopo tecnico deste subplan

- `src/orchestration/daily_pipeline_runner.py`
- `src/processing/quote_comparison.py`
- `src/export/upload_fretes.py`
- Scrapers (`src/scrapers/*.py`) no que for necessario para runtime cloud.

## Tarefas

1. Auditar paths hardcoded para ambiente local e remover dependencia indevida.
2. Validar que todos os caminhos criticos aceitam env vars.
3. Validar fluxo de upload cloud-first:
   - `UPLOAD_MODE=SHAREPOINT`
   - `UPLOAD_ENSURE_ONEDRIVE=FALSE`
4. Confirmar leitura de planilhas manuais:
   - `CMA_COTATIONS_FILE`
   - `ONE_COTATIONS_FILE`
   - `ZIM_COTATIONS_FILE`
5. Garantir que os tres outputs de cliente estao no fluxo normal:
   - `comparacao_carriers_cliente.xlsx`
   - `comparacao_carriers_cliente_special.xlsx`
   - `comparacao_carriers_cliente_granito.xlsx`
6. Adicionar preflight de ambiente (script simples) para validar envs obrigatorias antes do run.
7. Revisar logs para diagnostico remoto:
   - inicio/fim de etapas
   - codigos de retorno
   - mensagens de erro objetivas
8. Atualizar README com bloco "Execucao cloud".

## Testes obrigatorios

1. Rodar `daily_pipeline_runner.py --dry-run` em ambiente limpo.
2. Rodar ciclo completo local com variaveis cloud-like.
3. Validar existencia dos 3 arquivos XLSX finais no final da execucao.

## Entregaveis

- Codigo cloud-ready sem dependencia de desktop local.
- README atualizado para modo cloud.
- Evidencia de execucao local cloud-like.

## Definition of Done (DoD)

- Todos os testes obrigatorios passaram.
- Nao existe dependencia obrigatoria de OneDrive desktop quando `UPLOAD_MODE=SHAREPOINT`.
- Logs permitem diagnostico sem acesso interativo ao host.
