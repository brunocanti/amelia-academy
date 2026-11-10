# ADR 001 — Rust no plano de controle e Python nos workers de ML

**Status:** Accepted  
**Data:** 24 out. 2026

## Contexto

A Academy precisa manter invariantes de projeto, aprovação, jobs, artifacts e releases, ao mesmo tempo em que usa `mlx-lm`, tokenizers e avaliadores cujo ecossistema principal é Python. No Amelia 3, FastAPI, lógica de domínio, ML e acesso ao banco coexistem; exceções e fallbacks locais podem alterar o comportamento do sistema. Reimplementar treino em Rust descartaria o caminho MLX já comprovado. Dar o domínio ao Python repetiria o acoplamento.

## Decisão

Rust/Axum é o plano de controle e o único dono de API, autorização, tenancy, estado persistente, fila, auditoria, artifacts, promoção e chamadas online de inferência. Python executa tarefas ML delimitadas em processos filhos: renderização/tokenização, treino, avaliação e conversões autorizadas.

Workers não acessam PostgreSQL e não promovem entidades. Recebem manifests e grants de arquivos, emitem eventos e artifacts candidatos pelo protocolo JSONL versionado. Toda validação final e transição de estado ocorre no Rust.

## Alternativas consideradas

- **Tudo em Python/FastAPI:** melhor integração ML, mas mantém domínio, processo e dependências científicas no mesmo blast radius.
- **Tudo em Rust:** binário simples, porém exigiria reimplementar ou envolver APIs ML instáveis e perderia compatibilidade direta com MLX.
- **Serviço Python permanente:** separa processos, mas introduz deploy, autenticação e reconciliação de rede sem benefício local na v1.

## Consequências

- Invariantes permanecem tipadas, auditáveis e independentes de framework ML.
- Upgrade de biblioteca Python não exige alterar a API pública.
- Há dois toolchains, schemas compartilhados e testes de contrato obrigatórios.
- O worker pode ser substituído por outro runtime sem migrar o domínio.
- Recursos exclusivos do Python só entram após definição de contrato, não por import ad hoc.

## Validação

- Busca no pacote Python não encontra DSN nem cliente PostgreSQL.
- Teste mata o worker durante treino e confirma que o Rust recupera lease e estado.
- Golden tests serializam os mesmos envelopes em Rust e Python.
- Um worker malicioso não consegue escrever fora do output grant nem ativar release.
- O fluxo fonte→release termina com Python indisponível até a etapa ML e continua permitindo leitura/revisão.
