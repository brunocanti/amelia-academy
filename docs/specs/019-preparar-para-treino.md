# Especificação 019 — Preparar para treino

**Status:** proposta, 9 nov. 2026. Para construir.
**Relacionadas:** Especificações 012, 014, 015, 016, 017 (resultados E2 e E6), 018 (E8, que não deu certo); ADR 016.

## 1. Propósito

A spec 017 mostrou o que faz um modelo pequeno aprender os fatos de um projeto:

- **Perguntar o mesmo de várias formas.** Isso dobrou o acerto em perguntas novas.
- **Destilar.** O próprio modelo base responde cada pergunta com o trecho na frente, e o treino ensina a pergunta com essa resposta, sem o trecho. No E2, isso deu 30 de 32, contra 21–22 sem destilar.
- **Recusas e premissas falsas na mesma escala.** No E6, o modelo passou a dizer "não sei" sobre o que o trecho não diz em 8 de 10 perguntas, contra 4,6 antes.

Hoje a Amelia exporta cada par aprovado uma vez só. Esta spec acrescenta um passo entre o Curate e o Export. O passo multiplica **só o que a pessoa aprovou**, mostra uma amostra para conferir e entrega tudo pronto ao Export.

Ficam de fora:

- A busca nos arquivos na hora de responder ("buscar sempre"). Ela pertence ao uso do modelo, não aos dados, e fica para outra spec.
- O treino de ferramentas (E8), que não deu certo.

## 2. O que a pessoa vê

O passo fica na tela **Export**, acima do botão de exportar, e não ganha item novo no menu.

- **Sem material.** Um cartão diz "Make the model learn better" e, abaixo, em uma frase: "Writes other ways to ask each approved pair, with answers, so the model learns the facts and not just the wording." O botão é **Prepare**.
- **Rodando.** Roda como os outros runs (`runs.py`), com Stop e Continue na faixa de cima. Sair da tela não cancela.
- **Pronto.** O cartão mostra quantas linhas de cada tipo saíram e quantas foram descartadas, com o motivo em palavras simples ("talked about the source", "used a number that is not in the file", "did not correct the wrong detail").
- **Conferir.** Ao lado, "Do these look right?" mostra 3 exemplos de cada tipo. Cada exemplo tem **Drop this one**, com Undo na hora, e "Show more" abre os outros.
- **Pares desatualizados.** Se um par foi editado ou rejeitado depois, o cartão diz quantos pares estão desatualizados e o botão vira **Update**. Ele refaz só esses pares.
- **Export.** Usa o material pronto quando existe. Se não existe, exporta como hoje e mostra uma linha: "Without this step the model learns less."

Nenhuma configuração é exposta. As quantidades da seção 3 são padrões fixos.

## 3. O que o passo gera

Cada linha nasce de um par aprovado e guarda o id do par e a versão dele. A versão é um hash da pergunta, da resposta, da citação e do tipo.

| Tipo do par | Linhas por par | Quem escreve a pergunta | Quem escreve a resposta |
|---|---|---|---|
| Known | 5 outras formas de perguntar | modelo de geração do projeto, via `llm.py` | **modelo base do treino**, com o trecho da citação no contexto |
| Not known | 3 outras formas de perguntar | modelo de geração, via `llm.py` | modelo base, com os 4 trechos mais próximos: recusa em primeira pessoa que nomeia o assunto, ou `NOT_FOUND` |
| False premise | 3 perguntas com outro detalhe errado sobre o mesmo fato | modelo de geração, via `llm.py` | modelo base, com o trecho: corrige o detalhe e depois responde |

O par original também entra no Export, como hoje.

**Quem responde é o modelo que vai ser treinado.** No E3, as respostas do gemma deram menos acerto que as do próprio Qwen (23,4 contra 26,0). O modelo base é o mesmo que a tela Train usa por padrão, `Qwen3-4B-4bit` na revisão fixada. As respostas rodam no worker MLX local (`app/trainer/`), com o pensamento desligado, porque o treino também é sem pensamento. Usam a mesma coordenação de GPU do Train: o passo não roda junto com um treino.

**Os prompts de referência** estão nos scripts do experimento e devem ser adaptados para o produto, não copiados com caminhos:

- gerar perguntas por trecho: `exp2/prompts/passage_qa.md`;
- responder com o trecho na frente: `exp2/teacher.py`, a constante `SYS`;
- gerar e responder perguntas sem resposta e premissas: `exp2/gen_gaps_premises.py` e `exp2/teacher2.py`;
- filtros: `exp2/build_data3.py`.

Esses caminhos ficam dentro de `$SCRATCH/`. A diferença para o experimento é que lá as perguntas saíam por trecho, e aqui saem do par aprovado.

## 4. Filtros

Os filtros são de código e rodam antes de gravar. Cada linha descartada guarda o motivo, e o cartão mostra a contagem de cada motivo.

1. **Fala da fonte.** Descarta a resposta que fala da fonte: "the reference", "the passage", "the text", "mentioned in", "according to" e similares. Reusar a regra que já existe no código, se houver.
2. **Número ou termo inventado.** Descarta a resposta de Known e False premise com número ou termo técnico que não aparece no trecho nem na pergunta.
3. **Recusa onde não devia.** Descarta a recusa numa linha de Known.
4. **Resposta em outro arquivo.** Descarta a linha de Not known em que o modelo base escreveu `NOT_FOUND`, porque a resposta estava num trecho próximo.
5. **Detalhe não corrigido.** Descarta a linha de False premise cuja resposta não corrige o detalhe errado. Sem a correção, ela ensina a concordar com o erro.
6. **Repetição.** Descarta a pergunta quase igual a outra do mesmo par, pela regra de repetição quase literal que já existe.
7. **Perto do teste.** Descarta a pergunta parecida com as perguntas de teste do Compare (spec 015), por Jaccard de palavras ≥ 0,5. Sem isso, o Compare mede decoreba.

## 5. Dados e divisão

- **Tabela nova** `training_variants`, com: `id`, `project_id`, `pair_id`, `pair_version`, `kind`, `question`, `answer`, `status` (`kept`, `dropped_by_rule`, `dropped_by_person`), `reason`, `question_model`, `answer_model` e `created_at`. Migração no padrão do `db.py`.
- **Par editado ou rejeitado.** As linhas dele ficam desatualizadas e o Export não as usa. O Update apaga essas linhas e gera de novo.
- **Mesma divisão do par de origem.** A linha vai para a mesma parte (train, val, test) que o par de origem, usando a divisão em grupos que já existe em `datasets.py`. Uma variação de pergunta de teste nunca pode cair no treino.
- **`samples.jsonl`.** Cada linha leva `kind` igual ao do par e `derived_from` com o id do par.
- **Manifesto e README.** Contam as linhas por tipo e por origem.

## 6. Treino

Quando o dataset tem linhas deste passo, a tela Train usa o padrão do E6: todas as camadas, taxa 5e-5 e cerca de 2,8 épocas. Nos outros casos, o padrão continua o de hoje. A tela não mostra essa troca como opção. Ela só aparece no resumo do treino, em uma linha.

## 7. Como medir

O Compare já existe. A primeira versão precisa de um teste num projeto de cópia, nunca nos dados reais. Treinar duas vezes com o mesmo dataset, uma com e outra sem este passo, e registrar o acerto nas perguntas de teste.

A spec 017 indica um ganho grande. Mas lá as perguntas saíam por trecho, e aqui saem do par: o ganho desta forma ainda não foi medido. Registrar o resultado na seção 9.

## 8. Regras para quem construir

- Leia `AGENTS.md` e `docs/architecture/estado-atual.md` antes de mudar o produto.
- Não commite, não troque de branch e não rode formatadores no repositório. A pasta é compartilhada com outras sessões: não desfaça mudanças que não são suas.
- Não altere `~/Projects/Amelia3`.
- Geração de texto passa por `llm.py`. Um modelo externo roda pela CLI da ferramenta, nunca por API direta.
- Testes sem modelo de verdade: o modelo de geração e o worker MLX ficam simulados. Cubra os filtros, a versão do par, a divisão, o Export e a migração. Use o venv do backend (`app/backend/.venv`).
- A UI segue a premissa do `AGENTS.md`: perguntas simples, sem vocabulário da máquina, Undo em toda decisão. Textos em `en.js` e `pt-BR.js`. Rode `npm run build` em `app/ui`.
- No fim, atualize o `estado-atual.md` com o que foi construído e o que falta, e preencha a seção 9.

## 9. Execução

Implementado: tabela e migração de variações; cálculo da versão pelo conteúdo do par; geração de perguntas via cliente do projeto (`llm.py`) em run; respostas delegadas ao worker MLX isolado, com reserva da GPU; filtros de regras e proximidade com perguntas do Compare; revisão com remoção e Undo; variantes atuais entram em `samples.jsonl` na mesma divisão do par de origem, com `derived_from`; cartão de preparo em Export e textos em inglês e português. Known usa prompt de sistema no estilo E2, com trecho e resposta de especialista em 1–3 frases, sem falar da fonte. Not known busca até quatro trechos próximos do projeto por pergunta e devolve `NOT_FOUND` quando eles respondem. False premise gera uma pergunta com outro detalhe errado, carrega seu `false_claim` ao worker e ao filtro. O worker MLX responde em lotes de oito com `batch_generate` e limpa o cache entre lotes. Cada par é processado e persistido antes do próximo; Continue pula pares já completos. O padrão de treino com variantes usa as 36 camadas do Qwen3-4B.

Desvios/limites: Stop só é observado entre pares e não interrompe uma inferência MLX em andamento. Uma falha durante um par pode repetir esse par ao continuar; pares anteriores já foram persistidos e não são refeitos. A amostra inicial mostra três exemplos, sem paginação persistente de “Show more”. O filtro de termo técnico é heurístico e precisa ser refinado. Não foi feito o experimento comparativo em cópia de projeto exigido pela seção 7; o ganho desta forma segue não medido.

Testes: acrescentados testes com worker simulado para busca de quatro trechos Not known, propagação do `false_claim` e lotes de oito com timeout curto. A suíte completa e a build da UI serão registradas após a execução final. Os testes não carregam modelos reais.

Falta: teste de migração incremental de banco preexistente; Undo durável após recarregar a página; medir dois treinos comparáveis em cópia e registrar acerto no Compare.
