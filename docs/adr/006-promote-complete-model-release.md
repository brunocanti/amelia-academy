# ADR 006 — Promover ModelRelease completo, não adapter isolado

**Status:** Accepted  
**Data:** 24 out. 2026

## Contexto

Qualidade em uso depende de base model, quantização, runtime, tokenizer, chat template, adapters, charter, prompts, políticas, embedding, reranker e thresholds. Promover apenas o adapter — hipótese inicial do discovery e prática próxima ao Amelia 3 — atribui regressões ao componente errado e torna rollback incompleto. A superfície de produto já define release como configuração integral.

## Decisão

A única unidade publicável é `ModelRelease`, manifest imutável que referencia todos os componentes e avaliações exigidas por hash/versão. Adapter, treino ou avaliação são candidatos, nunca configuração ativa.

Publicação verifica integridade, licença declarada, compatibilidade de runtime/tokenizer, gates obrigatórios e pertencimento ao projeto; então troca atomicamente `active_release_id`. Novas conversas capturam o release ativo no início. Rollback publica novamente um manifest anterior e registra novo evento de auditoria.

## Alternativas consideradas

- **Promover adapter:** operação simples, mas deixa o restante implícito.
- **Tag mutável `production` em cada componente:** flexível, porém pode formar combinações nunca avaliadas.
- **Imagem/container completo:** reproduz ambiente, mas é pesado no local-first e não substitui linhagem semântica.
- **Configuração em arquivos Git:** auditável para desenvolvedor, insuficiente para operador e artifacts grandes.

## Consequências

- Conversa e avaliação podem citar uma configuração exata.
- Rollback restaura comportamento completo, não só pesos.
- Mudança pequena de threshold exige novo release; isso é intencional.
- Manifests precisam de schema versionado e resolução determinística.
- Releases podem compartilhar artifacts sem duplicá-los.

## Validação

- API não oferece endpoint de “promover adapter”.
- Teste altera somente o template e comprova que o hash do release muda.
- Publicação com artifact ausente, gate reprovado ou componente de outro projeto falha sem trocar o ativo.
- Conversa em andamento mantém seu release enquanto uma nova usa o recém-publicado.
- Rollback atômico restaura todos os fingerprints e aparece no histórico.
