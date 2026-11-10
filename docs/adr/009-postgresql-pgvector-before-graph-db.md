# ADR 009 — PostgreSQL com pgvector antes de graph DB

**Status:** Accepted  
**Data:** 24 out. 2026

## Contexto

Academy precisa de busca lexical/vetorial e relações de linhagem. Mind futuramente precisará de claims, entidades, relações temporais e travessias limitadas. Amelia 3 inicializa GraphSync/MemGraph opcional, mas sua própria documentação registra que o caminho de produção permaneceu no PostgreSQL. Um segundo banco multiplica backup, autorização, exclusão e consistência sem ganho medido.

## Decisão

PostgreSQL 16+ é o sistema de registro, busca textual, relações e fila; pgvector armazena embeddings. Relações usam tabelas com proveniência e validade; travessias limitadas usam joins e CTEs recursivas. O vetor é índice derivado e reconstruível, não autoridade.

Graph DB não entra na v1. Só será considerada após corpus e consultas representativos demonstrarem, por ablação, ganho material em qualidade multi-hop que compense latência, privacidade e operação. A decisão futura exigirá ADR e plano de consistência/exclusão.

## Alternativas consideradas

- **Neo4j/MemGraph desde o início:** travessia expressiva, mas segundo sistema e sincronização prematura.
- **Graphiti:** temporalidade útil, porém importa graph DB e domínio Python.
- **Vector DB dedicado:** escala vetorial maior, desnecessária para volume local e sem joins transacionais.
- **Somente busca textual:** simples, mas perde recuperação semântica útil.

## Consequências

- Backup, autorização e apagamento ficam em um sistema.
- SQL relacional atende linhagem e um/dois hops com evidência.
- Consultas de grafo muito profundas podem ser menos eficientes.
- Dimensão/modelo de embedding são versionados; reembedding não altera a fonte.
- HNSW só entra quando volume/latência justificarem; busca exata é baseline.

## Validação

- Benchmarks medem recall, nDCG, p95 e RAM em busca lexical, vetorial, híbrida e relacional.
- Exclusão de projeto remove relações e embeddings sem resíduo externo.
- Restore único recupera registro e índices reconstruíveis.
- Critério para spike de graph DB: ganho de pelo menos 10% em conjunto multi-hop privado, sem piorar p95 em mais de 20% e com plano comprovado de backup, consentimento e deleção.
- CI impede dependência de driver de graph DB antes de novo ADR aceito.
