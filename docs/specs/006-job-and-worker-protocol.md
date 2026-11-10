# Especificação 006 — Jobs e protocolo de worker

**Status:** normativa v1.

## Propósito e escopo

Define fila PostgreSQL, leases, tentativas e IPC JSONL entre o plano de controle e subprocessos sem autoridade de domínio.

## Entidades e tipos

- `Job`: projeto, tipo, payload versionado, prioridade, estado, tentativas e política de retry.
- `Attempt`: número, owner token, PID, grants, timestamps e resultado.
- `Lease`: owner e expiração; heartbeat a cada 10 s, duração inicial 30 s.
- `JobRequest` e `JobEvent`: contratos JSON versionados; `request_id`, `job_id`, `attempt`.

## Máquina de estados

`queued → leased → running → succeeded`; de `running` para `retry_wait → queued`, `cancelling → cancelled` ou `failed`. Estados terminais não reabrem. Tentativas são monotônicas.

## Invariantes

1. PostgreSQL é fonte de verdade; claim usa `FOR UPDATE SKIP LOCKED`.
2. Worker não recebe credencial de banco nem decide estado final, aprovação ou promoção.
3. Cada tentativa tem cwd e grants próprios; input é read-only e output é staging.
4. JSONL é UTF-8, uma mensagem por linha, máximo 1 MiB; stderr não é protocolo.
5. `seq` é monotônico; duplicata idêntica é ignorada após persistência.
6. Evento é persistido antes do efeito.
7. Somente erros transitórios e jobs idempotentes recebem retry automático.

## API e eventos

- `POST /training-jobs`, `GET /jobs/{id}`, `POST /jobs/{id}:cancel`.
- SSE `/jobs/{id}/events`, IDs monotônicos e retomada por `Last-Event-ID`.
- Handshake `hello/ready`; comandos `start|cancel|ping`; saídas `accepted|progress|log|checkpoint|artifact|result|error|cancelled`.

## Autorização e privacidade

API valida projeto e capacidade. Supervisor fornece ambiente mínimo, sem secrets. Logs são redigidos; artifacts precisam estar dentro do grant e do projeto. SSE não expõe payload sensível nem traceback.

## Semântica de falha

Linha inválida, >1 MiB, UTF-8 inválido, sequência regressiva, versão incompatível ou caminho fora do grant mata a tentativa e falha sem retry. Cancelamento espera 10 s, envia SIGTERM, espera 5 s e envia SIGKILL. Lease vencida vira `worker_lost`; somente job idempotente volta à fila.

## Testes de aceitação

1. Dez consumidores não executam a mesma tentativa.
2. Parsers Rust/Python aceitam os mesmos golden JSONL.
3. Worker morto converge para retry ou falha auditável.
4. SSE retoma sem reiniciar trabalho.
5. Artifact fora do grant e worker v2 são rejeitados antes de commit.

## Fora de escopo

Broker externo, workers remotos, treino distribuído e payload binário no IPC.
