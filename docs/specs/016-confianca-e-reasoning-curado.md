# Especificação 016 — Confiança da curadoria e duas saídas de treino

**Status:** implementação parcial em 7 nov. 2026: eventos, confiança, revisão de justificativas, filtros e export neutro construídos e testados em cópia. Renderer reasoned, loss e treino comparativo ainda pendentes.
**Altera:** ADR 004 e 016; specs 004, 005, 013, 014 e 015. As alterações abaixo são requisitos futuros, não descrição do app atual.

## 1. O que se recuperou

A ADR 016 registra três níveis por pilar, calculados a partir das comparações do Challenge. Foram removidos após leitura cega: repetição num paper elevava o nível sem demonstrar qualidade. Não foi recuperado um registro que estabeleça a nova fórmula abaixo; ela é uma proposta, não a reprodução de um acordo perdido.

Retomamos os três níveis com outra base: decisões humanas e verificações registradas sobre a revisão exata. O modelo não fornece nota. Uma regra determinística pode usar conclusões humanas sobre propostas do modelo, mas isso não torna o julgamento factual infalível.

## 2. Três dimensões separadas

- **Tipo:** Known, Not known, False premise, Vizinho ou Comportamento: o que se ensina.
- **Estado editorial:** proposto, aprovado ou rejeitado: o que a pessoa deixou entrar.
- **Confiança da curadoria:** baixa, média ou alta: quanto a conclusão daquela revisão foi conferida. Não é probabilidade de verdade nem confiança que o modelo sentirá ao responder.

Um Not known pode ter confiança alta: o limite foi conferido no corpus identificado. Uma premissa falsa pode ter confiança alta: foi conferido que a alegação é falsa naquele contexto. Nenhum deles vira Known por ganhar confiança.

## 3. Regra determinística v1

Aplicar na ordem, sem pontos, médias nem contagem de vizinhos:

1. **Baixa:** revisão ainda não aprovada; evidência/relação obrigatória inválida ou desatualizada; aviso editorial pendente; conflito pertinente aberto; ou suporte exigido rejeitado/editado. Rejeitados continuam fora do export. Aprovar sozinho não supera bloqueios.
2. **Alta:** aprovada, sem os bloqueios acima, e todas as verificações pertinentes explicitamente confirmadas pela pessoa sobre os hashes atuais.
3. **Média:** aprovada, sem bloqueios, mas ainda sem todas essas confirmações registradas.

As confirmações pertinentes são:

- Known: evidência sustenta a resposta e suas condições; Connected exige também a relação de combinação confirmada.
- False premise: alegação falsa identificada e correção sustentada na evidência.
- Not known: escopo da pergunta identificado e limite conferido no snapshot do corpus. Não afirma ausência universal. Arquivo novo invalida a confirmação do limite até rever.
- Vizinho: fronteira entre assuntos confirmada e parte geral conferida. Não recebe suporte documental fictício.
- Comportamento: adequação à revisão do card e à identidade confirmada. Não representa confiança factual.
- Tensão/depende: condições ou desacordo descritos, evidências e decisão humana confirmadas, preservando limites. Não converter desacordo em certeza numérica.

As verificações são apresentadas como uma pergunta contextual simples, ao conferir o par. Aprovação em lote mantém média; não fabrica confirmação detalhada. Uma decisão em Decide pode satisfazer uma verificação se a pergunta da tela realmente a verificou, com evento e hashes. `Both are right` confirma coexistência, não independência de fontes nem resposta nova; `Keep all` não confirma suporte.

Similaridade, proximidade no grafo, repetição, quantidade de arquivos, resposta do juiz e ausência de conflito não elevam nível. Nenhuma aprovação antiga é convertida retroativamente em alta. Pares aprovados antigos ficam médios se válidos; com bloqueio, baixos e excluídos do treino até revisão.

## 4. Como a confiança sai da Curate

Registrar eventos de aprovação, verificação, resolução, edição e Undo, com projeto, ator, instante, alvo e hashes. Projeção derivada: `level`, `rule_version`, `reason_codes`, `input_hashes`, `corpus_hash` quando pertinente. A função não chama LLM; mesmos eventos e hashes produzem mesmo nível.

Edição de resposta, evidência, relação, card ou identidade invalida confirmações dependentes; Undo recompõe a projeção. Mudança só de tema não aumenta confiança. Export congela essa projeção. Não reconstruir história humana a partir do estado atual do banco.

## 5. Reasoning que pode virar dado de treino

É uma **justificativa editorial explícita**, preparada com os dados curados e revisada pela pessoa. Não é leitura nem gravação de raciocínio privado do modelo. O motivo do juiz é uma proposta; não entra automaticamente.

Uma revisão de justificativa contém `sample_id`, revisão/hash da resposta, `basis_refs` com revisões de pares/evidências, `relation_refs`, `decision_refs`, conclusão tipada, texto curto, origem e estado editorial. Rejeitar/editar uma base invalida a justificativa dependente, salvo um registro de tensão que conserva versões históricas como posições, não como fatos endossados.

O texto explica somente a lógica necessária:

- Known: evidência ou composição dos fatos e conclusão.
- Not known: o que foi estabelecido e qual detalhe continua sem suporte no escopo.
- False premise: alegação errada, fato que a contradiz e correção.
- Vizinho: diferença de escopo e separação da resposta geral.
- Depende/tensão: condições dos dois lados ou desacordo ainda não resolvido.
- Comportamento: princípio do card aplicável ao caso, sem inventar fatos ou expor instruções privadas.

A vizinhança serve para achar bases, não para justificá-las. Só relações pertinentes, versionadas e confirmadas podem sustentar a justificativa. Não exportar o grafo inteiro, comentários do curador, votos ou frases como “a pessoa clicou em This one” no alvo de treino.

Exemplo ilustrativo de False premise: pergunta “O método com perdas permite reconstrução exata?”; justificativa “A compressão com perdas descarta informação; reconstrução exata não é garantida.”; resposta final “Não. Esse método não garante reconstrução exata.” O exemplo precisa de evidência real antes de virar sample.

## 6. Duas saídas, seleções explícitas

**Sem reasoning (`direct`):** pergunta e resposta final aprovada. Todos os tipos podem entrar, inclusive Not known, False premise e Vizinho: eles também ensinam respostas diretas úteis. Filtros por tema, tipo e confiança e exclusão individual; padrão inclui médios e altos sem bloqueios. “Sem sentido” é problema editorial: rejeitar/excluir das duas saídas. Interpretamos o pedido como selecionar pares que fazem sentido para resposta direta, sem obrigar uma explicação.

**Com reasoning (`reasoned`):** pergunta, justificativa aprovada e resposta final aprovada. Confiança média/alta e nenhuma dependência inválida. Não inventar justificativa no export, não preencher faltantes com frase fixa nem exportá-los como se tivessem reasoning. Mostrar quantos faltam e levar à curadoria. Justificativa tem aprovação própria; nível alto do par não a aprova automaticamente.

**Ambos:** variantes congeladas da mesma seleção. O reasoned pode ter menos pares; manifesto lista a diferença e os motivos. Para experimento controlado, oferecer interseção idêntica por IDs/revisões, com diferença apenas na justificativa. Ausência de reasoning não rebaixa a confiança do par.

## 7. Renderização e divisão

Conversa canônica permanece sem tokens de fornecedor. Justificativas ficam em artifact versionado separado, ligado ao hash canônico, preservando compatibilidade do canonical-sample v1. Manifesto novo declara perfil, seleção, confiança, versões das regras, hashes das justificativas e exclusões.

Dividir por componentes de todas as bases e relações ANTES de renderizar. Sample e variantes direct/reasoned e suas dependências não atravessam splits, mesmo em exports distintos destinados à mesma comparação. Dependências rejeitadas conservadas como posições de tensão também agrupam os splits. Nenhum texto do teste alimenta justificativa do treino.

Na renderização, o adaptador do modelo mapeia justificativa e resposta para canais oficialmente suportados; verificar tokens e loss mask por fixture. Não colar tags `<think>` universais. Perfil direct: loss na resposta final; perfil reasoned: loss na justificativa editorial e na resposta final. System/user/tool e metadados de confiança têm loss zero. Modelo sem renderização reasoned verificada bloqueia esse perfil com motivo visível. Modo de geração em inferência acompanha o perfil treinado.

Não há garantia atual de que o carregador mlx-lm aceite essa separação: a seção 2 da spec 015 provou somente direct. É obrigatório um novo teste real de ida e volta dos canais e da máscara antes de oferecer treino reasoned.

## 8. Tela e uso futuro

Curate mostra “Confiança: média — resposta aprovada; evidência ainda não conferida”, expansível para os motivos. Graph preserva cor de pilar e estado editorial; confiança usa contorno neutro fino/médio/grosso e tooltip com motivos. As relações de suporte usam traço pontilhado enquanto propostas e contínuo quando a verificação pertinente é confirmada; conflitos abertos permanecem pontilhados. Relações estruturais (tema/arquivo/trecho comum) não recebem nível. Seleção mantém destaque neutro e nunca transforma proposta em confirmação. A lista lateral tem filtro por nível, sem redesenhar proximidade nem fingir probabilidade. Ao selecionar, mostrar as bases e decisões que explicam o nível.

Export pergunta “Só resposta”, “Com justificativa” ou “Ambos”, informa contagens e exclusões antes do download. Filtros avançados recolhidos. Confidence ajuda a selecionar, priorizar revisão e estratificar avaliação; não entra no texto da resposta, não pesa a loss automaticamente e não vira nota de confiança do modelo em runtime.

Comparar direct e reasoned na mesma interseção, medindo acerto, recusa correta/indevida, correção de premissa, escopo de vizinho, consistência entre justificativa e final, latência e tokens. Ler justificativas amostradas por tipo. Separar desempenho por confiança sem assumir que alta terá mais acerto. Routing futuro depende desses resultados e de medição em runtime; metadado do dataset sozinho não decide quando o modelo deve pensar.

## 9. Contratos, falhas e implementação

Manter contratos v1 publicados; não adicionar campos em schemas com `additionalProperties: false` sem versão. Implementação deve introduzir manifesto e model-spec versionados (v2 para mudança de semântica de loss), schema de justificativa e fixtures; migrar consumidores explicitamente. `assistant_final_only` continua válido exclusivamente para direct; reasoned exige política própria identificada e testada. Esta spec não modifica o app ou contratos executáveis ainda.

Falha de geração preserva o par e mostra motivo; justificativa inválida fica fora. Conflito aberto bloqueia a exportação dos pares afetados até decisão, inclusive se estavam aprovados; baixa não pode ser liberada por filtro avançado. O usuário pode corrigir o bloqueio na Curate.

Entrega em ordem: eventos/hash e cálculo de confiança; tela com motivos/Undo; justificativa e revisão; export de variantes e contratos; adaptador de canais; treino e comparação real. Nada de afirmar a feature construída só porque as specs mudaram.

## 10. Aceitação

- Mesmo snapshot produz mesmo nível; nenhum LLM é chamado para calculá-lo.
- Repetição ou vizinhança não eleva média para alta; aprovação em lote também não.
- Not known alto continua Not known; corpus novo invalida a confirmação do limite.
- Edição e Undo invalidam/recompõem apenas as dependências correspondentes.
- Premissa falsa e Vizinho continuam elegíveis em direct; par inválido fica fora de ambos.
- Justificativa ausente, antiga ou não aprovada nunca entra em reasoned; totais mostram exclusões.
- Variantes e todas as bases ficam no mesmo split; comparação controlada usa mesma interseção.
- Fixtures comprovam loss nos canais corretos; metadado de confiança não vira resposta.
- Treino real verifica aprendizado dos dois perfis, sem concluir capacidade geral a partir de uma geração.
