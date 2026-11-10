# Especificação 013 — O que o dataset ensina

**Status:** aprovada e construída, 6 nov. 2026. Os pares que já existem não foram alterados.  
**Altera:** Especificação 012, quanto ao critério de "Sem resposta" e ao novo tipo "Vizinho".

**Extensão proposta (spec 016):** todos os tipos elegíveis para fine-tuning podem produzir resposta direta ou resposta com justificativa editorial aprovada. Known/Not known/False premise/Vizinho descrevem o conteúdo; baixa/média/alta descrevem a verificação da conclusão pela curadoria. Um eixo não determina o outro. Pares inválidos não entram em nenhum perfil.

## 1. A ideia

O dataset vira fine-tuning ou um módulo de conhecimento para um LLM que **já sabe generalidades**. Ele não ensina o mundo ao modelo. Acrescenta só o que falta:

1. o conteúdo dos arquivos;
2. onde esse conteúdo termina;
3. como o modelo se comporta.

## 2. Dois eixos

Cada par pertence a um só eixo.

- **Conhecimento:** o centro são os arquivos. Vale a distância da pergunta até eles.
- **Comportamento:** o centro é o card. O assunto é mais aberto, mas o par existe para ensinar aquele comportamento.

## 3. Eixo do conhecimento

| Tipo | Pergunta | Resposta | Teste para virar par |
| --- | --- | --- | --- |
| **Respondida** | Os arquivos respondem | Certa, com citação | Traz algo que o LLM não saberia sozinho? |
| **Premissa falsa** | Supõe algo que os arquivos contradizem | Corrige, com citação | O erro é sobre o conteúdo dos arquivos? |
| **Sem resposta** | Pede um detalhe deste trabalho que os arquivos não dão | "Não sei" | Sem este par, o LLM inventaria um número, nome ou data? |
| **Vizinho** | Parece do assunto, mas é outro campo ou outro problema | Marca o limite e responde em geral | O LLM misturaria o assunto vizinho com o conteúdo dos arquivos? |
| **Fora** | Sem relação com os arquivos | Não vira par | O LLM responde sozinho |

Uma pergunta que o LLM consegue raciocinar com o que já sabe, como "como aplicar isso a diagnóstico médico", não vira par.

### Exemplos, com arquivos sobre HopRAG

| Pergunta | Tipo |
| --- | --- |
| Qual é o limite de profundidade da busca no grafo? | Sem resposta |
| Quem liderou o módulo de geração de perguntas? | Sem resposta |
| Quanto custa a licença comercial? | Sem resposta, fraca: quase ninguém perguntaria |
| Como aplicar essa busca a diagnóstico médico? | Não vira par |
| Como essa memória se compara a uma rede recorrente? | Não vira par |
| Qual é a receita de um bolo? | Fora |

### Como é a resposta de um Vizinho

Exemplo de um projeto sobre compressão de texto, com a pergunta sobre compressão de sinais:

> Isso não está no que estudei, que é compressão de texto. Em geral, compressão de sinais reduz os dados aproveitando padrões do sinal.

1. A primeira frase marca o limite e diz o que o modelo estudou.
2. O resto é curto e geral, sem números, nomes ou afirmações sobre este trabalho.
3. Essa parte geral não tem citação, porque vem do LLM. Quem aprova confere se ela está certa e se não mistura os assuntos.

## 4. Eixo do comportamento

**Teste:** se eu tirar o comportamento, ainda sobra motivo para este par existir? Se sobrar, ele ensina um fato e pertence ao eixo do conhecimento.

| Pode | Não pode |
| --- | --- |
| Apoiar-se em generalidades, que o LLM já sabe | Existir para ensinar um fato |
| Falar de assuntos fora dos arquivos | Afirmar detalhes deste trabalho sem citação |
| Usar a identidade do projeto | Contradizer a identidade ou acrescentar algo a ela |

A identidade e o card "Who I am" pertencem a este eixo.

## 5. As duas saídas

| Tipo | Fine-tuning | Módulo de conhecimento |
| --- | --- | --- |
| Respondida | Entra | Entra, com citação |
| Premissa falsa | Entra | Entra, marcada como erro |
| Sem resposta | Entra | Entra, marcada como ponto em aberto |
| Vizinho | Entra | Não entra: o módulo não entrega nada e o LLM responde sozinho |
| Comportamento | Entra | Não entra |

## 6. O que mudou

| Antes | Agora |
| --- | --- |
| O prompt de "Sem resposta" pede comparações, falhas, escolhas e aplicações | Pede detalhes deste trabalho que o LLM inventaria |
| O prompt proíbe preço, data, autor e contagem exata | Esses pedidos passam a valer, se alguém perguntaria de verdade |
| O prompt pede assuntos vizinhos com resposta "não sei" (mudança recente, não aprovada) | Sai: vizinho vira um tipo próprio |
| Não existe o tipo Vizinho | Novo tipo, com geração, checagem e etiqueta na curadoria |
| Os 36 pares de `Out of scope` misturam vários casos | Curadoria um a um, pelo teste da seção 3 |
| A variação `Should not apply` existe em Behaviors | Sai: os negativos são Sem resposta, Premissa falsa e Vizinho |
| A checagem de behaviors não olha o teste da seção 4 | Quem aprova aplica o teste; a dica do card passa a dizer isso |
| O aviso do card diz que os arquivos não conferem a resposta | Fica, com a regra de não afirmar detalhes deste trabalho |

Na leitura de um arquivo, Vizinho tem sua própria porcentagem, de 0 a 30, começando em 5. Esse número é um ponto de partida, não uma medida.

## 7. O que esta definição não resolve

- O teste "o LLM inventaria?" depende de julgamento, e o modelo que gera as perguntas pode errar. A palavra final é de quem aprova.
- O projeto Comprimildo não tem nenhuma ocorrência de "compress" nos arquivos atuais, que tratam de RAG em grafos. Os exemplos de compressão são ilustrativos até esses arquivos existirem.
- Não medimos se os pares de Vizinho fazem o modelo calar menos do que os de "não sei". Isso pede uma avaliação depois do primeiro treino.
