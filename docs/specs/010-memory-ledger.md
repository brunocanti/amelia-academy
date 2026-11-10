# Especificação 010 — Ledger de memória

**Status:** normativa v1.

## Propósito e escopo

Define o contrato futuro de eventos imutáveis e claims corrigíveis do Mind, separado da Academy. Memória pertence ao runtime, não a um checkpoint.

## Entidades e tipos

- `MemoryEvent`: projeto, sessão, sujeito, tipo, payload/ref, `occurred_at`, `ingested_at`, privacidade e evidência.
- `MemoryClaim`: tipo (`episode|semantic|preference|goal|commitment|identity|source`), texto estruturado, confiança, explicitude, sensibilidade, escopo e bitemporalidade.
- `ClaimEvidence`: event/claim, citação permitida e autoridade.
- `Tombstone`: alvo, motivo, undo deadline e purge deadline.
- Visões e embeddings são projeções reconstruíveis.

## Máquina de estados

Claim: `candidate → active|ignored|contested`; `active → superseded|expired|tombstoned`. Ações: `ADD`, `REINFORCE`, `SUPERSEDE`, `COEXIST`, `IGNORE`, `ASK_CONFIRMATION`. Evento nunca muda.

## Invariantes

1. Ledger é append-only; correção adiciona evento e nova claim.
2. `occurred_at/valid_from/to` descrevem o mundo; `ingested_at/recorded_at` descrevem o sistema.
3. Correção explícita tem maior autoridade que declaração antiga; declaração direta supera inferência.
4. Claim derivada carrega evidência, extrator, prompt version, confiança e escopo.
5. Fonte documental não vira episódio pessoal.
6. Inferência emocional é `inferred`, não diagnóstico.
7. Decay reduz prioridade, não verdade.
8. Tombstone remove de retrieval/contexto e invalida projeções derivadas antes do purge.

## API e eventos

- `POST /memory/events`, `POST /memory/claims:propose`.
- `POST /memory/claims/{id}:confirm|correct|forget`.
- Eventos: `memory.event_appended`, `claim.activated`, `claim.superseded`, `claim.tombstoned`, `projection.rebuilt`.
- Payloads seguem `memory-event.schema.json` e `memory-claim.schema.json`.

## Autorização e privacidade

Filtrar privacidade, sujeito, tipo, status e validade antes de ranking. Acesso e retrieval são auditados. “Não guarde isto” bloqueia consolidação. Exclusão alcança índices, resumos, reflexões e backups conforme retenção declarada.

## Semântica de falha

Evento válido é preservado mesmo se consolidação falhar. Contradição sem contexto cria `contested` ou pede confirmação; não sobrescreve. Falha de embedding afeta índice, não fonte. Purge parcial mantém tombstone e agenda retry.

## Testes de aceitação

1. Correção fecha validade anterior sem apagar evidência.
2. Preferências contextuais coexistem.
3. Claim tombstoned não aparece no retrieval e invalida resumo derivado.
4. Views são reconstruídas somente do ledger e contratos versionados.
5. Busca em projeto/sujeito incorreto retorna zero itens.

## Fora de escopo

Graph DB, consciência, diagnóstico psicológico, autoedição irrestrita e treino paramétrico a partir da memória.
