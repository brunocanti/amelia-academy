# Especificação 011 — O que incorporar do Easy Dataset

**Status:** passo 1 (4.1) e o teto configurável de 4.3 construídos e medidos; os outros são proposta. Vira normativa quando a pessoa aprovar a ordem da seção 5.
**Testado em:** 6 nov. 2026, Easy Dataset 1.7.3, `gemma4:12b` no Ollama, paper `hoprag-2502.12442v2.pdf` (17 páginas).

## 1. Decisão

O Amelia não embute o Easy Dataset (ED). A proposta do Amelia continua: um arquivo vira pares com prova, a pessoa cura, só o aprovado sai. Do ED vêm ideias de chunking, árvore de temas, geração incremental e organização de tela.

O ED é AGPL-3.0. Nada de copiar código nem prompts: cada ideia é escrita de novo aqui.

## 2. O que o teste mostrou

Interrompemos o ED em 13 de 40 chunks. A geração não terminou, então isto **não compara a qualidade dos pares**: há só 3 respostas salvas.

| Medida | Resultado |
| --- | --- |
| Conversão do PDF | 41 chunks, cerca de 2 a 3 min |
| Perguntas | 13 de 40 chunks em 55 min: 6 ok, 7 falhas, 37 perguntas |
| Respostas | 8 de 30 em 38 min: 3 ok, 5 falhas |
| Chamadas de modelo | cerca de 320 para o paper no ED, cerca de 20 no Amelia (estimativa, nenhum dos dois medido até o fim) |

As duas tarefas dividiram o mesmo Ollama, o que piora o tempo e os timeouts. Parte das falhas vem do parser de JSON do ED, que quebra quando a cerca de código não fecha.

### Por que ele é lento

Cada chunk passa por pergunta, classificação de tema e uma chamada de resposta por pergunta. Separar dá uma vantagem real: revisar e corrigir perguntas antes de gastar com respostas, e refazer só a resposta. O Amelia obtém o mesmo com geração conjunta mais as ações da seção 4.4 e 4.5, a uma fração das chamadas.

### Defeitos a não repetir

| No ED | Consequência | Regra no Amelia |
| --- | --- | --- |
| Títulos de tema limitados a 6 caracteres | Temas ilegíveis: `Retr`, `Multi`, `Train` | Título de duas palavras (4.2) |
| Conversão do PDF promove autores a `##` | Seções falsas no começo do arquivo | Seção detectada por sinal do próprio PDF (4.1) |
| Idioma fora de `en` e `tr` cai no prompt em chinês | Pergunta em inglês com resposta em chinês, tarefa em `pt-BR` | Idioma vem do projeto, nunca da tela. Já é assim: manter e testar |
| Tarefa com erros termina como concluída, com o erro só no detalhe | Falha passa despercebida | Falha fica visível. Já é assim: manter |
| Resposta sem trecho citado; `chunkContent` fica vazio no dataset | Não dá para conferir a resposta na origem | Todo par de arquivo cita um trecho. Já é assim: manter |
| A tela avisa que a árvore é reconstruída a cada upload (não testado com um segundo arquivo) | Risco de perder a curadoria de temas | Árvore fechada, que só cresce nas vagas livres (4.2) |
| Interrupção só é checada antes de cada item | A chamada em andamento segue até o fim | Ver 4.6 |

O botão de interromper não funcionou na mão da pessoa, mas o mesmo `PATCH` pela API funcionou e a tarefa ficou parada. A tela depende de um `confirm()` do navegador; se ele foi bloqueado, a causa é essa. Não foi verificado.

## 3. O que não entra

- **Gênero e público** (5 combinações por arquivo): multiplica chamadas antes de termos o básico bom.
- **Destilação a partir da árvore**, sem documento: as respostas não teriam prova. Pode servir um dia para Behaviors.
- **Nota do modelo em cada par:** só vale, no futuro, para ordenar a fila. Nunca para aprovar ou rejeitar.
- **Conversas multi-turno, avaliação, teste cego, playground, praça de datasets:** fora do fluxo de quatro telas.
- **Oito ou mais itens de menu.** Files, Curate, Behaviors e Export continuam sendo o menu.

## 4. O que entra

### 4.1 Leitura por seção

Hoje `make_windows` agrupa chunks de 700 caracteres até 4500, cortando por página. O corte cai em qualquer lugar, e bibliografia e legendas chegam ao modelo.

- `_extract_pdf` detecta títulos pelo que o PDF informa: tamanho da fonte, negrito e numeração (`3.2 Título`). Markdown usa `#`. O título entra em `locator_json` como `section`.
- Janela nova: até 4500 caracteres, sem cruzar seção. Seção com menos de 1500 caracteres se junta à seguinte. Seção longa quebra em parágrafo. O limite de página deixa de ser corte obrigatório.
- Arquivo sem títulos detectados continua com o comportamento atual e a tela diz isso.
- **Filtro de lixo, por código:** seções `References`, `Bibliography`, `Acknowledgements` e equivalentes no idioma do projeto, e blocos que são só legenda, ficam fora. A tela mostra quantos trechos ficaram de fora e por quê.
- **Citação:** a comparação normaliza hífen de fim de linha e ligaduras (`ﬁ`) dos dois lados, além dos espaços que `_norm` já trata. O que se grava é o trecho como está na fonte.

Essas duas últimas partes andam juntas: no piloto, 59 de 80 pares caíram na checagem de citação, e afrouxar só a citação deixaria passar pares de bibliografia.

**Pronto quando:** no mesmo paper e modelo, menos de 15% dos pares caem por citação (meta inicial, ajustar depois de medir), nenhum par vem da bibliografia, e os arquivos antigos podem ser relidos com `reprocess_source`.

**Medido em 6 nov. 2026**, mesmo paper e modelo, uma execução: 5 de 52 pares caíram por citação (9,6%; no piloto, 59 de 80), 45 ficaram e nenhum veio da bibliografia. A qualidade dos pares não foi avaliada. Além do pedido acima, a citação pode continuar na passagem seguinte, porque metade das falhas restantes era citação correta cortada no limite de 700 caracteres. Sumário, texto de margem e o trecho curto antes do primeiro título também ficam de fora. Arquivo lido por um extrator anterior é extraído de novo ao ler, sem chamar modelo: os pares ficam com os trechos que citam e as leituras de figura são mantidas. Conferido em uma cópia do banco local.

### 4.2 Árvore de temas em dois níveis

- `qa_themes` ganha `parent_id`, nulo no primeiro nível.
- **Título com exatamente 2 palavras**, sem contar conectivos (`de`, `da`, `do`, `of`, `the`): "Recuperação lógica", "Qualidade de imagem". A descrição continua em uma frase.
- `max_themes` limita só o primeiro nível, com a reserva de `RESERVE_FOR_LATER`. Cada tema tem no máximo 4 subtemas. `Outros` e os temas de comportamento continuam fora do limite.
- Uma única chamada propõe a árvore, a partir dos títulos de seção detectados (4.1) e de trechos do arquivo. Sem títulos, usa o resumo de trechos atual.
- Título fora da regra: a checagem descarta o nó e a tela mostra o motivo. Sem cortar nem reescrever por conta própria.
- O par cai no nó mais específico da lista fechada. Se o modelo escolher um tema com subtemas, fica no próprio tema.
- Renomear, unir, aprovar e rejeitar em bloco valem para os dois níveis. O bloco de um tema inclui os subtemas. Unir um tema com subtemas a outro move os subtemas junto.
- Temas existentes viram primeiro nível, com os títulos como estão.

**Pronto quando:** um segundo arquivo acrescenta nós sem alterar os temas já curados, e o grafo mostra projeto, tema, subtema e par.

### 4.3 Perguntas e respostas juntas, em quantidade proporcional

A chamada conjunta com pergunta, resposta, trecho e tema continua. No lugar da fórmula proporcional proposta antes, a pessoa escolhe na tela: até 6 pares por seção por padrão (de 1 a 12), sempre como "até", e o tamanho da seção (padrão 4500, de 2000 a 8000). A razão foi a medida: com teto 4, todas as 13 janelas do paper bateram no teto (52 pares em 13 janelas), então o teto cortava pares.

**Figuras.** A mesma tela tem **Read images**, desligado por padrão: o modelo lê as figuras ainda não lidas antes das seções, e os pares podem citar a leitura.

**Medido em 6 nov. 2026**, mesmo paper e modelo, uma execução, teto 6 e imagens ligadas, somando aos 43 pares que já existiam: 19 janelas, 74 pares novos (53 do texto, 21 de figuras) e 28 descartados: 16 por citação (15,7%, contra 13,5% com teto 4), 10 quase-duplicatas dos pares anteriores e 2 por falar da fonte. Como a leitura somou à anterior, as quase-duplicatas não valem como comparação. A qualidade dos pares não foi avaliada. Há pares fracos vindos de figuras: `What does the figure in section P430 illustrate?` expõe um rótulo interno, e os prompts do apêndice viram pares sobre o prompt e não sobre o assunto.

**Limite medido e corrigido:** 3 das 10 figuras estouravam o timeout de 600 s. A causa é repetição: ao transcrever `visible_text`, o `gemma4:12b` entra em laço (`MLS CUP\nMLS CUP\n…`) e gera de 40 a 54 mil tokens até o timeout. Aparece em grafos com muitos rótulos parecidos. O tamanho da imagem não explica: figuras maiores passaram. Agora a leitura de figura tem teto de 3000 tokens (a maior leitura boa medida tem cerca de 1050). Ao bater no teto, tenta de novo uma vez com `repeat_penalty` 1.3, só nessa segunda tentativa, porque usado desde o início ele encurtou a transcrição de gráficos (de 184 para 66 caracteres, por exemplo). Se bater no teto de novo, uma última tentativa pede só a descrição, sem transcrição. Só se as três baterem no teto a figura fica como falha, com o motivo guardado nela. Nesta medida, 2 das 3 figuras passaram em segundos na segunda tentativa e 1 precisou da terceira (cerca de 1 min no total, em vez de 10), ficando sem transcrição. O resultado varia entre execuções: essa figura tinha passado com a mesma penalidade em um teste isolado.

### 4.4 Gerar mais

Botão em um tema ou subtema, e em um arquivo.

- Relê as janelas de onde vieram os pares daquele nó (ou do arquivo), enviando as perguntas já existentes daquela janela para o modelo não repeti-las.
- As mesmas checagens valem: citação, número solto, cópia da fonte, quase-duplicata.
- Os novos pares nascem `proposed`. A tela informa quantos vieram e quantos caíram.

### 4.5 Melhorar um par

Ação em cada par: a pessoa escreve o que quer ("mais curta", "explique o termo") e o modelo reescreve a partir do trecho citado.

- O resultado aparece ao lado do atual, e nada é trocado sem a pessoa aceitar.
- Aceitar segue a regra de editar: volta a `proposed` e conexões apoiadas no par voltam para revisão.

### 4.6 Parar uma leitura

O Amelia hoje não tem como parar uma leitura em andamento.

- Botão **Parar** na tela Files, sem `confirm()` do navegador. A checagem ocorre entre janelas, e a tela mostra "parando" até a janela atual terminar.
- Os pares já gerados ficam, e a leitura fica como parada, mostrando quantas janelas leu.
- **Retomar** continua da janela seguinte.

### 4.7 Tela

| Do ED | No Amelia |
| --- | --- |
| Cartão de chunk com caracteres e nº de perguntas | Files: seções do arquivo com caracteres, pares gerados e o que ficou de fora |
| Árvore recolhível | Coluna de temas do Curate em dois níveis, com contagem por status |
| Detalhe com anterior/próximo e confirmar no topo | Curate: abrir um par e andar pela fila com teclado (`a` aprova, `r` rejeita, setas navegam) |
| Contador "total, confirmados" | Topo do Curate: aprovados, para revisar e rejeitados do filtro atual |
| Metadados ao lado da resposta | Modelo, arquivo, seção e página ao lado do par, com o trecho visível |
| Indicador global de tarefas | Indicador no topo enquanto há leitura em andamento, que leva a Files |

## 5. Ordem

1. **Leitura por seção, filtro e citação (4.1).** Vem primeiro porque hoje a maioria dos pares do paper cai na citação, e isso compromete tudo o que vem depois.
2. **Árvore (4.2).**
3. **Quantidade proporcional e Gerar mais (4.3, 4.4).**
4. **Parar e Retomar (4.6).** Pode vir antes se as leituras longas começarem a incomodar.
5. **Melhorar um par e tela (4.5, 4.7).**
6. **Relações entre pares:** continuam como referência em `docs/architecture/relacoes-entre-pares.md`.

Cada passo é medido no mesmo paper e modelo, com os pares aprovados como medida de resultado, e não os pares gerados.

## 6. Decisões em aberto

- **Quantos subtemas por tema:** a proposta é 4. Ajustar depois de ver em dois arquivos reais.
- **Título de 2 palavras em siglas e nomes próprios:** "Busca RAG" passa. Um título como "HopRAG" sozinho cai. Ver se isso incomoda na prática.
