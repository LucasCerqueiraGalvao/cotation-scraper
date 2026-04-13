# Plan Master - Migracao para Execucao 100% Online no Azure

## Objetivo
Garantir que a rotina rode diariamente sem depender do computador local, com monitoramento, logs e upload SharePoint funcionando.

## Controle de execucao (feito e pendente)
- Fonte unica de status: `docs/execution_status.md`
- Regra: toda rodada de trabalho deve atualizar:
  - o status global (`execution_status.md`)
  - o subplan ativo

## Snapshot Atual (2026-03-31)
- Subplans concluidos: `00`, `01`, `02`
- Subplans em progresso com automacao pronta: `03`, `04`, `05`, `06`, `07`, `08`
- Bloqueio unico para execucao real Azure: autenticacao (`az login`) + preenchimento de `infra/azure/dev.env`
- Status de validacao local/cloud-like:
  - dry-run runner OK
  - comparacao/upload SharePoint OK
  - docker build + dry-run + comparacao/upload OK

## Escopo
- Scrapers: Hapag + Maersk
- Comparacao: quote_comparison
- Export e upload: upload_fretes
- Planilhas manuais: CMA, ONE, ZIM

## Decisoes Tecnicas (baseline)
1. Plataforma alvo: Azure Container Apps Jobs
2. Empacotamento: Docker
3. Segredos: Azure Key Vault
4. Logs e alertas: Log Analytics + Alerts
5. Storage de trabalho: Azure Files (recomendado para perfis/artifacts)

## Decisoes Operacionais Fechadas (2026-03-31)
1. Fallback oficial: Azure VM + Task Scheduler.
2. Regra de fallback:
   - 2 falhas consecutivas em producao, ou
   - 1 falha critica bloqueando upload SharePoint por mais de 4 horas.
3. Janela oficial:
   - timezone `America/Sao_Paulo`
   - horario `04:00`
   - dias uteis (segunda a sexta).
4. SLO/KPI:
   - sucesso em 30 dias >= 95%
   - hard timeout por execucao: 5h
   - alvo p95: <= 4h30.

## Mapa de Subplans (execucao detalhada)
1. `docs/subplans/subplan_00_scope_and_decisions.md`
2. `docs/subplans/subplan_01_code_cloud_readiness.md`
3. `docs/subplans/subplan_02_local_docker_predeploy.md`
4. `docs/subplans/subplan_03_azure_infra_foundation.md`
5. `docs/subplans/subplan_04_identity_secrets_sharepoint_graph.md`
6. `docs/subplans/subplan_05_container_apps_job_schedule.md`
7. `docs/subplans/subplan_06_cicd_and_release_management.md`
8. `docs/subplans/subplan_07_observability_and_runbook.md`
9. `docs/subplans/subplan_08_go_live_hypercare_rollback.md`

---

## Ordem de Execucao (macro)

## Fase 0 - Alinhamento e trava de escopo
1. Fechar escopo de primeira versao em producao.
2. Confirmar janela de execucao diaria (horario oficial).
3. Definir criterio de sucesso operacional.

Saida esperada:
- Escopo congelado.
- Cron definido.
- KPI de sucesso definido.

Gate para proxima fase:
- Checklist de escopo aprovado.

## Fase 0.5 - POC anti-bot em cloud (reduzir risco tecnico cedo)
1. Rodar uma POC curta em ambiente cloud controlado (manual).
2. Validar comportamento de login/navegacao para Hapag e Maersk.
3. Comparar estabilidade com baseline local.
4. Definir "go/no-go":
   - segue em Container Apps Jobs
   - ou ativa fallback temporario em VM

Saida esperada:
- Decisao tecnica baseada em evidencia para evitar retrabalho de infra.

Gate para proxima fase:
- POC registrada com recomendacao objetiva (container vs fallback).

## Fase 1 - Preparacao de codigo para cloud
1. Padronizar configuracoes por variavel de ambiente (sem dependencia de path local fixo).
2. Revisar pontos que dependem de OneDrive local.
3. Definir politica de paths temporarios para container.
4. Organizar docs de runbook basico.

Saida esperada:
- Codigo pronto para rodar em ambiente sem desktop local.

Gate para proxima fase:
- Pipeline roda localmente em modo "cloud-like" sem caminhos pessoais.

## Fase 2 - Containerizacao (base tecnica)
1. Criar Dockerfile da rotina.
2. Instalar dependencias Python e runtime dos browsers.
3. Definir comando de entrada para o runner diario.
4. Criar imagem local e validar execucao manual.

Saida esperada:
- Imagem Docker funcional localmente.

Gate para proxima fase:
- Execucao completa via container local com retorno 0.

## Fase 3 - Infra Azure
1. Criar Resource Group.
2. Criar ACR.
3. Criar Container Apps Environment.
4. Criar Container Apps Job (manual first-run).
5. Criar Log Analytics.
6. Criar Key Vault e cadastrar segredos.
7. (Opcional recomendado) Criar Azure Files e montar no job.

Saida esperada:
- Infra provisionada e acessivel.

Gate para proxima fase:
- Job manual executa no Azure sem erro de infra.

## Fase 4 - Integracao de configuracao e segredos
1. Injetar secrets do Key Vault no job.
2. Definir envs de producao:
   - `UPLOAD_MODE=SHAREPOINT`
   - `UPLOAD_ENSURE_ONEDRIVE=FALSE`
   - demais credenciais dos carriers e SharePoint
3. Validar leitura de CMA/ONE/ZIM no modo cloud.

Saida esperada:
- Job no Azure com configuracao completa.

Gate para proxima fase:
- Um ciclo completo termina com upload dos arquivos finais no SharePoint.

## Fase 5 - Agendamento e observabilidade
1. Configurar cron oficial.
2. Criar alertas de falha e timeout.
3. Definir retencao de logs.
4. Criar dashboard simples de status.

Saida esperada:
- Operacao automatica com visibilidade.

Gate para producao:
- 5 execucoes consecutivas com sucesso.

## Fase 6 - Go-live controlado
1. Ativar agenda oficial.
2. Acompanhar primeira semana com verificacao diaria.
3. Documentar incidentes e ajustes.

Saida esperada:
- Rotina estavel em operacao.

---

## Riscos Principais e Mitigacao
1. Bloqueios anti-bot em ambiente cloud:
- Mitigacao: validar POC tecnica cedo e manter plano fallback com VM.

2. Dependencia de perfil/sessao de browser:
- Mitigacao: persistencia em volume (Azure Files) + runbook de reset de perfil.

3. Falha de upload SharePoint por permissao:
- Mitigacao: teste de upload isolado por job dedicado.

4. Mudanca de layout dos sites de cotacao:
- Mitigacao: logs detalhados, screenshots e alerta rapido.

---

## Plano de rollback
1. Manter agendamento local desativado, mas pronto para reativar.
2. Se cloud falhar 2 ciclos seguidos:
   - desabilitar job no Azure
   - reativar rotina local temporariamente
   - abrir post-mortem tecnico

---

## Checklist final de sucesso
- Rotina roda sem PC local.
- Upload SharePoint gera:
  - `comparacao_carriers_cliente.xlsx`
  - `comparacao_carriers_cliente_special.xlsx`
  - `comparacao_carriers_cliente_granito.xlsx`
- Alertas de falha ativos.
- Runbook atualizado.
