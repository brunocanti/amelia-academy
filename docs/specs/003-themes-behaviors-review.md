# Especificação 003 — Temas, comportamentos e revisão

**Status:** normativa v1 do alvo. No app que roda, tema e ficha são nós do mesmo grafo; ver `docs/architecture/estado-atual.md`. Não recriar Evidence e Cards como etapas de menu a partir desta spec.

## Propósito e escopo

Regula propostas de temas, fichas versionadas de comportamento e decisões humanas. Material gerado é sempre proposta, nunca aprovação.

## Entidades e tipos

- `ThemeProposal`: resumo, limites, público, evidências e similaridades.
- `Theme`: versão aceita de uma proposta, com citations.
- `BehaviorCard`: intenção, tom, diretrizes, público, privacidade, limites, cenários e alvo de samples.
- `ReviewDecision`: ator, alvo/versão, ação, motivo, instante e diff quando editado.

## Máquinas de estado

Tema: `proposed → accepted|merged|rejected`; edição de aceito cria versão nova.
Ficha: `draft → in_review → approved → superseded|retired`.
Somente versões `approved` podem gerar lotes publicáveis.

## Invariantes

1. Aceitação, merge, rejeição e aprovação exigem ação explícita de ator autorizado.
2. Navegação, timeout, score ou saída de modelo NÃO constituem decisão.
3. Tema com origem declarada DEVE citar chunks resolvíveis; ficha manual DEVE registrar autoria manual.
4. Versão usada por sample ou dataset é imutável.
5. Policy gates de plataforma NÃO podem ser enfraquecidos por ficha ou charter.
6. Campos centrais são genéricos; voz e identidade pertencem aos dados do projeto.

## API e eventos

- `POST /themes:propose`, `POST /themes/{id}:accept|reject|merge`.
- `POST /behavior-cards`, `POST /behavior-cards/{id}:submit|approve|retire`.
- Eventos: `theme.proposed`, `theme.decided`, `behavior.version_created`, `behavior.approved`.
- Atualizações usam ETag e retornam diff estável.

## Autorização e privacidade

Propor exige escrita; decidir exige `review`; aprovar ficha exige `approve_behavior`. Evidência privada permanece no projeto. Conteúdo e reasoning bruto do gerador não aparecem em logs ou auditoria.

## Semântica de falha

Evidência ausente ou de outro projeto retorna erro não retryable. Concorrência retorna `412`; a decisão antiga permanece. Merge cíclico retorna `409`. Falha ao gravar auditoria aborta a decisão inteira.

## Testes de aceitação

1. Proposta gerada permanece `proposed` até clique/command explícito.
2. Ficha aprovada e já usada não pode ser editada in-place.
3. Merge preserva ancestrais e citações.
4. Política de plataforma contradita por ficha bloqueia aprovação.
5. Auditoria reproduz autor, diff, motivo e versão decidida.
6. Proposta vinda de fonte traz citação resolvível do trecho. O título não é as primeiras palavras do arquivo, nem a primeira frase reaproveitada como fala de um sample.
7. Criar ficha deixa o estado em `draft`. Aprovar é outra ação. Sem essa aprovação, gerar lote retorna erro.

## Fora de escopo

Geração de samples, treino, memória pessoal e validação automática da qualidade editorial.
