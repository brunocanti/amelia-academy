# ADR 018: O treino usa mlx-lm atrás de um worker nosso, sem interface de terceiros

- **Status:** Implementada para treino direct e comparação, 7 nov. 2026. Verificações e limites na Especificação 015, seção 14.
- **Escopo:** Motor de treino, processo de treino, interface de treino
- **Relacionadas:** ADR 003 (subprocesso supervisado com JSONL), ADR 004 (conversa canônica sem template de fornecedor), Especificações 006, 014, 015

## Contexto

A Amelia 3 tinha treino funcionando, com cerca de 13 mil linhas de interface em Svelte e um executor em Python. Aquilo que funcionou: subprocesso com `mlx_lm lora`, progresso por iteração, adapter como saída, dataset e treino em telas separadas.

O que não deve voltar, visto no código dela: `--num-layers` recebendo `lora_rank`; progresso lido do stdout com expressões regulares; `final_loss = 0.1` como padrão, um número inventado; validação desligada no Gemma para fugir de NaN; uma cópia inteira do modelo base por execução (1,1 GB de modelo para 1,3 MB de adapter).

Procuramos o que existe hoje. **Não existe um componente React de fine-tuning para embutir.** Existem aplicativos inteiros:

| Ferramenta | O que é | Por que não embutir |
|---|---|---|
| M-Courtyard | Tauri + React + mlx-lm, AGPL-3.0 | Aplicativo inteiro, com curadoria própria. A licença contaminaria a Amelia |
| Unsloth Studio | Interface web, interface em AGPL, núcleo Apache | Cria o dataset por conta própria; sem embutimento documentado; há relatos divergentes sobre Mac |
| MLX LoRA Studio | SwiftUI, MIT | Não é web. Serve de referência para estimativa de memória e arquivo de execuções |
| Transformer Lab | Electron + React, AGPL | Aplicativo inteiro; não achamos atividade de 2026 |
| Trackio | Painel local em Svelte | Só mostra métricas. O que precisamos mostrar cabe numa tela nossa |

O reaproveitável é o motor. A parte React que falta é pequena: um formulário curto e um gráfico de perda.

## Decisão

1. **O motor é `mlx-lm`, em versão fixada,** num ambiente isolado (`app/trainer/.venv`). Ele não entra no ambiente do backend, que continua sem MLX. Atualizar a versão é uma decisão registrada, com a verificação da Especificação 015 repetida.
2. **Nosso código não reescreve o laço de treino.** Um worker pequeno (cerca de 100 linhas) chama `train_model` do mlx-lm com um `TrainingCallback` próprio e emite eventos JSONL, conforme a ADR 003. Chamar `train_model` direto é necessário: `lora.main()` troca o callback pelos de relatório e não aceita um próprio.
3. **Nunca lemos progresso do stdout.** Número que aparece na tela veio de um evento do callback. Sem evento, a tela diz que não sabe.
4. **Guardamos só o adapter,** apontando para a base por repositório e revisão. O modelo base fica no cache do Hugging Face.
5. **Nenhuma interface de terceiros é embutida.** Elas duplicam a curadoria, e várias têm licença AGPL. Servem como referência.
6. **O gráfico é um SVG nosso, sem dependência nova.** Se não der conta do volume ao vivo, o próximo passo é uPlot (MIT, cerca de 50 KB).
7. **Treino não sai da máquina.** A ADR 017 continua valendo para modelos externos, mas ela não se aplica aqui: o treino é local e não passa por CLI de terceiro.

## Consequências

- O mlx-lm muda rápido, e `train_model` não é uma API prometida como estável. Por isso a versão é fixada e o worker é pequeno.
- Treino só em Apple Silicon. Em outra máquina, a tela diz isso em vez de falhar no meio. O motor fica atrás do worker e pode ser trocado depois sem tocar na interface.
- `mlx-lm` não tem parada antecipada nem guarda o estado do otimizador no checkpoint. A Especificação 015 trata disso no próprio produto, e o texto da tela não promete o que o motor não faz.
- Mais tarde, `mlx-lm-lora` (Apache-2.0) pode entrar como segundo motor, para DPO a partir das premissas falsas. Não faz parte desta decisão.
