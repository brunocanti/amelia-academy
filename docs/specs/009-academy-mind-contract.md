# Especificação 009 — Contrato Academy–Mind

**Status:** normativa v1.

## Propósito e escopo

Define a fronteira entre comportamento estável produzido pela Academy e eventos/memória mutável administrados pelo Mind, incluindo transferência deliberada de conversa para treino.

## Entidades e tipos

- `ModelReleaseRef`: projeto, release ID e manifest SHA-256.
- `TrainingCandidate`: seleção de eventos, finalidade, versão redigida, diff, consentimento e estado.
- `TrainingConsent`: sujeito/ator, projeto, escopo, finalidade, trechos, concessão e revogação.
- `AcademyImport`: candidato, sample draft criado e auditoria.

## Máquina de estados

`selected → redacting → awaiting_consent → awaiting_review → approved → imported`; qualquer estado anterior a `imported` pode ir a `revoked|rejected`. Importação cria sample `proposed`, nunca aprovado.

## Invariantes

1. Academy e Mind NÃO acessam tabelas internas um do outro.
2. Mind pode fixar um `ModelRelease`; não pode publicar ou mutá-lo.
3. Chat não vira fonte, sample, dataset ou job automaticamente.
4. Consentimento de memória, logging ou suporte NÃO equivale a treino.
5. Candidate aprovado contém somente conteúdo redigido, finalidade específica e referências permitidas.
6. Revisão humana é obrigatória após redação; edição material exige novo consentimento/revisão.
7. Revogação pré-publicação bloqueia novos datasets; histórico permanece auditável.
8. Campos são genéricos a qualquer projeto/persona.

## API e eventos

- Mind emite `training_candidate.created|redacted|consented|revoked`.
- Academy aceita `POST /projects/{id}/training-candidates:import`.
- Academy emite `training_candidate.imported` com `sample_id`.
- Contrato de payload é `training-candidate.schema.json`.

## Autorização e privacidade

Seleção e consentimento são ações distintas. Redação deve tratar PII, terceiros, menores, segredos e pedidos “não guarde isto”; o operador vê diff. Telemetria não contém corpo. Transferência é revogável por estágio.

## Semântica de falha

Consentimento ausente, expirado, revogado, finalidade divergente, redação incompleta ou projeto distinto falha sem retry. Importação idempotente devolve o mesmo sample draft. Falha após commit é retomada pela outbox sem duplicar.

## Testes de aceitação

1. Conversa comum não aparece na busca da Academy.
2. Candidate sem consentimento ou redação é rejeitado.
3. Candidate válido cria rascunho, não sample aprovado.
4. Revogação antes de freeze impede inclusão em dataset.
5. Fake do Mind satisfaz o contrato sem importar módulos internos.

## Fora de escopo

Desaprendizado garantido de pesos distribuídos, memória interna do Mind, ingestão automática e consentimento jurídico universal.
