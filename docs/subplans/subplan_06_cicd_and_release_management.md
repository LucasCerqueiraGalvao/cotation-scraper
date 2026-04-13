# Subplan 06 - CI/CD and Release Management

## Status Atual (feito e pendente)

- Ultima atualizacao: 2026-03-31
- Status do subplan: `in_progress`

### Done in this cycle

- Controle global de execucao definido em `docs/execution_status.md`.
- Pipelines CI/CD criados:
  - `.github/workflows/ci.yml`
  - `.github/workflows/cd-dev.yml`
  - `.github/workflows/cd-prod.yml`
- Guia de release criado:
  - `docs/cicd_release_guide.md`
- Script de rollback operacional criado:
  - `infra/azure/rollback_job_image.ps1`

### Still pending

- [ ] Configurar secrets/vars no repositório GitHub e validar runs reais.
- [ ] Ativar approvals de ambiente `production` no GitHub.
- [ ] Executar primeiro deploy `dev` por workflow e registrar evidencias.

### Blockers / info needed

- Requer configuração de secrets no GitHub (Azure credentials/nomes de recursos).

## Objetivo

Padronizar build, versionamento e promocao de release para reduzir deploy manual e risco operacional.

## Gate de entrada

- Subplan 05 concluido em `dev`.

## Tarefas

1. Definir estrategia de branch/release:
   - `main` como fonte de producao
   - tag de versao por deploy
2. Criar pipeline CI para:
   - instalar dependencias
   - rodar checks basicos
   - build da imagem Docker
3. Criar pipeline CD para:
   - push da imagem no ACR
   - update do Container Apps Job
4. Configurar variaveis/segredos do pipeline sem expor credenciais.
5. Adicionar gates de aprovacao para deploy em `prod`.
6. Definir rollback de versao:
   - reverter tag da imagem
   - reaplicar job com imagem anterior
7. Registrar changelog de release por versao.

## Artefatos de release

1. Tag de imagem (`vYYYYMMDD-HHMM` ou semver acordado).
2. Commit hash associado.
3. Registro de quem aprovou deploy para `prod`.

## Entregaveis

- Pipeline CI/CD funcional para `dev` e `prod`.
- Processo de rollback documentado e testado.

## Definition of Done (DoD)

- Deploy para `dev` e `prod` executavel por pipeline.
- Rollback validado em teste controlado.
- Nenhum passo critico depende de operacao manual fora de runbook.
