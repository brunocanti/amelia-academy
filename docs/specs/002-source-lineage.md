# Especificação 002 — Fontes e linhagem

**Status:** normativa v1.

## Propósito e escopo

Define ingestão explícita de fontes autorizadas, extração, trechos citáveis e linhagem navegável até objetos derivados.

## Entidades e tipos

- `Source`: projeto, artifact original, nome exibido, MIME detectado, finalidade, base de uso/licença declarada e estado.
- `SourceVersion`: hash SHA-256, tamanho, metadados e instante de ingestão.
- `Extraction`: extrator/versão, source version, artifact de texto e estado.
- `Chunk`: ID estável, offsets ou página/seção, texto, hash e versão de extração.
- `LineageEdge`: `from_type/id/version`, `to_type/id/version`, transformação e evidência.

## Máquina de estados

Fonte: `uploaded → validating → available`; de `validating` para `rejected|quarantined`. Extração: `queued → running → succeeded|failed|cancelled`. Nova versão não substitui a anterior.

## Invariantes

1. Upload DEVE declarar finalidade e base de uso; a plataforma NÃO DEVE afirmar validação jurídica.
2. Nome original nunca vira caminho físico.
3. Bytes originais são imutáveis e identificados por SHA-256.
4. Chunk DEVE resolver para versão exata, posição e hash da fonte.
5. Objeto derivado DEVE registrar todas as entradas materiais e transformação versionada.
6. Linhagem confirmada é imutável; correção cria versão/edge novo.
7. Fonte de Academy NÃO DEVE ser classificada como episódio pessoal.

## API e eventos

- `POST /projects/{id}/sources`, `GET /sources/{id}`, `GET /sources/{id}/lineage`.
- `POST /sources/{id}:extract`, `GET /chunks/{id}`.
- Eventos: `source.ingested`, `source.quarantined`, `extraction.completed`, `extraction.failed`, `lineage.created`.

## Autorização e privacidade

Upload e leitura exigem escopo do projeto. Workers recebem apenas grants read-only. Logs redigem texto, tokens, caminhos pessoais e nomes originais por padrão. Exclusão respeita retenção, consentimento e referências alcançáveis.

## Semântica de falha

MIME, tamanho, hash ou licença ausente falham antes de derivação. Falha de extração preserva o original e não cria chunks parciais visíveis. Divergência de checksum põe o artifact em quarentena. Erros transitórios podem criar nova tentativa, nunca nova identidade da fonte.

## Testes de aceitação

1. Alterar um byte cria hash e versão distintos.
2. Cada citação abre o trecho na versão correta.
3. Crash durante extração não publica texto parcial.
4. Fonte de outro projeto não pode ser citada.
5. Export de linhagem reconstrói fonte, transformação e decisões até um sample.

## Fora de escopo

OCR automático, crawling, validação legal, sincronização de nuvem e ingestão automática de chats.
