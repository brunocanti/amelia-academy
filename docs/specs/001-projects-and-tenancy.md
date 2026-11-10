# Especificação 001 — Projetos e tenancy

**Status:** normativa v1. Palavras **DEVE**, **NÃO DEVE**, **PODE** e **DEVERIA** são requisitos.

## Propósito e escopo

Define a fronteira de projeto, o ator local e o isolamento aplicável a toda entidade, API, job, evento e artefato. A v1 opera com um único ator local, sem transformar um projeto específico em padrão global.

## Entidades e tipos

- `Project`: `id` UUIDv7, `slug`, `display_name`, `status`, `active_release_id?`, timestamps.
- `ProjectScope`: `project_id` obrigatório e imutável durante um caso de uso.
- `Actor`: `id`, `kind=local_operator|service`, capacidades e `correlation_id`.
- `AuditEntry`: ator, projeto, ação, alvo, hashes antes/depois, motivo e instante.
- Catálogo global: somente itens explicitamente marcados `global_read_only`.

## Máquina de estados

`active → archived → active`; `active|archived → deletion_pending → deleted`.
Arquivar bloqueia novas mutações operacionais, mas preserva leitura. Exclusão exige análise de referências, janela de recuperação e evento de auditoria.

## Invariantes

1. Toda entidade de domínio e referência de artefato DEVE conter `project_id`.
2. Chaves únicas e FKs DEVEM incluir ou validar o mesmo projeto.
3. Repositórios DEVEM exigir `ProjectScope`; escopo implícito é proibido.
4. `active_release_id`, se presente, DEVE apontar para release publicado do mesmo projeto.
5. Nome, gênero, persona ou política de um projeto NÃO DEVEM existir como campos globais.
6. IDs não autorizam acesso; autorização sempre verifica ator, capacidade e projeto.

## API e eventos

- `POST /api/v1/projects`; `GET/PATCH /api/v1/projects/{project_id}`.
- Recursos ficam sob `/api/v1/projects/{project_id}`.
- Escritas exigem `Idempotency-Key`; atualizações exigem `If-Match`.
- Eventos: `project.created`, `project.updated`, `project.archived`, `project.deletion_requested`, `project.deleted`.
- Erros usam `application/problem+json`, com `code`, `correlation_id` e `retryable`.

## Autorização e privacidade

`local-operator` possui capacidades locais explícitas; serviços recebem o mínimo necessário. Bind padrão é `127.0.0.1`. Consultas DEVEM filtrar por projeto e testes DEVEM executar com RLS. Auditoria não deve registrar conteúdo privado.

## Semântica de falha

Escopo ausente retorna `400 scope_required`; acesso cruzado retorna `404` para não confirmar existência. ETag divergente retorna `412`. Arquivamento ou exclusão com job incompatível retorna `409`. Nenhuma falha parcial pode trocar o release ativo.

## Testes de aceitação

1. Dois projetos completam o mesmo fluxo sem campos específicos de persona.
2. FK, consulta, API, evento e artefato cruzados são rejeitados.
3. Repetir criação com a mesma chave idempotente devolve o mesmo projeto.
4. Projeto arquivado permanece legível e rejeita criação de job.
5. RLS bloqueia leitura sob contexto incorreto.

## Fora de escopo

Organizações, convites, RBAC remoto, colaboração simultânea, cobrança e isolamento contra outros usuários do mesmo sistema operacional.
