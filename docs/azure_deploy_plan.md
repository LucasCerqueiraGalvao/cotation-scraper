# Plano de Deploy Azure (Execução 100% Online)

## Objetivo
Rodar o pipeline de cotações (`hapag`, `maersk`, comparação e upload) no ambiente Microsoft/Azure sem depender do computador local ligado.

## Status Atual (feito e pendente)
- Controle detalhado: `docs/execution_status.md`
- Estado atual:
  - `Subplans 00/01/02`: concluidos
  - `Subplans 03..08`: automacao implementada e pronta para execucao real com credenciais
- Pendente imediato:
  - `az login` no tenant alvo
  - preencher `infra/azure/dev.env`
  - executar provisionamento/segredos/schedule no Azure real

## Estado Atual (Resumo Técnico)
- Orquestração diária: `src/orchestration/daily_pipeline_runner.py`
- Scrapers: `hapag_instant_quote.py` e `maersk_instant_quote.py`
- Comparação: `quote_comparison.py`
- Export/upload SharePoint: `upload_fretes.py`
- Upload atual já suporta Graph API (sem precisar OneDrive local), via `UPLOAD_MODE=SHAREPOINT`.
- Existem planilhas manuais de preço para `cma`, `one`, `zim`.

## Arquitetura Recomendada (Alvo)
### Opção recomendada: Azure Container Apps Jobs + Docker
Motivo:
- Execução agendada nativa (cron)
- Sem manter VM ligada 24/7
- Boa integração com ACR, Key Vault e Log Analytics
- Custo menor que VM dedicada para execução periódica

Componentes:
1. `Azure Container Registry (ACR)` para imagem Docker
2. `Azure Container Apps Job` para rodar pipeline agendado
3. `Azure Key Vault` para segredos (`MAERSK_*`, `HL_*`, `CMA_*`, `SHAREPOINT_*`)
4. `Log Analytics` para logs e alertas
5. `Azure Files` (opcional/recomendado) para persistir artifacts/perfis e facilitar debug

## Alternativa de Menor Risco Inicial
### Opção fallback: Azure VM (Windows) + Task Scheduler
Motivo:
- Menor mudança de runtime (mais parecido com sua máquina atual)
- Útil como plano B caso anti-bot/headless em container fique instável

Desvantagem:
- Custo fixo maior
- Operação mais manual (patches/SO)

---

## Decisões Técnicas (fechadas)
1. Plataforma inicial:
- Selecionado: `A` Container Apps Jobs
- Fallback oficial: `B` VM Windows + Task Scheduler

2. Persistência de artefatos:
- Selecionado: `A` Azure Files

3. Planilhas manuais (`cma/one/zim`):
- Selecionado: `A` baixar do SharePoint via Graph por execução
- Fallback: `B` cópia em Azure Files

4. Frequência de execução:
- Selecionado: `dias úteis`, `04:00`, `America/Sao_Paulo`

5. Critério de fallback:
- `2 falhas consecutivas` em produção
- ou `1 falha crítica` bloqueando upload SharePoint por mais de 4 horas

---

## Fases do Projeto

## Fase 0.5 - POC anti-bot em cloud (antes de acelerar infra)
1. Executar POC curta para validar estabilidade dos scrapers fora do desktop local.
2. Medir sucesso/fracasso por etapa (login, busca, retorno de oferta).
3. Registrar resultado e decidir caminho:
- seguir com Container Apps Jobs
- ou fallback temporario em VM para go-live mais seguro

## Fase 1 - Preparação de Infra
1. Criar `Resource Group`
2. Criar `ACR`
3. Criar `Container Apps Environment`
4. Criar `Container App Job` (sem schedule final ainda)
5. Criar `Log Analytics Workspace`
6. Criar `Key Vault` e cadastrar segredos
7. (Opcional) Criar `Storage Account + File Share`

Entrega:
- Infra provisionada e acessível

## Fase 2 - Containerização
1. Criar `Dockerfile` para pipeline
2. Instalar dependências de browser/runtime no container
3. Definir `ENTRYPOINT` para `daily_pipeline_runner.py`
4. Build local + teste de execução
5. Push da imagem para ACR

Entrega:
- Imagem versionada no ACR

## Fase 3 - Integração com Segredos e Arquivos
1. Injetar segredos do Key Vault no job
2. Ajustar env vars para modo cloud:
- `UPLOAD_MODE=SHAREPOINT`
- `UPLOAD_ENSURE_ONEDRIVE=FALSE`
- `SYNC_BEFORE_CMA_READ=0` (se não houver sync local)
3. Definir estratégia de obtenção de `cma/one/zim`:
- preferencialmente download via Graph antes da comparação

Entrega:
- Job executa sem depender de pasta local do usuário

## Fase 4 - Agendamento e Observabilidade
1. Configurar cron do job
2. Configurar alertas:
- falha de execução
- tempo de execução acima do esperado
3. Definir retenção de logs
4. Criar runbook de operação

Entrega:
- Rotina totalmente automática e monitorada

---

## Itens de Código Necessários
1. Adicionar `Dockerfile`
2. Adicionar (ou ajustar) script de bootstrap cloud
3. Adicionar suporte opcional para baixar `cma/one/zim` do SharePoint via Graph antes da comparação
4. Garantir paths cloud-friendly em `artifacts` (volume/mount)
5. Adicionar documentação de deploy e rollback

---

## Riscos e Mitigações
1. Anti-bot em ambiente headless:
- Mitigação: validar POC em container; manter fallback VM

2. Dependência de sessão/perfil browser:
- Mitigação: persistir perfil em volume (Azure Files)

3. Falha em upload SharePoint por credenciais/permissões:
- Mitigação: healthcheck de credenciais e teste de upload em etapa separada

4. Mudança de layout dos sites de cotação:
- Mitigação: alertas + screenshots + logs detalhados em storage persistente

---

## Critérios de Sucesso
1. Pipeline roda diariamente no Azure sem intervenção manual
2. Arquivos finais são publicados no SharePoint:
- `comparacao_carriers_cliente.xlsx`
- `comparacao_carriers_cliente_special.xlsx`
- `comparacao_carriers_cliente_granito.xlsx`
3. Alertas de falha funcionando
4. Nenhuma dependência do PC local

---

## Estimativa (alto nível)
- Fase 1-2: 1 a 3 dias úteis
- Fase 3: 1 a 2 dias úteis
- Fase 4: 0.5 a 1 dia útil
- Total: 3 a 6 dias úteis (com margem para ajustes de anti-bot)

---

## Próximo Passo Recomendado
Executar um **POC curto de container**:
1. Subir imagem no ACR
2. Rodar um job manual no Container Apps
3. Validar um ciclo completo (comparação + upload SharePoint)
4. Se scraper tiver instabilidade em container, seguir com VM como etapa intermediária
