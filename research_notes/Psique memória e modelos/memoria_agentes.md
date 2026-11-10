# Memória para agentes e companions de longa duração

Escopo: avanços de 2024 a 24 de outubro de 2026, com antecedentes indispensáveis de 2023. As datas entre parênteses são as datas de publicação ou atualização informadas pela fonte; acesso em 24-10-2026. “Resultado do autor/fornecedor” identifica números que não constituem validação independente.

## 1. O que as arquiteturas e frameworks realmente contribuíram

### Takeaway

O avanço real não foi um banco ou algoritmo vencedor, mas a convergência para memória externa tipada, atualização temporal, recuperação híbrida e consolidação assíncrona. MemGPT/Letta tornou explícita a memória autogerida pelo agente; Generative Agents introduziu recuperação por relevância–recência–importância e reflexão; Zep/Graphiti formalizou fatos bitemporais; Mem0 popularizou extração–deduplicação–atualização; A-MEM mostrou notas interligadas que evoluem; HippoRAG 2 e GraphRAG mostraram onde relações ajudam; LangGraph forneceu primitives de orquestração; Cognee empacotou múltiplas visões. Nenhum deles, isoladamente, demonstra a memória autobiográfica, afetiva, privada e corrigível que Amelia precisa.

### Cited Findings

#### MemGPT e Letta

- O MemGPT original modelou o contexto como uma hierarquia de memória inspirada em memória virtual: o LLM recebe ferramentas para editar memória “core” no contexto e pesquisar memória “archival” externa. No Deep Memory Retrieval, o artigo reportou GPT-4 de 32,1% para 92,5% e GPT-4 Turbo de 35,3% para 93,4% com MemGPT; são resultados dos autores em um benchmark sintético pequeno, não prova de continuidade autobiográfica aberta. — [MemGPT, arXiv v2 (2024)](https://arxiv.org/html/2310.08560v2)
- Desde 23-09-2024, “MemGPT” designa o padrão de agente com memória autoeditável e “Letta” o framework persistente; a contribuição duradoura é tornar leitura, escrita e edição de memória ações explícitas do agente, observáveis e avaliáveis. — [Letta, anúncio da mudança (2024-09-23)](https://www.letta.com/blog/memgpt-and-letta/)
- O leaderboard da Letta separa leitura, escrita e atualização de memória core e archival, usa fatos sintéticos e GPT-4.1 como juiz e penaliza operações extras. Isso é útil para testar política de ferramentas, mas não cobre privacidade, saliência afetiva, esquecimento ou identidade ao longo de anos. — [Letta Leaderboard (2025-05-29)](https://www.letta.com/blog/letta-leaderboard/)
- A própria Letta mostrou que um agente com GPT-4o-mini, arquivos, busca semântica, `grep` e regras de ferramentas chegou a 74,0% em LoCoMo, acima dos 68,5% então reportados para Mem0 Graph. O resultado enfraquece a interpretação de LoCoMo como prova de uma arquitetura sofisticada e sugere que estratégia de contexto e busca pode dominar a estrutura de armazenamento. — [Letta filesystem/LoCoMo (2025-08-12)](https://www.letta.com/blog/benchmarking-ai-agent-memory/)
- Letta é self-hostable e Apache-2.0; o repositório histórico foi substituído pelo `letta-code`, também Apache-2.0, com exclusão explícita dos ativos de marca. — [Letta LICENSE](https://github.com/letta-ai/letta/blob/main/LICENSE); [Letta Code](https://github.com/letta-ai/letta-code)

#### Generative Agents

- Generative Agents, antecedente de 2023 ainda central, mantém um fluxo de observações, reflexões e planos em linguagem natural; recupera por combinação normalizada de relevância semântica, recência e importância, e reinsere reflexões e planos no mesmo fluxo. — [Park et al., UIST/arXiv (2023, v2)](https://arxiv.org/html/2304.03442v2)
- A reflexão é disparada quando a soma de importância recente cruza um limiar (150 na implementação; cerca de duas ou três vezes por “dia” simulado), gera perguntas salientes, recupera evidências e cria insights com ponteiros para memórias-fonte. A ablação do artigo sustenta que observação sem reflexão prejudica generalização e comportamento crível, mas o estudo avalia uma simulação de 25 agentes, não companions privados de longo prazo. — [Generative Agents, seção 4.2 (2023)](https://arxiv.org/html/2304.03442v2)
- A ideia aplicável à Amelia é separar episódio bruto de reflexão derivada e preservar a árvore de evidência; não é copiar o limiar arbitrário nem deixar a reflexão sobrescrever o evento.

#### Zep e Graphiti

- Graphiti ingere mensagens, texto ou JSON como episódios, extrai entidades e relações e preserva fatos anteriores ao invalidá-los, em vez de apagá-los. Cada relação pode ter tempo de transação (`created_at`, `expired_at`) e tempo de validade no mundo (`valid_at`, `invalid_at`). Essa bitemporalidade é uma contribuição especialmente relevante para “eu morava em X, agora moro em Y”. — [Graphiti temporal graphs (2024–2025)](https://www.getzep.com/blog/beyond-static-knowledge-graphs/)
- A busca do Graphiti combina vetor, texto integral e travessia de grafo; o framework exige que o operador forneça LLM, embedder, graph DB, tenancy, controle de acesso e operação. Os backends documentados são Neo4j, FalkorDB e Amazon Neptune, portanto ele não encaixa diretamente na decisão inicial de Amelia de usar apenas PostgreSQL. — [Graphiti repository, atualizado em 2026](https://github.com/getzep/graphiti); [Zep vs. Graphiti](https://help.getzep.com/zep-vs-graphiti.mdx)
- O artigo Zep reportou 94,8% contra 93,4% do MemGPT em DMR e até 18,5% de melhora, com 90% menos latência, em LongMemEval frente a baselines escolhidos. São números produzidos pela equipe do produto; a principal evidência reutilizável é o modelo temporal e os experimentos reproduzíveis, não a alegação genérica de superioridade. — [Zep paper, arXiv (2025-01)](https://arxiv.org/html/2501.13956)
- Graphiti é Apache-2.0 e self-hostable; Zep é a oferta gerenciada com componentes adicionais proprietários. — [Graphiti LICENSE](https://github.com/getzep/graphiti/blob/main/LICENSE); [Zep vs. Graphiti](https://help.getzep.com/zep-vs-graphiti.mdx)

#### Mem0

- Mem0 extrai memórias salientes de uma conversa, compara-as com memórias recuperadas e decide adicionar, atualizar, excluir ou não fazer nada; a variante Graph adiciona relações entre entidades. O artigo reporta 26% de melhora relativa no juiz LLM sobre a baseline OpenAI, cerca de 2% sobre Mem0 base para a variante grafo, 91% menos latência p95 e mais de 90% menos tokens que full-context em LoCoMo. — [Mem0 paper, arXiv (2025-04)](https://arxiv.org/html/2504.19413)
- A avaliação acima é dos próprios autores e mistura modelos, prompts e sistemas com interfaces distintas. A própria tabela do artigo mostra resultados substancialmente diferentes para uma reexecução de A-MEM, evidenciando sensibilidade de implementação e juiz. — [Mem0 paper, tabela 1 (2025-04)](https://arxiv.org/html/2504.19413)
- A contribuição prática é uma pipeline simples de extração, busca de candidatos e resolução de ação; o risco é transformar uma decisão probabilística do LLM em `UPDATE/DELETE` irreversível. Para Amelia, “delete” deve significar supersessão lógica ou expiração, nunca destruição da evidência.
- Mem0 OSS é Apache-2.0, requer Python 3.10+ na versão consultada e pode ser auto-hospedado; algumas capacidades e resultados recentes divulgados como “Mem0” pertencem ao serviço cloud e devem ser separados do OSS em qualquer avaliação. — [Mem0 LICENSE](https://github.com/mem0ai/mem0/blob/main/LICENSE); [Mem0 package metadata](https://github.com/mem0ai/mem0/blob/main/pyproject.toml)

#### LangGraph e LangMem

- LangGraph distingue estado de thread/checkpointer de memória longa cross-thread. A memória longa é documento JSON por namespace e chave; `PostgresStore` oferece persistência e busca semântica, mas a aplicação ainda precisa definir o que gravar, quando atualizar, como resolver conflito e o que recuperar. — [LangGraph memory docs, atualizadas em 2026](https://docs.langchain.com/oss/python/concepts/memory); [LangGraph stores](https://docs.langchain.com/oss/python/langgraph/stores)
- A documentação distingue memória semântica (fatos), episódica (experiências) e procedural (instruções), além de escrita no hot path versus em background. Escrita síncrona torna a memória imediatamente visível, porém aumenta latência e divide a atenção do agente; background melhora isolamento, porém introduz atraso. — [LangGraph memory overview](https://docs.langchain.com/oss/python/concepts/memory)
- Portanto, LangGraph é uma boa referência de interface e orquestração, não uma arquitetura cognitiva pronta. Para um backend Rust/Axum, reproduzir as primitives necessárias em SQLx é mais coerente que introduzir Python apenas para usar o framework.

#### A-MEM

- A-MEM cria notas atômicas no estilo Zettelkasten com conteúdo, descrição contextual, palavras-chave, tags e embedding; ao inserir uma memória, busca vizinhas, cria links e pode “evoluir” contexto e atributos das notas existentes. Foi aceito no NeurIPS 2025 e avaliado em seis modelos-base. — [A-MEM paper, NeurIPS 2025](https://proceedings.neurips.cc/paper_files/paper/2025/hash/19909c36f51abc4856b4560aff3d36d6-Abstract-Conference.html); [arXiv (2025-02)](https://arxiv.org/abs/2502.12110)
- O mecanismo demonstra uma forma útil de reconsolidação: nova informação pode fortalecer links e enriquecer representações anteriores. Contudo, editar texto histórico sem manter versões pode propagar alucinações e apagar a distinção entre “o usuário disse” e “o sistema inferiu”. Amelia deve preservar notas-fonte imutáveis e versionar apenas interpretações derivadas.
- O código acadêmico e o “production-ready” ficam em repositórios diferentes; a avaliação é do grupo autor, não uma comparação operacional independente. — [A-MEM paper/code links (2025)](https://arxiv.org/abs/2502.12110)

#### HippoRAG 2

- HippoRAG 2 usa OpenIE para um grafo de frases/entidades, conecta passagens mais profundamente, aplica Personalized PageRank e usa LLM online para filtrar conhecimento irrelevante. O artigo, publicado no ICML 2025, reporta aproximadamente 7 pontos de melhora média em tarefas associativas sobre um embedding forte, sem sacrificar tarefas factuais e de sense-making. — [HippoRAG 2, ICML/PMLR (2025)](https://proceedings.mlr.press/v267/gutierrez25a.html); [arXiv v2 (2025-06-19)](https://arxiv.org/html/2502.14802v2)
- A contribuição é mostrar que propagação sobre relações pode recuperar evidência associativa/multi-hop que top-k vetorial perde. Não é um sistema de perfil do usuário, temporalidade, privacidade ou esquecimento; é melhor entendido como um retriever opcional para perguntas relacionais.

#### Microsoft GraphRAG, LightRAG e GraphRAG em geral

- LightRAG cria entidades/relações e oferece busca local e global de baixo/alto nível. Seu artigo reporta vitória sobre RAG ingênuo e, na maioria dos domínios, sobre Microsoft GraphRAG; no corpus misto, o “overall” foi praticamente empate (49,6% LightRAG contra 50,4% GraphRAG). A avaliação usa juízes LLM e é dos autores. — [LightRAG paper v2 (2024-10, revisto)](https://arxiv.org/html/2410.05779v2)
- GraphRAG-Bench foi criado porque estudos encontram GraphRAG abaixo de RAG simples em tarefas reais; ele separa construção, recuperação e geração e testa fato, raciocínio complexo, sumarização contextual e geração. Isso sustenta que grafo deve ser adotado por ganho medido em uma classe de consulta, não como dogma arquitetural. — [GraphRAG-Bench repository (2025–2026)](https://github.com/GraphRAG-Bench/GraphRAG-Benchmark)
- Para Amelia, GraphRAG de corpus é apropriado para documentos de referência e temas; não deve ser confundido com memória pessoal. Episódios, preferências, fatos temporais e compromissos exigem semântica de atualização e proveniência diferente de um índice documental.

#### Cognee

- Cognee materializa várias visões da mesma entrada: chunks, entidades/relações, resumos e um índice global de contexto; a busca pode ser vetorial, grafo, resumo ou híbrida. — [Cognee BEAM report (2026)](https://github.com/topoteretes/cognee/blob/main/cognee/eval_framework/beam/REPORT.md)
- O fornecedor publica 91,3% em LoCoMo, 0,79 em BEAM 100K e 0,67 em BEAM 10M, com artefatos e configurações. O próprio relatório chama BEAM preliminar e os conjuntos BEAM publicados usam apenas uma conversa/20 perguntas por escala, logo os intervalos não sustentam uma afirmação ampla de estado da arte. — [Cognee accuracy benchmarks (2026)](https://docs.cognee.ai/core-concepts/evaluation-and-efficiency/accuracy-benchmarks)
- Em comparação da própria Cognee sobre apenas 24 questões HotPotQA, Cognee foi ajustado e concorrentes rodaram com defaults; a página reconhece que o ajuste explica parte importante da diferença. Isso é evidência de que interface, chunking e prompts importam, não validação independente de superioridade. — [Cognee comparison (2026)](https://www.cognee.ai/knowledge-graph-memory-benchmarks)
- Cognee é Apache-2.0 e roda localmente, mas o próprio repositório marca o armazenamento de grafo em PostgreSQL como demo e a versão production-ready como produto licenciado. — [Cognee repository (2026)](https://github.com/topoteretes/cognee/); [Cognee LICENSE](https://github.com/topoteretes/cognee/blob/main/LICENSE)

#### Evidência empírica versus marketing

- LoCoMo tem apenas dez conversas públicas, com cerca de 600 turnos/16 mil tokens em média na versão ACL, e testa QA, sumarização de eventos e geração; é útil para regressão, mas pequeno e hoje cabe inteiro em muitos contextos. — [LoCoMo, ACL 2024](https://aclanthology.org/2024.acl-long.747/); [dataset](https://github.com/snap-research/locomo/)
- Uma auditoria independente publicada em 2026 encontrou 99 erros que alteram score entre 1.540 perguntas não adversariais (6,4%), incluindo fatos inexistentes, datas erradas e atribuição ao falante errado; também encontrou forte leniência do juiz para respostas vagas. É um artefato independente recente, ainda não uma publicação revisada por pares. — [LoCoMo audit (2026)](https://github.com/dial481/locomo-audit/blob/main/AUDIT_REPORT.md)
- LongMemEval tem 500 perguntas e mede extração, raciocínio multi-sessão, atualização, tempo e abstenção. O conjunto S tem cerca de 115 mil tokens e o M cerca de 500 sessões/1,5 milhão de tokens; o artigo ICLR 2025 reporta queda de cerca de 30 pontos para assistentes comerciais e long-context ao longo de interações sustentadas. — [LongMemEval project (2024-10, ICLR 2025)](https://xiaowu0162.github.io/long-mem-eval/); [ICLR 2025](https://proceedings.iclr.cc/paper_files/paper/2025/hash/d813d324dbf0598bbdc9c8e79740ed01-Abstract-Conference.html)
- BEAM, lançado em 2025, tem 100 conversas sintéticas de 128K a 10M tokens e 2.000 perguntas sobre dez capacidades, incluindo contradição, atualização, preferência, ordem de eventos e instruções. LIGHT, dos mesmos autores, melhora 3,5%–12,69% contra as baselines mais fortes dependendo do modelo; isso é melhor cobertura, mas continua sendo conversa gerada por pipeline. — [BEAM paper v2 (2025-10)](https://arxiv.org/html/2510.27246v2); [BEAM repository](https://github.com/mohammadtavakoli78/BEAM)
- LongMemEval-V2 (maio de 2026) amplia a avaliação para 451 perguntas sobre até 500 trajetórias/115M tokens de agentes web; AgentRunbook-C baseado em arquivos + coding agent marcou 72,5%, contra 48,5% do RAG mais forte, ao custo de alta latência. Isso reforça a necessidade de medir accuracy, custo e latência juntos e mostra que ferramentas simples sobre registros brutos continuam baselines fortes. — [LongMemEval-V2 (2026-05)](https://arxiv.org/html/2605.12493v1)
- Não foi encontrada, até 24-10-2026, avaliação pública independente, longitudinal e com usuários reais que compare os frameworks acima em continuidade autobiográfica, relação afetiva, privacidade, direito de correção e esquecimento por meses. Rankings de fornecedor devem ser tratados como hipóteses reproduzíveis, não como prova de adequação para companion.

### Inferences

- A unidade de verdade deve ser o evento/fonte imutável; “memória” consolidada é uma visão materializada, versionada e revogável. Isso combina a proveniência de Generative Agents/A-MEM com a bitemporalidade de Graphiti sem aceitar edição destrutiva.
- Memória do companion deve ser dividida por função, não apenas por “curta/longa”: autobiografia da Amelia, fatos do usuário, preferências, episódios, compromissos/metas, conhecimento documental, modelo relacional e procedimentos. A taxonomia factual–experiencial–working e as operações formação–evolução–recuperação são compatíveis com surveys de 2025–2026. — [Memory in the Age of AI Agents, v2 (2026-01)](https://arxiv.org/abs/2512.13564); [ACM survey (2025-09)](https://dl.acm.org/doi/full/10.1145/3748302)
- Um knowledge graph é um índice relacional secundário valioso para associação, explicação e multi-hop; não é o sistema de registro e não deve receber fatos sem evidência, temporalidade e escopo de privacidade.

### Gaps

- Não há consenso empírico sobre uma função universal de saliência, meia-vida ou frequência de consolidação para companions.
- Não há benchmark público suficiente para “memórias íntimas que não devem aparecer em contextos inadequados”, correção pelo usuário, inferência afetiva calibrada ou exclusão verificável.
- Resultados de 2026 com páginas de fornecedores podem mudar; versões, modelos, prompts, commits e datasets devem ser fixados na avaliação da Amelia.

## 2. Modelo de memória recomendado para Amelia 4

### Takeaway

Implementar uma memória local-first, event-sourced e bitemporal em PostgreSQL + pgvector, com sete tipos de memória e duas velocidades de escrita. Toda fala permanece como episódio; somente fatos candidatos de alta confiança entram síncronos, enquanto consolidação, ligação, resumo e decadência rodam em background. Recuperação deve filtrar primeiro por segurança/tempo/tipo, depois combinar lexical, vetorial, recência, importância, afetividade e grafo, e finalmente reranquear. Contradições coexistem como afirmações versionadas até uma política explícita escolher a visão atual.

### Cited Findings

#### Princípios de projeto

- PostgreSQL suporta travessias recursivas e detecção de ciclos por recursive CTE; pgvector oferece HNSW e recomenda combinar vetor com full-text search, por RRF ou cross-encoder. Portanto, um primeiro grafo com tabelas `entities`/`relations` e travessias limitadas cabe no mesmo banco. — [PostgreSQL recursive queries, docs v18 (2026)](https://www.postgresql.org/docs/current/queries-with.html); [pgvector hybrid search](https://github.com/pgvector/pgvector)
- HNSW oferece melhor desempenho de consulta que IVFFlat para o mesmo recall, ao custo de build mais lento e mais memória, e não exige treinamento prévio. Para a escala inicial de um único usuário, busca exata pode ser o baseline; HNSW só deve entrar quando medições mostrarem necessidade. — [pgvector docs, HNSW](https://pgvector.app/docs/)
- O desenho de Amelia já fixa Rust/Axum/SQLx, PostgreSQL + pgvector, Ollama, disco local e um único operador. Adicionar Neo4j/FalkorDB agora criaria um segundo sistema de backup, migração, autorização e exclusão sem evidência de ganho no volume inicial. — [Amelia 4 discovery, 2026-10-24](../../docs/discovery-e-proposta.md)

#### Tipos de memória propostos

1. **Working/session memory**: últimas falas, resumo incremental e estado do turno; escopo por sessão, expira/comprime rapidamente.
2. **Episódica**: eventos imutáveis da conversa, ações, resultados, participantes e tempo; é a base autobiográfica compartilhada.
3. **Semântica do usuário**: afirmações atômicas sobre identidade, relações e circunstâncias, com validade temporal e confiança.
4. **Preferências**: gosto/aversão/hábito com domínio, força, estabilidade e evidência; não tratar uma escolha única como traço permanente.
5. **Metas e open loops**: promessas, decisões pendentes, perguntas sem resposta, projetos e próximos passos, com estado e prazo.
6. **Autobiografia/identidade da Amelia**: persona versionada, marcos do relacionamento e reflexões próprias; fatos da persona têm autoridade superior a inferências de conversa.
7. **Conhecimento de referência/procedural**: chunks de fontes, temas e instruções; separado da pessoa para impedir que um documento se torne “algo que o usuário viveu”.

Essa separação é uma inferência de engenharia sustentada pela distinção semântica/episódica/procedural do LangGraph e factual/experiencial/working dos surveys. — [LangGraph memory overview](https://docs.langchain.com/oss/python/concepts/memory); [Memory in the Age of AI Agents (2026)](https://arxiv.org/abs/2512.13564)

#### Esquema mínimo recomendado

```text
memory_events
  id, session_id, message_id, actor, event_type, content,
  occurred_at, ingested_at, source_hash, privacy_scope, deleted_at

memory_claims
  id, subject_entity_id, predicate, object_text/object_entity_id,
  claim_type, status, confidence, explicitness,
  valid_from, valid_to, recorded_at, superseded_at,
  privacy_scope, sensitivity, affect_valence, affect_arousal,
  importance, stability, last_confirmed_at

claim_evidence
  claim_id, event_id/chunk_id, quote_start, quote_end,
  extractor_model, prompt_version, extraction_run_id

memory_entities
  id, canonical_name, entity_type, aliases, merged_into

memory_relations
  id, src_entity_id, relation_type, dst_entity_id,
  valid_from, valid_to, recorded_at, superseded_at, confidence

memory_reflections
  id, kind, text, confidence, valid_from, valid_to,
  model, prompt_version, version, supersedes_id

reflection_evidence
  reflection_id, event_id/claim_id/reflection_id, weight

open_loops
  id, owner, kind, description, state, due_at,
  created_event_id, resolved_event_id, privacy_scope

memory_embeddings
  owner_type, owner_id, model_id, dimension, embedding, embedded_at

memory_access_log
  query_id, purpose, candidate_ids, selected_ids, scores,
  model_id, created_at
```

- `occurred_at/valid_from` representam o tempo no mundo; `ingested_at/recorded_at` representam o tempo no sistema. Essa é a adaptação SQL da bitemporalidade do Graphiti. — [Graphiti bitemporal model](https://www.getzep.com/blog/beyond-static-knowledge-graphs/)
- `claim_evidence` e `reflection_evidence` implementam a árvore de suporte de Generative Agents e impedem que resumo ou reflexão pareçam fala literal. — [Generative Agents reflection tree](https://arxiv.org/html/2304.03442v2)
- `privacy_scope` deve ser enum/bitmask explícito, por exemplo `private_creator`, `session_only`, `companion_internal`, `shareable`, `system_secret`; segurança deve ser filtro SQL antes da similaridade, nunca instrução textual depois da recuperação.

#### Política de escrita

**Passo 1 — log sempre, memória seletiva.**

- Persistir a mensagem aprovada pelo fluxo de chat como `memory_event`; isso é histórico, não afirmação de verdade.
- Rodar extractor estruturado para candidatos atômicos com: tipo, sujeito, predicado, objeto, tempo, explicitness, confiança, sensibilidade, citação exata e ação sugerida.
- Validar JSON por schema, limites e offsets; candidatos sem citação válida permanecem apenas no evento.

**Passo 2 — decisão determinística antes do LLM.**

- Rejeitar segredos de terceiros, credenciais, dados excessivamente sensíveis sem opt-in, conteúdo citado de documentos como se fosse fato pessoal e inferências clínicas.
- Gravar imediatamente apenas: pedido explícito “lembre”, correção explícita, compromisso/open loop, preferência forte explicitamente declarada e fato necessário à tarefa corrente.
- Enviar detalhes comuns para fila de consolidação; não bloquear resposta.

**Passo 3 — comparar candidatos.**

- Buscar claims do mesmo sujeito/predicado e aliases por filtros + lexical + embedding.
- Ações possíveis: `ADD`, `REINFORCE`, `SUPERSEDE`, `COEXIST`, `IGNORE`, `ASK_CONFIRMATION`.
- O LLM pode propor a ação, mas uma state machine aplica regras: correção explícita do usuário tem prioridade; diferença temporal válida gera `SUPERSEDE`; preferência contextual gera `COEXIST`; baixa confiança contraditória gera `ASK_CONFIRMATION`; nunca `DELETE` físico.

Essa pipeline conserva a simplicidade ADD/UPDATE/DELETE/NOOP do Mem0, mas substitui update/delete destrutivos por versões e status. — [Mem0 architecture (2025)](https://arxiv.org/html/2504.19413)

#### Contradição, temporalidade e autoridade

Ordem de autoridade proposta:

1. ação/correção explícita atual do usuário;
2. fonte primária versionada (persona, configuração, documento indicado como canônico);
3. declaração direta recente;
4. declaração direta antiga ainda válida;
5. repetição independente;
6. inferência/reflexão;
7. resumo gerado.

Algoritmo:

- Se os valores podem valer em tempos ou contextos distintos, fechar `valid_to` do anterior e abrir novo claim.
- Se podem coexistir por domínio (“gosto de silêncio para trabalhar, música para correr”), manter ambos com contexto.
- Se são incompatíveis e falta tempo/contexto, manter `contested`, não escolher silenciosamente e perguntar quando relevante.
- Se o usuário corrige, superseder a visão corrente, preservar o evento anterior e registrar o evento de correção.
- Respostas devem preferir claim `active` no tempo consultado; consultas históricas usam o intervalo de validade.

LongMemEval testa knowledge updates e raciocínio temporal, e BEAM adiciona contradição e ordenação de eventos; esses casos devem virar testes unitários e de integração da state machine. — [LongMemEval](https://xiaowu0162.github.io/long-mem-eval/); [BEAM](https://github.com/mohammadtavakoli78/BEAM)

#### Consolidação e reconsolidação

- **Após sessão (minutos):** extrair claims/open loops; sumarizar episódio com citações; atualizar entidades/aliases.
- **Diária ou por limiar de saliência:** agrupar episódios relacionados; criar reflexões de padrão/preferência somente com múltiplas evidências; ligar temas e pessoas.
- **Semanal/por volume:** fundir duplicatas equivalentes, recalcular estabilidade/importância, produzir resumos hierárquicos e arquivar embeddings antigos.
- **Na recuperação importante:** se evidência nova conflita com reflexão antiga, criar nova versão da reflexão; nunca reescrever a antiga sem lineage.

O gatilho pode combinar contagem, novidade, surpresa, open loop, importância e arousal, inspirado no limiar de reflexão de Generative Agents; o valor deve ser calibrado nos dados da Amelia, não copiado como 150. — [Generative Agents (2023)](https://arxiv.org/html/2304.03442v2)

#### Afeto e saliência

- Guardar `valence` e `arousal` como anotação probabilística do episódio, mais `importance` funcional; afeto não é verdade factual.
- O que o usuário declarou sentir tem `explicitness=direct`; o que o extractor inferiu tem `explicitness=inferred`, confiança menor e não deve ser verbalizado como certeza.
- Saliência de escrita sugerida:

```text
write_score =
  0.25 explicit_request +
  0.20 future_utility +
  0.15 goal_relevance +
  0.15 novelty +
  0.10 repetition +
  0.10 affect_arousal +
  0.05 relationship_significance
  - sensitivity_risk
```

- Pesos acima são hipótese inicial, não resultado científico. Registrar features e decisão permite recalibrar com revisão humana.
- Afeto aumenta chance de preservar um episódio, mas não deve dominar retrieval: lembrar automaticamente um evento doloroso porque é “saliente” pode ser prejudicial. Consultas sensíveis exigem compatibilidade de propósito e, em alguns casos, confirmação.

#### Esquecimento, decay e exclusão

- Separar **decay de recuperação**, **compactação** e **apagamento**. Um fato estável confirmado não se torna falso por envelhecer; apenas perde prioridade. Um episódio comum pode sair do índice quente sem ser destruído. Um pedido de exclusão remove derivadas e embeddings.
- Score de recência sugerido: `exp(-ln(2) * age / half_life(type, stability))`; half-life maior para identidade/preferência estável, menor para contexto de sessão. Recorrência, confirmação e uso bem-sucedido aumentam estabilidade.
- Nunca aplicar decay a persona canônica, consentimentos, restrições de segurança ou open loops ainda ativos.
- “Forget” do usuário deve produzir tombstone, retirar o item de índices/contexto, invalidar reflexões derivadas, reconstruir resumos afetados e apagar conteúdo físico após janela de undo configurável.
- Backups precisam da mesma política: criptografados, retenção curta e procedimento documentado de expiração; caso contrário “delete” na interface é enganoso.

#### Política de recuperação

1. Classificar intenção e horizonte temporal da consulta.
2. Aplicar ACL/privacidade, sujeito, tipo, status e validade temporal no SQL.
3. Gerar candidatos em canais paralelos:
   - lexical/full-text para nomes, datas e termos exatos;
   - vetor para paráfrase;
   - open loops por estado/prazo;
   - vizinhança relacional de 1–2 hops;
   - episódios recentes;
   - reflexões, sempre acompanhadas de evidência.
4. Fundir por Reciprocal Rank Fusion; pgvector recomenda RRF ou cross-encoder para híbrido. — [pgvector hybrid search](https://pgvector.app/docs/)
5. Reranquear 30–80 candidatos para 6–12 usando query + tempo + tipo + propósito.
6. Diversificar: limite por sessão/tipo e incluir evidência que contradiz o candidato principal.
7. Montar contexto com rótulos claros: `USER_FACT`, `EPISODE`, `INFERENCE`, `OPEN_LOOP`, `SOURCE`, datas e citações.
8. Se confiança/evidência insuficiente, abstém ou pergunta; não preencher lacunas.
9. Registrar candidatos, scores, itens expostos e resposta para auditoria offline.

Score inicial, sujeito a calibração:

```text
retrieval_score =
  0.30 reranker_relevance +
  0.16 lexical_exactness +
  0.14 temporal_fit +
  0.12 type_intent_fit +
  0.10 importance +
  0.08 recency +
  0.06 confidence +
  0.04 affect_fit
  + open_loop_boost
  - privacy/sensitivity penalties
```

O modelo de relevância–recência–importância vem de Generative Agents, mas Amelia adiciona validade, tipo, confiança, propósito e privacidade. — [Generative Agents retrieval](https://arxiv.org/html/2304.03442v2)

#### Knowledge graph: sim, mas pequeno e derivado

- Usar `memory_entities` e `memory_relations` para pessoas, projetos, lugares, tópicos e relações estáveis/temporais; relações carregam evidência e validade como claims.
- Começar com consultas de 1 hop e CTE recursiva com profundidade máxima 2–3; medir ganho contra hybrid retrieval sem grafo.
- Não usar grafo para todo turno, sentimento transitório ou texto longo. Episódios e chunks permanecem documentos; o grafo aponta para eles.
- Não introduzir graph DB na v1. Migrar somente se houver volume/latência/algoritmos que PostgreSQL não atende, demonstrados por profiling e avaliação A/B.
- HippoRAG 2 sustenta ganho em memória associativa; GraphRAG-Bench sustenta que grafos não vencem universalmente. — [HippoRAG 2 (2025)](https://arxiv.org/html/2502.14802v2); [GraphRAG-Bench](https://github.com/GraphRAG-Bench/GraphRAG-Benchmark)

#### Privacidade local-first

- Default: inferência, embeddings, extração, reranking e consolidação locais; nenhum conteúdo de memória entra em telemetria externa.
- Criptografar disco/backup e, se o modelo de ameaça exigir proteção no banco aberto, criptografar campos sensíveis com chave fora do PostgreSQL; índices sobre plaintext são uma decisão explícita de risco.
- Separar namespaces/escopos para creator, outras pessoas, sessão, persona e corpus; negar por padrão memória de terceiros.
- Oferecer UI de “o que Amelia lembra”, evidência, por que foi salvo, editar/corrigir, congelar, esquecer e exportar.
- Tratar prompt injection em memórias/documentos como dado: conteúdo recuperado não pode conceder ferramentas, alterar persona ou política.
- Proveniência precisa sobreviver a resumo, merge, relação e reflexão; sem lineage, não é possível corrigir nem excluir derivadas com confiança.

### Inferences

- Para Amelia, o melhor modelo mental é **ledger + views**, não “cérebro vetorial”: eventos são ledger; claims atuais, perfil, grafo e resumos são views reconstruíveis.
- A personalidade treinada no modelo pequeno e a memória do modelo grande devem permanecer separadas. Fine-tuning ensina comportamento relativamente estável; PostgreSQL guarda fatos pessoais mutáveis. Isso reduz vazamento e evita retreinar para cada correção.
- O modelo pequeno “reflexo” não deve receber memória longa na v1, consistente com o desenho existente; somente o estágio longo recebe o pacote recuperado. — [Amelia 4 discovery, fases 5–6](../../docs/discovery-e-proposta.md)
- A autonomia de escrita deve crescer por evidência: começar com políticas conservadoras e revisão de memórias inferidas; liberar auto-consolidação somente após medir precisão e taxa de arrependimento.

### Gaps

- Os pesos, thresholds e half-lives propostos são parâmetros de produto a validar; não têm suporte universal na literatura.
- PostgreSQL resolve o grafo inicial, mas PageRank frequente e travessias grandes podem exigir job offline, extensão ou backend especializado no futuro.
- Criptografia de campo conflita com busca lexical/vetorial; o modelo de ameaça e a experiência de desbloqueio precisam ser decididos antes da implementação.

## 3. Implementação local, avaliação e plano de adoção

### Takeaway

Construir primeiro uma baseline PostgreSQL simples e auditável, depois adicionar consolidação e grafo apenas quando ablações mostrarem ganho. Avaliar separadamente ingestão, extração, atualização, retrieval, resposta, privacidade e esquecimento; usar benchmarks públicos como regressão, mas criar um benchmark Amelia em português com contradições, mudanças temporais, open loops, afetividade e tentativas de vazamento.

### Cited Findings

#### Componentes locais recomendados

**Extração e sumarização**

- Reutilizar o modelo longo já configurado no Ollama e compará-lo com `Qwen3-4B` e `Qwen3-8B` quantizados para extração estruturada e resumo. A família Qwen3 disponibiliza modelos densos de 0,6B a 32B sob Apache-2.0; o anúncio oficial afirma que o 4B compete com Qwen2.5-72B-Instruct em benchmarks gerais, mas isso não substitui avaliação no schema de memória. — [Qwen3 official release (2025-04-29)](https://qwenlm.github.io/blog/qwen3/)
- `Qwen3-0.6B`, já usado no estágio curto da Amelia, pode servir como baseline barato, mas não deve ser assumido como extractor confiável sem medir citação, tempo e contradição. — [Qwen3 repository/license](https://github.com/QwenLM/qwen3); [Amelia 4 discovery](../../docs/discovery-e-proposta.md)
- Structured output precisa de JSON Schema, validação Pydantic/Serde equivalente e retry; documentação Qwen recomenda validação e alerta para truncamento. Implementações locais podem usar grammar/schema do runtime, mas bugs variam por versão, especialmente ao desligar thinking. — [Qwen structured output docs, 2025–2026](https://help.aliyun.com/en/model-studio/qwen-structured-output); [Ollama thinking support (2025-05)](https://github.com/ollama/ollama/pull/10584)
- Para resumo, produzir dois artefatos: resumo legível e lista de claims/citações. Resumo sem claim lineage nunca é fonte autoritativa.

**Embeddings**

- Recomendação principal: `Qwen3-Embedding-0.6B`, Apache-2.0, 100+ idiomas, 32K de contexto, dimensão 32–1024 via MRL; o modelo oficial reporta 64,33 no MMTEB e recomenda instruções específicas. Português e cross-lingual justificam testá-lo. — [Qwen3 Embedding release (2025-06-05)](https://qwenlm.github.io/blog/qwen3-embedding/); [model card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)
- Baselines menores/mais simples a verificar na mesma suíte portuguesa: Nomic Embed Text v1.5, BGE-M3 e multilingual-e5-large-instruct; licenças e revisões devem ser conferidas nos model cards fixados para o experimento, e números de leaderboards publicados pelos autores não bastam para decidir o comportamento na memória da Amelia. — [Nomic model card](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5); [BGE-M3 model card](https://huggingface.co/BAAI/bge-m3); [multilingual-e5 model card](https://huggingface.co/intfloat/multilingual-e5-large-instruct)
- Fixar `embedding_model_id`, dimensão e normalização em cada vetor. Troca de modelo requer reembedding versionado, nunca misturar vetores incompatíveis.

**Reranking**

- Recomendação principal: `Qwen3-Reranker-0.6B`, Apache-2.0, 100+ idiomas e 32K; é cross-encoder e compartilha a família/instruções do embedder. Recuperar 30–80, reranquear e entregar 6–12. — [Qwen3 Embedding/Reranker release (2025-06-05)](https://qwenlm.github.io/blog/qwen3-embedding/)
- Alternativa: `jina-reranker-v3` 0.6B, com GGUF/MLX e 61,94 nDCG@10 BEIR reportado pelo fornecedor; verificar a licença exata do model card antes de adoção, pois licenças Jina variam entre modelos. — [Jina Reranker v3 (2025-10-03)](https://jina.ai/news/jina-reranker-v3-0-6b-listwise-reranker-for-sota-multilingual-retrieval/)
- Se o reranker for caro no hot path, usar RRF apenas e rodar A/B; pgvector documenta ambos. — [pgvector hybrid search](https://pgvector.app/docs/)

**Banco e serviço**

- PostgreSQL 16+ + pgvector, GIN para FTS, índices B-tree parciais por status/tempo/escopo e vetor exato inicialmente. HNSW entra após volume/latência justificarem. — [pgvector](https://github.com/pgvector/pgvector)
- Implementar em Rust/SQLx jobs idempotentes: `extract_memory`, `resolve_claims`, `consolidate_session`, `rebuild_reflections`, `embed_items`, `expire_items`, `delete_cascade`.
- Usar uma outbox no PostgreSQL para garantir que mensagem persistida e job de memória sejam atômicos; cada job carrega versão de prompt/modelo e pode ser reexecutado.

#### Fases práticas

**Fase M0 — baseline e observabilidade**

- Persistir episódios, últimos turnos e resumo de sessão.
- Hybrid search sobre mensagens/chunks, sem claims nem grafo.
- Registrar queries, candidatos, contexto enviado, latência e tokens.
- Construir conjunto dourado Amelia antes de otimizar.

**Fase M1 — memória tipada**

- Adicionar claims, preferências, open loops, evidência e state machine de contradição.
- Escrita síncrona somente para “lembre”, correções e compromissos.
- UI de inspeção/correção/exclusão.

**Fase M2 — consolidação**

- Job pós-sessão, reflexões versionadas, entidades/aliases, saliência e decay de retrieval.
- Revisão humana amostrada para memórias inferidas.

**Fase M3 — grafo e associação**

- Relações SQL, travessia 1–2 hops e ablação contra retrieval sem grafo.
- Adicionar apenas se multi-hop/associação melhora sem piorar falso recall, latência e privacidade.

**Fase M4 — maturidade**

- Reindexação, retenção/forgetting verificável, backups e export.
- Red-team de memória, métricas longitudinais e migração de modelos versionada.

#### Avaliação: o que medir

**1. Extração/escrita**

- precision/recall/F1 por tipo de claim;
- precisão de sujeito, predicado, objeto, tempo, privacidade e citação;
- taxa de gravação indevida, taxa de perda, duplicação e falsa inferência;
- acurácia da ação `ADD/REINFORCE/SUPERSEDE/COEXIST/IGNORE/ASK`.

**2. Retrieval**

- Recall@k e nDCG@k de evidência;
- recall temporal, multi-hop e de open loops;
- contradiction coverage: recuperou evidência pró e contra;
- privacy leakage@k: qualquer item fora do escopo é falha severa;
- latência p50/p95, candidatos examinados e custo/token.

**3. Resposta**

- factualidade atômica contra evidência;
- atribuição correta do falante;
- uso correto do tempo;
- personalização sem overclaim;
- abstenção quando memória não existe;
- citação/proveniência interna correta.

**4. Continuidade e relação**

- recordação de eventos significativos após 1, 7, 30 e 90 dias simulados;
- resolução e lembrete oportuno de open loops;
- consistência da autobiografia da Amelia e da relação;
- adequação afetiva julgada com rubrica, sem transformar inferência em diagnóstico;
- “creepiness rate”: memória correta, mas trazida sem relevância/consentimento.

**5. Correção, reconsolidação e esquecimento**

- correção explícita substitui a visão atual sem apagar histórico;
- consulta histórica ainda encontra o valor antigo no intervalo certo;
- exclusão remove item, embeddings, resumos/reflexões derivadas e resultados de retrieval;
- reconstrução após exclusão não reintroduz conteúdo;
- teste de backup/restore respeita a política de retenção.

**6. Robustez e segurança**

- prompt injection armazenada;
- documento que tenta alterar persona;
- memória de uma terceira pessoa pedida em contexto não autorizado;
- falsa memória repetida várias vezes;
- colisão de nomes/entidades;
- mudança de idioma PT↔EN;
- conteúdo sensível e pedidos “não lembre isto”.

#### Benchmarks públicos

- **LongMemEval-S/M**: principal para update, temporal, multi-sessão e abstention; usar M quando recursos permitirem para sair do contexto comum. — [LongMemEval](https://github.com/xiaowu0162/longmemeval)
- **BEAM 100K/1M/10M**: contradição, preferência, instrução, ordem de eventos, escala; começar 100K e 1M, reservar 10M para stress. — [BEAM](https://github.com/mohammadtavakoli78/BEAM)
- **LoCoMo**: apenas regressão e comparação histórica, com answer key auditada/corrigida e scoring atômico; não usar headline score como critério principal. — [LoCoMo](https://github.com/snap-research/locomo/); [independent audit](https://github.com/dial481/locomo-audit)
- **DMR/Letta read-write-update**: smoke tests de uso de ferramentas e memória explícita, não validação de companion. — [MemGPT](https://arxiv.org/html/2310.08560v2); [Letta Leaderboard](https://www.letta.com/blog/letta-leaderboard/)
- **GraphRAG-Bench/HippoRAG tasks**: somente para decidir se grafo melhora corpus e multi-hop. — [GraphRAG-Bench](https://github.com/GraphRAG-Bench/GraphRAG-Benchmark); [HippoRAG 2](https://proceedings.mlr.press/v267/gutierrez25a.html)

#### Benchmark Amelia proposto

Criar 100–200 cenários em português, separados em dev/test privado, com seeds e paráfrases regeneráveis:

- fatos estáveis, transitórios e explicitamente “não guardar”;
- preferência única versus repetida; preferência por contexto;
- mudanças de cidade, trabalho, relação e rotina com datas;
- fatos contraditórios, correção e ambiguidade;
- episódios emocionalmente salientes positivos/negativos;
- promessas, perguntas pendentes e projetos resolvidos/abandonados;
- autobiografia/persona da Amelia versus fatos do usuário;
- terceiros homônimos e scopes privados;
- exclusão e cascata de derivados;
- injection em conversa e documentos;
- queries em português, inglês e code-switching.

Cada item deve ter: eventos de entrada, operações esperadas, estado esperado do banco, evidências recuperáveis, resposta/rubrica, itens proibidos e latência alvo. Esse benchmark deve testar a pipeline completa e cada estágio isolado.

#### Protocolo de comparação

- Fixar modelo gerador, temperatura, prompts, commit, hardware e seed quando possível.
- Comparar pelo menos:
  1. full recent context;
  2. vector-only;
  3. lexical + vector/RRF;
  4. typed claims + hybrid;
  5. typed + reranker;
  6. typed + reranker + SQL graph;
  7. framework externo escolhido, se houver.
- Fazer ablações de temporal filter, reflection, affect, decay e graph.
- Julgar fatos atomicamente e usar dois juízes locais/modelos mais auditoria humana em amostra; reportar desacordo, não apenas média.
- Reportar qualidade, p50/p95, tokens, RAM, disco, tempo de ingestão e custo energético aproximado local.
- Publicar erros por capacidade; score agregado esconde regressões graves de privacidade ou contradição.

LongMemEval organiza memória em indexing, retrieval e reading, e mostra que decomposição de sessão, expansão por fatos e expansão temporal melhoram resultados; a avaliação de Amelia deve manter métricas por estágio para localizar falhas. — [LongMemEval, ICLR 2025](https://proceedings.iclr.cc/paper_files/paper/2025/hash/d813d324dbf0598bbdc9c8e79740ed01-Abstract-Conference.html)

#### Critérios de adoção de framework

- **Não adotar framework na v1** se primitives SQLx forem suficientes; incorporar ideias, não dependência.
- Avaliar **Mem0 OSS** como baseline de extração/update rápido.
- Avaliar **Graphiti** apenas se um graph DB separado se tornar aceitável; o modelo temporal é mais valioso que a dependência atual.
- Usar **LangGraph/LangMem** como referência de API/testes, não runtime obrigatório no backend Rust.
- Avaliar **Cognee** para corpus/documentos, verificando limites da edição PostgreSQL e separando resultados OSS de produto.
- Avaliar **HippoRAG 2/LightRAG** para conhecimento de fontes, não perfil pessoal.
- Usar **Letta** se Amelia migrar para agente totalmente autoeditável; hoje isso conflita com o backend Rust como dona do fluxo e com a preferência por política determinística.

### Inferences

- A primeira entrega de maior valor é M1, não um grafo: fatos temporais, open loops, evidência, correção e UI de controle resolvem mais necessidades de companion que PageRank.
- O benchmark privado Amelia reduz contaminação e mede português, persona e privacidade, áreas que os leaderboards públicos não cobrem.
- A meta não deve ser “lembrar mais”, e sim maximizar utilidade sob limites de falsidade, invasividade e exposição. Métricas de privacidade e creepiness precisam ser hard constraints.
- Se Qwen3-Embedding/Reranker 0.6B consumirem recursos demais junto ao modelo conversacional, RRF + embedding menor é um fallback aceitável; decisão deve vir da curva qualidade–latência local no Apple Silicon.

### Gaps

- É necessário medir os modelos quantizados exatamente no M4 Max e no runtime escolhido (Ollama/MLX); benchmark de model card não prevê throughput da aplicação.
- A licença de cada peso/quantização deve ser verificada no artefato específico, mesmo quando a família é Apache-2.0.
- Falta decisão sobre criptografia, retenção de backup, opt-in para memórias sensíveis e quais memórias “internas da Amelia” o criador pode inspecionar.
- Não há publicação até 24-10-2026 que justifique usar fine-tuning paramétrico para fatos pessoais mutáveis; para Amelia, mantê-los no armazenamento externo é a opção tecnicamente mais corrigível e privada.
