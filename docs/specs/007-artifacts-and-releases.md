# Especificação 007 — Artefatos e releases

**Status:** normativa v1.

## Propósito e escopo

Define CAS imutável, manifests canônicos, publicação atômica de configuração completa e rollback.

## Entidades e tipos

- `Artifact`: projeto, SHA-256, tamanho, media type, kind, origem e retenção.
- `ModelSpec`: base model, revisão/hash/licença, runtime, tokenizer e template.
- `ModelRelease`: model spec, adapters, charter, policies, retrieval e avaliações.
- `Publication`: release, ator, predecessor, instante e resultado dos gates.

## Máquinas de estado

Artifact: `staging → verified → available`; divergência leva a `quarantined`; retenção: `available → tombstoned → collected`.
Release: `draft → candidate → publishable → published|rejected`; rollback é nova publicação de manifest anterior.

## Invariantes

1. Blob disponível é imutável e fica em `sha256/{2 primeiros}/{hash}`.
2. Commit exige fsync, tamanho/hash verificados e rename atômico.
3. Manifest usa JSON canônico sem campos voláteis; seu hash identifica conteúdo.
4. A única unidade publicável é `ModelRelease`; adapter isolado não é publicável.
5. Todas as referências pertencem ao mesmo projeto e resolvem para bytes existentes.
6. Publicação troca `active_release_id` e grava auditoria/outbox na mesma transação.
7. Conversa fixa o release no início e não muda durante a sessão.

## API e eventos

- `POST /releases`, `POST /releases/{id}:publish`, `POST /releases/{id}:rollback`.
- `GET /artifacts/{sha256}:verify`.
- Eventos: `artifact.committed`, `artifact.quarantined`, `release.published`, `release.rolled_back`.

## Autorização e privacidade

Workers escrevem apenas staging; Rust admite no CAS. Publicar exige capacidade específica. Deduplicação física não concede leitura cruzada. Backups são criptografados e verificados por restore.

## Semântica de falha

Disco cheio ou crash deixa no máximo staging limpável. Hash divergente põe bytes em quarentena. Artifact ausente, licença não declarada, incompatibilidade ou gate reprovado bloqueia publicação sem mudar o ativo. Job de publicação nunca recebe retry implícito.

## Testes de aceitação

1. Alterar um byte bloqueia load/publicação.
2. Duas gravações idênticas geram um blob e duas referências autorizadas.
3. Mudar apenas template muda o hash do release.
4. Falha entre validação e commit preserva o release ativo.
5. Rollback restaura todos os fingerprints e cria novo evento.

## Fora de escopo

S3, assinatura criptográfica, distribuição pública e garantia de licença por inspeção automática.
