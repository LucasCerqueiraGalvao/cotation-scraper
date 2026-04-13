# Subplan 08 - Go-live, Hypercare and Rollback

## Status Atual (feito e pendente)

- Ultima atualizacao: 2026-03-31
- Status do subplan: `in_progress`

### Done in this cycle

- Controle global de execucao definido em `docs/execution_status.md`.
- Artefatos de go-live/hypercare preparados:
  - `docs/go_live_checklist.md`
  - `docs/hypercare_daily_log_template.md`
- Procedimento tecnico de rollback automatizavel implementado:
  - `infra/azure/rollback_job_image.ps1`
- Fluxo de rollback referenciado em runbook:
  - `docs/runbook_cloud_operations.md`

### Still pending

- [ ] Executar go-live real em `prod`.
- [ ] Registrar 7 dias de hypercare.
- [ ] Validar rollback em ambiente controlado (execucao real no Azure).

### Blockers / info needed

- Dependente de ambiente `prod` provisionado e credenciais/configuração final.

## Objetivo

Fazer entrada em producao com risco controlado, acompanhamento intensivo inicial e rollback pronto.

## Gate de entrada

- Subplans 00 a 07 concluidos.
- Ambiente `prod` provisionado e validado com ao menos 1 run manual.

## Estrategia de go-live

1. Congelar mudancas de codigo 24h antes do go-live.
2. Publicar release candidata em `prod`.
3. Rodar execucao manual de validacao em `prod`.
4. Ativar cron oficial.
5. Acompanhar primeira semana em modo hypercare.

## Checklist de validacao diaria (hypercare)

1. Job iniciou no horario correto.
2. Scrapers completaram sem erro fatal.
3. `quote_comparison` concluiu.
4. Upload SharePoint concluiu.
5. Arquivos finais presentes no destino:
   - `comparacao_carriers_cliente.xlsx`
   - `comparacao_carriers_cliente_special.xlsx`
   - `comparacao_carriers_cliente_granito.xlsx`
6. Alertas nao indicam regressao de tempo/erro.

## Criterios para rollback

1. 2 falhas consecutivas em producao.
2. Falha de upload SharePoint por mais de 1 ciclo.
3. Regressao grave sem contorno rapido.

## Procedimento de rollback

1. Suspender cron do job em `prod`.
2. Reverter imagem para ultima tag estavel.
3. Rodar execucao manual de confirmacao.
4. Reativar cron.
5. Se persistir falha, ativar fallback temporario (VM/local) conforme Subplan 00.

## Entregaveis

- Go-live executado com evidencias.
- Registro de hypercare (minimo 7 dias).
- Relatorio final com ajustes pos-go-live.

## Definition of Done (DoD)

- 7 dias consecutivos com execucao estavel em producao.
- Sem dependencia operacional do computador local.
- Processo de rollback testado e documentado.
