# Subplan 03 - Azure Infra Foundation

## Status Atual (feito e pendente)

- Ultima atualizacao: 2026-03-31
- Status do subplan: `in_progress`

### Done in this cycle

- Controle global de execucao definido em `docs/execution_status.md`.
- Gate de entrada atendido: Subplan 02 concluido.
- Estrutura de automacao Azure criada:
  - `infra/azure/dev.env.example`
  - `infra/azure/prod.env.example`
  - `infra/azure/common.ps1`
  - `infra/azure/provision_foundation.ps1`
  - `infra/azure/create_job_manual.ps1`
  - `infra/azure/README.md`
- Script de fundacao inclui baseline de:
  - Resource Group
  - Log Analytics
  - ACR
  - Key Vault
  - Storage Account + File Share
  - Container Apps Environment
- Script de job manual inclui:
  - criacao de Container Apps Job manual
  - disparo de execucao manual inicial
  - parametrizacao de imagem via ACR/tag
- Azure CLI instalado no host:
  - `Microsoft.AzureCLI 2.84.0`
  - scripts atualizados para detectar `az.cmd` sem depender de PATH da sessao.

### Still pending

- [ ] Executar provisionamento real em `dev` usando Azure CLI autenticado.
- [ ] Validar job manual no Azure com logs no Log Analytics.

### Blockers / info needed

- Azure CLI instalado com sucesso (`2.84.0`), mas sem sessao autenticada no tenant:
  - `az account show` retornou `Please run 'az login'`.
- Arquivo `infra/azure/dev.env` foi criado localmente, mas ainda precisa ser preenchido com IDs/nomes reais do tenant/assinatura.

## Objetivo

Provisionar a infraestrutura base no Azure para executar os containers com seguranca e observabilidade.

## Gate de entrada

- Subplan 02 concluido com imagem local funcional.

## Recursos Azure (baseline)

1. Resource Group
2. Azure Container Registry (ACR)
3. Container Apps Environment
4. Container Apps Job (manual first run)
5. Log Analytics Workspace
6. Key Vault
7. Storage Account + File Share (recomendado para artifacts/perfis)

## Tarefas

1. Criar naming convention e tags padrao de recursos.
2. Provisionar Resource Group por ambiente (`dev`, `prod`).
3. Provisionar ACR e habilitar push/pull.
4. Provisionar Container Apps Environment integrado ao Log Analytics.
5. Provisionar Key Vault com politica de acesso minima.
6. Provisionar Storage Account/File Share (se aprovado no subplan 00).
7. Criar Container Apps Job em modo manual para validacao inicial.
8. Testar conectividade entre job e recursos (ACR, Key Vault, logs).

## Entregaveis

- Infra base provisionada em `dev`.
- Inventario de recursos com IDs principais.
- Evidencia de um job manual iniciado no Azure.

## Controles minimos de seguranca

1. Acesso por principio de menor privilegio.
2. Segredos somente em Key Vault.
3. Permissoes de deploy separadas de permissao de operacao.

## Definition of Done (DoD)

- Todos os recursos baseline criados em `dev`.
- Job manual consegue subir a imagem e iniciar execucao.
- Logs aparecem no Log Analytics.
