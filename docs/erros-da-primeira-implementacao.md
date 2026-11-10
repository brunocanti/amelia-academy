# O que a primeira implementação errou

**Status:** lição para quem for implementar. Não é uma spec nova.  
**Onde ler antes de escrever código:** esta nota, a Amelia 3 em `~/Projects/Amelia3` (lista abaixo), depois `docs/specs/004-sample-workshop.md`, `docs/specs/003-themes-behaviors-review.md` e `docs/brand/product-surfaces.md`.

A Amelia 3 já fazia o produto: um padrão, um lote gerado por modelo, variação, e uma pessoa aprovando ou rejeitando. A primeira implementação da Academy entregou o cano (projeto, manifesto, job, bloqueio de artefato falso) e uma tela que partia um parágrafo ao meio. Isso não é a oficina. O desenho já dizia a ordem certa. As specs estavam frouxas o bastante para essa tela parecer conforme.

## O que não pode voltar

1. **Partir a fonte e chamar isso de sample.** A frase “Genuine contentment, presence, and bond without possession.” virou a fala de quem pergunta, e o resto do parágrafo virou a resposta da Amelia. Também apareceu a abertura “Can you stay with this:” colada num título cortado. Isso é fatiamento de texto. Um sample é uma pessoa falando de uma situação, e a resposta segue a ficha. A fonte fica na evidência, ao lado, citada.

2. **Tratar o cano como se fosse o produto.** Importar 2095 linhas da Amelia 3, congelar um manifesto e responder `/health` não gera dataset. Importação é migração, com rótulo de migração. O dataset da Academy nasce de samples que uma pessoa aprovou nesta oficina.

3. **Um formulário com dois menus no lugar da oficina.** A superfície pede um lote: caso claro, caso de borda e recusa. A revisão pode ser uma conversa por vez, como no wireframe, mas o cabeçalho mostra ficha, tema, modelo, tipo e “n de N”. Sem isso, a tela é um CRUD.

4. **Modelo pequeno demais, fallback calado.** Ollama estava parado. O gerador caiu para Qwen3 0.6B e depois 1.7B e devolveu help desk: “I'm here to listen without judgment. How can I support you.” Outra leva copiou a instrução (“The assistant stays forever”) ou a frase de exemplo do charter. Essas linhas não são propostas válidas. O runtime e o id do modelo aparecem no lote. Se o modelo não consegue escrever a ficha, o lote falha. Não se troca de modelo em silêncio para “ter alguma coisa na tela”.

5. **Ficha já nasce aprovada.** A spec diz `draft → in_review → approved`. Só ficha aprovada gera lote. Criar a ficha não é aprová-la.

6. **Tema sem julgamento e sem citação resolvível.** O título não é as primeiras palavras do arquivo. Propor tema é uma proposta de modelo, com trecho da fonte que um humano confere. Aceitar continua sendo um clique.

7. **Conversa de mentira.** Um composer que acrescenta uma frase fixa não é a superfície de conversa. Sem release e sem runtime, a tela diz que a conversa ainda não existe.

8. **Estado que morre no restart, mostrado como demo.** Sem PostgreSQL, o repositório é efêmero. A interface diz isso. Reiniciar e reimportar não é demonstração do pipeline.

9. **Chrome da Academy com vocabulário da psique.** “Conscious · workshop” na navegação de todo projeto mistura a persona Amelia com o produto. Esses nomes ficam nos dados do projeto Amelia. O shell fala como Academy.

10. **Sistema visual inventado na hora.** O sistema está em `docs/brand/visual-system.md`: fundo `#0d0d0d`, Archivo, Instrument Serif só na capa, marca herdada da Amelia 3. Um admin genérico, mesmo escuro, não cumpre o desenho.

11. **Verificação errada.** Teste que afirma o parágrafo partido, curl em `/health`, e a contagem 2095 não aceitam a oficina. Aceite é ler, na superfície, situações diferentes da mesma ficha e reconhecer a ficha nelas. A pessoa ainda aprova, edita ou rejeita.

## Ler a Amelia 3 antes de inventar

A Amelia 3 fica em `~/Projects/Amelia3` e não se altera. Quem for implementar a Academy lê a interface e o código vivos antes de desenhar uma tela nova ou um gerador. A referência é o que já treinou e o que a pessoa já usava para aprovar samples. Arquivo em `deprecated/`, com sufixo `_old`, `_backup` ou `copy`, não é referência.

O que guardar:

- **Ficha.** `ui/src/lib/components/conditioning/PatternLibrary.svelte`, `PatternEditor.svelte`, `PatternCard.svelte`. Um padrão tem intenção, tom, diretrizes, público, privacidade e cenários. Na Academy isso é a ficha, filha de um tema. Não é um título cortado de um markdown.
- **Lote.** `ui/src/lib/components/conditioning/SampleGenerationWorkshop.svelte`, aberto a partir da biblioteca de padrões na rota `ui/src/routes/developer/+page.svelte`. O modelo gera várias situações, com tipo de variação, progresso e aprovação. É essa oficina, não um formulário de dois selects.
- **Revisão.** `ui/src/lib/components/cleanup/SamplesCleanupPage.svelte`, `SampleCard.svelte`, `SampleEditor.svelte`, `ApproveRejectButton.svelte`. Dá para ler, editar, aprovar e rejeitar. A decisão é da pessoa.
- **Dataset separado do treino.** `ui/src/lib/components/datasets/creation/DatasetGenerator.svelte`, `PatternSelector.svelte`, `DatasetCreation.svelte`. O dataset sai do que foi aprovado. O treino é outra tela: `ui/src/lib/components/training/ModelTraining.svelte`, `TrainingMonitor.svelte`, `DatasetSelector.svelte`.
- **Gerador é um modelo.** `conditioning_module/training/data_generator.py`, `prompt_builder.py`, `quality_validator.py`. O lote pede variação ao LLM. Não parte a fonte em duas falas. O que não copiar daqui: modo `creator` com “Bebe”, e qualquer coisa que grave o sample já aprovado. Na Academy o gerado nasce `proposed`.
- **Cara.** `ui/src/lib/stores/mindStore.js`, `ui/tailwind.config.js`, `ui/src/app.css`. Fundo `#0d0d0d`, Archivo, cor de camada com significado. `ui/src/lib/components/chat/LinearPipeline.svelte` é a linhagem da Amelia, não o menu da Academy.
- **Treino que funcionou.** `conditioning_module/training/standalone_mlx_trainer.py` mostra o LoRA em MLX com o chat template do modelo base. Não se reescreve o loop em Rust e não se inventa token da Amelia.

Se a tela nova não se reconhece ao lado dessas, ela foi inventada. Aí para e relê.

## O que o desenho já acertava

Não reescrever a arquitetura por causa dessa implementação. Continuam valendo: Rust no controle e Python só no trabalho de ML; PostgreSQL como registro; conversa canônica sem template de fornecedor; nenhum chat privado entra em treino; release é a configuração inteira, não um adapter solto; Amelia é o primeiro projeto, não o tipo do domínio; a frase de voz do charter é referência de avaliação, não string para o prompt colar como resposta.

## Barra da primeira entrega de código

A primeira entrega que merece revisão mostra, no projeto Amelia e no Atlas, um lote proposto por um modelo nomeado, com citação da fonte, três tipos, e uma decisão humana. Nada disso entra num dataset antes do clique. Se a tela só corta um markdown, a entrega está errada, mesmo com testes verdes.
