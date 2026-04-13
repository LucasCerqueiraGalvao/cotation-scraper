# Subplan 00 - Scope and Decisions

## Status Atual (feito e pendente)

- Ultima atualizacao: 2026-03-31
- Status do subplan: `done`

### Done in this cycle

- Estrutura de planejamento revisada e consolidada.
- Controle central de execucao criado em `docs/execution_status.md`.
- Fase `0.5` (POC anti-bot em cloud) adicionada ao plano master para reduzir risco tecnico.
- Alinhamento de saidas finais atualizado para incluir:
  - `comparacao_carriers_cliente_granito.xlsx`
- ADR baseline criado:
  - `docs/adr/adr_0001_scope_and_ops_baseline.md`

### Still pending

- [x] Fechar plataforma primaria (`Container Apps Jobs`) com confirmacao formal.
- [x] Definir fallback oficial (`Azure VM + Task Scheduler`) com criterio de acionamento.
- [x] Definir horario oficial de execucao diaria.
- [x] Definir SLA/KPI operacional (sucesso minimo e tempo maximo de run).
- [x] Definir politica final de segredos e ownership de rotacao.
- [x] Definir estrategia final para `cma/one/zim` no cloud.
- [x] Definir estrategia de persistencia de artifacts/perfis no cloud.
- [x] Fechar matriz de ambientes (`dev`/`prod`) com escopo de recursos.

### Blockers / info needed

- Nenhum bloqueio aberto para inicio do Subplan 01.

## Decisoes Fechadas (baseline oficial)

1. Plataforma primaria: `Azure Container Apps Jobs`.
2. Fallback oficial: `Azure VM + Task Scheduler`.
3. Regra de fallback:
   - acionar com `2 falhas consecutivas` em producao
   - ou `1 falha critica` bloqueando upload SharePoint por mais de 4 horas
4. Janela oficial:
   - timezone: `America/Sao_Paulo`
   - horario: `04:00`
   - frequencia: `dias uteis (segunda a sexta)`
5. SLA/KPI:
   - sucesso em 30 dias: `>= 95%`
   - timeout maximo (hard timeout): `5h`
   - alvo operacional (p95): `<= 4h30`
6. Politica de segredos:
   - segredos somente em `Azure Key Vault`
   - sem segredo hardcoded
   - rotacao trimestral (ou imediata em incidente)
7. Estrategia para `cma/one/zim` no cloud:
   - preferencial: download via Graph a cada execucao
   - fallback: copia persistida em volume montado
8. Persistencia cloud de profiles/artifacts:
   - usar `Azure Files`
9. Matriz de ambientes:
   - `dev`: validacao tecnica e ajuste de estabilidade
   - `prod`: rotina oficial com controle de mudanca

## Objetivo

Fechar as decisoes de arquitetura e operacao antes de iniciar implementacao de infra/deploy.

## Gate de entrada

- `docs/plan_master.md` aprovado como direcao geral.
- Escopo funcional atual congelado para migracao (sem novas features no meio da migracao).

## Tarefas

1. Fechar plataforma alvo primaria: `Azure Container Apps Jobs`.
2. Definir fallback oficial: `Azure VM + Task Scheduler`.
3. Definir janela de execucao diaria (timezone e horario oficial).
4. Definir SLA de execucao:
   - sucesso diario minimo
   - tempo maximo aceitavel de pipeline
5. Definir politica de segredos:
   - tudo em Key Vault
   - zero segredo hardcoded no repositorio
6. Definir estrategia de dados manuais (`cma/one/zim`):
   - leitura via SharePoint/Graph por execucao (preferencial)
7. Definir estrategia de armazenamento de artifacts/logs:
   - persistencia minima para troubleshooting
8. Definir matriz de ambientes:
   - `dev` (validacao tecnica)
   - `prod` (rotina oficial)

## Entregaveis

- Documento de decisoes aprovado (ADR simples).
- Cron oficial definido.
- Critérios de sucesso definidos para go-live.
- Baseline de decisoes fechado neste subplan.

## Definition of Done (DoD)

- Todas as 8 tarefas fechadas e registradas.
- Time concorda com plataforma primaria, fallback, SLA e cron.
- Nao existe decisao aberta bloqueando containerizacao.
