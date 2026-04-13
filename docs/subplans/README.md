# Subplans de Deploy Azure

Este diretorio organiza os subplans em ordem de execucao para levar o projeto do modo local para execucao 100% online no Azure.

## Ordem recomendada

1. `subplan_00_scope_and_decisions.md`
2. `subplan_01_code_cloud_readiness.md`
3. `subplan_02_local_docker_predeploy.md`
4. `subplan_03_azure_infra_foundation.md`
5. `subplan_04_identity_secrets_sharepoint_graph.md`
6. `subplan_05_container_apps_job_schedule.md`
7. `subplan_06_cicd_and_release_management.md`
8. `subplan_07_observability_and_runbook.md`
9. `subplan_08_go_live_hypercare_rollback.md`

## Regra operacional

- Nao comecar um subplan sem fechar o "Gate de entrada" do subplan anterior.
- Cada subplan termina com "Definition of Done (DoD)" para aprovacao objetiva.
- Sempre registrar decisoes tecnicas no mesmo dia em um changelog de deploy.
- Atualizar sempre o status de feito/pendente em:
  - `docs/execution_status.md` (status global)
  - subplan ativo (status local)

## Resultado final esperado

- Pipeline diario rodando no Azure sem depender do computador local.
- Upload SharePoint automatico dos arquivos:
  - `comparacao_carriers_cliente.xlsx`
  - `comparacao_carriers_cliente_special.xlsx`
  - `comparacao_carriers_cliente_granito.xlsx`
- Observabilidade com alertas e runbook para suporte.
