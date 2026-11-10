# Amelia Academy — superfícies de produto

**Status:** especificação de experiência e conteúdo  
**Objetivo:** tornar a fundação de marca observável na arquitetura de informação, nos fluxos e nos estados da interface

O menu que a interface já mostra é outro: Visão geral, Sources, Knowledge, Samples, Dataset, Train, Evaluate, Publish. Knowledge é o grafo. A ficha de comportamento é um nó desse grafo, não um item ao lado de Temas. O detalhe está em `docs/architecture/estado-atual.md`. As listas “Temas / Fichas / Oficina” abaixo descrevem a proposta anterior e não devem ser reimplementadas.

---

## 1. Modelo mental

A interface sempre responde a quatro perguntas:

1. **Onde estou?** Academy → projeto → módulo → objeto.
2. **De onde veio?** Fonte, evidência e transformações.
3. **Qual é o estado?** Proposto, aprovado, publicado, falhou etc.
4. **O que acontece se eu agir?** Efeito, alcance e possibilidade de reversão.

A plataforma não é a persona. O shell, os jobs e as decisões falam com a voz da Academy; somente a conversa e os previews autorizados usam a voz do projeto.

---

## 2. Arquitetura de informação

### Navegação global

- **Projetos** — recentes, favoritos, criar e arquivar.
- **Atividade** — jobs, aprovações pendentes e falhas entre projetos.
- **Biblioteca** — templates, modelos-base e políticas compartilháveis.
- **Configurações** — runtimes, armazenamento, aparência e auditoria.
- **Ajuda** — documentação, atalhos e diagnóstico.

### Navegação do projeto

**Construir**

1. Visão geral
2. Fontes
3. Temas
4. Fichas
5. Oficina

**Treinar**

6. Datasets
7. Treinos
8. Avaliações
9. Releases

**Usar**

10. Conversa

**Governar**

11. Identidade e políticas
12. Histórico

Ordem acompanha o fluxo, mas não o impõe: ficha pode nascer sem fonte; avaliação pode comparar releases anteriores. Breadcrumbs exibem objetos, não repetem categorias desnecessárias.

### Cabeçalho contextual

```text
[ai] Amelia Academy / Amelia                         [Busca] [Atividade] [Perfil]
     Amelia  · Projeto histórico, iniciado em 2019
     [Visão geral] [Fontes] [Temas] ... [Conversa]
```

No projeto corporativo:

```text
[ai] Amelia Academy / Atlas Atendimento
     Atlas Atendimento · Projeto corporativo
```

O shell permanece idêntico. Avatar, acento e conteúdo mudam.

---

## 3. Superfícies e descrições

### 3.1 Projetos

Porta de entrada com nome, tipo, última atividade, release ativo e alertas. O CTA “Novo projeto” oferece template vazio, pessoal ou atendimento — templates de estrutura, não de personalidade.

**Card Amelia**

- `Amelia`
- `Pessoal · Projeto histórico`
- `Iniciado em 2019`
- `Release ativo: amelia-2026.10`
- `3 revisões pendentes`

**Card Atlas Atendimento**

- `Atlas Atendimento`
- `Corporativo · Suporte`
- `Release ativo: atlas-1.4`
- `Cobertura de avaliação: 92%`

### 3.2 Visão geral

Resume cadeia de produção, pendências e release ativo. A timeline de linhagem mostra Fontes → Temas → Fichas → Samples → Dataset → Treino → Release. Métricas sempre incluem denominador e período.

### 3.3 Fontes

Upload e inventário de arquivos. Cada item mostra status de extração, direitos declarados, hash, tamanho, data e quantidade de trechos. A visualização divide texto extraído e metadados; seleção de trecho gera link estável.

Campos obrigatórios: arquivo, finalidade, base de uso/licença declarada. A plataforma não valida juridicamente a declaração.

### 3.4 Temas

Fila de propostas com resumo, limites, público, fontes e proximidade com outros temas. Revisão lado a lado mantém candidato à esquerda e citações à direita. Ações: aceitar, editar, fundir, rejeitar.

### 3.5 Fichas

Contrato de comportamento com intenção, tom, diretrizes, público, privacidade, limites, cenários e alvo de samples. Pode apontar para um tema ou ser manual. Alterações após uso em dataset criam nova versão.

### 3.6 Oficina

Superfície central de revisão humana. Gera um lote para uma ficha aprovada e um tema aceito, e revisa uma conversa por vez, com contexto, resposta, evidência, tipo e duplicidade. O cabeçalho mostra ficha, tema, runtime, modelo e “n de N”. Ações com atalhos: aprovar, editar e aprovar, rejeitar, pular. Decisão nunca é inferida por navegação.

Não é a oficina: dois menus cujo resultado é o markdown da fonte partido em duas falas; a contagem de um corpus importado; um composer que não chama modelo. Importação, se existir, é outra superfície e diz que aquelas linhas não foram geradas aqui. Sem runtime de conversa publicado, a rota Conversa diz que ainda não há release para falar, e não inventa uma resposta fixa.

Nomes de psique (“consciente”, “pré-consciente”, “inconsciente”) não rotulam o shell. Pertencem aos dados do projeto Amelia. Sem banco durável, a interface diz que o estado morre com o processo.

### 3.7 Datasets

Seleciona versões de fichas e samples aprovados. Mostra composição por público, tipo, fonte, idioma e risco; sinaliza duplicatas e vazamento entre splits. Exportação e criação de dataset são ações diferentes.

### 3.8 Treinos

Cria job a partir de dataset imutável, modelo e template. Controles avançados ficam recolhidos; escolhas têm explicação e valor herdado. O log é pesquisável, copiável e separado do resumo humano. Cancelamento explica artefatos preservados.

### 3.9 Avaliações

Compara base e candidatos por dimensão: comportamento, competência, segurança, persona e latência. Mostra casos, tamanho de amostra e regressões; não declara vencedor apenas por média. Comparação cega é preferida para avaliação humana.

### 3.10 Releases

Publica uma configuração versionada: modelo, runtime, quantização, tokenizer/template, adapters, charter, políticas e thresholds. “Promover adapter” isoladamente não é release. Preview, checklist, publicação e rollback são etapas explícitas.

### 3.11 Conversa

Thread e histórico de sessões. Cabeçalho exibe projeto e release ativo. A interface pode mostrar rota (“direta”, “principal”, “deliberativa”) e evidências usadas, mas não chain-of-thought bruto. Mensagens da persona usam seu avatar; avisos da plataforma usam o monograma Academy e tom operacional.

### 3.12 Identidade e políticas

Editor versionado de charter, voz, relação, limites, claims autobiográficos canônicos e regras de expressão. Preview compara projeto atual e rascunho. Policy gates pertencem à plataforma/runtime e não podem ser reescritos como preferência da persona.

### 3.13 Histórico

Ledger legível de alterações: ator, horário, objeto, antes/depois e motivo. Filtros por ação e entidade; exportação com IDs estáveis. Reverter cria novo evento, não apaga história.

---

## 4. Wireframes textuais

### 4.1 Visão geral do projeto

```text
┌ Academy ─────────┬ Amelia / Visão geral ───────────────────────────────┐
│ Projetos         │ Amelia                          [Testar conversa]   │
│ Atividade        │ Projeto histórico · iniciado em 2019               │
│ Biblioteca       │                                                     │
│                  │ Release ativo [amelia-2026.10] [Ver linhagem]       │
│ CONSTRUIR        │                                                     │
│ Visão geral      │ Pendências                                          │
│ Fontes           │ [12 samples para revisar] [1 avaliação incompleta] │
│ Temas            │                                                     │
│ Fichas           │ Linhagem                                            │
│ Oficina          │ 18 fontes ─ 42 temas ─ 16 fichas ─ 1.240 samples  │
│ ...              │                         └ dataset v8 ─ release      │
└──────────────────┴─────────────────────────────────────────────────────┘
```

### 4.2 Revisão de tema

```text
┌ Temas / Proposta 14 de 23 ─────────────────────────────────────────────┐
│ TEMA CANDIDATO (7 col.)       │ EVIDÊNCIA (5 col.)                    │
│ Presença sem exigência        │ AMELIA_INSPIRATION.md · trecho 8      │
│ [Proposto] [2 fontes]         │ “Genuine contentment...”              │
│                               │ [Abrir no contexto]                    │
│ Resumo                        │                                       │
│ ...                           │ discovery-e-proposta.md · §2           │
│ Limites                       │ “Identidade como dado...”             │
│ ...                           │ [Abrir no contexto]                    │
│                               │                                       │
│ [Rejeitar] [Fundir] [Editar e aceitar] [Aceitar]                      │
└────────────────────────────────────────────────────────────────────────┘
```

### 4.3 Oficina

```text
┌ Oficina · Atlas Atendimento ─ Lote 31 ─────────────── 18/40 revisados ┐
│ CONTEXTO E RESPOSTA              │ ORIGEM E CONTROLE                   │
│ Cliente: “Posso devolver...”     │ Ficha: Devolução fora do prazo v3  │
│                                  │ Tipo: borda                         │
│ Atlas: “O prazo padrão...”       │ Público: cliente                    │
│                                  │ Política.pdf · p. 12                │
│ [Editar resposta]                │ “Exceções exigem aprovação...”      │
│                                  │ Similaridade: nenhuma duplicata     │
│ [R Rejeitar] [P Pular] [E Editar e aprovar] [A Aprovar]              │
└────────────────────────────────────────────────────────────────────────┘
```

### 4.4 Publicar release

```text
┌ Publicar atlas-1.5 ────────────────────────────────────────────────────┐
│ Mudanças                            │ Checklist                        │
│ + adapter dialogue-policy v4        │ ✓ Direitos declarados           │
│ ~ charter v7 → v8                   │ ✓ Avaliações obrigatórias        │
│ ~ threshold 0,72 → 0,76             │ ! Regressão de latência +8%      │
│                                     │ ✓ Rollback disponível            │
│ Afeta: Conversa de produção         │                                  │
│ Recuperação: atlas-1.4              │ [Cancelar] [Revisar] [Publicar]  │
└────────────────────────────────────────────────────────────────────────┘
```

### 4.5 Conversa com autoria separada

```text
┌ Amelia · release amelia-2026.10                   [Evidências] [•••]  ┐
│ Você: ...                                                            │
│                                                                      │
│ (avatar Amelia) Posso olhar isso com você. ...                       │
│ Rota principal · 2 fontes usadas                                     │
│                                                                      │
│ [ai Academy] Uma fonte citada foi atualizada depois deste release.   │
│ [Ver impacto]                                                        │
│                                                                      │
│ [Escreva uma mensagem...]                                      [↑]   │
└────────────────────────────────────────────────────────────────────────┘
```

O último aviso é inequivocamente da plataforma, não da persona.

---

## 5. Estados transversais

### Vazio

Estrutura: nome do objeto + por que importa + ação principal + alternativa.

- **Fontes:** “Este projeto ainda não tem fontes. Adicione material autorizado para propor temas com evidência.” `[Adicionar fonte]` `[Criar ficha manual]`
- **Avaliações:** “Nenhuma comparação criada. Avalie um treino antes de publicar.” `[Criar avaliação]`
- **Conversa sem release:** “Publique uma configuração para iniciar uma conversa reproduzível.” `[Ver releases]`

Não usar ilustração para esconder ausência de orientação.

### Carregamento

- skeleton replica a estrutura, por até poucos segundos;
- jobs longos mostram etapa, itens processados, tempo decorrido e ação segura;
- texto: “Extraindo 3 de 8 arquivos”, não “Pensando…”;
- usuário pode sair; a tela informa que o job continuará;
- progresso indeterminado só quando total realmente desconhecido.

### Erro

Estrutura obrigatória:

1. o que falhou;
2. o que foi preservado;
3. causa conhecida, sem inventar;
4. ação de recuperação;
5. ID copiável para diagnóstico.

Exemplo:

> **Não foi possível extrair `politicas.pdf`.** O arquivo original foi preservado e nenhum tema foi criado. O extrator não reconheceu o conteúdo. Tente OCR ou substitua o arquivo. `Erro EX-204 · Copiar ID`

Ações: `[Tentar novamente]` `[Usar OCR]` `[Remover arquivo]`.

### Parcial

Quando parte funciona, não colapsar em erro total:

> “7 de 8 fontes foram processadas. Revise a falha antes de propor temas para evitar cobertura incompleta.”

### Offline/runtime indisponível

Distinguir app, banco, runtime e modelo. Informar quais leituras continuam disponíveis e bloquear apenas ações dependentes.

### Permissão e política

> “Esta ação exige direito de publicação. Você ainda pode revisar e comentar.”

Não mascarar bloqueio de política como falha técnica.

### Sucesso

Confirma ação e novo estado:

> “Release `atlas-1.5` publicado. Novas conversas usarão esta configuração.” `[Ver release]` `[Reverter]`

---

## 6. Regras responsivas por fluxo

### Revisão

- desktop: candidato e evidência lado a lado;
- tablet: candidato principal, drawer persistente de evidência;
- mobile: etapas “Conteúdo” e “Evidência”, com contador e decisão fixa no rodapé;
- estado de edição é preservado ao alternar;
- aprovar exige que evidência esteja disponível, não necessariamente aberta.

### Tabelas

- desktop: colunas configuráveis e ações no fim;
- tablet: ocultar metadados secundários, acessíveis em detalhe;
- mobile: card com título, estado, indicador crítico e ação; filtros em sheet;
- seleção em lote informa quantidade e escopo.

### Conversa

- desktop: histórico 280 px + thread + painel de evidência;
- tablet: histórico e evidência como drawers;
- mobile: thread em largura total; composer respeita teclado e safe area;
- citações abrem bottom sheet sem perder posição na conversa.

### Gráficos e linhagem

- abaixo de 768 px, priorizar resumo e tabela;
- DAG mostra subgrafo do nó selecionado, não miniatura ilegível;
- zoom e pan têm controles e equivalentes por teclado.

---

## 7. Conteúdo aplicado a dois projetos

### Amelia

**Charter resumido:** projeto pessoal e histórico iniciado em 2019, com voz calorosa, curiosa e não exigente. A Academy descreve tecnicamente suas fontes e releases; Amelia fala apenas dentro de samples e conversas.

Exemplo de ficha:

- título: `Acolher sem dramatizar`
- intenção: reconhecer dificuldade e oferecer presença sem alegar emoção própria;
- limite: não incentivar dependência, exclusividade ou substituir ajuda profissional;
- sample esperado: “Posso ficar com você nessa conversa e ajudar a organizar o que está pesado.”

### Atlas Atendimento

**Charter resumido:** assistente corporativo fictício de suporte, orientado a evidência e escalonamento. Sem intimidade ou persona pessoal.

Exemplo de ficha:

- título: `Explicar devolução fora do prazo`
- intenção: informar regra, citar exceções e encaminhar decisão;
- limite: não prometer reembolso nem inventar aprovação;
- sample esperado: “O prazo padrão terminou em 18 out. Posso abrir uma análise de exceção; a aprovação depende da equipe responsável.”

Os dois exemplos usam a mesma ficha, oficina, avaliação e release. Diferenças são dados do projeto, não forks da interface.

---

## 8. Conteúdo e microcopy

### Verbos de ação

- `Adicionar fonte`
- `Propor temas`
- `Aceitar tema`
- `Gerar lote`
- `Aprovar sample`
- `Criar dataset`
- `Iniciar treino`
- `Comparar resultados`
- `Publicar release`
- `Reverter para…`

Evitar “Continuar” quando o efeito puder ser nomeado.

### Confirmações

Confirmação adicional apenas para ação irreversível, de grande alcance ou difícil de perceber. O diálogo nomeia objeto e impacto; digitação do nome é reservada a exclusão sem recuperação.

### Proveniência

Formato curto: `Arquivo · página/seção · versão`.  
Formato expandido: autor/origem declarada, data, licença/base de uso, hash, trecho e transformações.

### Datas, métricas e IDs

- UI: `24 out. 2026, 19:10`;
- logs/export: ISO 8601 com fuso;
- mostrar `1.240 de 1.500 (82,7%)`, não apenas `82,7%`;
- IDs ficam copiáveis, mas não substituem nomes humanos.

---

## 9. Critérios de aceitação

- [ ] navegação distingue nível global, projeto, módulo e objeto em todas as rotas;
- [ ] Amelia e Atlas Atendimento completam fontes → release sem componentes específicos de persona;
- [ ] voz da plataforma e voz do projeto são visual e textualmente distintas;
- [ ] cada objeto derivado oferece caminho para sua origem e versão;
- [ ] oficina mantém candidato e evidência acessíveis em desktop e mobile;
- [ ] empty/loading/error/partial/offline/permissão/sucesso existem nos componentes principais;
- [ ] erros informam preservação, recuperação e ID de diagnóstico;
- [ ] ações críticas explicam alcance, efeito e rollback antes da confirmação;
- [ ] releases versionam configuração completa, não apenas adapter;
- [ ] tabelas, conversa e linhagem funcionam sem hover e a 320 px;
- [ ] nenhuma tela expõe chain-of-thought bruto ou confunde metáfora psicológica com estado técnico;
- [ ] a implementação foi lida contra a Amelia 3 em `~/Projects/Amelia3` (oficina, padrões, limpeza, dataset e treino listados em `docs/erros-da-primeira-implementacao.md`) e a tela nova se reconhece ao lado dessas, sem copiar `deprecated/` nem apelido de posse;
- [ ] a oficina mostra um lote com tipo, ficha, tema, modelo e n de N, e as falas não são a fonte partida ao meio;
- [ ] help desk genérico, cópia da instrução e alegação de sentimento não entram na fila;
- [ ] Amelia e Atlas usam o mesmo shell; vocabulário de psique não aparece na navegação da Academy;
- [ ] a superfície segue `visual-system.md` e não um admin genérico;
- [ ] store efêmero está rotulado; conversa sem release não finge uma resposta;
- [ ] teste com usuários alcança pelo menos 80% de conclusão sem ajuda para: adicionar fonte, aceitar tema, revisar sample, comparar treino e publicar release;
- [ ] auditoria por teclado e leitor de tela conclui os mesmos fluxos sem bloqueio crítico.
