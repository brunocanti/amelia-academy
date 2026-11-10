# ADR 008 — Academy separada de Mind e memória

**Status:** Accepted  
**Data:** 24 out. 2026

## Contexto

Academy administra material autorizado, comportamento estável, treino, avaliação e publicação. Amelia Mind administrará eventos em uso, memória pessoal corrigível, workspace, retrieval, appraisal, roteamento e gates. Fundir os dois transformaria episódios mutáveis em material de treino, daria ao pipeline offline autoridade sobre memória e confundiria voz da persona com operação da plataforma. A pesquisa arquitetural exige ritmos e autoridades diferentes.

## Decisão

Academy e Mind são bounded contexts distintos. Academy possui fontes, temas, fichas, samples, datasets, jobs, avaliações e releases. Mind possui event ledger, sessões, claims, evidências pessoais, validade temporal, workspace e decisões de runtime.

A integração ocorre apenas por contratos explícitos:

- Academy publica `ModelRelease`; Mind fixa uma versão para inferência.
- Mind pode criar `TrainingCandidate` redigido, com consentimento, finalidade e referências permitidas.
- Academy importa esse candidato como rascunho isolado, ainda sujeito a revisão humana.
- Academy nunca lê tabelas internas de memória; Mind nunca modifica dataset ou release.

Na v1, Conversation pode existir como superfície mínima da Academy, mas mensagens permanecem no contexto Conversation e não ganham semântica de fonte ou memória automaticamente.

## Alternativas consideradas

- **Um domínio “Amelia” único:** menos fronteiras iniciais, mas mistura autoridade e lifecycle.
- **Academy dona da memória:** facilita UI, porém atrela memória pessoal ao treinamento.
- **Mind dono do treino:** aproxima feedback do runtime, mas enfraquece curadoria e reversão humana.
- **Compartilhar tabelas com flags:** fronteira nominal sem isolamento real.

## Consequências

- Evolução do Mind não bloqueia a oficina da Academy.
- Há duplicação intencional de IDs de referência e contratos de integração.
- Transferência de dado pessoal é visível e revogável.
- Policies da plataforma não podem ser reescritas pelo charter da persona.
- Deploy inicial pode omitir Mind sem criar stubs falsos.

## Validação

- Grafo de dependências não contém import de módulos internos entre Academy e Mind.
- Usuário pode apagar/corrigir memória sem mutar dataset ou release histórico; retenção legal é sinalizada separadamente.
- Publicar release não escreve claims de memória.
- TrainingCandidate sem consentimento ou redação é rejeitado na fronteira.
- Teste de contrato troca implementação do Mind por fake sem alterar fluxos Academy.
