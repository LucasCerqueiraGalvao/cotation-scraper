# Subplan 05 - Container Apps Job and Schedule

## Status Atual (feito e pendente)

- Ultima atualizacao: 2026-03-31
- Status do subplan: `in_progress`

### Done in this cycle

- Controle global de execucao definido em `docs/execution_status.md`.
- Automacao de job/schedule preparada:
  - `infra/azure/build_and_push_image.ps1`
  - `infra/azure/configure_job_schedule.ps1`
  - `infra/azure/start_job_smoke.ps1`
  - `infra/azure/verify_job_configuration.ps1`
- Parametros operacionais externalizados via `dev.env`/`prod.env`:
  - cpu/memory
  - timeout/retry/parallelism
  - cron UTC oficial (`0 7 * * 1-5`)

### Still pending

- [ ] Executar deploy/schedule real em `dev` com credenciais Azure.
- [ ] Rodar 3 smokes manuais em `dev` e registrar historico.
- [ ] Confirmar estabilidade de 2 dias com schedule ativo.

### Blockers / info needed

- Dependente de `az login` e dados reais em `infra/azure/dev.env`.

## Objetivo

Colocar a rotina em execucao automatica no Azure Container Apps Jobs com cron oficial.

## Gate de entrada

- Subplan 04 concluido (segredos e SharePoint validados em `dev`).

## Tarefas

1. Publicar imagem validada no ACR.
2. Configurar Container Apps Job para usar a imagem correta.
3. Definir parametros de execucao:
   - CPU/memoria
   - timeout maximo
   - numero maximo de retries
4. Configurar cron no timezone oficial do projeto.
5. Configurar concorrencia para evitar overlap de execucoes.
6. Configurar politica de falha:
   - retry controlado
   - erro final com log explicito
7. Rodar 3 execucoes manuais em `dev`.
8. Habilitar schedule em `dev` por pelo menos 2 dias de validacao.

## Checkpoints de qualidade

1. Nao existe execucao concorrente no mesmo horario.
2. Tempo medio de run dentro do limite definido no Subplan 00.
3. Todos os passos do pipeline aparecem no log:
   - scrapers em paralelo
   - comparacao
   - upload

## Entregaveis

- Job agendado em `dev` com cron ativo.
- Historico minimo de execucoes com sucesso.

## Definition of Done (DoD)

- 5 execucoes consecutivas com sucesso em `dev` (manual + schedule).
- Upload SharePoint validado em todas as execucoes.
- Parametros de timeout/retry documentados.
