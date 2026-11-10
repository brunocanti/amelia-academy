# 022 — Compare simples

## Problema

A tela Compare tem 3 caixas e 4 botões para uma coisa só ("a versão treinada ficou melhor?"): "Compare answers" / "Try it" parecem abas, "Did it learn? + Draft questions" exige revisar perguntas à mão, "Which questions should we check? + Prepare comparison" é outro passo. A pessoa não entende que A e B são "treinado" e "original", nem por que a ordem é escondida, e não tem a resposta certa ao lado para julgar.

## A tela

Título: **"Is Version 2 better than the original?"** (versão da spec 021; seletor "Compare which version?" só se houver mais de uma pronta).

### Antes do teste
Uma frase e um botão:
> "We ask both the same questions. You pick the better answer without knowing which is which."
> **[Start the test]**

Enquanto prepara: progresso na barra de atividade (spec 020 §4) e na própria tela ("Writing answers… 6 of 14").

### O teste — um cartão por vez
- Contador "3 of 14" e o grupo em palavras: "Something it studied", "A new question about your files", "General knowledge".
- A pergunta.
- **"From your files:"** + a resposta certa, quando existe (estudadas e novas). Em conhecimento geral não aparece.
- **Answer 1** e **Answer 2**, lado a lado (empilhadas no celular).
- "Which one is right?" → **Answer 1 · Answer 2 · Both right · Both wrong**.
- Escolher avança sozinho. "Back" volta e permite mudar (clicar é seguro).
- Linha pequena: "We hide which one is trained until you finish, so you judge fairly."

### O fim — placar em palavras
- "Version 2 won 5 · Original won 2 · Tie 1".
- Por grupo: "Something it studied: better in 4 of 5", "New questions: 2 of 6", "General knowledge: no loss" (ou "worse in 1 of 3" visível, em palavras simples).
- Só aqui revela: em cada cartão, Answer 1/2 viram "After training" / "Before training".
- "Test again" refaz com perguntas novas.
- O placar alimenta o resumo da versão (spec 021: "Better in 5 of 8").

### Ask it yourself
Embaixo, sempre visível, uma caixa simples: digita a pergunta → vê **Before training | After training** lado a lado, sem esconder (é para explorar, não para julgar). Substitui "Try it".

### Suas perguntas no teste
"Add your own question" (fechado) antes de começar; até 6, entram no grupo "Your questions" sem resposta certa.

## O que sai
- Abas "Compare answers" / "Try it".
- Caixa "Did it learn?" e o botão "Draft questions" (revisão manual de paráfrases).
- "Which questions should we check?" e "Prepare comparison".

## Backend

- `POST /projects/{p}/train/runs/{id}/compare` sem perguntas monta sozinho ~14 itens:
  - **studied** (5): pares do split de treino, de tipos diferentes (Known, False premise, Not known), com a pergunta **reescrita** pelo agente Eco (`question_varier`, via `llm.py`, modelo de perguntas do projeto) para não ser a frase decorada. `expected` = resposta do par.
  - **new** (6): `held_out` como hoje, agora guardando `expected` = resposta do `test.jsonl`.
  - **general** (3): como hoje (+1 pergunta), sem `expected`.
  - **yours**: as do corpo `questions`, sem `expected`.
  - Renomear `set_name`: recall→studied, held_out→new, manual→yours (migração mantém as antigas legíveis).
- `train_comparisons`: coluna `expected TEXT NOT NULL DEFAULT ''`.
- Ordem: grupos misturados; dentro do cartão o lado continua aleatório (`base_on_left`).
- `GET .../comparison` devolve `expected`, o grupo, e — só quando todos têm escolha — `revealed=true` e o lado de cada um + placar por grupo (`better/worse/same/both_wrong`).
- Choices aceitam `left|right|both_right|both_wrong` (mapear `same` antigo → `both_right`).
- `POST .../try` continua para "Ask it yourself", resposta já identificada (before/after).
- Remover `recall/draft` e `recall/{item}/review` da UI; endpoints podem ficar, sem uso.
- Memória: rescrever as perguntas usa Ollama **antes** de reservar a GPU para MLX; descarregar o modelo Ollama depois, como hoje.

## Regras (CLAUDE.md)
Pergunta simples, respostas curtas. Sem "held-out", "recall", "base", "adapter", "A/B". Falhas aparecem em palavras simples ("Could not write the answers: …" com "Try again").

## Testes
- compare sem perguntas cria os 4 grupos com `expected` onde se aplica (MLX e LLM falsos).
- revelação só quando todos escolhidos; placar por grupo correto, inclusive `both_wrong`.
- `same` antigo lido como `both_right`; `set_name` antigos mapeados.
- try devolve before/after identificados.
