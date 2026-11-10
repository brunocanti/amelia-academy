# Especificação 020 — Prepare explicado, um só modelo do Prepare ao Train, e a barra de atividade

**Status:** proposta, 9 nov. 2026. Para construir.
**Relacionadas:** Especificação 019 (Preparar para treino), ADR 016, CLAUDE.md ("o difícil fica por baixo").

## 1. Propósito

O teste e2e da 019 deixou três coisas para resolver:

1. **O Prepare usa dois modelos, e a tela não diz isso.**
   - O modelo do projeto (por exemplo gemma4:12b) escreve as perguntas novas e confere as de "Not known".
   - O modelo que vai ser treinado (hoje Qwen3 4B) escreve as respostas.

   Isso é de propósito: com as respostas escritas pelo próprio modelo, o treino ensina os fatos e não um jeito novo de escrever (spec 017, E2 e E6). Mas a pessoa não sabe disso e não tem como escolher.
2. **O Prepare e o Train podem usar modelos diferentes.**
   - O Prepare usa sempre `CATALOG[0]`.
   - O Train deixa escolher outro modelo.

   Se forem diferentes, o treino ensina ao modelo B as respostas do modelo A, e o ganho da destilação some sem aviso.
3. **O progresso e os avisos ficam espalhados.**
   - A `RunsStrip` (`components/Runs.jsx`) empilha uma linha por run no topo e empurra a tela para baixo.
   - Cada tela tem seus próprios "ok", "removed / Undo" e erros soltos.

## 2. Prepare: o que a pessoa vê

O cartão **Make the model learn better** (Export) continua com um botão principal. Abaixo da descrição entra uma linha curta, sempre visível, inclusive antes da primeira preparação:

> Questions by **gemma4:12b** · Answers by **Qwen3 4B**, the model you will train · [Change]

Os nomes vêm dos modelos realmente selecionados; o exemplo acima não é texto fixo.

- **Change** abre um painel pequeno dentro do cartão com três escolhas:
  - **Which model writes the new questions?** O mesmo `ModelSelect` e o modelo de projeto usados em Files. A pessoa não vê uma segunda lista ou uma preferência independente.
  - **Which model will you train?** Seletor com modelos de `train/models`; grava a escolha no projeto (ver §3). Ajuda em uma frase: “This model writes the answers in its own words, so training teaches it the facts, not a new way of writing.”
  - **How many ways to ask each pair?** Few / Normal / Many. Normal é o padrão e reproduz os `COUNTS` atuais. Few usa metade, Many o dobro, por tipo, arredondado para inteiro e com mínimo 1. É a única opção de quantidade; não há números por tipo.
- Mudanças são salvas ao selecionar. **Done** fecha o painel. Enquanto salva, a escolha fica desabilitada e a tela mostra o estado; falha fica visível com opção de tentar de novo.
- Mudar uma escolha marca como desatualizados os exemplos afetados e troca o botão para **Update**: modelo de perguntas afeta todos; modelo de treino afeta todas as respostas; quantidade acrescenta ou remove apenas o excedente por par. Exemplos mantidos pela pessoa dentro da nova quantidade continuam mantidos. Reduzir a quantidade não apaga linhas: excedentes ficam fora do Export e voltam a ser elegíveis se a quantidade aumentar.
- **Update** processa somente pares aprovados novos/desatualizados e somente linhas necessárias à quantidade selecionada. Ao final, totais, motivos e amostras refletem os dados persistidos. Uma falha mantém o trabalho já gravado e Continue não refaz pares completos.
- Enquanto roda, a mensagem mostra etapa, pessoa/modelo e contagem, por exemplo: “Pair 12 of 200 (known): Qwen3 4B is writing answers · 40 kept, 6 dropped”. Em geração/checagem de perguntas, nomeia o modelo de perguntas; em respostas, o modelo de treino. Use nomes de modelos, não “worker”, “variant”, “distillation” ou “MLX”.
- A barra pode mostrar proporção de pares concluídos. Sem total conhecido, usa indicador indeterminado; não inventa percentual. A mensagem detalhada permanece no balão do chip.
- Se um modelo necessário não estiver disponível/baixado, diga qual e como resolver em palavras simples, por exemplo: “Qwen3 4B is not downloaded yet. Download it in Train first.” Não há troca silenciosa de modelo nem download automático.

## 3. Um só modelo do Prepare ao Train

- O projeto guarda `train_model`, campo novo com migração em `db.py`; o padrão é `training.CATALOG[0]['id']`. A pergunta “Which model will you train?” no Prepare e o modelo inicialmente escolhido no Train leem o mesmo campo por `GET/PATCH /projects/{id}`. PATCH sem `train_model` preserva o valor. Banco antigo/nulo recebe o padrão. Id fora do catálogo é rejeitado com erro claro. Se um id salvo sair do catálogo, o projeto continua legível e a interface explica que aquele modelo não pode ser usado.
- O projeto guarda também `prepare_count` (`few`, `normal`, `many`), com migração, padrão `normal` e validação estrita. PATCH é a fonte comum da escolha. A API de preparação não aceita contagens arbitrárias. O backend escala `prepare.COUNTS` por 0,5, 1 ou 2, arredondando e impondo mínimo 1.
- O modelo de perguntas continua sendo o modelo de projeto já selecionado na barra superior/Files. O Prepare usa o mesmo `ModelSelect`; não cria preferência duplicada. A chamada segue `llm.py`; as respostas seguem o worker local existente.
- `training.answer_variants` recebe explicitamente `train_model`, em vez de fixar `CATALOG[0]`. Cada linha salva o id efetivo em `training_variants.answer_model`; `question_model` mantém o modelo que escreveu a pergunta.
- O manifesto do Export inclui `answer_model`, `question_model` e `prepare_count` quando há exemplos preparados. Se exemplos mantidos de configurações diferentes entrarem no mesmo Export, registra todas as combinações presentes; não declara uma configuração única para todas as linhas. Exportações sem variantes não incluem esses campos.
- No Train, compara o id completo do modelo selecionado com os `answer_model` dos exemplos preparados no dataset:
  - se todos forem iguais, não mostra aviso;
  - se forem diferentes, mostra junto ao dataset: “These examples were written by Qwen3 4B. Training another model on them teaches it Qwen3 4B's way of writing.” Se houver vários, identifica os nomes distintos sem ocultar a mistura;
  - **Prepare again for {model}** salva o modelo no projeto, navega para Export e deixa a atualização pronta;
  - não bloqueia treino. O preflight retorna essa condição em `warnings`, nunca em `errors`.
- Datasets sem exemplos preparados ou com manifesto antigo sem `answer_model` não mostram comparação como se os dados fossem conhecidos. Manifestos antigos continuam treináveis.
- A escolha no Train também atualiza `projects.train_model`. Ainda é possível escolher outro modelo para um treino; essa escolha se torna a preferência do projeto.
- O catálogo do Train continua sendo `train/models` e sua seleção de modelos suportados. A preferência não significa que o modelo está em cache. Se faltar download, o preflight explica como obtê-lo; não baixa automaticamente.

## 4. Barra de atividade (vale para a Amelia toda)

A `RunsStrip` do topo e os avisos passageiros das telas são substituídos por uma barra fina fixa embaixo, com uma única linha (cerca de 36 px). O conteúdo recebe `padding-bottom` equivalente. Ela respeita a navegação lateral, safe area, temas claro/escuro e não cobre controles nem conteúdo rolável.

**O que entra na barra.** Itens são chips horizontais, mais novo à direita:

- **Run rodando:** título curto, progresso quando houver total e “12/200”. Sem total conhecido, indicador indeterminado. Clique abre o detalhe.
- **Run terminado:** ✓ ou ✕ e título. Sucesso sem ação some após 8 s e vai ao histórico. Falhas e runs que podem continuar ficam até a pessoa agir. Runs parados que podem continuar também ficam até Continue ou OK.
- **Aviso de tela:** exemplos “Example removed · Undo”, “Saved”, “Exported 204 pairs”. Com Undo expira em 10 s; sem ação, em 5 s; erros não expiram até fechar.

Erros de formulário e explicações necessárias para decidir (incluindo aviso de modelo diferente da §3) ficam perto do campo/cartão. A barra serve para avisos passageiros e trabalho em segundo plano, não substitui estados duráveis nem o erro do treino.

**Clique num chip.** Abre balão acima dele com mensagem completa (`run.message`, erro ou texto da notificação) e só as ações disponíveis: **Stop**, **Continue**, **Go to it**, **Undo**, **OK**. Stop pede parada no próximo ponto seguro e preserva o que foi concluído; Continue só aparece quando o backend permite; Go to it navega para tela/parâmetros registrados no run. Undo executa uma vez, fecha o chip ao concluir e mantém o aviso aberto com erro se falhar. OK apenas oculta o run na interface; não cancela nem apaga dados. Para runs, o detalhe preserva a mensagem atual: “Stopped at 40 of 200. What is done stays.”

**Muitos chips.** Os mais antigos que não exigem ação se agrupam em “+N” à esquerda, que abre uma lista vertical ancorada. Runs em andamento, falhas e ações pendentes têm prioridade de visibilidade. Nada some do histórico por agrupamento. A faixa não quebra em duas linhas nem cria rolagem horizontal na página.

**Histórico.** Ícone de relógio na ponta direita abre os últimos 30 eventos da sessão, com hora local e projeto. Inclui itens expirados e fechados. O histórico fica em `sessionStorage`, não serializa ações e pode ser limpo ao fechar a sessão. Runs ativos continuam sendo lidos do backend; histórico local não é fonte de verdade.

**Console.** Só há uma faixa fixa inferior. O botão do Console é o último item da barra. Aberto, o Console vira gaveta acima dela, com altura limitada e rolagem própria. Texto ao vivo, logs e detalhes de chamadas continuam no Console; o chip resume a execução, sem duplicar fluxo de tokens.

**Celular (largura até 600 px).** Só o chip mais novo e “+N” ficam visíveis. Detalhes/listas abrem como folha inferior com ações alcançáveis sem rolagem horizontal.

**API para as telas.**

- Criar `components/Activity.jsx` com provider no shell do projeto e hook `useActivity()`. Pode incorporar `RunsProvider`; `useRuns()` continua funcionando para componentes legados, incluindo `runs`, `refresh`, `find`, `stop`, `resume`, `isRunning`, `runsChanged` e `trouble`.
- `notify({ text, tone: 'ok' | 'error' | 'info', action?: { label, onClick }, ms? })` devolve id; `dismiss(id)` remove. Padrões: 5 s sem ação, 10 s com ação, erro sem expiração. `ms` sobrescreve o tempo. Notificações iguais consecutivas podem atualizar o chip existente.
- A ação roda uma vez. Em sucesso, fecha o aviso; em falha, preserva-o e apresenta o erro. Notificações/ações ficam em memória enquanto a aplicação está aberta; o histórico guarda apenas texto e metadados em `sessionStorage`.
- Compatibilidade: itens de run fechados com OK continuam respeitando `academy.runs.hidden` em `localStorage`. O provider continua consultando runs por projeto e atualiza chips por mudança de estado, sem cancelar tarefas ao trocar de tela. Falha de polling é um aviso persistente com nova tentativa, não um chip por tentativa. Histórico separa projetos.
- Migrar avisos passageiros em Export, Curate, Files, Compare, Train e Behaviors: removidos/Undo, salvos, exportados e erros de ação que não pertencem a campos. Em Export, remoção de exemplo vira “Example removed” com Undo; sucesso simples expira em 5 s.
- Erros de campo, estados que orientam a tela, preflight, falta de arquivo/modelo, avisos de export que exigem revisão e erro persistente do treino permanecem junto ao contexto.

**Aparência.** Usar variáveis de cor já existentes para claro/escuro; chip ativo com cor de destaque, ✓ verde discreto e ✕ vermelho. Fade curto ao entrar/sair, sem outras animações e sem sombra pesada.

## 5. Testes

- Backend, sem modelos reais e com stubs como em `test_prepare.py`:
  - migração incremental de `train_model` e `prepare_count`, padrão e validação;
  - leitura/gravação pelo PATCH do projeto e consistência entre Prepare e Train;
  - propagação de `train_model` a `answer_variants`, persistência de `answer_model` e `question_model`;
  - troca de modelo invalida respostas afetadas; troca de modelo de perguntas invalida perguntas; mudança de quantidade acrescenta/remove excedente sem apagar decisões da pessoa;
  - Few/Normal/Many altera contagem com mínimo 1;
  - manifesto registra configuração usada, incluindo conjunto com mais de uma configuração;
  - preflight sem variantes, com modelo igual e diferente, e com mais de um modelo de resposta;
  - chamadas ao gerador/worker continuam pelos pontos existentes, sem modelo real.
- Cobrir também que exemplos antigos sem metadado de modelo continuam exportáveis e treináveis e não disparam aviso falso.
- UI: `npm run build` passa. Se houver infraestrutura de testes de UI, cobrir `notify`, expiração, ação Undo bem-sucedida/falha, histórico de 30 itens, agrupamento “+N”, prioridade de itens pendentes, layout até 600 px, `useRuns()` legado e `academy.runs.hidden`. Se não houver infraestrutura, registrar isso e verificar esses critérios por revisão manual; não criar ferramenta de testes apenas para esta spec.
- Não carregar modelos reais. Não iniciar nem reiniciar servidores nos testes; suíte automatizada e build local não dependem das portas do app.

## 6. Regras

- Não commite, não troque de branch, não rode formatadores no repositório.
- Não desfaça mudanças de outras sessões. Há mudanças não commitadas em `prepare.py`, `agents/question_varier/`, `agents/answer_checker/nearby.md` e `tests/test_agents.py`, que dão nome aos agentes do Prepare no console. Mantenha-as.
- Não reinicie os servidores que estão rodando (portas 8000, 8001 e 5174). Há um Prepare em andamento na 8001.
- Modelos só pelo `llm.py` ou pelo worker local, nunca por API direta.
- Use o venv: `PYTHONPATH=app/backend app/backend/.venv/bin/python -m pytest app/backend/tests -q`.
- Textos da UI em inglês, com as mesmas chaves em `i18n/en.js` e `i18n/pt-BR.js`.
- No fim, liste o que mudou, por arquivo, e o resultado dos testes e do build.

## 7. Emenda (9 nov. 2026): o Prepare mora na tela Train

O teste e2e mostrou que o Prepare na tela Export fica estranho: os exemplos são escritos pelo modelo que vai ser treinado, então o Prepare é parte do treino, não do export. Esta seção substitui o que a §2 e a §3 dizem sobre onde as coisas ficam.

**Tela Train, uma sequência só, de cima para baixo:**

1. **"Which model should learn this?"** — o seletor de modelo, que grava `train_model` no projeto. É a única escolha de modelo de treino da Amelia.
2. **"Get it ready"** — o cartão do Prepare inteiro sai da tela Export e vem para cá, com:
   - a linha "Questions by X · Answers by Y · Change", onde o Change só oferece o modelo das perguntas e Few / Normal / Many, porque o modelo das respostas é o do passo 1;
   - os contadores por tipo;
   - "Do these look right?" com Drop, Undo e Show more;
   - os botões Prepare / Update / "Up to date".

   Uma frase explica: "{model} writes practice answers in its own words, so training teaches it the facts. Check a few."

   Se o modelo do passo 1 mudar e já houver exemplos, eles ficam desatualizados, e o botão vira **"Get it ready again"**.
3. **"Teach"** — o treino. O botão exporta o dataset por baixo, com os pares aprovados e os exemplos prontos, e treina em seguida. A pessoa não escolhe dataset nem precisa ter passado pela tela Export.
   - Os ajustes atuais (épocas, batch, lr) ficam num "More settings" fechado.
   - Se ainda não houver exemplos prontos, o botão continua ativo e mostra uma linha: "Without getting it ready the model learns less."
   - Escolher um dataset exportado antes continua possível dentro do "More settings". Nesse caso vale o aviso de modelo diferente da §3.

**Tela Export:** volta a ser só exportar os dados, sem o cartão do Prepare. Quando há exemplos prontos, ela mostra uma linha: "Includes {n} practice examples written by {model}." Se não houver, nada.

**Backend:**
- `POST /projects/{id}/train/runs` passa a aceitar `dataset_id` opcional. Sem ele, exporta com o perfil `direct` e a saída `finetune`, e usa esse dataset.
- O preflight aceita a mesma ausência.
- Cubra com testes.

## 8. Train em passos (emenda)

Train com Prepare na mesma página e scroll longo ficou confuso. A tela vira três passos, um visível por vez:

1. **Model** — "Which model should learn this?" Só a escolha do modelo.
2. **Get it ready** — o PrepareCard: números por tipo, alguns exemplos para conferir, botão Prepare/Update.
3. **Teach** — o que aprender, "More settings" fechado, checagem e botão de treino.

- Uma linha pequena no topo mostra os passos: atual em destaque, feitos com ✓, clicáveis para voltar. Avançar com um botão "Next" no fim de cada passo.
- A tela abre no primeiro passo que falta; se tudo estiver pronto, abre em Teach.
- Nada de tabs: é uma sequência, não telas independentes.

Ajustes junto:
- Enquanto os modelos carregam, a linha "Answers by …" não aparece com nome vazio (esconde até ter o nome).
- "Questions by X" mostra o modelo que de fato escreveu as perguntas já preparadas (`question_model` das variantes); o seletor global só vale para a próxima preparação. Não marcar como "changed" só porque o seletor global mudou.
- Plural correto: "1 approved pair is new or changed" / "{n} approved pairs are…" (en e pt-BR).
- Uma barra só embaixo: a faixa preta do Console sai; o estado do modelo ("The model is idle", tokens, problemas) vai para a barra de atividade, e o Console abre pelo botão dela.
