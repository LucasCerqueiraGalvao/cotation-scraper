# Subplan - Preparar Ambiente Local em Docker para Deploy

> Nota: este arquivo foi mantido por compatibilidade. A versao oficial atual esta em:
> `docs/subplans/subplan_02_local_docker_predeploy.md`.

## Status Atual (feito e pendente)

- Ultima atualizacao: 2026-03-31
- Status deste arquivo: `legacy_reference`
- Execucao ativa: acompanhar em `docs/subplans/subplan_02_local_docker_predeploy.md` e `docs/execution_status.md`.

## Objetivo
Transformar o projeto atual em um pacote Docker confiavel para subir no Azure sem surpresas.

## Resultado esperado
- Container roda o pipeline completo localmente.
- Build reproduzivel.
- Configuracao pronta para push em ACR.

---

## Etapa 1 - Pre-check tecnico local
1. Confirmar versoes locais:
   - Docker Desktop
   - Python
2. Confirmar que pipeline atual roda fora do Docker (baseline).
3. Congelar dependencias se necessario (`requirements.txt` revisado).

Critero de saida:
- Baseline local funcionando.

## Etapa 2 - Estrutura de container
1. Criar `Dockerfile`.
2. Criar `.dockerignore`.
3. Definir estrategia para:
   - arquivos de entrada (`artifacts/input`)
   - logs/output (`artifacts/output`, `artifacts/logs`)
4. Decidir se `artifacts` sera bind mount local para testes.

Critero de saida:
- Imagem builda sem erro.

## Etapa 3 - Runtime de browser no container
1. Instalar dependencias de sistema para Playwright.
2. Garantir browser/canal suportado no container.
3. Validar modo headless conforme usado em producao.
4. Validar performance minima.

Critero de saida:
- Scrapers iniciam e navegam dentro do container.

## Etapa 4 - Configuracao por ambiente
1. Remover dependencia de `.env` local no build.
2. Padronizar execucao com env vars externas (`docker run -e ...`).
3. Criar template `.env.example` para cloud.
4. Validar:
   - SharePoint credenciais
   - CMA/ONE/ZIM paths

Critero de saida:
- Container roda somente com variaveis injetadas.

## Etapa 5 - Teste de ciclo completo em Docker local
1. Rodar pipeline completo via container.
2. Conferir outputs:
   - `comparacao_carriers.csv`
   - `comparacao_carriers_cliente.xlsx`
   - `comparacao_carriers_cliente_special.xlsx`
   - `comparacao_carriers_cliente_granito.xlsx`
3. Validar upload SharePoint em ambiente de teste.

Critero de saida:
- Ciclo fim-a-fim OK.

## Etapa 6 - Hardening para deploy
1. Definir tag de imagem por versao (ex.: `vYYYYMMDD-HHMM`).
2. Adicionar health checks e timeout de execucao.
3. Garantir logs claros para diagnostico.
4. Documentar comandos de build/run/tag/push.

Critero de saida:
- Imagem pronta para ACR.

---

## Comandos base (modelo)
## Build
```powershell
docker build -t cotation-scrapers:local .
```

## Run (exemplo)
```powershell
docker run --rm `
  --env-file .env `
  -v "${PWD}\\artifacts:C:\\app\\artifacts" `
  cotation-scrapers:local
```

Observacao:
- Ajustar paths Linux/Windows conforme imagem final.
- Em Azure Container Apps, o padrao sera injetar secrets/env sem `.env` local.

---

## Riscos locais antes do upload
1. Incompatibilidade de browser no container.
2. Dependencia de path Windows hardcoded.
3. Permissao de escrita em pastas de artifacts.
4. Segredos expostos em imagem por engano.

Mitigacoes:
- Teste em ambiente limpo.
- Revisao de env vars obrigatorias.
- Nao copiar `.env` para dentro da imagem.

---

## Definicao de pronto para subir no Azure
- Build reproduzivel.
- Execucao local em Docker sem erro.
- Upload SharePoint validado.
- Documentacao de operacao atualizada.
