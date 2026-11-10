# Especificação 004 — Oficina de samples

**Status:** normativa v1 do alvo. No app que roda, o sample sai de um nó selecionado como tema: claim citado se o nó é conhecimento, conversa da ficha se o nó é comportamento. Os dois aprovados entram no mesmo dataset. Ver `docs/architecture/estado-atual.md`.

## Propósito e escopo

Define criação, revisão, deduplicação e aprovação de conversas canônicas usadas como unidades editoriais de treino.

Antes de implementar, ler na Amelia 3 (`~/Projects/Amelia3`) a oficina que já existe: `ui/src/lib/components/conditioning/SampleGenerationWorkshop.svelte`, `PatternLibrary.svelte` e `conditioning_module/training/data_generator.py`. A lista e o que não copiar estão em `docs/erros-da-primeira-implementacao.md`. Inventar outra oficina sem essa leitura é fora desta spec.

## Entidades e tipos

- `SampleBatch`: projeto, behavior versions, parâmetros de geração e estado.
- `CanonicalSample`: conversa estruturada, idioma, público, cenário, proveniência e risco.
- `SampleRevision`: conteúdo canônico imutável, hash e autor/origem.
- `SampleDecision`: `approve|reject|skip`, revisão alvo, ator, motivo e instante.
- `DuplicateAssessment`: método/versão, candidatos e scores; é informativo.

## Máquinas de estado

Lote: `draft → generating → reviewable → closed|failed|cancelled`.
Sample: `proposed → in_review → approved|rejected`; editar cria revisão `proposed`; aprovação anterior não migra automaticamente.

## O que é um sample

Um sample é uma situação falada. A linha de quem pede é uma pessoa, em primeira pessoa, sobre o próprio caso. A linha do assistant responde na intenção e no tom da ficha aprovada, em uma ou duas frases. O tema e a fonte explicam de onde a situação veio; não são o texto das duas falas.

O lote declara runtime e id do modelo. Troca de runtime ou de modelo não acontece em silêncio. A frase de exemplo do charter é referência de avaliação. Ela não entra no prompt como a resposta a copiar.

Não é sample, e não é proposta preservada:

- a fonte, o título ou o resumo do tema partidos em fala de usuário e fala de assistant;
- abertura fabricada colada num título cortado, como “Can you stay with this:”;
- a instrução do gerador repetida como se fosse diálogo (“The assistant stays forever”);
- help desk genérico (“I'm here to help”, “How can I assist”, “I'd be happy”, “Let me help you”);
- o assistant alegando sentimento, consciência ou corpo, ou usando apelido de posse;
- um corpus importado de outro sistema. Importação é migração rotulada, não este gerador.

Falha parcial preserva só linhas que passam nessas regras, e mostra o denominador pedido. Linha inválida não conta como proposta. Se nenhuma linha passa, o lote falha e a oficina não finge que há o que revisar.

## Invariantes

1. Conteúdo canônico contém mensagens e partes tipadas, nunca delimitadores, token IDs ou template de fornecedor.
2. Aprovação referencia hash e revisão exatos.
3. Apenas samples aprovados podem entrar em dataset.
4. Reasoning privado e chain-of-thought bruto NÃO integram conteúdo, log ou metadata. Justificativa editorial explícita é permitida em artifact separado, versionado e aprovado, conforme a proposta da spec 016; não é raciocínio privado recuperado.
5. Score de duplicidade não decide rejeição.
6. Sample oriundo de chat exige `training_candidate_id` e consentimento válido.
7. Perfil direct cobre só a resposta final. Perfil reasoned cobre justificativa editorial aprovada e resposta final, com contratos e máscara verificados segundo a spec 016.
8. Só uma ficha `approved` gera lote. Material gerado permanece `proposed` até decisão humana.
9. O lote registra o modelo que escreveu. Um modelo que não cumpre a ficha não é substituído por um menor sem erro visível.

## API e eventos

- `POST /sample-batches`; `POST /samples/{id}:approve|reject|skip`.
- `POST /samples/{id}/revisions`; `GET /samples/{id}/lineage`.
- Eventos: `sample.proposed`, `sample.revised`, `sample.approved`, `sample.rejected`, `batch.closed`.

## Autorização e privacidade

Gerar requer `create_sample`; decidir requer `review_sample`. Conteúdo sensível usa marcação e acesso por projeto. Telemetria não contém corpo. Export exige autorização e registra finalidade.

## Semântica de falha

Resposta canônica inválida é rejeitada sem criar sample. Falha parcial de lote preserva propostas válidas e informa denominador. ETag divergente impede decisão. Consentimento revogado invalida proposta derivada ainda não publicada.

## Testes de aceitação

1. Mesmo sample renderiza com dois templates sem mudar hash canônico.
2. Aprovação antiga não cobre uma revisão editada.
3. Lote parcialmente falho mostra itens preservados.
4. Tentativa de persistir token IDs ou reasoning privado é rejeitada; justificativa editorial segue artifact e aprovação próprios (spec 016).
5. Chat comum não aparece na oficina; candidato consentido aparece como rascunho.
6. Partir um parágrafo da fonte em duas falas não cria sample, e o teste que afirma esse corte falha.
7. Help desk genérico, cópia da instrução e alegação de sentimento não entram na fila.
8. Um lote de três pede caso claro, borda e recusa, e a superfície mostra tipo, ficha, tema, modelo e n de N.
9. Importar um export já aprovado não aparece como lote gerado pela oficina.
10. `/health`, contagem de manifesto e teste do corte de parágrafo não aceitam esta spec. Aceite é ler as falas na oficina e reconhecer a ficha.

## Fora de escopo

Renderização/tokenização, balanceamento de dataset, preferência automática e aprendizagem online.
