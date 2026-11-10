# ADR 010 — Sem ingestão automática de chat privado para treino

**Status:** Accepted  
**Data:** 24 out. 2026

## Contexto

Conversas privadas contêm fatos pessoais, terceiros, segredos, inferências e pedidos transitórios. Memória precisa mudar e ser corrigida rapidamente; pesos são difíceis de inspecionar, apagar e reverter. Transformar cada diálogo em treino confundiria uso com consentimento, reforçaria erros e contrariaria a promessa de autoria humana da Academy. A marca explicitamente não promete aprendizagem contínua de chats privados.

## Decisão

Mensagens e sessões nunca entram automaticamente em fontes, samples, datasets ou jobs. Não há opt-out global porque o padrão é ausência de transferência.

Uma conversa só pode originar treino pelo fluxo:

1. ator seleciona trechos e finalidade específica;
2. sistema cria `TrainingCandidate` separado;
3. conteúdo passa por redação de PII/terceiros e mostra diff;
4. consentimento registra escopo, finalidade, projeto, trechos, data e revogação;
5. operador revisa e aprova a versão redigida;
6. Academy cria sample rascunho com lineage para o consentimento;
7. apenas sample posteriormente aprovado pode integrar dataset.

Consentimento para memória, logging ou suporte não equivale a consentimento para treino. Revogação anterior à publicação impede novos datasets e invalida candidatos; artifacts já distribuídos exigem política de retirada e novo release, não promessa de “desaprender” bytes.

## Alternativas consideradas

- **Ingestão automática com opt-out:** maximiza volume, mas consentimento é ambíguo e revisão tardia.
- **Ingestão de chats anonimizados automaticamente:** redação pode falhar e contexto reidentificar pessoas.
- **Apenas feedback positivo:** um like não define finalidade nem autoriza falas de terceiros.
- **Nunca permitir conversa como fonte:** máxima proteção, mas impede contribuição deliberada e útil do operador.

## Consequências

- Dataset cresce mais devagar e com maior custo humano.
- Privacidade, autoria e finalidade ficam auditáveis.
- UI precisa separar “lembrar”, “usar nesta sessão” e “propor para treino”.
- Exclusão e revogação têm semântica concreta por estágio.
- Métricas de produto não podem pressionar aceitação silenciosa.

## Validação

- Fitness function falha se dataset referenciar mensagem sem `training_consent_id`, versão redigida e aprovação.
- E2E confirma que chat comum não aparece em busca de fontes/samples.
- Testes cobrem terceiro citado, menor, segredo, “não guarde isto”, consentimento revogado e edição após consentimento.
- Export de auditoria reconstrói seleção, diff, consentimento, revisores e datasets afetados.
- Telemetria e logs não contêm corpo da conversa por padrão.
