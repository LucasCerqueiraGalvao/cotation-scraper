# Subplan 07 - Observability and Runbook

## Status Atual (feito e pendente)

- Ultima atualizacao: 2026-03-31
- Status do subplan: `in_progress`

### Done in this cycle

- Controle global de execucao definido em `docs/execution_status.md`.
- `run_id` padronizado no runtime:
  - `src/orchestration/daily_pipeline_runner.py` propaga `RUN_ID` e `PIPELINE_STAGE`
  - `src/processing/quote_comparison.py` registra metadata de runtime
  - `src/export/upload_fretes.py` registra metadata de runtime
  - evidencias:
    - `artifacts/logs/20260331_124233_runner_dryrun_after_runid.log`
    - `artifacts/logs/20260331_124243_runid_component_smoke.log`
    - `artifacts/logs/20260331_124907_docker_dryrun_after_rebuild.log`
- Runbook operacional consolidado:
  - `docs/runbook_cloud_operations.md` (status `active`)
- Baseline de observabilidade preparado:
  - `infra/azure/observability/create_alerts_baseline.ps1`
  - `infra/azure/observability/kql_queries.md`

### Still pending

- [ ] Executar criacao de alertas no Azure com action group real.
- [ ] Publicar dashboard final no workspace e anexar links no runbook.
- [ ] Validar alerta por falha simulada.

### Blockers / info needed

- Dependente de acesso Azure autenticado e email/notification target final.

## Objetivo

Criar visibilidade operacional e capacidade de resposta rapida a falhas.

## Gate de entrada

- Subplan 06 concluido (deploy padronizado).

## Tarefas

1. Padronizar logs com identificador de execucao (`run_id`) em todos os passos.
2. Garantir envio de logs do job para Log Analytics.
3. Criar alertas:
   - falha de execucao
   - timeout acima do limite
   - ausencia de execucao no horario esperado
4. Criar dashboard operacional:
   - status ultima execucao
   - taxa de sucesso 7d/30d
   - tempo medio de execucao
5. Definir trilha de troubleshooting:
   - onde ver logs
   - como validar upload SharePoint
   - como validar scrapers individualmente
6. Publicar runbook operacional com:
   - acoes em incidente
   - matriz de escalonamento
   - checklist de rollback

## KPIs minimos

1. Success rate diario.
2. Tempo medio e p95 de execucao.
3. Numero de falhas por etapa (scraper/comparacao/upload).

## Entregaveis

- Alertas ativos e testados.
- Dashboard de acompanhamento.
- Runbook final em `docs/`.

## Definition of Done (DoD)

- Time recebe alerta em falha simulada.
- Runbook permite operar sem dependencia de conhecimento tacito.
- Tempo de diagnostico inicial reduzido (alvo definido no Subplan 00).
