# ADR 003 — Subprocesso supervisionado e IPC JSONL versionado

**Status:** Accepted  
**Data:** 24 out. 2026

## Contexto

Treinos MLX podem consumir horas, memória e disco, travar em código nativo ou imprimir logs não estruturados. Chamar funções Python embutidas no processo Rust ampliaria o blast radius; interpretar stdout do `mlx-lm` diretamente tornaria progresso e erros dependentes de texto humano. Um serviço de rede permanente é custo desnecessário para execução local.

## Decisão

Cada tentativa ML roda em subprocesso Python supervisionado pelo Rust. stdin e stdout carregam JSONL UTF-8 no schema `academy.worker.v1`; stderr é exclusivamente log humano. Há handshake de versão, `request_id`, sequência monotônica, limite de linha, mensagens `start`, `progress`, `artifact`, `result`, `error`, `cancel` e `cancelled`.

O supervisor controla PID, cwd, ambiente mínimo, tempo, memória observável, heartbeat, sinais e diretórios concedidos. Artifacts são escritos em staging da tentativa e só entram no CAS depois de verificação no Rust. Cancelamento escala de mensagem cooperativa para `SIGTERM` e `SIGKILL`.

## Alternativas consideradas

- **Bindings FFI/PyO3:** baixa latência, mas falha nativa e GIL compartilham o processo de controle.
- **gRPC/HTTP localhost:** contratos fortes, porém exige servidor, porta, lifecycle e segurança adicionais.
- **Invocar CLI e fazer regex em stdout:** rápido para protótipo, sem estabilidade nem erros tipados.
- **Arquivos de progresso:** polling e risco de escrita parcial; não resolve comandos ou heartbeat.

## Consequências

- Falha ML não derruba a API.
- Fixtures simples permitem replay e depuração.
- JSONL não é ideal para payload binário; arquivos são referenciados por hash/caminho concedido.
- Mudança incompatível exige `academy.worker.v2`; mudanças aditivas permanecem na v1.
- O supervisor precisa drenar stdout/stderr para evitar deadlock.

## Validação

- Corpus de golden lines é aceito igualmente pelos parsers Rust e Python.
- Fuzzing cobre linha truncada, UTF-8 inválido, 1 MiB excedido, sequência duplicada e tipo desconhecido.
- Testes comprovam cancelamento cooperativo e escalado, sem processo órfão.
- Um artifact com caminho fora do grant ou hash incorreto é rejeitado.
- Worker v2 conectado a supervisor v1 falha no handshake antes de iniciar treino.
