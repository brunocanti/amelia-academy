# Amelia 4 — Discovery e proposta

24 de outubro de 2026. Documento de desenho inicial. O Amelia 3 fica intacto em `~/Projects/Amelia3` e serve de referência.

A Amelia 4 guarda a parte que ainda vale — dataset com revisão humana e fine-tuning local — e troca o que foi construído à mão por ferramentas que já existem. O pipeline ganha um passo anterior: arquivos de referência sobem primeiro, e os temas nascem desses arquivos antes de qualquer sample.

> **Implementação descartada:** a primeira tentativa de código foi apagada. O que ela errou, e o que a próxima não pode repetir, está em [`erros-da-primeira-implementacao.md`](erros-da-primeira-implementacao.md).
>
> **Revisão após pesquisa:** o desenho de dois estágios abaixo é uma hipótese inicial, não a arquitetura recomendada. A revisão em [`reports/Psique memória e modelos.md`](../reports/Psique%20memória%20e%20modelos.md) propõe o **Amelia Mind**: memória compartilhada pelo runtime, workspace limitado, appraisal, scheduler, deliberação sob orçamento e policy gates. “Consciente”, “pré-consciente”, “inconsciente”, “ego”, “id” e “superego” continuam como vocabulário da Amelia, mas cada nome passa a apontar para um mecanismo observável. O Academy administra conhecimento e comportamento estáveis; o Mind administra memória episódica e mudança.

---

## 1. O que a Amelia 3 realmente é

A Amelia começou em 2019 como um agente de conversa com uma personalidade estável, inspirada numa leitura própria da psicologia freudiana e na personagem da canção. O código que ficou de pé em 2025 é mais concreto do que o mito das três camadas.

O caminho que chegou a treinar de verdade é este:

1. Um padrão descreve uma situação de conversa: intenção, tom, diretrizes de resposta, público (`creator` ou `others`), privacidade, camada alvo, elementos-chave e cenários.
2. Um LLM local gera samples em lote, com variação de contexto. O lote fica só em memória.
3. A pessoa aprova ou rejeita. Só o aprovado entra no banco.
4. Os samples aprovados viram um dataset.
5. Um job de LoRA treina um modelo pequeno.
6. Na conversa, esse modelo pequeno tenta responder direto. Se não cobre o caso, a conversa segue para um modelo maior, com memória.

O último treino concluído, em 25 de julho de 2025, é LoRA do `Qwen/Qwen3-0.6B` no MLX, adapter `MLXQwen06b2EpochsSuper`, sem tokens especiais inventados. A documentação mais antiga ainda fala em SmolLM2-360M. A ideia que sobreviveu à troca de modelo é o modelo pequeno condicionado como reflexo, com o modelo base tratado como parâmetro.

Em volta disso existe um sistema grande: FastAPI, SvelteKit, PostgreSQL no schema `amelia_memory`, Ollama, pgvector, dezenas de planos em `docs/`, e várias gerações de arquivos `_old`. MemGraph aparece nos princípios e está fora do caminho de produção. PyTorch e MLX conviveram; o treino que ficou é MLX, no Apple Silicon.

As superfícies da interface são chat, treino, padrões de conditioning, limpeza de samples, memória, uma visualização “mind” e uma área de developer.

---

## 2. O que entra na Amelia 4

Estas peças são o produto. Framework nenhum as substitui.

**Oficina de samples com portão humano.** O lote é gerado, mostrado e só gravado depois da aprovação. Esse corte entre “gerado” e “aceito” é o que mantém o dataset honesto.

**Padrão como unidade de comportamento, agora filho de um tema.** A ficha que já existe continua fazendo sentido: descrição, intenção, tom desejado, diretrizes de resposta, público, privacidade, estágio da conversa, elementos que a resposta precisa carregar, cenários. Na Amelia 4 essa ficha nasce de um tema extraído das fontes, e ainda pode ser escrita à mão quando não houver arquivo.

**Variação de verdade, não paráfrase.** O gerador de lote já pede ao LLM situações diferentes. Os eixos que valem a pena guardar:

- público: criador ou outras pessoas
- estágio da conversa
- nível de privacidade
- tom
- contexto anterior presente ou ausente
- sample negativo: o tema não se aplica, e a resposta precisa recusar, desviar ou escalar com naturalidade

A mistura que o gerador já buscava — por volta de 60% positivos, 15% de borda, 25% negativos — continua como alvo de balanceamento, visível no relatório do dataset.

**Deduplicação por mensagem normalizada mais tipo de público.** A mesma frase dita pelo criador e por outra pessoa são samples diferentes.

**Dataset e treino separados.** Gerar arquivo e disparar LoRA são trabalhos distintos. Um dataset versionado pode treinar mais de um job.

**Poucos knobs na interface de treino.** Learning rate e épocas vêm da pessoa. O resto — rank do LoRA, batch, módulos alvo, comprimento — vem de um template por modelo base, já medido na máquina. O template do Qwen3-0.6B no M4 Max é o primeiro.

**O chat template é o do modelo base.** O Amelia 3 chegou a escrever um Jinja próprio e documentou o estrago: treino e inferência divergem em silêncio. Na exportação, as mensagens guardadas como papéis (`system`, `user`, `assistant`) passam pelo `chat_template` que veio com o tokenizer. Tags de raciocínio, se entrarem no dataset, usam o formato desse modelo. No Qwen3 isso é o bloco de thinking do próprio modelo.

**Identidade como dado.** Nome, voz, relação com o criador, o que ela conta sobre si e o que não conta ficam num arquivo de persona versionado. O código não carrega frase de personalidade.

**Local primeiro.** Ollama para gerar temas e samples e para a conversa longa. PostgreSQL para o estado. MLX para o LoRA. Nada disso depende de API paga para o fluxo principal.

**Dois tempos na conversa.** O modelo pequeno responde quando o caso cabe no que foi treinado. O modelo grande responde quando não cabe, e é ele que recebe memória. Os nomes das camadas podem voltar na interface se fizerem sentido para a persona. No código da primeira versão existem dois estágios, porque preconscious, unconscious e a validação estrutural de ego/superego não fecharam como comportamento estável.

**Memória curta de verdade.** As últimas falas da sessão entram no estágio longo. Resumo de sessão fica para quando a conversa passar de um tamanho. Embedding entra para achar trechos parecidos, não para decidir a resposta no lugar do modelo treinado.

---

## 3. O que fica de fora da primeira versão

- MemGraph e qualquer segundo banco de grafo. Relação entre memórias, se voltar, nasce dentro do PostgreSQL.
- Dois motores de treino. A primeira versão treina com MLX nesta máquina. PyTorch volta só se aparecer um alvo que não seja Apple Silicon.
- Tokens especiais “da Amelia” acrescentados ao vocabulário. A remoção deles já foi a decisão certa.
- A biblioteca de ícones, o protocolo de WebSocket com eventos próprios, o cache de sessão que morre quando o processo reinicia, e as seis funções de geração que fazem variações da mesma coisa.
- A visualização “mind” e o browser de grafo de memória.
- Autenticação de vários usuários. A Amelia 4, nesta fase, é um estúdio de uma pessoa nesta máquina.
- Reimplementar o loop de LoRA em Rust. O ecossistema que já treinou o Qwen3-0.6B é o `mlx-lm`. O backend Rust dispara esse trabalho, lê o progresso e guarda o adapter.

---

## 4. O que deixa de ser feito à mão

| Peça feita à mão no Amelia 3 | O que passa a fazer esse trabalho |
| --- | --- |
| Chat em Svelte: streaming, input, painel de raciocínio, histórico, websocket próprio | [assistant-ui](https://www.assistant-ui.com/) no React, com um adapter fino que fala com o backend |
| DaisyUI e o conjunto próprio de ícones | Tailwind e shadcn/ui, ícones Lucide, nas telas de estúdio |
| Eventos `pipeline_step`, `token`, `complete` num WebSocket caseiro | SSE com poucos eventos estáveis. O chat usa o runtime do assistant-ui. Jobs de geração e de treino usam o mesmo tipo de stream |
| Cliente Python em volta do Ollama | Cliente HTTP no Rust. Ollama já é uma API |
| Leitura de PDF, DOCX e texto, que não existia | [`extractous`](https://github.com/yobix-ai/extractous) para extrair texto no processo Rust. Markdown e txt entram direto |
| `sentence-transformers` e mais um índice vetorial | Um embedder só. Primeira opção: Ollama com o mesmo modelo de embedding da casa, gravado em `pgvector`. `fastembed` fica como alternativa se a geração de embedding precisar sair do Ollama |
| HDBSCAN para inventar tópicos | O LLM propõe temas a partir dos trechos, com citação. Embedding só serve para avisar que dois temas estão perto demais |
| Biblioteca de paráfrase por cima do sample | O próprio lote pede situações novas. Paráfrase mecânica sai |
| Jinja de chat escrito no projeto | `chat_template` do tokenizer do modelo base, aplicado na exportação pelo worker |
| PyTorch e MLX, subprocesso e três cargas do dataset | Um job, um comando `mlx-lm`, um dataset já exportado |
| Arquivo JSON de progresso mais streamer próprio | O worker escreve eventos; a API repassa em SSE |
| Monaco para editar o YAML do sistema no meio da UI | Persona e templates de treino são arquivos no repositório. A UI edita temas, amostras e jobs |
| JWT, sessões e cadastro completos | Operador local, sem conta |

O assistant-ui entra na superfície de conversa. A oficina de temas, samples e treino é um estúdio, e aí o shadcn chega melhor: tabelas, formulários, painéis de revisão. Os dois convivem no mesmo app React.

---

## 5. O passo novo: fontes, depois o grafo, depois samples

Esta seção, em outubro, separava tema extraído e ficha de comportamento. Isso foi construído e depois recolhido. O fluxo em pé está em [`docs/architecture/estado-atual.md`](architecture/estado-atual.md): um grafo, nó de conhecimento ou nó de comportamento, e samples a partir do nó selecionado como tema. O desenho abaixo fica como histórico da proposta, não como instrução.

Hoje o padrão nasce de uma descrição escrita na hora, ou de uma sugestão do LLM em cima dessa descrição. A Amelia 4 coloca um corpus na frente.

```
arquivos de referência
        ↓
extração e trechos, com proveniência
        ↓
temas propostos, cada um com citações
        ↓
revisão humana do tema
        ↓
ficha de comportamento (o antigo pattern)
        ↓
lote de samples ancorado no tema e nos trechos
        ↓
aprovação
        ↓
dataset versionado
        ↓
LoRA
        ↓
conversa
```

Uma fonte é um arquivo que a pessoa considera matéria da Amelia: notas, transcrições, textos de referência, um markdown de princípios, uma conversa exportada. O sistema guarda o arquivo, o hash e o texto extraído. Cada trecho aponta para o arquivo e para a posição.

Um tema é uma unidade ensinável descoberta nesse material. A proposta de tema traz:

- título curto
- resumo do que a Amelia deve saber fazer nessa área
- limites: o que esse tema não autoriza
- tom
- público sugerido
- citações com ponteiro para o trecho de origem
- temas vizinhos, para a pessoa fundir ou separar

A pessoa aceita, edita, funde ou descarta. Tema aceito pode virar uma ou mais fichas de comportamento. A ficha é o contrato da geração: diretrizes, tom, público, negativos. O tema é a origem e o contexto. Separar os dois evita que o arquivo inteiro vire um prompt gigante na hora de gerar o sample.

A geração de samples recebe a ficha e um punhado de citações, e devolve um lote. Cada sample guarda de qual tema veio e quais trechos usou. Na oficina, a pessoa vê a resposta e a origem lado a lado.

Dá para criar uma ficha sem arquivo. O passo das fontes é o caminho principal, e o caminho antigo continua disponível.

---

## 6. Arquitetura

```
React (Vite)
  estúdio: fontes, temas, fichas, samples, datasets, jobs
  conversa: assistant-ui
        │  HTTP + SSE
        ▼
Rust (Axum)
  API, estado, filas no Postgres, extração, proposta de temas,
  geração de samples via Ollama, exportação, promoção de adapter
        │
        ├── PostgreSQL + pgvector
        ├── disco local: originais, exports, adapters
        ├── Ollama: temas, samples, conversa longa, embeddings
        └── worker MLX: mlx-lm lora, mesmo binário Rust dispara o processo
```

O backend é a dona do fluxo. O React não chama Ollama nem o MLX. Assim a proveniência, a deduplicação e o portão de aprovação acontecem num lugar só.

O worker de treino é um processo filho. O Rust escreve o diretório do dataset no formato que o `mlx-lm` espera, monta o comando a partir do template do modelo mais learning rate e épocas, e acompanha stdout. O adapter resultante entra numa linha de `training_jobs` com caminho e métricas. Promover um adapter é uma ação explícita: a conversa passa a carregar aquele adapter no estágio curto.

Inferência do modelo pequeno fica no próprio `mlx-lm` (servidor local ou chamada de geração), que é o runtime em que o adapter foi treinado. Ollama continua responsável pelo modelo grande. Os dois estão atrás da API Rust, e a tela só enxerga um stream.

### Módulos Rust

- `sources` — upload, hash, extração, trechos
- `themes` — proposta, revisão, fusão
- `behaviors` — a ficha, herdeira de `conditioning_patterns`
- `samples` — lote, aprovação, hash, negativos
- `datasets` — recorte, estatística, exportação com o chat template
- `training` — templates, jobs, log, promoção
- `chat` — sessão, estágio curto, estágio longo, memória recente
- `persona` — carga do arquivo de identidade

### Contrato de stream

Geração de temas, geração de samples e treino emitem eventos curtos: `started`, `progress`, `item`, `done`, `failed`. O chat emite `stage` (qual estágio respondeu), `token` e `done`. O adapter do assistant-ui traduz isso para o componente de mensagem. O painel de raciocínio, quando o modelo grande devolver thinking, usa o componente de reasoning do assistant-ui.

---

## 7. Modelo de dados

PostgreSQL continua sendo o sistema de registro. Schema novo, desenhado para este fluxo. Nada de migrar o schema `amelia_memory` para dentro da Amelia 4; se um dia algum dataset antigo interessar, a importação é um script à parte.

```text
sources
  id, filename, media_type, sha256, stored_path, extracted_text, status, created_at

chunks
  id, source_id, ordinal, text, char_start, char_end

themes
  id, title, summary, boundaries, tone, audience, status, created_at
  status: proposed | accepted | rejected | merged

theme_evidence
  theme_id, chunk_id, quote

behaviors
  id, theme_id nullable, title, description, intent, tone, guidelines,
  audience, privacy, layer_hint, key_elements jsonb, scenarios jsonb,
  samples_target, status

samples
  id, behavior_id, audience, kind,          -- positive | edge | negative
  user_message, assistant_message,
  context jsonb,                            -- histórico sintético, se houver
  provenance jsonb,                         -- theme_id, chunk ids, batch id
  content_hash, status,                     -- draft | approved | rejected
  batch_id, created_at

datasets
  id, name, behavior_ids, sample_count, stats jsonb,
  export_path, base_model, created_at

training_jobs
  id, dataset_id, base_model, status, learning_rate, epochs,
  template jsonb, log_path, adapter_path, metrics jsonb,
  started_at, finished_at

adapters
  id, job_id, base_model, path, promoted, promoted_at

sessions / messages
  sessão, papel, texto, estágio que respondeu, created_at
```

`content_hash` é SHA-256 de mensagem normalizada mais público. Amostras aprovadas de um mesmo behavior não repetem esse hash.

O export de treino é JSONL de mensagens. A coluna de thinking, quando existir, já vai no conteúdo do assistant no formato do modelo alvo. O arquivo de treino é derivado. A fonte editável continua sendo a tabela `samples`.

---

## 8. Telas

Uma aplicação, duas áreas.

**Estúdio**

1. Fontes — subir, ver texto extraído, apagar.
2. Temas — lista de propostas, citações ao lado, aceitar, editar, fundir, rejeitar.
3. Fichas — o contrato de geração, ligado ou não a um tema.
4. Oficina — disparar um lote, ler sample com a citação de origem, aprovar, rejeitar, editar o texto antes de aprovar.
5. Dataset — escolher fichas, ver contagem por público e por tipo (positivo, borda, negativo), duplicatas, exportar.
6. Treino — escolher dataset e modelo base, ajustar learning rate e épocas, acompanhar o log, promover o adapter.

**Conversa**

Histórico de sessões e a thread, ambos com assistant-ui. Acima da resposta, um indicador pequeno do estágio: reflexo (modelo treinado) ou conversa (modelo grande). O painel de pipeline com quatro camadas sai. O que a pessoa precisa ver é qual modelo falou e, no modelo grande, o reasoning quando ele existir.

---

## 9. Stack fechada para a primeira versão

**Backend**

- Rust estável, Axum, Tokio, SQLx
- PostgreSQL 16+ com pgvector
- extractous para PDF e DOCX
- reqwest para o Ollama
- Serde
- disco local para arquivos e adapters
- processo filho para `mlx-lm`

**Frontend**

- Vite, React, TypeScript
- TanStack Router e TanStack Query
- Tailwind e shadcn/ui no estúdio
- assistant-ui na conversa
- um cliente SSE compartilhado pelos jobs e pelo chat

**Máquina e modelos**

- Esta máquina, Apple Silicon, MLX
- Modelo curto inicial: `Qwen/Qwen3-0.6B`, porque já existe template e um adapter de referência no Amelia 3
- Modelo longo: o que já estiver no Ollama para raciocínio, configurável
- Embedding: um modelo só, via Ollama, dimensão gravada na migração

**Persona**

- Um arquivo TOML ou YAML no repositório, carregado na subida. Se faltar, o processo não sobe. O Amelia 3 já tinha essa regra e ela evitou resposta genérica no lugar da Amelia.

---

## 10. Fases

Cada fase termina com algo que dá para usar sozinho.

**Fase 0 — este documento.** Desenho aceito, decisões em aberto respondidas.

**Fase 1 — esqueleto.** API Rust no ar, React no ar, Postgres com as tabelas, healthcheck, persona carregada. Sem modelo ainda.

**Fase 2 — fontes e temas.** Upload, extração, trechos, proposta de temas com citação, revisão na tela. Este é o passo que o Amelia 3 não tinha.

**Fase 3 — oficina.** Ficha a partir de um tema, lote via Ollama, aprovação, hash, edição. Dá para exportar JSONL das aprovadas mesmo antes do treino existir na UI.

**Fase 4 — dataset e treino.** Relatório de balanceamento, export no chat template do Qwen3, job MLX, log na tela, adapter no disco.

**Fase 5 — conversa.** assistant-ui, estágio curto com o adapter promovido, estágio longo via Ollama, histórico de sessão persistido.

**Fase 6 — memória curta no estágio longo.** Últimas falas e, depois, resumo. O estágio curto permanece sem memória longa: ele responde o que foi treinado.

Avaliação automática do adapter fica para depois da fase 4, com um conjunto pequeno de samples aprovados segurados fora do treino. Antes disso, a avaliação é a própria oficina e uma conversa manual.

---

## 11. Decisões que ainda são suas

1. **A persona continua pessoal.** A relação com o criador, o tratamento, o que ela revela sobre a própria origem: isso segue como dado da Amelia, ou a primeira versão trata a persona como um perfil trocável e a Amelia específica entra só como o primeiro perfil?
2. **Língua do dataset.** Um dataset mistura português e inglês, ou a primeira leva é só português?
3. **Thinking dentro do modelo pequeno.** O Qwen3 já pensa por conta própria. A primeira leva ensina só a resposta final, e o thinking fica no modelo grande?
4. **Nomes das camadas na tela.** O código nasce com dois estágios. A interface fala “reflexo” e “conversa”, ou você prefere manter conscious / preconscious / unconscious como vocabulário visível?
5. **O que sobe como primeira fonte.** Quais arquivos existentes — princípios, transcrições, notas — entram no primeiro corpus para testar a extração de temas?

Enquanto essas respostas não vêm, o desenho assume: persona única da Amelia, dataset em português, modelo pequeno sem canal de thinking, interface com os dois estágios em linguagem simples, e nenhum arquivo copiado do Amelia 3 até você apontar quais.

---

## 12. De onde cada ideia veio

| Ideia na Amelia 4 | Onde vive no Amelia 3 |
| --- | --- |
| Ficha de comportamento | `conditioning_patterns` e `PatternManager` |
| Lote em memória e gravação só do aprovado | `DataGenerator.generate_incremental_batch` e `save_approved_samples` |
| Eixos de variação e sample negativo | gerador, `QualityValidator`, spec de negative samples |
| Hash de mensagem + público | `_normalize_message_hash` |
| Dataset separado do job de treino | `docs/DATASET_CREATION_REFACTORING_PLAN.md` e os routers `datasets` e `training` |
| Template de hiperparâmetros, UI com learning rate e épocas | `model_training_templates.py` e `CLAUDE.md` |
| Chat template do modelo, sem token inventado | `docs/CHAT_TEMPLATE_INTEGRATION_PLAN.md` e `amelia_tokens_added: 0` no metadata do Qwen3-0.6B |
| LoRA MLX como runtime de treino | `models/MLXQwen06b2EpochsSuper` |
| Dois tempos, modelo pequeno primeiro | `core/engine.py`, `layers/conscious.py`, fallback |
| Persona fora do código | `config/prompts/amelia_identity.yaml` e a regra de falhar se o template falta |
| Memória recente na conversa longa | `memory/unified_memory_manager.py`, reduzida ao que a sessão realmente usa |
| Voz e limites da personagem | `docs/AMELIA3_PRINCIPLES.md` e `docs/AMELIA_INSPIRATION.md` |

O passo das fontes e dos temas não tem antecessor no código. O que chega mais perto é o criador de padrão assistido por LLM, que sugere campos a partir de um parágrafo. Na Amelia 4 esse parágrafo deixa de ser a origem e passa a ser o resumo de um tema com citações.
