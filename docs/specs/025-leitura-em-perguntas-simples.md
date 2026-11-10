# 025 — Leitura em perguntas simples

Vem do reteste com 4 artigos de tardígrados (`prj_d091bc3caf97`). Hoje "Reading options" pede números absolutos que a pessoa não sabe escolher:

- pares por seção (6);
- caracteres por seção (4.500);
- premissas falsas e "não sabe" por seção (2 e 2);
- vizinhos (5%);
- imagens (desligado).

Os temas são 8 fixos (`DEFAULT_MAX_THEMES`, limite 50). Esses números decidem o tamanho do dataset, o comportamento do modelo (recusar × inventar), a velocidade do Challenge e o split de teste. A pessoa não vê nenhum desses efeitos.

Premissa (CLAUDE.md): perguntas simples, respostas curtas, o difícil fica por baixo.

## 1. Duas perguntas no lugar das opções

**"How much should it take from each file?"** — Quick · Normal (padrão) · Everything.
- Não é mais um número fixo por seção. A Amelia conta os fatos de cada trecho (frases com afirmação verificável, número, nome, causa) e gera de acordo.
- Trecho denso dá mais pares, e trecho de método, referência ou agradecimento dá zero.
- Quick ≈ os fatos principais, Normal ≈ a maioria, Everything ≈ todos os fatos com citação.
- Teto técnico por trecho continua por baixo, para segurança.

**"How careful should the model be?"** — Answers directly · Balanced (padrão) · Very careful.
- Define a mistura do dataset em percentual do total, não por seção: Balanced ≈ 70% sabe · 15% corrige premissa falsa · 15% diz que não sabe; Very careful sobe as duas últimas.
- Uma barra única mostra a mistura ("70% knows · 15% corrects · 15% says it doesn't know"). Arrastar ajusta, e Undo aparece na hora.
- Os vizinhos entram dentro do "diz que não sabe".

## 2. Estimativa antes de ler

Antes de "Read all", uma linha: "About 150 pairs, about 20 min with qwen3:14b".
- A estimativa sai de páginas, trechos, a escolha acima e a velocidade medida do modelo nas leituras anteriores.
- Ela muda na hora quando a pessoa muda a resposta.
- Depois da leitura, Files mostra o real ao lado do estimado.

## 3. O que sai da tela

- **Tamanho do trecho:** a Amelia escolhe pela janela do modelo e pela estrutura do arquivo (seções, páginas). O backend continua com `WINDOW_CHARS_LIMITS`.
- **Imagens:** automático. Se o arquivo tem figuras e há um modelo local que enxerga, elas são lidas com ele. Se não há, aparece o aviso já existente ("N figures not read — this model can't see images").
- **"Reading options":** some. Para quem precisa, fica um "Details" recolhido, só leitura, com os números que a Amelia usou.

## 4. Temas sem número fixo

- O número sai do conteúdo, com um teto proporcional, por exemplo `clamp(3, passagens/40, 20)`. O campo "Maximum themes" sai de "More options".
- No Curate, a pessoa pode juntar dois temas ("Merge") e separar um tema ("Split"), com Undo.
- A Amelia sugere o merge quando dois temas são quase iguais.
- Os temas guiam o Challenge (compara só dentro do tema) e o split de teste agrupado. Ao juntar ou separar, essas duas coisas se recalculam por baixo.

## 5. O que estava faltando

**"What is this model about?"** — uma frase de escopo, rascunhada pela Amelia a partir dos arquivos, que a pessoa aceita ou edita (regra do expander).
- Trechos fora do escopo viram "Out of scope" e não geram pares de conhecimento.
- No teste, o paper de levedura levou 5 dos 8 temas.

**"How should it answer?"** — Short and direct · Explains a bit. Substitui o limite fixo de 3–4 frases, e o filtro de frases usa o limite escolhido.

**"Include method details?"** — No (padrão) · Yes.
- Com No, protocolos, configurações de instrumento, reagentes e fornecedores não geram pares.
- No teste vieram "Which encoder settings…" (3x) e "name of the instrument".

**Reformulações** — o número de reformulações por fato hoje é decidido no Prepare. Ele passa a seguir a resposta de "How much…": Everything gera mais reformulações, porque é o que mais ensina fatos (ver memória do projeto sobre fine-tune).

## 6. Compatibilidade

- Projetos existentes viram as respostas mais próximas dos números que já usam.
- A API continua aceitando os números antigos, que passam a ser derivados das respostas.
- Nada muda nos pares já gerados até a pessoa clicar "Read again".

## Pronto quando

- Files mostra as duas perguntas, a estimativa e nenhum campo numérico.
- Testes sem modelo real cobrem:
  - densidade: trecho denso gera mais pares que um trecho vazio, e trecho de referências gera zero;
  - mistura percentual respeitada no total do projeto;
  - estimativa calculada;
  - teto proporcional de temas;
  - merge e split com Undo;
  - escopo filtra trecho fora do assunto;
  - "Include method details? No" filtra perguntas de método.
- No projeto tardígrado relido do zero:
  - os temas de levedura não passam de 2 (ou ficam em Out of scope);
  - nenhum par sobre configuração de instrumento;
  - o tempo real fica perto da estimativa (±30%).
- Textos em en.js e pt-BR.js. `estado-atual.md` atualizado. `npm run build` e os testes do backend passam com o venv.
