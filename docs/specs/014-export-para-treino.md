# Especificação 014 — Export pronto para treino

**Status:** construída em 7 nov. 2026. Testada numa cópia do Comprimildo (198 pares) e aceita pelo `mlx_lm.lora` 0.32.2 num treino curto. O que mudou em relação ao texto original está na seção 12.  
**Altera:** o export descrito em `docs/architecture/estado-atual.md`, seção 3, e `app/backend/amelia_academy/datasets.py`.  
**Relacionadas:** Especificação 005 (manifesto e grupos), 012 e 013 (tipos de par), 015 (treino), ADR 004.

## 1. Propósito e escopo

Hoje o export gera arquivos válidos, mas eles não permitem medir o treino com segurança. Esta especificação corrige o que foi encontrado lendo o código. O formato continua simples e neutro: `{"messages": [...]}`, sem template de modelo (ADR 004).

O que depende de um modelo específico (contagem de tokens, template, canal de pensamento) fica fora do export, no passo de treino (Especificação 015).

## 2. Defeitos que motivam a mudança

| # | Defeito | Consequência |
|---|---|---|
| 1 | `assign_splits` não equilibra por tipo | O teste pode ficar sem nenhuma premissa falsa ou sem "não sabe"; um padrão de comportamento inteiro pode ficar fora do treino |
| 2 | Os grupos de `similar_groups` não entram nos splits; só vale a similaridade de 3-gramas ≥ 0,6 | Uma paráfrase de um par de treino pode cair no teste, e a nota sobe sem o modelo ter aprendido |
| 3 | `projects.identity` nunca chega aos arquivos de treino | O modelo é treinado sem a identidade que recebe ao ser usado |
| 4 | O manifesto só tem `canonical_sha256` | Não dá para provar quais arquivos renderizados um treino usou |
| 5 | O texto da tela diz "for MLX", e não há descrição do dataset | O formato parece preso a uma ferramenta, e quem recebe o zip não sabe o que tem nele |

## 2.1. Dois perfis e seleção por confiança (extensão da spec 016)

Export deve oferecer direct (só resposta), reasoned (justificativa editorial aprovada + resposta) ou ambos. Filtros por temas, tipos, confiança e exclusão individual; médios/altos sem bloqueios são o padrão. Pares sem justificativa continuam elegíveis para direct, mas não entram em reasoned; mostrar contagens e motivos. Conhecido, Sem resposta, Premissa falsa e Vizinho podem entrar em ambos. Pares sem sentido devem ser rejeitados, não destinados a um perfil especial.

Justificativas e projeções de confiança são artifacts versionados ligados às revisões exatas. O manifesto novo registra perfis, seleção, versões, hashes e exclusões. O formato messages simples abaixo descreve direct; reasoned exige artifact neutro + renderer específico, conforme spec 016. O schema v1 não recebe campos silenciosamente. Dividir variantes e suas bases em conjunto antes de renderizar; comparação dos perfis pode selecionar a mesma interseção de IDs.

## 3. Entidades e arquivos

O zip continua com `samples.jsonl`, `manifest.json`, `train.jsonl`, `valid.jsonl`, `test.jsonl`, `wiki/`, `memory.jsonl`, `sources.json`. Muda ou entra:

- **`train/valid/test.jsonl`:** quando a identidade do projeto estiver preenchida, cada linha começa com `{"role": "system", "content": <identidade>}`. Sem identidade, não há mensagem de sistema. O schema canônico já aceita o papel `system`.
- **`manifest.json`, novos campos:**
  - `rendered`: para cada arquivo, `sha256`, número de linhas e contagem por tipo de par;
  - `identity_sha256`: hash da identidade usada, ou `null`;
  - `split_policy`: versão da regra de divisão e semente;
  - `split_warnings`: o que não pôde ser equilibrado.
- **`README.md` (novo, gerado):** o que há no dataset em palavras simples: quantos pares de cada tipo em cada split, de onde vieram, direitos de uso, avisos, e um exemplo de comando de treino com a ferramenta que for testada.

O avaliador liga cada linha ao seu tipo por `samples.jsonl` e pelo split no manifesto. O formato das linhas de treino não ganha campos extras.

## 4. Regra de divisão

Determinística para a mesma entrada e a mesma semente.

**Etapa 1, o que anda junto.** Pares ficam no mesmo split quando estão ligados por qualquer um destes motivos:

- mesmo cenário (similaridade de 3-gramas ≥ 0,6, a regra de hoje);
- mesma fonte ou passagem;
- par ligado explicitamente, como premissa falsa e sua versão verdadeira;
- **novo:** mesmo grupo de `similar_groups`, respeitando o que a pessoa marcou como diferente (`qa_kept_apart`).

Pares de comportamento do mesmo `pattern:` são a exceção à regra da unidade: o padrão é o que se quer ensinar, então eles se dividem entre os splits, desde que não sejam paráfrases entre si.

**Etapa 2, o equilíbrio.** Cada componente vai para o split que estiver mais abaixo da meta **considerando os tipos que o componente contém**, e não só o total. A meta de 80/10/10 vale para cada tipo: Conhecido, Sem resposta, Premissa falsa, Premissa verdadeira, Vizinho e Comportamento.

**Etapa 3, o limite.** Vazamento nunca é trocado por equilíbrio. Se um tipo não couber em todos os splits, o export sai e o aviso fica registrado, em palavras simples: "Só 3 pares de premissa falsa. O teste ficou sem nenhum, então não dá para medir isso."

## 5. Invariantes

1. Um grupo de paráfrases nunca atravessa splits.
2. A mesma entrada com a mesma semente gera os mesmos arquivos, byte a byte, e os mesmos hashes.
3. Todo arquivo renderizado tem hash no manifesto, e o hash confere com o conteúdo.
4. Par não aprovado nunca entra no export. Nenhum export conta rascunho como dado de treino.
5. O export não recebe tokenizer nem template de modelo.

## 6. Interface

A tela Export acrescenta a escolha “Só resposta”, “Com justificativa” ou “Ambos”, com contagens e motivos das exclusões (spec 016). Filtros de seleção ficam recolhidos. Também muda:

- o texto "for MLX" sai; os arquivos são descritos como "for fine-tuning";
- depois de exportar, uma tabela curta mostra os pares por tipo e split;
- os avisos de `split_warnings` aparecem ao lado do resultado.

Nada novo para configurar: nem proporção de split, nem semente. Se a pessoa não tem nenhum par aprovado, a tela diz isso e aponta para Curate.

## 7. API e eventos

O contrato futuro de export aceita perfil e seleção explícitos conforme spec 016, em versão compatível identificada. A resposta ganha `rendered`, `split_warnings` e exclusões por perfil, vindos do manifesto. Não implementar campos novos em contratos v1 fechados sem versionamento.

## 8. Privacidade

A identidade passa a sair no zip, junto com o resto. O `README.md` não inclui caminhos da máquina nem nome de usuário.

## 9. Semântica de falha

- Falha ao escrever um arquivo: nenhum registro de dataset é criado, e a tela diz o que falhou.
- Exports antigos continuam válidos. A Especificação 015 recusa treinar sem `training-manifest.json` v2 com `split_policy` e diz: "Export this again to train with it."

## 10. Testes de aceitação

1. Dois pares de um mesmo grupo de `similar_groups` caem sempre no mesmo split; marcados como diferentes em `qa_kept_apart`, podem se separar.
2. Com pelo menos 10 pares de cada tipo em componentes independentes, cada split tem todos os tipos.
3. Com 2 pares de um tipo, o export sai e o aviso nomeia o tipo e o split vazio.
4. Com identidade preenchida, toda linha de `train/valid/test.jsonl` começa com `system`; sem identidade, nenhuma tem.
5. Dois exports iguais geram hashes iguais; mudar um par muda o hash do arquivo em que ele está.
6. O hash em `rendered` confere com o arquivo escrito.
7. Par em rascunho ou rejeitado não aparece em nenhum arquivo.
8. Os arquivos `train/valid/test.jsonl` são aceitos pelo carregador de dados do `mlx-lm` na versão fixada, sem conversão.

## 11. Fora de escopo

- Outros formatos (Alpaca, ShareGPT). `messages` é o formato comum; só muda se um teste com outra ferramenta mostrar necessidade.
- Enviar o dataset ao Hugging Face.
- Configurar proporção de split na tela.

## 12. Como foi construída

Onde o código difere do texto acima, vale o seguinte:

- **Sem campo `rendered` novo.** Hash, linhas e contagem por tipo (`by_kind`) ficam em `files`, no `training-manifest.json` v2. O manifesto v1 não mudou (seção 2.1). `identity_sha256`, `split_policy` e `split_warnings` também ficam no v2.
- **Sem semente.** A ordem vem do hash de cada grupo. `split_policy` guarda só a versão da regra (`balanced-by-kind-1`). Mudar a regra muda a versão.
- **"Mesma fonte" continua sendo mesma passagem,** como já era. Juntar por arquivo deixaria um projeto de um arquivo só sem teste.
- **Comportamento.** Cada par tem grupo próprio (`behavior:<id>`), e o padrão fica em `evidence_refs`. Assim a regra da Especificação 005, de que um `source_group` não cruza splits, continua valendo sem exceção.
- **Tipo pequeno.** Com menos de 5 grupos independentes, o tipo fica no treino, onde ensina mais do que mediria, e sai o aviso. A partir de 5, validação e teste recebem ao menos um.
- **O equilíbrio vale para o conjunto aprovado inteiro.** Exportar uma parte mantém os mesmos splits, então uma seleção pode ficar sem um tipo num split. Os avisos são calculados sobre o que realmente saiu.
- **Sem par aprovado.** A tela desliga o botão com "Approve some pairs first."; ainda não há link direto para Curate.
- **Respostas repetidas.** Quando 5 ou mais pares aprovados (e ao menos 5% deles) têm a mesma resposta, ignorando pontuação, o export avisa em `answer_warnings` e no `README.md`: "49 pairs answer only "I don't know.". A model trained on them tends to say it to every question." A tela Export mostra o aviso antes de exportar.
- **Reword them.** Se as repetidas são "não sei" escritos pelo modelo, a tela oferece **Reword them**: o modelo reescreve cada um dizendo o que não sabe, com as palavras da pergunta ("I don't know how many layers the encoder uses."). Cada par reescrito volta para Curate para ser aprovado de novo. **Undo** devolve a resposta e o estado anteriores, exceto nos pares que a pessoa mudou depois (`qa_rewords`).
- **Recusa nua.** A geração de Not known passou a descartar a resposta que só diz que não sabe, sem nomear o quê. Vale para o que o modelo escreve; a resposta escrita pela pessoa continua livre.

