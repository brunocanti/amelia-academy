# ADR 002 — Fila e outbox no PostgreSQL antes de broker

**Status:** Accepted  
**Data:** 24 out. 2026

## Contexto

Geração, extração, treino e avaliação são assíncronos e precisam sobreviver a restart, cancelamento e falha do worker. A implantação inicial é local, de um operador, e já depende de PostgreSQL como sistema de registro. Adicionar Redis, RabbitMQ ou Kafka criaria outro processo, backup e modelo de consistência antes de existir carga que o justifique. O Amelia 3 possui tracking e streaming, mas não um contrato único de lease e recuperação.

## Decisão

Jobs, tentativas, leases e outbox ficam no PostgreSQL. Workers internos reivindicam jobs com `FOR UPDATE SKIP LOCKED`; toda mudança de domínio e seu evento de outbox são gravados na mesma transação. Eventos SSE vêm de `job_events` persistidos. Leases expiram e são recuperadas por reaper; handlers são idempotentes.

Um broker só será adotado se métricas mostrarem contenção, throughput ou distribuição entre máquinas que PostgreSQL não atenda. Nesse caso, a outbox existente alimentará o broker; o banco continuará como fonte de verdade.

## Alternativas consideradas

- **Redis + Bull/Celery:** operação simples em alguns ambientes, mas adiciona durabilidade e reconciliação separadas.
- **RabbitMQ:** semântica madura de entrega, excessiva para um nó local e sem transação atômica com o domínio.
- **Kafka:** ótimo log distribuído, incompatível com escala, operação e latência esperadas.
- **Fila só em memória:** simples, mas perde trabalho e não permite retomada auditável.

## Consequências

- Commit de negócio e publicação de intenção não se separam.
- Backups e diagnóstico cobrem domínio e fila juntos.
- Polling, vacuum e índices de fila precisam ser medidos.
- Entrega é pelo menos uma vez; idempotência não é opcional.
- Jobs longos não mantêm transação aberta: usam lease e heartbeat.

## Validação

- Teste derruba o processo após o commit e antes do dispatch; a outbox é publicada no restart.
- Dez consumidores concorrentes não executam a mesma tentativa simultaneamente.
- Lease vencida retorna a job idempotente à fila com nova tentativa.
- `EXPLAIN` da query de claim usa índice parcial e mantém p95 acordado com 100 mil jobs históricos.
- Critério para rever: claim p95 acima de 100 ms, mais de 1.000 jobs prontos sustentados ou necessidade comprovada de workers em múltiplas máquinas.
