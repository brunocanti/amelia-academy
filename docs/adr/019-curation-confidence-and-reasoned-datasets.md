# ADR 019 — Confiança derivada da curadoria e datasets com justificativa

**Status:** proposta, construída em parte em 7 nov. 2026. Eventos, confiança, justificativas e export neutro construídos e testados em cópia. Renderer reasoned, loss e treino comparativo pendentes (spec 016).
**Altera:** ADR 016, item 6, e ADR 004 quanto à loss de justificativa editorial.

Recuperamos da ADR 016 o teste que rejeitou confiança derivada de repetição entre trechos. Preservamos esse resultado. A nova proposta calcula baixa/média/alta a partir de eventos e confirmações humanas sobre revisões e bases exatas, conforme a spec 016. Um modelo pode preparar as propostas; nunca atribui o nível. Nenhum clique cria resposta aprovada, prova independente ou confiança alta. `It depends`, `Yes` e `Partly` podem gravar um par escrito pelo modelo, mas ele entra como proposta em To review, com autoria registrada e Undo, e só sobe de nível com as confirmações da spec 016. A escolha da pessoa decide o que o par diz; a aprovação decide se ele vale.

Do mesmo conjunto curado saem perfis direct e reasoned. Reasoned usa justificativa explícita, versionada e aprovada, fundamentada nas relações Known/Not known/False premise/Vizinho e nas decisões pertinentes; raciocínio privado continua fora. O perfil direct aprende só a resposta final; reasoned aprende justificativa editorial e final, com renderer e máscara verificados. Confiança é metadado da curadoria, não certeza do modelo em runtime.

A spec 016 define a proposta normativa, bloqueios, visualização, contratos futuros e critérios de aceite. As specs 004/014/015 passam a remeter a ela; contratos executáveis v1 não mudam nesta etapa de desenho.
