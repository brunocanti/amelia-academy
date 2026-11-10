# Amelia Academy — sistema visual

**Status:** corrigido após rejeição do protótipo editorial  
**Direção:** herança direta da Amelia 3 — fundo `#0d0d0d`, marca `oi`, paleta de camadas  
**Dependência:** aplicar em conjunto com `brand-foundation.md`

A primeira versão deste documento inventou um sistema “papel + serif + cobre”. Isso não existia na Amelia e foi descartado. A paleta abaixo replica os tokens reais de `mindStore.js` e `tailwind.config.js`.

---

## 1. Princípios

1. **O conteúdo lidera.** Interface densa, legível e silenciosa; decoração nunca compete com revisão.
2. **A origem permanece à vista.** Citações, relações e versões usam fios, camadas e marcadores de linhagem.
3. **Cor comunica estado.** A identidade é preto, branco e neutros; acentos têm significado e contraste verificável.
4. **Tipografia herda a Amelia 3.** Archivo opera a interface; Instrument Serif aparece só no título de capa.
5. **Movimento explica mudança.** Transições revelam relação espacial ou progresso; não simulam “vida”.

---

## 2. Tokens fundamentais

Tokens usam nomes semânticos. Valores abaixo são baseline para tema claro e escuro, não classes aplicadas diretamente em componentes.

### Cor

```css
:root {
  --canvas: #0d0d0d;
  --surface: #171717;
  --raised: #1f1f1f;
  --ink: #f9f9f9;
  --muted: #9b9b9b;
  --faint: #676767;
  --line: #262626;
  --conscious: #10b981;
  --preconscious: #f59e0b;
  --unconscious: #ef4444;
  --memory: #06b6d4;
  --psyche: #8b5cf6;
  --structural: #84cc16;

  --brand-ink: var(--ink);
  --brand-mark: #10b981;
  --brand-mark-ink: #04140e;
  --brand-origin: #06b6d4;
  --brand-review: #f59e0b;
  --brand-refuse: #ef4444;
}

[data-theme="light"] {
  --canvas: #f9f9f9;
  --surface: #ffffff;
  --raised: #ececec;
  --ink: #171717;
  --muted: #4e4e4e;
  --line: #e3e3e3;
}
```

A marca-mãe usa **cinco primárias**. O resto é chão (neutros) ou estado derivado.

| Primária | Token | Hex | Uso |
| --- | --- | --- | --- |
| Ink | `--brand-ink` | `#f9f9f9` / `#171717` | texto, tipo, identidade |
| Mark | `--brand-mark` | `#10b981` | pulso da Academy: CTA, aprovar, ao vivo |
| Origin | `--brand-origin` | `#06b6d4` | fonte, citação, evidência, foco |
| Review | `--brand-review` | `#f59e0b` | proposta, pendente, caso de borda |
| Refuse | `--brand-refuse` | `#ef4444` | rejeitar, recusa, falha |

Botão primário e sample aprovado usam Mark. Sample de recusa e botão destrutivo usam Refuse. Citação e foco usam Origin. Pendência usa Review. Ink é o tipo, não um acento.

As camadas históricas da Amelia 3 (`conscious`, `memory`, …) mapeiam nessas cinco. `psyche` e `structural` não são primárias da Academy — ficam em jobs de modelo e publicação, se precisarem.

Neutros vêm da escala `#f9f9f9` … `#0d0d0d`. Não usar paleta bege, cobre de projeto nem serif de capa.

### Uso semântico

| Papel | Uso permitido | Nunca usar só para |
| --- | --- | --- |
| `info` | ajuda contextual, seleção informativa | marca |
| `success` | aprovado, concluído, saudável | decoração |
| `warning` | revisão necessária, risco reversível | atenção genérica |
| `danger` | falha, exclusão, bloqueio crítico | CTA primário comum |
| `pending` | proposto, fila, processamento | diferenciar projeto |

Cada ocorrência deve combinar cor com texto, forma ou ícone. Visualizações de dados usam paleta própria e testada; não reutilizar verde/vermelho para categorias neutras.

### Tipografia

Direção:

- **Sans funcional:** Archivo (fonte primária da Amelia 3).
- **Serif de capa:** Instrument Serif (fonte secundária da Amelia 3), só no título de entrada.
- **Mono:** uma família licenciada com zero distinguível, como JetBrains Mono, após verificação.
- **Fallbacks:** `Arial, sans-serif`; `Georgia, serif`; `ui-monospace, monospace`.

| Token | Tamanho/linha | Peso | Uso |
| --- | --- | --- | --- |
| `display` | 48/52 | serif 400 | capa e onboarding amplo |
| `title-1` | 32/38 | sans 550 | título de página |
| `title-2` | 24/30 | sans 550 | seção principal |
| `title-3` | 18/24 | sans 600 | card e painel |
| `body-lg` | 18/29 | sans 400 | introdução e leitura |
| `body` | 16/24 | sans 400 | conteúdo padrão |
| `body-sm` | 14/20 | sans 400 | tabelas e metadados |
| `label` | 13/16 | sans 600 | campos e controles |
| `caption` | 12/16 | sans 450 | proveniência e timestamps |
| `code` | 13/20 | mono 400 | IDs, logs e snippets |

Regras:

- corpo nunca abaixo de 14 px; 16 px em formulários móveis;
- largura de leitura de 60–72 caracteres;
- serif não é usada em controles, tabelas ou mensagens de erro;
- títulos não usam caixa alta; labels compactos podem usar caixa alta apenas com espaçamento de `0.06em`;
- pesos 400, 550/600 e 700 bastam; evitar aparência de catálogo de fontes.

### Espaçamento e dimensão

Base de 4 px:

`space-0 0`, `space-1 4`, `space-2 8`, `space-3 12`, `space-4 16`, `space-5 20`, `space-6 24`, `space-8 32`, `space-10 40`, `space-12 48`, `space-16 64`, `space-20 80`.

Dimensões:

- controle compacto: 32 px;
- controle padrão: 40 px;
- controle confortável/touch: 44–48 px;
- sidebar global: 240 px expandida, 64 px recolhida;
- painel contextual: 320–400 px;
- conteúdo: máximo 1440 px; leitura: máximo 760 px;
- raio: `4 px` campos, `8 px` cards, `12 px` diálogos; pill só para status;
- borda: 1 px; borda selecionada: 2 px sem alterar layout;
- sombra: apenas para elevação real (`0 8px 28px rgb(0 0 0 / 10%)`).

---

## 3. Grid e composição

### Desktop ≥ 1200 px

- grid de 12 colunas, gutter 24 px, margens 32–48 px;
- shell: navegação global + área principal + painel contextual opcional;
- revisões usam divisão 7/5: conteúdo candidato à esquerda, evidência à direita;
- listas e tabelas mantêm cabeçalho fixo; ações em lote ficam em barra contextual.

### Tablet 768–1199 px

- grid de 8 colunas, gutter 20 px, margens 24 px;
- sidebar recolhida por padrão;
- painel contextual vira drawer de até 60% da largura;
- comparações podem empilhar, preservando alternância candidato/evidência.

### Mobile < 768 px

- grid de 4 colunas, gutter 16 px, margens 16 px;
- navegação global em sheet; navegação do projeto em seletor;
- tabelas viram listas de cards com os três campos decisivos visíveis;
- painel lateral vira rota ou bottom sheet;
- ações primária e secundária ficam em barra inferior segura;
- nenhuma revisão crítica exige hover, arrastar ou largura desktop.

Breakpoints são guias; componentes devem responder ao próprio contêiner quando possível.

---

## 4. Componentes e iconografia

### Componentes essenciais

- **Panel:** superfície de trabalho, raio `--radius-lg`, profundidade `--elev-panel`.
- **Card:** objeto elevado, raio `--radius-md`, profundidade `--elev-card`.
- **Button:** primário e aprovar em Mark; secundário com borda e profundidade; ghost sem sombra; destrutivo em Refuse. Altura única de 40 px, o mesmo do seletor de modelo. Ações da mesma barra alinham pelo centro, com 8 px entre elas. Não se encolhe um botão para caber num cabeçalho.
- **Totais de um artigo:** número grande e uma barra de composição por nó. O texto extraído não entra nesse resumo.
- **Sample card:** Card com faixa esquerda — Mark (positivo/aprovado), Review (caso de borda/pendente), Refuse (negativo/rejeitado). Citações usam Origin.
- **Status badge:** ícone + texto + superfície semântica; nunca só ponto colorido.
- **Evidence chip:** arquivo, posição e link; expande sem perder contexto.
- **Lineage trail:** sequência navegável com tipo, versão e estado.
- **Review card:** conteúdo, origem, diferenças, decisão e nota.
- **Metric card:** número, denominador, período e explicação; sem “score” órfão.
- **Command/search:** acesso por teclado, resultados agrupados por projeto e entidade.
- **Toast:** confirmação transitória apenas quando a mudança também fica visível na tela.

### Ícones

- Lucide é a direção de biblioteca, sujeita a registro da licença e versão;
- 20 px padrão, stroke 1.75 px; 16 px em metadados, 24 px em navegação;
- usar metáforas literais: arquivo, filtro, versão, comparar, publicar, reverter;
- reservar estrela/constelação para relações e descoberta, não para “IA” genérica;
- ícone sem label apenas quando universal e com nome acessível;
- o monograma `ai` não substitui ícones de ação.

### Motivos

- **Fio:** linha de 1 px, sólida para derivação confirmada, tracejada para proposta.
- **Nó:** círculo de 6 px; forma interna indica tipo, não cor isolada.
- **Camada:** deslocamento de 4 px entre planos; no máximo três planos visíveis.
- **Constelação:** somente em visão relacional, com lista textual equivalente.

---

## 5. Movimento

Tokens:

```css
--duration-instant: 80ms;
--duration-fast: 140ms;
--duration-base: 220ms;
--duration-slow: 360ms;
--ease-standard: cubic-bezier(.2, 0, 0, 1);
--ease-exit: cubic-bezier(.4, 0, 1, 1);
```

Regras:

- fade/slide de 4–8 px para entrada de painéis;
- lineage pode desenhar um fio uma vez para explicar a nova relação;
- progresso indeterminado usa pulso sutil, não shimmer em texto longo;
- streaming não faz cada token saltar;
- nenhuma animação essencial dura mais de 500 ms;
- respeitar `prefers-reduced-motion`: remover transformações, desenho de fios e loops; preservar mudança instantânea de estado;
- nunca usar movimento como único sinal de atualização.

---

## 6. Acessibilidade

Meta: WCAG 2.2 AA em todos os fluxos; AAA para corpo quando viável.

- contraste mínimo 4,5:1 em texto comum, 3:1 em texto grande, ícones e limites de componentes;
- foco visível de 2 px com offset de 2 px, nunca removido;
- ordem de tabulação acompanha a leitura; “Pular para conteúdo” é o primeiro link;
- alvo de toque mínimo 44 × 44 px;
- labels persistentes; placeholder não funciona como label;
- erros aparecem no campo, no resumo e em `aria-live` apropriado;
- jobs anunciam marcos, não cada token ou percentual;
- gráficos têm resumo, legenda, valores acessíveis e versão tabular;
- zoom de 200% não perde ação; reflow a 320 CSS px;
- modo escuro é preferência, não inversão automática sem teste.

### Linguagem inclusiva

Não atribuir gênero ao modelo por padrão. Projetos definem seus próprios pronomes no charter. Referências a Amelia respeitam sua identidade de projeto, sem transformar traços culturais ou femininos em regra da plataforma.

---

## 7. Visualização de dados

### Semântica

- **Volume:** barras neutras.
- **Composição:** barras empilhadas com labels diretos; evitar pizza com muitas categorias.
- **Mudança no tempo:** linha; intervalo e lacunas explícitos.
- **Distribuição:** histograma/box plot quando amostra suficiente.
- **Linhagem:** DAG focado, com lista alternativa.
- **Qualidade:** nunca reduzir a um único número; mostrar dimensão, amostra e incerteza.

Paleta categórica inicial, a validar em simuladores de daltonismo:

`#3264A8`, `#A65E2E`, `#617A3D`, `#8058A5`, `#A64D79`, `#3D7E78`.

Regras:

- verde/vermelho ficam reservados a sucesso/erro, não a séries;
- padrões (`solid`, `dash`, `dot`) complementam cor;
- eixos começam em zero para barras; truncamento de linha é sinalizado;
- tooltip nunca é o único acesso aos valores;
- “60% positivos / 15% borda / 25% negativos” é alvo configurável de balanceamento, não pontuação de qualidade;
- toda métrica informa conjunto, período, `n` e definição.

---

## 8. Temas de projeto

Projetos recebem um único `project-accent` que:

- aparece em avatar, foco contextual e visualizações do próprio projeto;
- deve atingir 3:1 em elementos não textuais e 4,5:1 quando sustenta texto;
- nunca substitui cores de status;
- possui par claro/escuro aprovado.

Exemplos:

- **Amelia:** pulso `conscious` (`#10b981`) — o projeto histórico permanece na camada de presença.
- **Atlas Atendimento:** pulso `memory` (`#06b6d4`) — o corpus corporativo se distingue pela evidência, não por uma cor inventada.

Não há “tema feminino” ou “tema corporativo”; o contraste entre projetos vem de charter, imagem e acento controlado.

---

## 9. Assets e follow-ups

- redesenhar o favicon `ai` em SVG e comparar opticamente com o PNG histórico;
- confirmar licença, arquivos, subsets e direitos de redistribuição de Archivo, Instrument Serif, JetBrains Mono e Lucide;
- não copiar fontes do Amelia 3 até concluir essa verificação;
- produzir favicons 16/32 px, mask icon, app icon e lockups responsivos;
- testar fallback sem webfont e evitar layout shift com métricas compatíveis;
- registrar autoria e licença de qualquer textura, fotografia ou ilustração futura.

---

## 10. Critérios de aceitação

- [ ] tokens claro/escuro estão implementados por papel semântico, sem hex disperso nos componentes;
- [ ] contraste e foco passam auditoria automatizada e revisão manual;
- [ ] Archivo + serif editorial distinguem função e narrativa sem depender de asset não verificado;
- [ ] layouts funcionam a 320, 768, 1024 e 1440 px, e com zoom de 200%;
- [ ] todos os estados por cor também têm texto/ícone/forma;
- [ ] visualizações têm alternativa textual ou tabular e não usam verde/vermelho como categorias;
- [ ] `prefers-reduced-motion` remove animações não essenciais;
- [ ] monograma vetorial continua legível a 16 px e em uma cor;
- [ ] Amelia e Atlas usam a mesma biblioteca, diferenciados só por conteúdo e acento de projeto;
- [ ] inventário de licenças está aprovado antes do primeiro release distribuível.
