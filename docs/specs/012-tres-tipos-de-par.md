# Especificação 012 — Três tipos de par na leitura do arquivo

**Status:** construída em 6 nov. 2026 (ADR 015). O que mudou em relação ao desenho está na seção 9.  
**Altera, se aprovada:** ADR 013 ("Negative and refusal samples are not written for files") e ADR 014, itens 3 (o que entra na memória) e 5 (recusas só por pedido).

## 1. O que muda

Ao ler um arquivo, a pessoa define que parte do lote serão perguntas sem resposta e que parte serão perguntas com premissa falsa. A curadoria continua igual: tudo nasce `proposed`, e só o aprovado sai.

| Tipo | Pergunta | Resposta | Para que serve |
| --- | --- | --- | --- |
| **Respondida** | O arquivo responde | Certa, com trecho citado | Ensinar o assunto |
| **Sem resposta** | Do assunto, mas os arquivos não respondem | "Não sei" | Ensinar a não inventar |
| **Premissa falsa** | Afirma ou pressupõe algo que o arquivo contradiz | Corrige, com trecho citado | Ensinar a não aceitar um erro, e registrar esse erro como conhecimento |

Exemplo, a partir de um par respondido:

```text
Par de origem  P: Quantos saltos o HopRAG faz na busca?
               R: Faz N saltos, ...

Premissa falsa P: Por que o HopRAG faz M saltos na busca?
               R: O HopRAG não faz M saltos: faz N, ...
```

## 2. Por que premissa falsa

Uma resposta errada não pode entrar em `train.jsonl`: nesse arquivo, todo texto do assistente é o que o modelo aprende a dizer. Exemplos marcados como errados pedem treino por preferência (DPO), que o `mlx_lm.lora` não documenta.

Na premissa falsa, o erro fica na pergunta e o assistente diz o certo. É um par comum, em formato de chat, que funciona hoje no `mlx_lm.lora`.

O limite: ela ensina a corrigir uma afirmação de quem pergunta. Não faz o modelo preferir a resposta certa quando ele mesmo estaria errado. Esse efeito ainda não foi medido, porque o Amelia ainda não treina.

## 2.1 O erro rotulado também é conhecimento

O par não serve só para fine-tuning. Certo e errado juntos, com rótulo, dizem a qualquer agente que consulte a memória ou o wiki o que responder e em que erro não cair. Por isso este tipo sai em todos os exports.

Duas condições:

- **O rótulo vem primeiro.** Uma afirmação falsa solta, encontrada em uma busca, ensina o erro a quem consulta. Cada registro traz a afirmação falsa em campo próprio, o tipo e a correção, com a prova. Quem lê não precisa deduzir o que está errado a partir da pergunta.
- **"Possível" e não "comum".** O modelo inventa um erro plausível a partir do trecho. Ninguém observou esse erro acontecer. O export diz `Possible mistakes` e nunca afirma frequência, porque "erro comum" seria um fato sem prova.

## 2.2 A pergunta sem resposta também é conhecimento

Ela marca até onde este conhecimento vai: quem consulta sabe que não deve responder aquilo a partir daqui. Por isso também sai em `memory.jsonl` e no wiki, com rótulo. Isso reverte o item 3 da ADR 014, que a deixava de fora.

O que ela afirma é limitado:

- **Quer dizer "os arquivos lidos não respondem", não "ninguém sabe".** O registro diz contra quais arquivos foi checada. Um agente pode procurar em outro lugar.
- **É uma lacuna dentro do assunto, não a borda do assunto.** O prompt pede perguntas perto dos temas. Ela limita o domínio pelo lado de dentro. Perguntas de fora do assunto são outro tipo, que não é gerado aqui (seção 10).
- **Pode vencer.** Quando um arquivo novo parece respondê-la, volta à revisão (5.1).

## 3. Na tela

Em Files, junto das opções de leitura:

```text
Unanswered questions [10] %   (?)      False premises [10] %   (?)      Answered: 80%
```

- Cada campo vai de 0 a 30, e 0 desliga. Os valores ficam guardados no navegador, como as outras opções.
- A leitura mostra quanto foi pedido, quanto foi escrito e quanto caiu, com o motivo: `False premises: 12 asked, 9 written, 3 discarded (number not in the passage)`.
- Curate ganha um filtro por tipo. O par de premissa falsa mostra o trecho citado e um rótulo. Aprovar significa "a pergunta está mesmo errada e a resposta corrige".
- Export mostra a mistura real de aprovados por tipo. O percentual vale para o que é gerado, e a curadoria muda o resultado.
- **Write refusals** continua, para pedir mais depois. Entra **Write false premises**, com a mesma função, para arquivos já lidos.

## 4. Como o percentual vira quantidade

A base é o número de pares respondidos **válidos desta leitura**, porque só se sabe esse número ao fim dela:

```text
total = respondidos / (1 − sem_resposta − premissa_falsa)
```

Com 100 respondidos e 10% + 10%, o total é 125: 13 sem resposta e 13 de premissa falsa (arredondando para cima). Se a leitura não gerar nenhum par respondido, nada mais é gerado.

Não há nova tentativa para completar a cota: o que caiu fica contado na tela. Pedir de novo é um clique da pessoa.

## 5. Geração

Uma etapa nova no fim da leitura, depois de todas as seções. Um arquivo relido só conta os pares novos, porque a leitura de hoje não apaga pares e ignora os repetidos.

**Falha:** se a etapa falhar, os pares respondidos ficam, e a tela mostra o erro com um botão para repetir só a etapa, sem reler o arquivo.

### 5.1 Sem resposta

Reaproveita `kb.write_refusals`, em lotes, com o que ela já exige: primeira pessoa, sem citar documentos, sem números próprios e tema `Out of scope`. Duas mudanças:

- **Hoje o pedido é de até 5 e o modelo vê só até 40 perguntas conhecidas.** Com a cota por percentual, a chamada precisa de lotes e de uma amostra de perguntas por tema, para não concentrar tudo nos primeiros.
- **Toda pergunta passa por uma checagem antes de ser gravada.** `kb.answered_in` mostra ao modelo os 8 trechos mais próximos da pergunta, com os vizinhos, e pede o trecho que dá a resposta. Se ele apontar um, a pergunta cai com o motivo. Uma resposta quebrada do modelo é erro visível, não um "não". `looks_answered` continua como filtro por palavras, antes dessa chamada.
- **Um arquivo novo pode responder uma pergunta antiga.** Ao ler outro arquivo, cada pergunta aberta passa pela mesma checagem contra ele. A que parecer respondida volta a `proposed` com o aviso e o trecho, mesmo se já estava aprovada. A checagem erra para os dois lados, então não substitui a revisão.

### 5.2 Premissa falsa

O modelo recebe a pergunta, a resposta e o trecho de pares respondidos sorteados de forma determinística, e escreve três coisas: a afirmação falsa, em uma frase (`false_claim`); uma pergunta que a afirma ou pressupõe; e a resposta que corrige.

Cada pedido devolve também a **versão verdadeira** da mesma pergunta (`X é Z, certo?` → "Sim, ..."), para o modelo não aprender a negar toda confirmação. Ela conta dentro do percentual: os 13 do exemplo viram 7 falsas e 6 verdadeiras. Fica com `origin = 'true_premise'` e o mesmo vínculo, e sai só no treino, porque na memória e no wiki o par de origem já diz o mesmo.

Formas pedidas: número ou data trocados, entidade trocada, relação invertida.

**A forma da pergunta precisa variar.** Só `X é Y, certo?` ensinaria o modelo a responder "não" a todo pedido de confirmação. O prompt pede também a falsidade embutida, como "Por que X faz Y?", e o sorteio varia a forma pedida.

Checagens por código, que só descartam:

- A pergunta difere da pergunta de origem depois de normalizar.
- `false_claim` não está contida no trecho.
- Todo número da resposta aparece no trecho ou na afirmação falsa, porque a correção pode repetir o número errado.
- A resposta não diz "não sei".
- A resposta não cita documento, arquivo ou fonte (`MATERIAL_TALK`, a mesma regra das recusas).

**Nenhum código prova que a premissa é falsa.** Um par pode passar por todas as checagens e a pergunta ser verdadeira, ou a resposta corrigir a coisa errada. Por isso a pessoa decide.

## 6. Dados

Em `qa_samples`:

- `origin = 'false_premise'`, novo. O tipo sem resposta usa o `origin = 'refusal'` que já existe.
- `question`, `answer`, `quote`, `chunk_id` e `source_id` usam as colunas de sempre.
- `false_claim`, coluna nova, vazia nos outros tipos. Editar o par permite editá-la, e ela aparece em Curate.
- O vínculo com o par de origem usa `qa_sample_links`, como as conexões.

Regras herdadas das conexões:

- Só é exportado com o par de origem aprovado.
- Editar o par de origem devolve o par de premissa falsa a `proposed`.
- Fica na mesma divisão do par de origem, para o conteúdo do teste não vazar para o treino.
- Fica no tema do par de origem.

## 7. Exportação

```text
train.jsonl, valid.jsonl, test.jsonl   os três tipos e as versões verdadeiras, como pares de chat
samples.jsonl                          todos, com o tipo e false_claim
manifest.json                          contagem por tipo e por divisão
memory.jsonl                           respondidas, conexões, premissas falsas e sem resposta, rotuladas
wiki/                                  seções "Possible mistakes" no tema e "Not answered here" em Out of scope
sources.json                           sem mudança
```

Em `memory.jsonl`:

```json
{"kind": "false_premise", "false_claim": "O HopRAG faz M saltos.", "question": "Por que o HopRAG faz M saltos?",
 "answer": "O HopRAG não faz M saltos: faz N, ...", "corrects": "<id do par de origem>",
 "evidence": [{"source": "...", "page": 3, "quote": "..."}], "theme": "...", "tags": ["..."], "approved_at": "..."}
```

No wiki, a página do tema separa o certo do errado, para ninguém ler uma afirmação falsa como fato do tema:

```markdown
## Quantos saltos o HopRAG faz na busca?
Faz N saltos, ...

## Possible mistakes

### Wrong: O HopRAG faz M saltos.
Correct: O HopRAG não faz M saltos: faz N, ...
```

Registro de pergunta sem resposta em `memory.jsonl`:

```json
{"kind": "unanswered", "question": "Qual é o custo do HopRAG por consulta?", "checked_against": [{"source": "...", "sha256": "..."}],
 "theme": "Out of scope", "tags": ["..."], "approved_at": "..."}
```

Sem o campo `answer`, porque "não sei" na primeira pessoa é texto para o treino, e o `kind` já diz isso a quem consulta. `checked_against` lista os arquivos do projeto no momento da exportação. Hoje `qa.wiki_files` escreve todo par exportado como seção comum: é preciso separar esses dois tipos, senão a afirmação falsa aparece como conteúdo do tema.

## 8. Testes de aceite

1. O par de premissa falsa aparece em `train/valid/test.jsonl`, em `memory.jsonl` com `kind` e `false_claim`, e no wiki só sob `Possible mistakes`, nunca como seção comum do tema.
   O par sem resposta aparece em `memory.jsonl` com `kind` e `checked_against`, sem `answer`, e no wiki só sob `Not answered here`. A versão verdadeira só aparece no treino.
2. Ele, a versão verdadeira e o par de origem caem na mesma divisão.
3. Com a origem não aprovada, ele não sai, e a exportação conta quantos ficaram de fora.
4. Editar a origem o devolve a `proposed`.
5. Percentual 0 não faz nenhuma chamada a mais ao modelo.
6. Falha na etapa nova mantém os respondidos, mostra o erro e pode ser repetida sem reler.
7. Um arquivo novo que responde uma pergunta sem resposta a devolve a `proposed`.
8. A contagem da seção 4 bate com o pedido, e o que falta aparece como descartado.
9. Ensaio real no paper `hoprag-2502.12442v2.pdf`, com tempo e chamadas medidos e com uma leitura humana dos pares gerados. Conta quantas premissas estão mesmo falsas, quantas soam como um erro que alguém cometeria e quantas respostas corrigem o ponto certo, porque as checagens não medem isso.

## 9. Decisões

Tomadas: premissa falsa em vez de DPO, os dois tipos rotulados também na memória e no wiki, versão verdadeira dentro do percentual e campos começando em 10% e 10%.

Os 10% são ponto de partida, não dado medido: não encontrei uma proporção aceita. O excesso de "não sei" é um risco real (o relatório do Phi-4 traz um exemplo com cerca de 94% de recusas), e esse excesso e o de negação só aparecem testando o modelo. Até existir Evaluate, o percentual é um palpite.

Decidido na construção:

- A verificação de números aceita o número da afirmação falsa, porque o próprio exemplo da seção 7 repete o número errado na correção.
- A checagem de quase-duplicata não se aplica às premissas, só a de texto idêntico, porque elas se parecem com o par de origem de propósito.
- Em um arquivo já lido, a base é a última leitura, não todos os pares do arquivo.

## 10. Fora desta spec

- Treino por preferência (DPO). Uma pasta `dpo/` com `prompt`, `chosen` e `rejected` pode ser somada quando houver Train; o `mlx-lm-lora` faz esse treino.
- Usar pares de premissa falsa para avaliar o modelo.
- Perguntas de fora do assunto, que marcariam a borda do domínio. Um dataset sem elas não ensina o modelo a recusar o que não é do assunto.

## 11. Fontes

- [Formatos do `mlx_lm.lora`](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/LORA.md)
- [`mlx-lm-lora`, modo DPO](https://github.com/Goekdeniz-Guelmez/mlx-lm-lora)
- [Phi-4 Technical Report](https://arxiv.org/pdf/2412.08905)
