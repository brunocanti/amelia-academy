# 024 — Dados certos, números que batem, mais rápido

Vem do teste com 4 artigos de tardígrados (PLOS), no projeto `prj_5205f58eba19`. A spec 023 cuida das telas. Esta cuida do resto que o teste encontrou: respostas erradas, números que não batem entre telas e lentidão. Como é o mesmo backend, deve ser feita depois da 023.

## 1. Respostas certas

**1.1 Citação inteira.** O par guarda e mostra a frase inteira da citação, não um pedaço cortado. No teste, "15–20%" era sobre artrópodes e nematoides, mas a resposta disse que era sobre tardígrados, e o fragmento citado escondia a troca. O gerador recebe junto a frase anterior e a seguinte, e o verificador confere o sujeito da resposta contra a citação inteira.

**1.2 Pares "não sabe".**
- Antes de gravar um par Not known, buscar nos trechos do projeto. Se algum trecho responde a pergunta, o par é descartado. No teste, 15 dos 20 conflitos eram assim.
- Não gerar perguntas sobre metadados: data de aceite, endereço, financiamento, quem cedeu um plasmídeo, títulos de referências, agradecimentos. Filtrar as seções de referências, afiliações e agradecimentos antes de gerar.

**1.3 Premissa falsa.**
- Gerar a afirmação errada mudando um único detalhe verificável. Rejeitar quando a afirmação "errada" for verdadeira segundo a citação.
- O Prepare não descarta premissa falsa por "não corrigiu" quando a resposta nega a premissa com outras palavras. A meta é que pelo menos metade das geradas chegue a ready (hoje são 9 de 33).

**1.4 Sem acréscimos.** Respostas do Prepare não acrescentam termos que não estão na citação. Exemplo do teste: "osmoprotective mechanisms". O filtro existente de apoio na citação passa a valer para cada frase da resposta.

**1.5 Limite de frases.** O limite de 3 ou 4 frases conta frases reais. Uma resposta de um fato com nome científico ou abreviação ("Chlorella vulgaris (C. vulgaris)…") não pode ser rejeitada. Usar um separador de frases que ignore abreviações e nomes binomiais.

**1.6 Símbolos do PDF.** Preservar α, β, ~, ±, µ, Δ na extração. No teste, viraram a, b e vírgula. Conferir a extração atual (fitz/pymupdf) e corrigir a normalização que os perde.

**1.7 Nada de máquina no texto.** Respostas e referências nunca citam o processo ("The original statement incorrectly claimed…", "the corrected information shows"). Rejeitar ou reescrever.

**1.8 "Expand" de verdade.** Quando o expander devolve o mesmo texto, isso não conta como sugestão. Ele tenta de novo uma vez e, se continuar igual, diz "Nothing to add".

**1.9 Perguntas do Compare.** Não repetir no mesmo teste perguntas quase iguais. No teste, 6≈9 e 8≈11. Usar a mesma checagem de duplicadas do Curate.

## 2. Números que batem

Um só número por coisa, com o mesmo nome em todas as telas, e cada diferença explicada em palavras numa linha.

- **Files × Curate.** Os pares contados em Files batem com o total do Curate, ou o Curate diz de onde vêm os outros (por exemplo, "35 came from the Challenge"). No teste eram 181 × 216.
- **Cartões por arquivo.** Os números de cada cartão somam o total. No teste, 38+5+11 ≠ 43.
- **Prepare → Teach → versão.** Cada tela nomeia a contagem que mostra e reconcilia as diferenças: Prepare conta variantes mantidas; Teach conta linhas de treino e checagem (e deixa teste explícito); a versão conta pares originais mais variantes mantidas em todos os splits. No teste eram 668 variantes mantidas, 666+81 linhas nos splits de treino e validação, e 839 registros no total; 92 estavam no split de teste. Contagens de variantes descartadas, pares aprovados sem preparo, exclusões no export e linhas cortadas ficam acompanhadas do motivo.
- **Descartes.** Mostrar o motivo agrupado ("39 were too long, 4 repeated"), não uma lista repetida.

## 3. Mais rápido

- **Challenge.** No teste levou 24 minutos (439 comparações). Só comparar pares do mesmo tema e com trechos próximos (embedding ou palavras), comparar em lotes e pular pares idênticos. A meta é menos de 5 minutos para cerca de 200 pares.
- **Curate.** Abrir pela lista sem esperar o grafo. O grafo carrega depois e não bloqueia cliques.
- **Read.** Ler arquivos em sequência sem a pessoa clicar em cada um (o botão "Read all" é da spec 023). Reaproveitar o modelo carregado entre arquivos.
- **Servidores.** Quando o app reinicia e derruba o backend, a UI mostra "Starting again…" e tenta de novo sozinha. O texto "Cannot reach API" continua só se a tentativa falhar.

## Pronto quando

- Testes novos, sem modelo real:
  - citação inteira;
  - Not known descartado quando há um trecho que responde;
  - filtro de metadados;
  - premissa falsa verdadeira rejeitada;
  - contagem de frases com nome binomial;
  - símbolos preservados;
  - números iguais em Files, Curate, Prepare e versão.
- Refazer o projeto tardígrado do zero: Challenge com menos de 5 minutos e nenhum Not known respondido nos arquivos.
- `npm run build` passa e os testes do backend passam com o venv.
