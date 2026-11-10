# Especificação 005 — Manifest de dataset

**Status:** normativa v1.

**Extensão proposta (spec 016 / ADR 019):** o manifesto versionado registra perfis direct/reasoned, confiança da curadoria, hashes de justificativas, seleção/exclusões e agrupamento comum das variantes e bases. Contratos v1 publicados permanecem válidos; a nova semântica exige versão e fixtures próprias antes da implementação.

## Propósito e escopo

Define seleção, congelamento, splits e representação reproduzível de datasets canônicos e de suas renderizações derivadas.

## Entidades e tipos

- `DatasetDraft`: consulta/seleção mutável de revisões aprovadas.
- `DatasetManifest`: seleção congelada, hashes, splits, composição, direitos e consentimentos.
- `DatasetEntry`: sample revision, split, scenario/source group e canonical hash.
- `RenderedDataset`: artifact derivado com model spec, tokenizer/template e loss mask.

## Máquina de estados

`draft → validating → frozen`; de `validating` para `rejected`; `frozen → superseded`. Manifest congelado nunca volta a draft.

## Invariantes

1. Cada entrada referencia revisão aprovada do mesmo projeto.
2. Split ocorre por cenário e grupo de fonte antes da renderização.
3. O mesmo `scenario_group` ou `source_group` NÃO pode cruzar splits.
4. Manifest congelado é serializado canonicamente e identificado por SHA-256.
5. Conversa canônica é fonte; texto renderizado e tokens são artifacts derivados.
6. Entrada de chat exige consentimento de treino válido e versão redigida aprovada.
7. Estatísticas incluem contagem e denominador; nenhum campo específico de persona é obrigatório.

## API e eventos

- `POST /datasets`, `PATCH /datasets/{id}`, `POST /datasets/{id}:freeze`.
- `POST /datasets/{id}:render` retorna job.
- Eventos: `dataset.created`, `dataset.validation_failed`, `dataset.frozen`, `dataset.rendered`.

## Autorização e privacidade

Criar exige acesso aos samples; congelar exige `freeze_dataset`; exportar exige capacidade separada. Manifest pode registrar IDs de consentimento, mas não conteúdo privado não necessário. Revogação bloqueia novos manifests e renderizações.

## Semântica de falha

Item não aprovado, hash divergente, leakage entre splits ou consentimento inválido falha a validação inteira. Falha de renderização não altera o manifest. Divergência de tokenizer/template invalida cache e exige novo artifact.

## Testes de aceitação

1. Ordem de entrada diferente produz a mesma serialização canônica após normalização.
2. Paráfrases do mesmo cenário não cruzam splits.
3. Dataset congelado rejeita PATCH.
4. Dois templates produzem artifacts distintos e mantêm o mesmo manifest canônico.
5. Revogação impede novo render/job sem apagar histórico auditável.

## Fora de escopo

Tokenizer específico, hiperparâmetros de treino, inferência de licença e garantia de reprodutibilidade numérica.
