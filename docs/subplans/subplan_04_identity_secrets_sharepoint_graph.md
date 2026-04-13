# Subplan 04 - Identity, Secrets and SharePoint Graph

## Status Atual (feito e pendente)

- Ultima atualizacao: 2026-03-31
- Status do subplan: `in_progress`

### Done in this cycle

- Controle global de execucao definido em `docs/execution_status.md`.
- Automacao de segredos/identidade preparada:
  - `infra/azure/secret_catalog.ps1`
  - `infra/azure/seed_keyvault_secrets_from_dotenv.ps1`
  - `infra/azure/configure_job_identity_and_secrets.ps1`
- Fluxo cobre:
  - seed de segredos no Key Vault
  - atribuicao de identidade system-assigned no job
  - role assignments `Key Vault Secrets User` e `AcrPull`
  - config de `registry identity=system`
  - injecao de env vars com `secretref:*` e non-secrets operacionais

### Still pending

- [ ] Executar scripts no tenant `dev` autenticado e validar fim-a-fim.
- [ ] Confirmar permissoes Graph do app SharePoint (evitar `401/403`).
- [ ] Rodar smoke em Azure com upload SharePoint real e registrar evidencias.

### Blockers / info needed

- Necessario `az login` em tenant/subscription alvo.
- `infra/azure/dev.env` ja criado localmente, pendente apenas completar nomes/IDs reais.

## Objetivo

Configurar identidade, segredos e acesso ao SharePoint para a rotina funcionar 100% online.

## Gate de entrada

- Subplan 03 concluido (infra `dev` pronta).

## Tarefas

1. Definir principal de identidade do job (Managed Identity recomendado).
2. Conceder acesso ao Key Vault para leitura de segredos pelo job.
3. Cadastrar segredos obrigatorios no Key Vault:
   - `HL_USER`, `HL_PASS`
   - `MAERSK_USER`, `MAERSK_PASS`
   - `CMA_USER`, `CMA_PASS` (se ainda usados)
   - `SHAREPOINT_TENANT_ID`
   - `SHAREPOINT_CLIENT_ID`
   - `SHAREPOINT_CLIENT_SECRET`
   - `SHAREPOINT_SITE_ID` ou (`SHAREPOINT_HOSTNAME` + `SHAREPOINT_SITE_PATH`)
   - `SHAREPOINT_DRIVE_ID` (opcional)
   - `SHAREPOINT_FOLDER_PATH`
4. Configurar env vars de runtime no job:
   - `UPLOAD_MODE=SHAREPOINT`
   - `UPLOAD_ENSURE_ONEDRIVE=FALSE`
   - `SHAREPOINT_GRAPH_TIMEOUT_SEC`
5. Validar permissao do app no Microsoft Graph para upload/listagem no SharePoint.
6. Executar teste isolado de upload para os arquivos finais.
7. Validar leitura das planilhas manuais (`cma`, `one`, `zim`) no modo cloud.

## Testes obrigatorios

1. Teste de autenticacao Graph sem erro `401/403`.
2. Teste de upload de:
   - `comparacao_carriers_cliente.xlsx`
   - `comparacao_carriers_cliente_special.xlsx`
   - `comparacao_carriers_cliente_granito.xlsx`
3. Validacao de leitura de `one_cotations.xlsx` e `zim_cotations.xlsx` no mesmo fluxo da `cma_cotations.xlsx`.

## Entregaveis

- Job `dev` com secrets injetados via Key Vault.
- Evidencia de upload SharePoint sem usar OneDrive desktop.
- Mapa de variaveis por ambiente (`dev` e `prod`).

## Definition of Done (DoD)

- Execucao no Azure acessa todos os segredos obrigatorios.
- Upload SharePoint funciona para os tres arquivos finais.
- Nao existe segredo hardcoded em codigo, scripts ou Docker image.
