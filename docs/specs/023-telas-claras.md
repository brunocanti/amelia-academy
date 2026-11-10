# 023 — Telas claras

## Problema

Um teste com 4 artigos reais (tardígrados, PLOS) num projeto novo, feito como se fosse a primeira vez de uma pessoa, encontrou telas que pedem que a pessoa saiba como a máquina funciona: palavras internas, configurações que aparecem antes de qualquer coisa, opções que não dá para usar e números sem explicação. A premissa do CLAUDE.md diz que o difícil fica por baixo. Esta spec corrige só as telas. A qualidade das respostas, os números que não batem e a lentidão ficam para outras specs.

Em todos os itens vale o mesmo teste: alguém que nunca viu a Amelia sabe o que clicar sem ler uma explicação?

## Mudanças

### 1. Criar projeto (`views/ProjectNew.jsx`, `i18n`)
- "Identifier" sai da tela. O identificador é gerado a partir do nome e continua podendo ser editado em "More options", que vem fechado.
- "Maximum themes" vai para "More options" com um padrão bom. Se precisar de rótulo, usar "How many topics at most".

### 2. Barra de atividade (`components/Activity.jsx:44`)
- Nunca mostrar o nome do agente (`theme_proposer`) nem contagem de tokens. Mostrar o que está acontecendo em palavras: "Finding topics…", "Reading cell-stiffening-2022.pdf…", "Writing answers…".
- Usar um mapa de agente para frase. Agente sem frase no mapa aparece como "Working…".
- Tokens e problems ficam só dentro do Console.

### 3. Files (`views/Files.jsx`)
- Os 6 números de configuração vão para "Reading options", fechado, com os padrões atuais.
- Botão **"Read all"** quando houver mais de um arquivo não lido. Arquivos na fila mostram "Waiting…" (hoje o segundo Read entra na fila sem mostrar nada).
- Rights:
  - Dizer em palavras se é obrigatório para seguir. Se não for, usar "Rights (optional)".
  - Quando o PDF ou os metadados indicarem licença (CC-BY etc.), já vir sugerido "Open license · CC BY 4.0", com Undo. O modelo prepara e a pessoa confirma.
- `"{n} model call(s), {s}s"` (linha 266) sai. Se for mostrar tempo, mostrar o tempo real de parede: "Took about 5 min".
- Motivo de descarte sem repetição. Hoje aparece "longer than 3 sentences; longer than 3 sentences": juntar motivos iguais.

### 4. Curate (`views/Curate.jsx`, `components/CurationReview.jsx`, `components/BrainGraph.jsx`)
- Abrir em **List**, não em Graph. O grafo demora a desenhar e ignora cliques enquanto isso.
- "Confidence: low · No explanation yet" em todo par não ajuda. Mostrar só quando houver explicação. Sem explicação, não mostrar nada.
- Aprovar em massa: quando o número mudar (198 → 171), dizer por quê numa linha ("27 were set aside by the check").
- **Challenge:** quando houver pares aprovados e o Challenge ainda não tiver rodado, sugerir numa linha visível fora do Decide: "Check these against each other? Finds answers that disagree." [Check]. Avisar quanto tempo deve levar.
- Recarregar a página mantém a tela e a aba atuais (guardar na URL: `#curate/decide`). Hoje sempre volta para Files.

### 5. Cartão de premissa falsa (`views/Conflicts.jsx:27`)
- "Does this quote prove the claim wrong?" é negativa dupla. Trocar por "Is this claim wrong, based on the quote?", com as respostas "Yes, it's wrong" / "No, it's right".

### 6. Prepare (Train → Get it ready)
- O progresso não mostra o tipo entre parênteses. Em vez de "Pair 35 of 167 (known)", mostrar "Pair 35 of 167".
- Se preparar menos pares do que os aprovados (167 de 171), dizer por quê numa linha.

### 7. Teach (`views/Train.jsx:240-255`)
- Opção desligada "Answers with explanations — not ready yet" sai. Opção só existe se a pessoa pode usar.
- "Ollama models are unloaded…" e "Refresh options" saem da tela principal. Se a memória for um problema real, avisar em palavras simples só quando acontecer.
- Depois de "Start training", a tela não fala do próprio treino como se fosse outra tarefa ("Another task is running", "One model can train at a time"). Mostrar só o progresso do treino que a pessoa iniciou.

### 8. Compare (`i18n/en.js:91`, `pt-BR.js`, `views/Compare.jsx`, `components/Prose.jsx`)
- O título está fixo como "Version 2". Usar o número da versão real: "Is Version {n} better than the original?". No primeiro treino é Version 1. Vale para o placar ("Version {n} won…").
- `Prose` renderiza itálico com um asterisco: `*R. varieornatus*` → *R. varieornatus*.

## Fora do escopo
- Qualidade das respostas: pares "não sabe" errados, premissas falsas descartadas, fatos trocados.
- Números que não batem entre telas: 181/216, 668/666+81/839.
- Velocidade do Challenge e do Curate.

## Pronto quando
- Nenhuma tela mostra nome de agente, tokens, "model call", "Identifier" ou opção desligada.
- Um projeto novo com 4 PDFs vai de Files a Compare usando só botões visíveis, sem abrir "More options".
- Recarregar em Curate/Decide continua em Curate/Decide.
- Compare do primeiro treino diz "Version 1".
- `npm run build` passa, os textos existem em `en.js` e `pt-BR.js`, e os testes do backend continuam passando se algo mudar lá.
