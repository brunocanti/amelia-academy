# ADR 004 — Conversas estruturadas canônicas; texto tokenizado derivado

**Status:** Accepted  
**Data:** 24 out. 2026

## Contexto

Um sample precisa sobreviver à troca de base model, tokenizer, template e runtime. Texto ChatML ou tokens persistidos como fonte misturam conteúdo editorial com formato de fornecedor. O Amelia 3 documentou degradação silenciosa quando treino e inferência usaram templates diferentes e chegou a considerar tokens especiais próprios. A revisão posterior recomenda usar o `chat_template` do tokenizer do modelo.

## Decisão

A fonte canônica de samples e datasets é uma conversa estruturada e versionada: mensagens com papéis, partes tipadas de conteúdo, metadados de idioma, público, cenário, proveniência e decisão humana. Não contém delimitadores de modelo, tokens especiais nem IDs tokenizados.

Cada job de treino produz uma renderização derivada usando revisão exata do modelo, tokenizer e `chat_template`. O manifest registra hashes, versões, BOS/EOS/PAD, flags de thinking e loss mask. Fixtures de tokenização são compartilhadas entre treino e inferência. Reasoning privado não integra dataset. No perfil direct, loss incide somente na resposta final do assistant. A proposta ADR 019/spec 016 acrescenta o perfil reasoned: justificativa editorial explícita, versionada e aprovada, com loss na justificativa e na resposta final; exige novos contratos e renderer verificado antes de implementar.

## Alternativas consideradas

- **Persistir JSONL ChatML:** simples para um modelo, mas acopla o dado ao template e dificulta rerender.
- **Persistir token IDs:** reprodução aparente, porém inválida ao trocar tokenizer e opaca para revisão.
- **Template universal da Amelia:** reduz formatos, mas adiciona tokens ou semântica incompatível com bases diferentes.
- **Texto user/assistant em duas colunas:** insuficiente para system, tools, contexto e conteúdo multimodal futuro.

## Consequências

- Um dataset pode alimentar múltiplos modelos sem duplicar autoria.
- Revisão humana vê conteúdo, não marcadores.
- Renderizações são artifacts imutáveis, nunca atualização do dataset.
- Reprodutibilidade exige preservar ou identificar exatamente tokenizer/template.
- Migração de schema de conversa é explícita e produz nova versão derivada.

## Validação

- O mesmo dataset canônico renderiza para dois modelos com templates distintos.
- Golden fixtures com casos unicode, tool e múltiplos turnos produzem IDs esperados no worker e runtime.
- CI rejeita delimitadores reservados inseridos pela camada de persistência.
- Alterar hash de template invalida cache e exige nova renderização/avaliação.
- Inspeção de loss mask comprova zero loss em system, user, tool e raciocínio privado; a justificativa editorial só recebe loss no perfil reasoned verificado (spec 016).
