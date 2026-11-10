# 018. Destilar trajetórias de busca (E8, experimento)

Estado: a executar. Continua a spec 017, seções 12 e 13.

## 1. Pergunta

Um 4B treinado com trajetórias de busca aprende quando buscar, buscar de novo quando a primeira busca falha e dizer "não sei" quando nada serve? E faz isso sem perder o que o E6 sabe sem busca?

## 2. Por que

Resultados da spec 017, seção 13:

- **Destilação (E6).** Chega a ≈26 de 32 fatos e recusa 8 de 10 perguntas que a passagem não responde. Não corrige premissas sobre fatos novos (fp 2,8 de 8) e quase não recusa partes nunca lidas (u 1 de 11).
- **Agente (E7).** Com o adapter E2 e a primeira busca forçada, faz 29 de 32 e fp 5. Mas busca sempre, e as perguntas gerais caem de 14 para 10. Nunca busca uma segunda vez nem usa `read`. Nenhum modelo local, nem o qwen3:14b, decide buscar sem ser forçado.

Ensinar a usar ferramentas é treinar trajetórias. Esta é a direção do Search-R1 e do Toolformer; aqui fazemos a versão supervisionada, sem aprendizado por reforço.

## 3. Onde está tudo

Os scripts e dados ficam no scratchpad da sessão que rodou a 017. Esse caminho é a raiz do experimento; abaixo ele aparece como `SP`:

`SP = $SCRATCH`

| O quê | Caminho |
|---|---|
| Base da cópia do Comprimildo (projeto `prj_1bb36bf446f1`) | `SP/data/academy.sqlite3` |
| Dados do E6 (1.993 linhas, chat sem ferramentas) | `SP/exp2/data/E6/{train,valid}.jsonl` |
| Perguntas e respostas do professor por passagem | `SP/exp2/teacher.jsonl` (campo `teacher`), `SP/exp2/passage_qa.jsonl` |
| Perguntas sem resposta e premissas, com resposta do professor | `SP/exp2/teacher2.jsonl` (campo `kind`: `gap` ou `premise`) |
| Filtros e protetor contra vazamento | `SP/exp2/build_data3.py` (reusar `near()`, `SOURCE`, `unsupported()`, `FP_FACTS`) |
| Agente, busca, ferramentas e prompt de sistema | `SP/exp2/agent2.py` (`search()`, `read()`, `TOOLS`, `SYS`; embeddings em `SP/exp2/win_emb.json`) |
| Treino e avaliação por checkpoint | `SP/exp/train.py`, `SP/exp/pipeline.sh`, `SP/exp/eval_run.sh`, `SP/exp/answer.py` |
| Teste fixo (75 itens) e contagem | `SP/exp/eval_items.json`, `SP/exp/evalset.py`, `SP/exp/score_wide.py` (usar esta contagem) |
| Respostas anteriores | `SP/exp/answers/E6_*.json`, `E7_agent_E2.json`, `E7a_agent_base.json`, `E7b_agent_qwen14b.json` |
| Adapters | `SP/exp/runs/E6/adapters/`, `SP/exp/runs/E2/adapters/0001200_adapters.safetensors` |

O modelo é `mlx-community/Qwen3-4B-4bit`, revisão `4dcb3d10`, já em cache.

O treino usa o worker do produto (`app/trainer/worker.py --mode train`) com mlx-lm 0.32.2: batch 4, `mask_prompt`, pensamento desligado. `NUM_LAYERS=36` significa todas as camadas.

Para ler código e dados, comece por `SP/exp2/agent2.py` e `SP/exp2/build_data3.py`.

## 4. Dados do E8

Escreva `SP/exp2/build_data4.py`. Ele grava `SP/exp2/data/E8/{train,valid}.jsonl` e `SP/exp2/data4_report.json`. Cada linha é uma conversa no formato de chat do Qwen com ferramentas: `messages` com papéis `system`, `user`, `assistant` (com `tool_calls`) e `tool`, mais `tools` = `TOOLS` do `agent2.py`. O `system` é o `SYS` do `agent2.py`, ajustado: "busque só quando a pergunta for sobre a base".

**Uma amostra por passo do assistente.** Com `mask_prompt`, o mlx-lm treina só a última mensagem do assistente. Por isso, cada trajetória de N passos do assistente vira N linhas: cada linha é o prefixo da trajetória até um passo do assistente. Assim, as chamadas de ferramenta também são treinadas. Antes de gerar tudo, confirme no código do mlx-lm 0.32.2 que:

- o carregador de chat aceita `tools`;
- o template renderiza `tool_calls` e mensagens `tool`;
- `mask_prompt` mascara tudo antes da última mensagem do assistente.

Se algo disso não valer, pare e anote na seção 8, em vez de contornar.

**Os resultados das ferramentas são reais.** Rode `search()` e `read()` do `agent2.py`, sobre as mesmas 199 janelas. "Achou" quer dizer que a janela que contém a passagem de origem está entre os 4 resultados.

Tipos de trajetória:

| Tipo | Fonte | Trajetória |
|---|---|---|
| K1 (fato, achou na primeira) | QA filtradas do E6 | busca → resposta do professor |
| K2 (fato, achou na segunda) | QA do E6 em que a primeira busca não achou | busca → busca com outras palavras → resposta. Se a segunda também não achar, descarte |
| G (sem resposta) | perguntas `gap` aceitas no E6 | busca → busca com outras palavras → recusa do professor (primeira pessoa, sem falar de trechos) |
| P (premissa falsa) | premissas aceitas no E6 | busca → correção do professor |
| D (geral) | perguntas gerais novas | resposta direta, sem ferramenta |

Detalhes:

- **Consulta da primeira busca.** O modelo escreve consultas curtas, não a pergunta inteira. Gere-as com gemma4:12b via `app/backend/amelia_academy/llm.py`, de 3 a 8 palavras, sem copiar a pergunta. Gere também a consulta da segunda busca, com outras palavras.
- **Resposta final.** É a do professor, que já está no `teacher.jsonl` ou no `teacher2.jsonl`. Ela foi escrita com a passagem na frente. Não reescreva. Aplique os mesmos filtros do `build_data3.py`.
- **Perguntas gerais (D).** Gere ≈300 com gemma via `llm.py`: aritmética, geografia, literatura, ciência, e computação geral fora dos artigos da base. Responda-as com o 4B base, sem adapter e sem ferramentas. Descarte as que ficarem perto das 14 perguntas `c` do teste. Use `near()`, com o mesmo limiar de 0,5.
- **Mistura.** Mantenha todas as linhas do E6 sem ferramentas, para preservar o que o modelo sabe responder sem busca. Some as trajetórias. Mire em 15% a 25% de linhas do tipo D entre as linhas com o prompt de sistema do agente, para o modelo aprender a não buscar.
- **Vazamento.** Nenhuma pergunta, consulta ou resposta pode ficar perto de um item do teste, pelos mesmos critérios e filtros do `build_data3.py`. Conte no relatório quantas caíram em cada filtro.

## 5. Treino

Rode `cd SP/exp && NUM_LAYERS=36 ./pipeline.sh E8 ../exp2/data/E8 2000 5e-5`, em segundo plano.

Se `train.py` ou o worker não aceitarem linhas com `tools`, ajuste só os scripts do scratchpad. O código do produto fica intacto, e a mudança vai para a seção 8.

## 6. Avaliação

1. **Sem ferramentas.** `pipeline.sh` já roda o `answer.py` em cada checkpoint. Compare com o E6, com a mesma contagem (`score_wide.py`): melhor checkpoint e média dos passos 1.600–2.000.
2. **Como agente, sem forçar a busca.** Acrescente ao `agent2.py` um modo `mlx-free`, sem o prefill que força a primeira busca. Rode-o:
   - no melhor checkpoint do E8 e no do passo 2.000;
   - no adapter E2, como controle.

   Para cada um, meça:
   - os números do `score_wide.py`;
   - a taxa de busca nas perguntas `c` (deve ser baixa) e nas `a`, `fp`, `nk` e `u` (deve ser alta);
   - a taxa de segunda busca;
   - a média de chamadas por pergunta.
3. **Como agente, forçando a busca.** Rode o modo `mlx` atual no melhor checkpoint do E8, para comparar com o E7 (29 de 32; fp 5; c 10).

Para as perguntas `u`, guarde as respostas; a regra não as avalia. Em 10 delas, leia a resposta e diga se o trecho buscado a sustenta.

**Critério de sucesso.** O E8 livre, sem forçar a busca:

- iguala ou passa o E7 em `a` e fp;
- volta c para pelo menos 13 de 14;
- busca em menos de 20% das perguntas `c`;
- faz a segunda busca em parte das perguntas `nk`.

Sem ferramentas, o E8 não pode perder mais de 2 pontos em `a` contra o E6.

## 7. Regras

- **Não use os dados reais.** Só a cópia em `SP/data/academy.sqlite3`.
- **Onde ficam scripts e dados:** em `SP/exp2/`. No repositório, edite só esta spec, nas seções 8 e 9. Não commite, não troque de branch, não rode formatadores no repositório e não altere `~/Projects/Amelia3`. O código do produto fica para depois.
- **Geração de dados** passa pelo `llm.py`, com modelo local do Ollama. Nunca use API direta. O professor 4B roda via mlx local, como na 017 (desvio já registrado lá).
- **Python sempre pelo venv.**
  - mlx: `app/trainer/.venv/bin/python`. Esse venv não tem `httpx`; o `agent2.py` já usa `urllib`.
  - `llm.py`: `app/backend/.venv/bin/python`.
- **Memória.** São 36 GB. O gemma4:12b ocupa ≈16 GB, e gemma junto com mlx já deu falta de memória de GPU. Antes de rodar mlx, espere `ollama ps` não mostrar o gemma. O treino usa ≈4 GB e pode rodar junto com uma avaliação mlx em lotes de 8.
- **Downloads.** Não baixe modelos nem pacotes.
- **Tempo.** Rode em segundo plano o que passar de alguns minutos. O treino de 2.000 passos leva cerca de 1 h, e a avaliação dos 80 checkpoints, mais um tanto.
- **Bloqueios.** Se o sandbox impedir o mlx (Metal) ou o acesso ao Ollama em `localhost:11434`, pare e escreva o bloqueio na seção 8.

## 8. Desvios e execução

- **Metal e ferramentas.** O venv autorizado teve acesso ao Metal; `mlx_lm` 0.32.2 carregou o Qwen3-4B-4bit local, sem baixar modelos ou pacotes. Confirmei no código instalado do `mlx-lm` que o carregador passa `tools` ao template de chat e que `mask_prompt` deixa a perda somente na última mensagem do assistente. Também conferi a renderização de chamadas e respostas de ferramenta no template Qwen3. O bloqueio anotado anteriormente nesta seção foi removido.
- **Dados.** Os resultados vieram da cópia `SP/data/academy.sqlite3`, nas mesmas 199 janelas e com as funções `search()`/`read()` de `agent2.py`. As consultas e perguntas gerais foram geradas pelo `llm.py` com Gemma 4 local; as respostas de D vieram do 4B base via MLX. Não usei API direta. Relatório: 1.366 QA aceitas (934 K1 e 87 K2 de segunda busca; 333 K2 descartadas), 349 G, 117 P e 289 perguntas D geradas (11 removidas por proximidade). A mistura final preservou as 1.993 linhas do E6, expandiu as trajetórias em passos do assistente, repetiu D para 19,0% das linhas com sistema do agente e totalizou 6.192 linhas. O filtro final removeu zero grupos por proximidade de pergunta, consulta ou resposta.
- **Comprimento.** O pré-teste com limite de 2.048 tokens não comportava as trajetórias K2 mais longas. Limitei mensagens de ferramenta a 2.200 caracteres e usei `MAX_SEQ_LENGTH=3072` (máximo pré-testado: 2.327 tokens; zero exemplos acima do limite). O relatório registra 2.352 mensagens de ferramenta truncadas. A alteração ficou em scripts do scratchpad; o código do produto não mudou.
- **Treino e avaliação.** Executei `NUM_LAYERS=36 MAX_SEQ_LENGTH=3072 ./pipeline.sh E8 ../exp2/data/E8 2000 5e-5`, batch 4, seed 0 e pensamento desativado. Os 2.000 passos levaram 23.345 s, pico de 13,50 GB; melhor loss de validação 1,4533 no passo 1.424. O pipeline terminou a avaliação sem ferramentas dos 80 checkpoints, e depois rodei as avaliações longas dos três agentes e do modo forçado.
- **Escopo.** Scripts, dados e saídas ficaram no scratchpad. No repositório, só esta spec foi editada. Não alterei o código do produto, não troquei de branch, não rodei formatadores e não commitei.

## 9. Resultados

Usei `score_wide.py` e somei as metades `rep` e `sel` para `a` e `c`. “Melhor” no treino sem ferramentas é o checkpoint com maior `a`; o melhor foi o passo 1.875. A média tardia inclui os 17 checkpoints de 1.600 a 2.000, inclusive.

| Run | `a` melhor (passo) | Média tardia `a` | fp / 8 | nk recusa / 10 | `c` / 14 | u recusa / 11 |
|---|---:|---:|---:|---:|---:|---:|
| E6 — destilação sem ferramentas (spec 017, §13) | 28 (13) | 25,0 | 2,8 | 8,3 | 13,8 | 1,0 |
| E7 — E2 com busca forçada (spec 017, §13) | 29 (15) | — | 5 | 4 | 10 | 2 |
| E8 — sem ferramentas, melhor checkpoint | 24 (1.875) | — | 4 | 7 | 13 | 1 |
| E8 — sem ferramentas, passo 2.000 | 23 (2.000) | 21,5 | 2,6 | 8,6 | 13,2 | 0,9 |

O melhor checkpoint E8 não igualou o E6 sem ferramentas: 24 contra 28 em `a`; a média tardia foi 21,5 contra 25,0. Na média, `fp` ficou em 2,6, recusas `nk` em 8,6, `c` em 13,2 e recusas `u` em 0,9.

### 9.1. Agentes

| Execução | `a` / 32 | fp / 8 | nk recusa / 10 | `c` / 14 | u recusa / 11 | Busca em `c` | Perguntas com segunda busca | Chamadas médias por pergunta |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| E8 livre, melhor checkpoint (1.875) | 25 | 4 | 10 | 13 | 1 | 4/14 (28,6%) | 14/75 (18,7%) | 1,05 |
| E8 livre, passo 2.000 | 24 | 4 | 10 | 13 | 1 | 3/14 (21,4%) | 15/75 (20,0%) | 1,05 |
| E2 livre, controle | 25 | 3 | 9 | 14 | 2 | 0/14 | 0/75 | 0,00 |
| E8 com primeira busca forçada, melhor checkpoint | 25 | 4 | 10 | 13 | 1 | 14/14 | 14/75 (18,7%) | 1,19 |

No E8 livre do melhor checkpoint, a busca ocorreu em 32/32 `a`, 8/8 `fp`, 10/10 `nk` e 11/11 `u`; nas perguntas `c`, ocorreu em 4/14. Houve segunda busca em 10/10 `nk`, 2/32 `a`, 1/8 `fp` e 1/11 `u`; a média geral foi 1,05 chamadas. O controle E2 não chamou ferramentas. Com a busca forçada, E8 chamou `search` em todas as 14 perguntas `c`.

### 9.2. Conferência das perguntas `u`

Guardei as 11 respostas `u` do agente livre do melhor checkpoint em `exp2/E8_free_best.json` e conferi as primeiras 10 contra as janelas realmente recuperadas. Em 9, o trecho sustenta a resposta: `u01`–`u09`. Em `u00`, a busca trouxe janelas sem o total de modelos e variações perguntado, e o modelo respondeu “I don't know”; a recusa é apropriada, embora a resposta não contenha informação sustentada. Não contei `u` no critério de acerto.

### 9.3. Critério e leitura

O E8 livre atende ao limite de `c` no score (13/14) e aprende a buscar de novo em `nk` (10/10), mas não alcança E7 em `a` (25 contra 29), busca em mais de 20% das perguntas `c` (28,6%) e perde mais de 2 pontos de `a` contra E6 sem ferramentas (24 contra 28 no melhor; média tardia 21,5 contra 25,0). Portanto, não cumpre o critério de sucesso da seção 6. No passo 2.000, a taxa de busca em `c` caiu para 21,4%, ainda acima do limite. O resultado indica que as trajetórias ensinaram busca repetida para conteúdo não encontrado, mas não bastaram para preservar o desempenho factual do E6 ou restringir a busca geral abaixo do limite definido.
