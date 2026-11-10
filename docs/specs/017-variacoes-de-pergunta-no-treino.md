# Especificação 017 — Variações de pergunta no treino

**Status:** experimento feito em 7 nov. 2026, numa cópia do Comprimildo. Nada do produto mudou; a seção 10 propõe as mudanças e espera aprovação. A seção 9 compara com a literatura: os achados principais já eram conhecidos, e a configuração do experimento ficou fora do recomendado.  
**Relacionadas:** Especificações 013 (o que o dataset ensina), 014 (export e splits), 015 (treinar e comparar), 016 (confiança).

## 1. Pergunta

Depois do fine-tune, o modelo sabe os fatos dos artigos quando a pergunta vem com outras palavras? E criar variações de pergunta e resposta no export ajuda?

**Resposta curta:** ajuda, e muito. Quatro outras formas de perguntar cada par Known dobraram o acerto em pergunta nova: de 10–17 para 21–22 de 32, na média dos checkpoints, nas duas sementes. Variar também a resposta não acrescentou nada medível. Pares gerais e vizinhos não melhoram o acerto, mas firmam o "não sei" nas perguntas sem resposta. A perda de validação escolheu, em 11 de 11 treinos, um checkpoint que não sabia quase nada. A taxa de 1e-4 aprende; 2e-4 estraga o conhecimento geral; 1e-5, o padrão atual da spec 015, aprende devagar demais para 400 passos.

**Cuidado ao usar estes números.** O dataset é pequeno (≈27 mil tokens de resposta em R1), o LoRA cobriu só 16 das 36 camadas e a base era 4-bit. A literatura faz diferente nas três coisas e, para fatos novos, prefere buscar os trechos (RAG) a confiar só no fine-tune (seção 9). Os números servem para comparar os treinos entre si, não como o teto do que um fine-tune consegue.

## 2. Hipóteses

| # | Hipótese | Isolada em |
|---|---|---|
| H1 | 3 a 5 formas de pergunta por par Known aprovado, com a mesma resposta, melhoram o acerto em pergunta nova | R1 contra R0 |
| H2 | Variar também a resposta ajuda além de H1 | R2 contra R1 |
| H3 | Pares vizinhos e gerais protegem o conhecimento geral e o "não sei" | R3 contra R0; R4/R4b contra R1/R2 |
| H4 | Escolher o checkpoint por acerto, não pela perda de validação | todos os treinos |
| H5 | Passos e taxa de aprendizado. Ponto de partida: 200 passos a 1e-4 decoraram | H5min, H5lo, H5hi contra R4b/R1 |

## 3. Protocolo

**Dados.** Cópia de `academy.sqlite3`, `datasets/` e `runs/` no scratchpad da sessão. O original não foi tocado. Export `ds_11449a68fe9d` (já com as recusas reescritas): 159 treino (96 Known de arquivo, 1 complexo, 40 Not known, 22 premissa falsa), 20 validação, 19 teste. Divisão por grupo de passagem (spec 014).

**Treino.** O worker do produto (`app/trainer/worker.py --mode train`), sem mudanças: `mlx-community/Qwen3-4B-4bit` revisão `4dcb3d10`, LoRA rank 8, 16 camadas, lote 4, `mask_prompt`, sem pensamento, semente 0, 400 passos, checkpoint a cada 25. A taxa é constante; por isso o checkpoint do passo k equivale a um treino de k passos. Cada treino levou de 6 a 8 minutos, com pico de 3,65 GB.

**Variações.** Geradas pelo caminho do produto, `OllamaClient('gemma4:12b').complete_json` em `llm.py` (o mesmo modelo que escreveu os pares), temperatura 0,7. Para cada um dos 97 pares Known do treino, o modelo escreveu 4 perguntas e 3 respostas. 96 saíram, e 1 falhou por falta de memória na GPU. Isso deu 384 perguntas e 288 respostas, em 1118 s (mediana de 4,2 s por par). As variações só existem para pares do treino, então ficam no mesmo grupo e nunca atravessam splits (spec 014, §4 e §5).

**Vizinhos e gerais.** Os vizinhos vieram de `kb.write_neighbours` (o caminho do produto), em 10 rodadas sobre a cópia. Ficaram 24, e as checagens do produto recusaram 32: 25 quase iguais a perguntas já no dataset, 4 que os arquivos respondem e 3 que falavam da fonte. Os gerais foram 50 pares de conhecimento geral escritos pelo gemma4:12b, longe das perguntas gerais da avaliação.

**Conjunto de avaliação fixo**, escrito à mão uma vez, nunca treinado (75 itens):

| Parte | Itens | Certo quando |
|---|---|---|
| a. Fato treinado, pergunta nova | 32 (16 para escolher checkpoint, 16 só para relatar) | a resposta tem o fato (regra de palavras) |
| fp. Premissa falsa sobre fato treinado | 8 | a resposta diz o fato verdadeiro |
| nk. Not known fora do treino (valid+test) | 10 | recusa |
| c. Conhecimento geral | 14 (7 + 7) | acerta sem recusar |
| u. Known de passagens nunca treinadas (test) | 11 | só se relata quantos recusou |

**Juiz.** Uma regra simples, sem modelo: o texto é dobrado para minúsculas, e cada item tem grupos de palavras ou expressões regulares que precisam aparecer; a recusa é uma expressão regular ("I don't know…", "not what I studied", …). Geração gulosa com `mlx_lm.batch_generate` e no máximo 160 tokens. A regra foi conferida lendo as respostas (seção 6).

**Ruído.** Uma segunda semente para R0 e R1 mostra o quanto um número oscila. Checkpoints vizinhos variam ±3 em `a`. Por isso as tabelas mostram a média dos checkpoints 200–400 (9 pontos) e não só um ponto.

**Limpeza imperfeita.** Durante R0, o Ollama gerava variações ao mesmo tempo. Os tempos de R0 não são limpos, e um checkpoint precisou ser avaliado de novo, por falta de memória.

## 4. Matriz de treinos

| Treino | Dados de treino | Linhas | Taxa | Semente | Vezes que cada fato Known é visto em 400 passos |
|---|---|---|---|---|---|
| R0 | export como está | 159 | 1e-4 | 0 | ≈10 |
| R0s1 | igual a R0 | 159 | 1e-4 | 1 | ≈10 |
| R1 | + 4 perguntas por Known, resposta original (H1) | 543 | 1e-4 | 0 | ≈15 (5 formas × 2,9 épocas) |
| R1s1 | igual a R1 | 543 | 1e-4 | 1 | ≈15 |
| R2 | + 4 perguntas, cada uma com uma resposta reescrita (H2) | 543 | 1e-4 | 0 | ≈15 |
| R3 | + 24 vizinhos + 50 gerais (H3) | 233 | 1e-4 | 0 | ≈7 |
| R4 | H2 + H3 | 617 | 1e-4 | 0 | ≈13 |
| R4b | H1 + H3 | 617 | 1e-4 | 0 | ≈13 |
| H5min | igual a R1 | 543 | 1e-5 | 0 | ≈15 |
| H5lo | igual a R4b | 617 | 5e-5 | 0 | ≈13 |
| H5hi | igual a R4b | 617 | 2e-4 | 0 | ≈13 |

A validação é sempre a do export (20 pares), igual em todos.

## 5. Resultados

### 5.1. Média dos checkpoints 200–400

| Treino | a (de 32) | a, metade só relatada (de 16) | recusa em a | fp (de 8) | nk recusa (de 10) | c (de 14) | recusa em c | u recusa (de 11) |
|---|---|---|---|---|---|---|---|---|
| Base, sem adapter | 5 | 3 | 0 | 2 (lendo: 1) | 0 | 14 | 0 | 1 |
| R0 | 10,5 | 5,2 | 6,0 | 2,1 | 6,4 | 10,9 | 2,3 | 2,0 |
| R0s1 | 16,7 | 8,4 | 3,2 | 1,4 | 7,1 | 12,1 | 0,0 | 1,2 |
| **R1 (H1)** | **21,5** | **10,2** | 3,2 | 2,9 | 6,1 | 11,7 | 0,1 | 1,9 |
| **R1s1 (H1)** | **22,5** | **10,8** | 2,2 | 4,1 | 6,1 | 12,4 | 0,1 | 1,8 |
| R2 (H2) | 21,9 | 11,9 | 2,8 | 2,9 | 7,6 | 12,6 | 0,0 | 1,0 |
| R3 (H3) | 12,2 | 8,3 | 6,6 | 2,2 | 8,1 | 11,1 | 0,0 | 2,4 |
| R4 (H2+H3) | 20,9 | 12,0 | 3,7 | 3,4 | 6,3 | 11,6 | 0,0 | 1,7 |
| R4b (H1+H3) | 20,8 | 10,1 | 3,0 | 3,8 | 6,3 | 11,8 | 0,0 | 1,9 |
| H5min (1e-5) | 13,9 | 8,4 | 3,0 | 3,4 | 4,9 | 12,7 | 0,0 | 1,6 |
| H5lo (5e-5) | 19,0 | 9,4 | 3,6 | 2,8 | 6,3 | 13,0 | 0,0 | 1,9 |
| H5hi (2e-4) | 15,3 | 8,2 | 3,2 | 3,0 | 4,7 | **4,9** | 0,4 | 1,6 |

O antigo treino de 200 passos do produto (`trn_766b5b1cb4d2`, mesma receita de R0) teve no passo 200 a = 7, recusa em a = 12, nk = 10 e c = 11 com 2 recusas: decorou a forma da pergunta e passou a dizer "não sei" quando ela muda.

### 5.2. Qual checkpoint escolher (H4)

| Treino | Escolhido pela menor perda de validação | Escolhido pelo acerto (a + c da metade de escolha) |
|---|---|---|
| R0 | passo 25, val 1,76: a 0, recusa em a 25, c 4 | passo 125, val 2,37: a 15, nk 7, c 11 |
| R0s1 | 25, val 1,80: a 3, nk 0 | 225, val 2,68: a 19, nk 8, c 14 |
| R1 | 25, val 1,77: a 3, nk 0 | 275, val 2,06: a 24, nk 4, c 10 |
| R1s1 | 25, val 1,77: a 5, nk 0 | 250, val 2,12: a 24, nk 6, c 13 |
| R2 | 25, val 1,81: a 4, nk 3 | 250, val 1,95: a 22, nk 3, c 14 |
| R3 | 25, val 1,81: a 0, recusa em a 25 | 325, val 3,11: a 18, nk 8, c 11 |
| R4 | 75, val 1,74: a 9, nk 0 | 150, val 1,85: a 22, nk 1, c 13 |
| R4b | 25, val 1,71: a 6, nk 0 | 275, val 2,05: a 23, fp 5, nk 8, c 12 |
| H5min | 50, val 1,73: a 2, nk 0 | 175, val 2,39: a 15, nk 0, c 14 |
| H5lo | 50, val 1,71: a 5, nk 0 | 350, val 2,17: a 22, nk 6, c 13 |
| H5hi | 25, val 2,15: a 3, nk 0 | 325, val 2,86: a 19, nk 0, c 6 |

Na metade só relatada de `a`, que não entrou na escolha, o checkpoint escolhido pela validação acerta de 0 a 7 de 16; o escolhido pelo acerto, de 6 a 12.

### 5.3. Qualidade das variações

| Conferência | Resultado |
|---|---|
| Falhas de geração | 1 de 97 pares (memória da GPU) |
| Automática: pergunta perdeu número ou termo | 2 de 384 ("GMM" sumiu, sentido igual) |
| Automática: pergunta idêntica à original | 3 de 384 |
| Automática: pergunta parecida com a da avaliação (3-gramas ≥ 0,5) | 0 |
| Automática: resposta perdeu número ou termo | 0 de 288, **mas a regra deixou passar "BGing" no lugar de BPG**, porque BPG aparecia em outro ponto da frase |
| Leitura, 40 perguntas sorteadas | 0 mudaram o fato; 1 idêntica; 1 ficou vaga ("Why does the model perform poorly when it is fully factorized?" perdeu "entropy model") |
| Leitura, 40 respostas sorteadas | 0 números errados; 1 juntou duas afirmações e mudou a relação entre elas; 1 acrescentou um detalhe que não estava no original |

**O que decide a revisão:** nas perguntas, 0 de 40 mudaram o fato, e 2 de 40 ficaram mais fracas. Nas respostas, 2 de 40 mudaram algo, e uma terceira, fora da amostra, trocou um nome. A resposta é onde o fato pode mudar, e variar a resposta não trouxe ganho (seção 7, H2).

## 6. Regra contra leitura

| Onde | Regra | Leitura | Diferença |
|---|---|---|---|
| a, R1 passo 275 | 24 | 23 ou 24 | "VTM 5.2.2" contado certo; o certo é 5.2 |
| fp, base | 2 | 1 | a base cita Adam como alternativa sem corrigir SGD |
| fp, R0 passo 200 | 2 | 2 | depois de duas correções na regra (abaixo) |
| fp, R1 passo 275 | 2 | 1 | "4096 … 2048-byte samples" aceita a premissa e cita 2048 |
| fp, R4b passo 275 | 5 | 5 | — |
| c, R1/R2/R4b | — | — | "reduces the data needed for storage" é certo e a regra pede "compress" |

Duas regras foram corrigidas depois da primeira leitura, e todas as tabelas foram recalculadas: fp4 passou a aceitar "does not, in general" e fp6 passou a exigir "2 bytes". A regra é boa para `a`, `nk` e `c`. Em `fp` ela erra para cima por cerca de 1, porque a resposta pode citar o número certo e ainda aceitar a premissa. Os números de `fp` são o teto.

## 7. Leitura

**H1, confirmada.** Com o mesmo número de passos, `a` vai de 10,5/16,7 (R0, duas sementes) para 21,5/22,5 (R1). Na metade só relatada, de 5,2/8,4 para 10,2/10,8. R1 vê cada fato mais vezes (≈15 contra ≈10), mas, com exposição igual, R1 no passo 275 acerta 24 e R0 no passo 400 acerta 10 e 16. Também some a recusa errada quando a pergunta muda de forma, que o treino antigo mostrava: em R0, a pergunta reescrita recebia "I do not know…" em 8 de 32. A diferença entre sementes de R0 (10,5 contra 16,7) é maior que a de R1 (21,5 contra 22,5): com variações, o resultado depende menos da sorte.

**H2, sem efeito medível.** R2 (21,9) fica igual a R1 (21,5), dentro do ruído; nk sobe um pouco (7,6 contra 6,1), e c também (12,6 contra 11,7), as duas diferenças do tamanho do ruído. R4 contra R4b repete isso. Como a resposta é onde a variação muda o fato, H2 não compensa.

**H3, protege o "não sei", não ensina fatos.** R3 contra R0: `a` fica igual (12,2), nk sobe para 8,1 e nunca cai abaixo de 8 nos checkpoints 200–400 (R0 vai de 5 a 8), e a recusa em pergunta geral cai de 2,3 para 0. Mas R0s1 também tem recusa geral 0: a fuga do "não sei" para perguntas gerais depende da semente, e H1 sozinha já a tira (0,1). Com H1, somar H3 (R4b) não mudou `a` nem nk. Os vizinhos não têm itens próprios na avaliação: o efeito deles no limite do assunto não foi medido. **Risco visto:** a 2e-4, respostas curtas dos pares gerais viraram molde, e o modelo respondeu "F. Scott Fitzgerald." para Dom Quixote e Romeu e Julieta.

**H4, confirmada com folga.** A menor perda de validação caiu nos passos 25–75 em todos os 11 treinos. Nesses checkpoints o modelo sabe de 0 a 9 de 32, e quase sempre não recusa nada do que não sabe. A perda de validação sobe enquanto o acerto sobe: ela mede o quanto o modelo decora o texto exato das respostas de validação, não se ele sabe o fato. **Outro achado:** o "não sei" oscila muito entre checkpoints vizinhos (em R4, nk = 1 no passo 150 e 9 no 400; em R4b, 0 no passo 100 e 6 no 125). Escolher só pelo acerto pode pegar um checkpoint que inventa tudo. A escolha precisa olhar acerto, recusa e conhecimento geral juntos.

**H5.** A 1e-4, o acerto chega a 20–24 entre os passos 200 e 300 (cada fato visto 7 a 11 vezes) e para de subir. A 5e-5, chega a 22 no passo 350, com o melhor conhecimento geral de todos (13,0). A 2e-4 destrói o conhecimento geral (4,9 de 14: "Tokens are composed of carbon and hydrogen" para a capital do Japão). A 1e-5, padrão atual da spec 015, chega a 15 no melhor checkpoint e a 13,9 na média. Com `iters = ceil(3n / lote)` (120 passos para 159 pares), isso daria perto de nada.

**O que não melhorou em nenhum treino:**

- **Premissa falsa:** a correção ficou em 1–5 de 8, sem padrão claro; os 22 pares de treino não bastam, e as variações não os cobriram.
- **Fatos de passagens nunca treinadas** (u): recusados em só 1–3 de 11. O resto o modelo responde, provavelmente inventando, porque o assunto parece conhecido.
- **Conhecimento geral:** caiu em todos os treinos, de 14 para 11–13. Os erros são de fato ("Alan Turing" para entropia, "0°C" para a fervura da água), não de recusa.

## 8. Limites

- Um projeto, uma base (Qwen3 4B), 32 fatos avaliados. Diferenças menores que 2–3 em `a` são ruído.
- O juiz é uma regra de palavras. Lida em parte (seção 6), não em tudo.
- Variações só para Known; premissa falsa e Not known não foram variados.
- Só a taxa mudou em H5; os passos foram lidos nas curvas, sem treinos mais longos que 400.
- Vizinhos sem itens próprios na avaliação.
- **Dataset pequeno.** R0 tem ≈7 mil tokens de resposta; R1, ≈27 mil. O EntiGraph (seção 9) gerou ≈350 vezes o corpus original, 455 M tokens; o Active Reading usou 1 T tokens.
- **LoRA parcial.** O worker usa o padrão do mlx-lm: LoRA em todas as lineares, mas só nas últimas 16 das 36 camadas do Qwen3-4B, rank 8, `scale` 20.
- **Base 4-bit.** O treino rodou sobre `Qwen3-4B-4bit`. O adapter não é 4-bit, então o efeito é incerto. O `Qwen3-4B` completo **não** está no cache: só os arquivos do tokenizador estão. Ele não foi testado, nem o 8B, porque baixar pede permissão (seção 12).
- **Um modelo só.** Não testei 8B nem outra família. Pela conta de capacidade (≈2 bits por parâmetro), 97 fatos cabem com folga em 4B; o problema medido aqui é tirar o fato com outra pergunta, não espaço.
- **Sem comparação com RAG.** Ninguém mediu o mesmo conjunto com os trechos no contexto.

## 9. O que a literatura já sabia

| Achado aqui | O que já se sabia | Fonte |
|---|---|---|
| H1: outras formas de perguntar dobram o acerto | Sem paráfrases, o modelo decora o fato mas não o tira com outra pergunta; com variação, tira. Paráfrase também ajudou em fine-tune de fatos novos. | Allen-Zhu e Li, *Physics of LMs 3.1* (ICML 2024, [2309.14316](https://arxiv.org/abs/2309.14316)); Ovadia et al. (EMNLP 2024, [2312.05934](https://arxiv.org/abs/2312.05934)) |
| u: inventa sobre partes nunca treinadas | Fatos novos são aprendidos mais devagar e, quando aprendidos, aumentam a alucinação quase em linha reta. Fine-tune serve mais para usar o que o modelo já sabe. | Gekhman et al. (EMNLP 2024, [2405.05904](https://arxiv.org/abs/2405.05904)) |
| H4: escolher pelo acerto, não pela perda | Os mesmos autores recomendam parar pelo desempenho na validação. | Gekhman et al. |
| 5 formas por fato bastam? | Paráfrase simples satura. Gerar texto novo sobre as relações entre entidades continua rendendo: 1,3 M tokens viraram 455 M, com acerto subindo em escala log até o fim. | Yang et al., *Synthetic continued pretraining* (EntiGraph, [2409.07431](https://arxiv.org/abs/2409.07431)) |
| Escala do dado sintético | Active Reading: o modelo estuda o material com estratégias que ele mesmo gera; 8B com 1 T tokens; ≈4× o acerto do fine-tune simples em perguntas da Wikipédia. | Lin et al., Meta (2025, [2508.09494](https://arxiv.org/abs/2508.09494)) |
| Como gerar as perguntas | Gerar por fato, não por volume de texto: cobre os fatos por igual. | Mecklenburg et al., Microsoft ([2404.00213](https://arxiv.org/abs/2404.00213)) |
| H3: pares gerais | Receita que funciona: paráfrases mais passagens no contexto com relevância variada, mais uma reserva de QA geral para não esquecer. Aqui foram 50 pares curtos, pouco perto disso. | Bhushan et al. (NAACL 2025 Findings, [2025.findings-naacl.329](https://aclanthology.org/2025.findings-naacl.329)) |
| H5: taxa, e o LoRA parcial | LoRA em todas as camadas, MLP incluída; só atenção fica bem abaixo, e rank maior não compensa. A taxa ótima do LoRA é ≈10× a do fine-tune completo e quase não depende do rank. Lote grande atrapalha o LoRA. | Thinking Machines, *LoRA Without Regret* ([blog](https://thinkingmachines.ai/blog/lora/)); Biderman et al., *LoRA Learns Less and Forgets Less* (TMLR 2024, [2405.09673](https://arxiv.org/abs/2405.09673)) |
| Fine-tune para fatos, em geral | APIs comerciais de fine-tune acertaram em média 37% dos fatos novos com pergunta generalizada; as do Gemini não aprenderam. Com os trechos no contexto, RAG acertou 0,875 contra 0,504 do fine-tune (Mistral 7B, notícias). | FineTuneBench ([2411.05059](https://arxiv.org/abs/2411.05059)); Ovadia et al. |
| Juntar os dois | RAFT: treinar o modelo para responder a partir dos trechos certos e ignorar os que não servem. | Zhang et al., Berkeley ([2403.10131](https://arxiv.org/abs/2403.10131)) |

**O que isso muda.** A spec 017 confirmou, num projeto da Amelia, resultados que já existiam. Ela não testou a receita que a literatura recomenda: mais dado por fato, LoRA em todas as camadas e uma comparação com RAG. A Amelia já guarda os trechos e a wiki com citações (`memory.jsonl`). Então decidir entre o modelo responder de memória, com os trechos (RAG) ou treinado para usar os trechos (RAFT) é uma decisão de produto que vem antes das telas da seção 10.

## 10. Recomendação para o produto

Nada disto está construído. As mudanças esperam aprovação e a decisão do fim da seção 9. Curate e Compare valem nos três caminhos; Export e Train valem para o modelo que responde de memória.

**Curate.** Cada par Known aprovado ganha, abaixo dele, **"Other ways to ask"**: o modelo rascunha 4 perguntas, e a resposta é sempre a do par. A pessoa vê uma pergunta só: "Use these too?", com **Use them** e **Not these**, e pode editar ou tirar uma linha. Há também **Use all** por tema, porque na leitura 0 de 40 perguntas mudaram o fato. A tela não diz que as perguntas foram conferidas; ela põe em destaque, primeiro, as que perderam um número ou um nome do original. Toda escolha tem **Undo** na hora. Mudar a resposta do par descarta as perguntas dele, com Undo. Não rascunhar outras respostas (H2).

**Export.** As perguntas aceitas saem só no treino, cada uma como uma linha com a resposta do par, no mesmo grupo dele. Par em validação ou teste sai sem elas. O `README.md` e o manifesto contam quantas entraram ("384 other ways to ask, for 96 pairs"). Pares gerais **não** entram por padrão: H1 já tira a recusa das perguntas gerais, e respostas gerais curtas podem virar molde. Vizinhos continuam como na spec 013.

**Train.** Padrão de 1e-4 (5e-5 quando proteger o conhecimento geral importar mais), no lugar de 1e-5. Passos para cada fato ser visto cerca de 10 vezes, contando as outras formas de perguntar (≈275 passos para este projeto com H1), em vez de 3 épocas. Checkpoint a cada 25 passos. LoRA em todas as camadas, como recomenda a seção 9, e não só nas últimas 16; isso muda a taxa boa, então os valores acima precisam ser medidos de novo. A curva de validação continua visível, com o rótulo **"Memorizing the exact wording"**, e não escolhe nada.

**Compare.** Quem escolhe o checkpoint são as perguntas, não a perda. O modelo prepara três grupos já previstos na spec 015: as perguntas de "Aprendeu?" (outras formas de perguntar, que **nunca** entram no treino), as perguntas do teste que pedem "não sei" e as gerais. Ele roda os checkpoints salvos e sugere um, mostrando em palavras simples: "Knows 23 of 32 · Says it doesn't know 8 of 10 · General questions 12 of 14". A pergunta para a pessoa é "Which version should we keep?", com a sugestão marcada e Undo. Quando o melhor em acerto inventa nas perguntas sem resposta, a tela diz isso, em vez de esconder. Os limites também ficam visíveis, em palavras simples: "It still answers questions about parts it never read" e "It rarely corrects a wrong question".

**Próximos testes** (não feitos aqui), seguindo receitas publicadas em vez de novas:

1. Mesmo conjunto de avaliação, com os trechos no contexto (RAG), contra o modelo respondendo de memória.
2. LoRA em todas as 36 camadas, sobre a base bf16, com R1, para ver quanto da diferença era configuração.
3. Dado por fato em escala: dezenas de perguntas por fato e passagens reescritas sobre as relações entre entidades (EntiGraph), mais uma reserva real de QA geral.
4. Um braço RAFT: treinar com o trecho certo e trechos que não servem no contexto.
5. Variar as perguntas de premissa falsa e de Not known, avaliar os vizinhos com itens próprios e repetir num segundo projeto.

## 11. Reproduzir

Scripts e dados ficaram só no scratchpad da sessão: avaliação (`evalset.py`, `build_eval.py`, `answer.py`, `score.py`), geração (`gen_variations.py`, `gen_neighbours.py`, `gen_general.py`, `build_data.py`) e treino (`train.py`, `pipeline.sh`). O caminho de cada peça do produto usada está na seção 3.

## 12. Segunda rodada (E1–E5)

Rodada feita em 8 nov. 2026, sobre a mesma cópia, a mesma base `Qwen3-4B-4bit` e o mesmo conjunto de avaliação de 75 itens. O juiz é o mesmo: a regra de palavras. Os testes E1 a E5 seguem receitas da seção 9; nenhuma foi inventada aqui.

| Teste | O que mudou | `a` no melhor passo (rep) | `a` média final | fp | nk | c | u recusa |
|---|---|---|---|---|---|---|---|
| R1 (referência) | 16 camadas, 1e-4, 400 passos | 24 (11) | 21,5 | 2,9 | 6,1 | 11,7 | 1,9 |
| E1a | **36 camadas**, 1e-4, R1 | 23 (11) | 20,4 | 4,9 | 6,4 | 11,5 | 1,1 |
| E1b | 36 camadas, **5e-5**, R1 | 23 (11) | 20,8 | 4,5 | 6,6 | **13,9** | 1,4 |
| **E2** | 36 camadas, 5e-5, **destilação**, 1.200 passos | **30 (15)** | **26,0** | 2,3 | 4,5 | 13,6 | 0,1 |
| E3 | igual ao E2, respostas do gemma | 24 (13) | 23,4 | 0,9 | 4,9 | 12,7 | 0,6 |
| E4 | pensamento ligado na resposta | base 5; E1a 24; E1b 17 | — | — | — | — | — |
| E5b | agente com busca, sem treino | 23 (11) | — | 4 | **0** | 12 | 1 |

A coluna "média final" é a média dos checkpoints de 200 a 400 passos para R1 e E1, e de 800 a 1.200 para E2 e E3. As colunas fp, nk, c e u são médias nesses mesmos trechos; para E4 e E5b são de uma rodada só. A base sem adapter acerta 5 de 32.

### 12.1. E1: LoRA em todas as camadas

Passar de 16 para 36 camadas **não** aumentou o acerto: 20,4 contra 21,5, dentro do ruído. O que mudou foi o conhecimento geral. Com 5e-5, ele ficou em 13,9 de 14, contra 11,7 do R1, sem perder acerto. Então a configuração não era o gargalo; o ganho foi proteger o que o modelo já sabia.

### 12.2. E2 e E3: mais dado, e quem escreve a resposta

O gemma4:12b, via `llm.py`, escreveu 20 perguntas por passagem de treino, para 79 passagens: 1.572 perguntas. Nenhuma ficou parecida com as perguntas da avaliação (Jaccard ≥ 0,5: zero). O prompt está em `exp2/prompts/passage_qa.md`. Passagens de validação e teste ficaram de fora.

- **E2 (destilação de prompt, Kujanpää et al.).** O próprio `Qwen3-4B-4bit`, sem adapter, respondeu cada pergunta **com a passagem no contexto**. O aluno treinou a pergunta com essa resposta, sem a passagem. Foram descartadas 8 respostas que eram recusa. Isso deu cerca de 73 mil tokens de resposta, ≈4× o R1 na mesma conta.
- **E3 (mesmas perguntas, respostas do gemma).** As respostas são curtas, com média de 13 palavras contra 33 do professor; ≈34 mil tokens.

As duas bases levam também as 159 linhas de treino do export, com as recusas. Os dois treinaram 1.200 passos, ≈2,8 épocas.

**Leitura.**

- **O E2 é o melhor resultado até aqui.** Acerta 30 de 32 no passo 1.200, e 15 de 16 na metade que não escolheu o passo. A média do fim da curva é 26,0, contra 21,5 do R1.
- **A curva ainda subia no passo 1.200.** Treinar mais pode render mais.
- **O professor importa.** Com as mesmas perguntas, o E2 ganhou do E3 em `a` (26,0 contra 23,4) e em fp (2,3 contra 0,9). Uma ressalva: respostas mais longas têm mais chance de conter a palavra da regra, então parte da diferença pode ser do juiz.
- **O custo aparece nas recusas.** O modelo quase não diz "não sei" sobre partes nunca lidas: 0,1 de 11, contra 1,9 do R1. E aceita mais premissas falsas que o E1. As recusas viraram ≈9% das linhas, contra ≈30% no R1, e nenhuma resposta do professor corrige uma pergunta errada.
- **O professor às vezes inventa.** Ele acrescenta afirmações que não estão na passagem, por exemplo "larger vocabularies allowing for more efficient representation". Às vezes também cita a fonte: "as stated in the reference".
- **Desvio do protocolo.** O professor rodou fora do `llm.py`, via mlx local. Por ser o próprio modelo aluno, ele não passa pelo Ollama.

### 12.3. E4: com pensamento

Com `enable_thinking=True` e até 1.200 tokens, guardei só a resposta final.

- **Base.** Continuou em 5 de 32. Levou 483 s contra ≈9 s, e 24 de 75 respostas não terminaram de pensar dentro do limite.
- **Modelos treinados.** Não pensam: o adapter aprendeu a responder direto, porque o treino tinha o pensamento vazio no prompt. O E1a ficou igual, com 24. O E1b caiu para 17, e o nk caiu de 6 para 1.
- **Leitura.** Pensar não tira um fato que o modelo não tem. Para pensar depois de treinado, o treino precisaria de exemplos com pensamento (Ma e Hewitt, seção 9).

### 12.4. E5: agente com busca, sem treino

A base sem adapter recebeu duas ferramentas sobre os 1.501 trechos do Comprimildo: `search_kb(query)`, com BM25 e 6 trechos, e `read(chunk_id)`, com o trecho e 3 vizinhos de cada lado. O limite foi de 3 chamadas.

- **Sem empurrão (E5).** O modelo chamou a ferramenta em 3 de 75 perguntas e respondeu de memória: `a` = 3. Várias respostas dizem "I will search…" e param sem chamar a ferramenta.
- **Com a primeira busca obrigatória (E5b).** O modelo escreve a consulta. Ele acertou 23 de 32, o mesmo nível do R1, sem treino nenhum. Mas:
  - Nunca buscou uma segunda vez nem usou `read`.
  - Não recusa nada que não esteja na base: nk 0 de 10. Quando a busca traz um trecho próximo, ele responde com ele.
  - Os erros vêm de busca ruim (trechos curtos, de ≈120 caracteres, e BM25 com a pergunta inteira) ou de a resposta ignorar o trecho.
- **O que não medi.** As 11 perguntas `u` vêm de partes que a base tem, mas que o modelo nunca treinou. O agente pode acertá-las, e a regra não avalia isso.

### 12.5. O que isto muda

1. **Para fine-tune, a receita que funcionou foi mais dado gerado por passagem e respondido pelo próprio modelo com a passagem na frente.** Não foi mudar o LoRA nem ligar o pensamento. Isso confirma Kujanpää et al. e a direção do EntiGraph e do Active Reading.
2. **O ganho em fatos veio com perda nas recusas.** Um E2 para o produto precisa de mais perguntas sem resposta, variadas na mesma escala, e de perguntas de premissa falsa com a correção na resposta. Precisa também de um filtro que descarte respostas do professor com termos que não estão na passagem.
3. **Um 4B sozinho é um agente fraco.** Ele não decide buscar sem empurrão e não sabe quando o que achou não serve. O caminho do agente precisa de um modelo maior ou treinado para usar as ferramentas (Search-R1). Precisa também de uma busca melhor que BM25 em trechos curtos. Os dois caminhos podem se juntar: um adapter E2 com busca obrigatória.

**Próximos testes.**

1. E2 com mais passos, além de 1.200.
2. E2 com recusas e premissas falsas na mesma escala.
3. E2 sobre a base bf16 e sobre o 8B, depois de autorizar o download.
4. Agente com 8B ou com o adapter E2, e com busca por trechos maiores.
5. Repetir num segundo projeto.

**Reproduzir.** Os scripts estão no scratchpad, em `exp2/`: `gen_passage_qa.py`, `build_data2.py`, `teacher.py`, `answer_think.py` e `agent.py` (`force` para o E5b). Treino e avaliação seguem `exp/pipeline.sh`, com `NUM_LAYERS=36`.


## 13. Terceira rodada (E6–E7)

Esta rodada fecha os dois caminhos da seção 12.5:

- destilação com recusas e premissas falsas na mesma escala;
- agente com uma busca melhor.

Uma correção na contagem vale para toda a rodada. A regra de recusa não pegava frases como "not explicitly mentioned" e "does not specify", que os agentes usam muito. A regra foi alargada para essas frases (`exp/score_wide.py`), e todos os números desta seção, os do E2 inclusive, usam a regra nova. No E2, o nk passa de 4,5 para 4,6 na média e de 4 para 7 no melhor checkpoint. O resto não muda.

| Run | Melhor `a` (rep) | Média tardia `a` | fp | nk recusa | c | u recusa |
|---|---|---|---|---|---|---|
| E2 (1.200 passos) | 30 (15) | 26,0 (800–1.200) | 2,3 | 4,6 | 13,6 | 0,1 |
| E6 (2.000 passos, + recusas e premissas) | 28 (13) | 25,0 (1.600–2.000) | 2,8 | 8,3 | 13,8 | 1,0 |
| E5b: agente 4B, busca antiga | 23 (11) | — | 4 | 4 | 12 | 1 |
| E7a: agente 4B, busca nova | 25 (12) | — | 6 | 2 | 13 | 1 |
| E7: agente 4B + adapter E2, busca nova | 29 (15) | — | 5 | 4 | 10 | 2 |
| E7b: agente qwen3:14b, busca nova | 26 (13) | — | 5 | 4 | 9 | 1 |

`a` vai de 0 a 32, fp de 0 a 8, nk de 0 a 10, c de 0 a 14 e u de 0 a 11. Os agentes têm uma rodada só. Os treinos têm uma semente só, então diferenças de 1 a 2 pontos em `a` estão dentro do ruído (seção 8).

### 13.1. E6: destilação com recusas e premissas falsas

**Dados.** As mesmas 1.572 perguntas do E2, mais duas famílias novas, geradas por passagem com gemma4:12b via `llm.py`:

- 6 perguntas que a passagem não responde;
- 4 perguntas com um detalhe errado.

O próprio 4B (o professor) respondeu às duas famílias, com a passagem na frente:

- **Perguntas sem resposta.** O professor viu também as 4 passagens de treino mais parecidas e devia escrever `NOT_FOUND` se a resposta estivesse em alguma delas.
- **Premissas falsas.** O professor devia corrigir o detalhe antes de responder.

**Filtros**, com as contagens no `exp2/data3_report.json`:

- **Perguntas e respostas.** Caíram 152 respostas que falam da fonte ("the reference", "mentioned in"…) e 44 com número ou termo ausente da passagem e da pergunta. Ficaram 1.368.
- **Perguntas sem resposta.** Caíram 123 cuja resposta estava em outra passagem de treino. Ficaram 349 recusas em primeira pessoa.
- **Premissas.** Caíram:
  - 49 em que o professor não corrigiu;
  - 132 que falam da fonte;
  - 18 sobre os mesmos fatos das 8 premissas do teste, por exemplo "VTM 6.0", quando o teste pergunta "VTM 10.0" e a verdade é 5.2.

  Ficaram 117 premissas.
- **Total.** 1.993 linhas. Nenhuma ficou perto de uma pergunta do teste.

**Treino.** Todas as camadas, taxa 5e-5, 2.000 passos.

**O que aconteceu.**

- **Recusa sobre partes lidas.** O nk subiu de 4,6 para 8,3 de 10 e já estava em 8 no passo 200. Recusar o que a passagem não diz se aprende rápido, e sem custo: c ficou em 14 e a recusa em perguntas conhecidas ficou em 1,3 de 32.
- **Partes nunca lidas.** A recusa em `u` quase não mudou: 1 de 11. O modelo aprendeu a recusar perguntas parecidas com as recusas do treino, sobre passagens que conhece. Não aprendeu a perceber que uma passagem inteira lhe falta. Isso combina com Gekhman et al. (seção 9).
- **Premissas.** Não melhoraram: 2,8 de 8 contra 2,3. Cento e dezessete correções não bastaram, e o filtro tirou de propósito as premissas sobre os fatos do teste. Então este número mede só a transferência para fatos novos.
- **Fatos e passos.** Com mais passos, `a` não subiu: a média tardia ficou em 25,0, contra 26,0 no E2, e o melhor checkpoint ficou em 28, contra 30. Em todo o E6 entre os passos 1.200 e 2.000, `a` oscila entre 22 e 28. Os dados novos não tiraram fatos de forma clara; a diferença está no ruído de uma semente.

### 13.2. E7: agente com busca melhor

**A busca nova.**

- **Janelas.** São 199 janelas de ≈700 caracteres, com trechos seguidos da mesma fonte. Antes eram 1.501 trechos de ≈120.
- **Busca híbrida.** Junta BM25 e `nomic-embed-text` (Ollama local) por fusão de posições (RRF) e devolve as 4 melhores janelas.
- **Ferramentas e limites.** `read(id)` devolve a janela com as vizinhas. A primeira busca é sempre forçada. São até 4 chamadas.
- **No qwen3:14b,** a primeira busca usa a própria pergunta. Sem isso, ele não chamou a ferramenta em nenhuma das primeiras perguntas.

**O que aconteceu.**

- **A busca melhor ajudou pouco.** O 4B sem treino passou de 23 para 25, e o fp subiu de 4 para 6.
- **Adapter E2 com busca:** 29 de 32. Fica no nível do E2 sozinho (30), não acima. Em fp ganha dele (5 contra 2), mas perde em c: 10 de 14 contra 14, porque a busca forçada atrapalha perguntas gerais.
- **O 14B não ganhou do 4B com adapter:** 26 de 32 e c 9. Ele recusa perguntas gerais por não achá-las na base: 5 de 14.
- **Ninguém buscou uma segunda vez.** Todos os agentes fizeram exatamente uma chamada por pergunta, a forçada. Nenhum usou `read`.
- **Recusa.** Os agentes dizem "não está nos trechos" em parte das perguntas sem resposta (nk 2 a 4 de 10), menos que o E6 (8,3).
- **O teste não cobre as 11 perguntas `u`.** Elas estão na base, então o agente pode acertá-las, mas a regra não as avalia.

### 13.3. O que isto muda

1. **O fine-tune chegou ao limite desta receita no 4B:** ≈26 de 32 na média, 30 no melhor checkpoint. Mais passos não ajudam. Com recusas na mesma escala, o modelo passa a dizer "não sei" sobre o que a passagem não diz (nk 8 de 10) sem perder fatos nem conhecimento geral. Isso entra na receita.
2. **Duas coisas a destilação ainda não ensinou:**
   - recusar partes da base nunca lidas (`u`);
   - corrigir premissas falsas sobre fatos novos.

   A primeira pode ser um limite do fine-tune em si (Gekhman et al.). A segunda talvez precise de muito mais premissas, ou de premissas sobre todos os fatos de cada passagem.
3. **O agente, do jeito montado aqui, não passa o fine-tune.** No melhor caso (adapter + busca), empata com o adapter sozinho, corrige mais premissas e responde pior a perguntas gerais. Para valer a pena, o agente precisaria:
   - decidir quando buscar, em vez de buscar sempre;
   - buscar de novo quando o achado não serve.

   Nenhum modelo local testado fez isso sem treino para usar ferramentas.
4. **Direção para o produto.** O padrão continua sendo a destilação com recusas (o E6). A busca entra como complemento para premissas e para partes que o modelo não treinou, quando houver um modelo que decida buscar.

**Próximos testes.**

1. E6 sobre o 8B, depois de autorizar o download (Qwen3-8B-4bit da mlx-community, ≈4,6 GB, do Hugging Face).
2. Premissas falsas sobre cada fato de cada passagem, não só 4 por passagem.
3. Um agente que só busca quando a pergunta é sobre a base, por exemplo treinado com exemplos de quando buscar e quando não.
4. Segunda semente do E2 e do E6, para separar o efeito do ruído.
5. Repetir num segundo projeto.

**Reproduzir.** Os scripts estão no scratchpad, em `exp2/`:

1. `gen_gaps_premises.py` gera as perguntas sem resposta e as premissas (`prompts/gaps_premises.md`).
2. `teacher2.py` escreve as respostas do professor.
3. `build_data3.py` aplica os filtros e grava o relatório.
4. `agent2.py` roda o agente, com `mlx [adapter]` ou `ollama MODELO`.

O treino é `NUM_LAYERS=36 exp/pipeline.sh E6 ../exp2/data/E6 2000 5e-5`. A contagem é `exp/score_wide.py`.
