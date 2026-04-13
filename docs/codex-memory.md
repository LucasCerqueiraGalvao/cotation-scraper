# Codex Memory

Notas duraveis extraidas da auditoria de chats do Codex em `2026-04-11`.

Este arquivo nao substitui o `README.md` nem os runbooks existentes. Ele concentra detalhes de manutencao que apareceram de forma recorrente nas threads e continuam uteis depois que o chat some.

## Scrapers e comparacao

- A comparacao final depende de manter a planilha da CMA como entrada valida sempre que o fluxo de consolidacao ou exportacao for alterado.
- Parte da manutencao recente ficou em torno de extrair datas, transit time e free time dos cards de cotacao antes da comparacao final. Mudancas nesses campos costumam impactar `quote_comparison.py` e `upload_fretes.py`.
- O fluxo Hapag ja precisou de tuning de waits/timeouts e de um teste de paridade headed/headless. Quando o comportamento mudar no site, vale revisar os knobs de ambiente e o harness de comparacao antes de mexer no scraper principal.
- Na Maersk, logs intermediarios como `DATA | OK` nao significam cotacao final salva. Para validar sucesso real da rotina, conferir o `status` final no arquivo de saida e nao apenas etapas de preenchimento.

## Publicacao e upload

- O caminho de publicacao final ja acumulou mudancas relevantes em `upload_fretes.py`, incluindo suporte operacional ao upload direto via SharePoint Graph.
- Falhas `HTTP 423 Locked` com `resourceLocked` no Graph costumam significar arquivo aberto, checkout pendente ou lock temporario no SharePoint. Antes de tratar como bug do codigo, fechar a planilha, fazer check-in se necessario e tentar novamente com retry/backoff.

## Threads de origem

- `Usar planilha CMA na comparação`
- `Extrair datas e duração do card`
- `Clarify missing column error`
- `Adaptar maersk instant quote`
- `Explicar erro upload_fretes`
