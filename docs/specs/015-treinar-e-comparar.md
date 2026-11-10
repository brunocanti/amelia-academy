# Especificação 015 — Treinar e comparar

**Status:** construída para treino direct local, 7 nov. 2026. Train, comparação cega, perguntas de aprendizado revisáveis e coordenação da GPU implementados. Reasoned e métricas automáticas de acerto ainda não implementados; ver seção 14.  
**Relacionadas:** ADR 003, ADR 004, ADR 018, Especificações 005, 006, 007, 008, 013, 014.

## 1. Propósito e escopo

A pessoa escolhe um modelo, clica em treinar, acompanha, e depois vê com as próprias perguntas se o modelo melhorou. Primeira versão: LoRA local em Apple Silicon, com um treino por vez. Por pedido da pessoa, os testes e a lista inicial ficam limitados a modelos da classe de até 4B: somente Qwen3 4B em 4 bits, revisão fixada já baixada. Gemma E4B fica fora desse limite, porque o nome não assegura até 4B parâmetros totais. Não há download nem troca de base automática.

O produto precisa responder com honestidade: **melhorou?** Pode ser que não. Datasets pequenos podem não vencer o modelo base (arXiv 2504.04569), e LoRA pode enfraquecer recusas. Por isso a comparação faz parte da mesma entrega que o treino.

## 2. Verificação antes de construir

Executado em 7 nov. 2026, nesta máquina (36 GB), com `mlx-lm` 0.32.2, `mlx` 0.32.4, `transformers` 5.22.2 e Ollama 0.40.14. Bases: `mlx-community/Qwen3-4B-4bit` (revisão `4dcb3d10`) e `mlx-community/gemma-4-e4b-it-4bit` (revisão `475b9088`). Dados: um arquivo temporário com pares propostos do Raguero, com mensagem de sistema, que não é dataset. Os treinos foram curtos (15 e 40 iterações): isto prova que o caminho funciona, não que o modelo melhora.

| Pergunta | Resultado |
|---|---|
| LoRA em Gemma 4 roda sem NaN, com validação ligada? | **Sim.** E4B: perda de validação de 4,54 para 2,29 em 40 iterações, sem NaN |
| LoRA em um Qwen pequeno roda? | **Sim.** Perda de validação de 4,93 para 2,08 em 40 iterações |
| `--mask-prompt` funciona com a mensagem de sistema? | **Sim.** A máscara termina exatamente no início da vez do modelo, nos dois |
| O template do Gemma 4 precisa do canal vazio de pensamento? | **Não para treinar, mas os templates diferem.** Ver abaixo |
| O adapter carrega e responde? | **Sim, nos dois,** e a resposta difere da base |
| O modelo fundido (`fuse`) abre de novo? Importa no Ollama? | **Não serve como saída na v1.** Ver abaixo |
| Quanto ocupa de memória, com lote 4 e 16 camadas? | **Qwen 3,7 GB, Gemma E4B 6,4 GB** em 15 iterações, com `grad_checkpoint`. Lote 4 pode ficar como padrão nestes modelos. Medido com `qwen3:14b` (13 GB) carregado no Ollama |

**Pensamento.** O Qwen renderiza `<think>\n\n</think>` vazio na resposta de treino, e isso entra na perda. O Gemma coloca `<|think|>` na mensagem de sistema e a resposta de treino vai sem canal de pensamento. Nos dois, a base pensa antes de responder e o adapter passa a responder direto: **nestes exemplos o adapter respondeu diretamente; isso não demonstra perda geral da capacidade de raciocinar.** O teste não usou justificativas editoriais aprovadas nem validou treino reasoned. A spec 016 exige um teste novo para esse perfil. A comparação precisa rodar base e adapter no mesmo modo.

**Fundir.** Neste teste curto, as respostas após `fuse` em 4 bits não preservaram o comportamento observado com o adapter: no Qwen, a saída do fundido é idêntica à da base, e no Gemma fica quase igual à base e bem diferente do adapter. O motivo mais provável é a reamostragem para 4 bits apagar uma diferença pequena; com treino mais longo o efeito pode mudar, e isso não foi medido. Com `--dequantize`, o Qwen (7,5 GB) responde igual ao adapter; o Gemma (14 GB) estourou a memória da GPU ao abrir com o Ollama ocupando 13 GB.

**Ollama.** A importação aceita os fundidos, mas rodar falha: Qwen com "Invalid quantization mode ''" (funciona ao acrescentar `mode: affine` ao config, mas nesse caso carrega o fundido em 4 bits, que perdeu o treino) e Gemma com "layer 24: missing attention k projection". Os modelos `gemma4` que já estão no Ollama também não carregam no `mlx-lm`: usam NVFP4 com `global_scale`, sem suporte na versão fixada.

**Decisão que sai disto:** na v1, a saída é o adapter em zip e a comparação usa `mlx_lm.load(path, adapter_path=...)`. Fundir e levar ao Ollama fica fora, até um novo teste.

**Dados:** em 7 nov. 2026, o Comprimildo tem 198 pares aprovados, e o Raguero, 0. O Comprimildo já pode alimentar um treino real, depois da Especificação 014.

## 2.1. Extensão para direct e reasoned (spec 016)

A verificação acima cobre somente direct. Reasoned precisa de artifact de justificativas aprovadas, manifesto/model-spec versionados e renderer testado para a base escolhida. O preflight bloqueia reasoned sem esses itens; verifica ida e volta dos canais, tokenização e loss na justificativa editorial e na resposta final. Direct mantém loss somente na resposta final. Registrar perfil, hashes, política de máscara e modo de geração na execução.

Comparar os perfis na interseção idêntica de pares e splits, além da comparação de cada perfil com sua base. Medir acerto, limites, premissas falsas, vizinhos, consistência da justificativa, tokens e latência. Confiança da curadoria estratifica os resultados e não é peso automático de treino nem confiança de runtime. Nenhum ganho é presumido por haver justificativa mais longa.

## 3. Entidades

**`train_runs`:** `id`, `project_id`, `dataset_id`, `canonical_sha256`, `rendered_sha256` (train e valid), `base_repo`, `base_revision`, `engine_version`, `config` (JSON com tudo, inclusive semente), `identity_sha256`, `status`, `best_iteration`, `best_val_loss`, `error`, datas.

**`train_events`:** `run_id`, `seq`, `type`, `payload`, `at`. Os tipos seguem a Especificação 006: `accepted`, `progress`, `log`, `checkpoint`, `artifact`, `result`, `error`, `cancelled`.

**`compare_sets` e `compare_answers`:** conjuntos de perguntas de uma execução, com as respostas do modelo base e do adapter, os sinais e a escolha da pessoa.

**No disco:** `app/var/runs/<id>/`, com `run.yaml`, os adapters, `adapter_config.json`, e o comando exato. Nunca há cópia do modelo base.

## 4. Máquina de estados

```
preparing → training → finished
preparing → failed
training  → failed | stopped
stopped   → training   (Continue)
```

- **Stop:** SIGTERM; depois os prazos da Especificação 006 (10 s, SIGTERM, 5 s, SIGKILL). O último checkpoint fica disponível.
- **Continue:** retoma do adapter e roda só os passos que faltam, contando a partir do último passo salvo. O otimizador recomeça, e a tela diz isso.
- Ao reiniciar o backend, execução sem processo vivo vira `failed`, com a mensagem "Stopped when the app closed", e os checkpoints continuam utilizáveis.

## 5. O treino

**Execução.** O backend lança o worker pelo `runs.py`, como as outras tarefas longas, com `app/trainer/.venv`. Um processo por execução. `runs.py` hoje só conhece trabalho em thread, com parada cooperativa; a thread passa a supervisionar o subprocesso, e o Stop precisa chegar até ele. O callback transforma `on_train_loss_report` e `on_val_loss_report` em eventos.

**Antes de começar (preflight, feito com o tokenizer da base):**

1. renderiza com o template do modelo e conta os tokens de cada par;
2. avisa se algum par passa de `max_seq_length`, porque o mlx-lm corta sem falhar: "2 pairs are too long and would be cut.";
3. recusa se houver menos pares que o tamanho do lote;
4. recusa se não houver `training-manifest.json` v2 com `split_policy` (Especificação 014, seção 12);
5. confere a memória livre e a arquitetura;
6. reserva a GPU antes de iniciar o trabalho: chamadas locais já em andamento terminam, novas chamadas ficam aguardando com Stop disponível;
7. consulta `/api/ps`, descarrega cada modelo com `keep_alive: 0` e confere que a lista ficou vazia antes de carregar a base MLX. O serviço Ollama continua de pé. Nunca matar o daemon nem recarregar um modelo grande ao acabar;
8. sucesso, falha ou Stop encerram o subprocesso antes de liberar a reserva. A próxima geração de dataset carrega sob demanda o modelo escolhido no Ollama. Comparação e preparação de paráfrases usam a mesma reserva. Toda chamada local passa pelo mesmo controle; programas externos não são controlados por essa reserva da Academy.

**Padrões.** São ponto de partida, **não medidos**, e a seção 2 pode mudá-los: LoRA, rank 8, scale 20, 16 camadas, lote 4, taxa 1e-5, `mask_prompt` ligado, cerca de 3 épocas (`iters = ceil(3n / lote)`), semente fixa e registrada.

**Avaliação na validação.** `steps_per_eval` é igual a `save_every`, para cada checkpoint ter uma perda de validação. O **melhor checkpoint** é o de menor perda de validação, e é ele que segue para a comparação. O motor não tem parada antecipada; a v1 também não, mas a tela diz quando a validação está piorando e oferece Stop.

**Falhas nunca viram número.** NaN, memória esgotada ou processo morto levam a `failed`, com a causa em palavras simples. Não existe valor padrão para perda.

## 6. A comparação

Divisão por passagem tem uma consequência: os pares Conhecidos do teste vêm de passagens que o modelo nunca viu. Esse conjunto mede alucinação sobre material novo, **não aprendizado**. Medir só com ele diria que o treino nunca funciona. Por isso, são três conjuntos, sempre comparados com a base, com as mesmas perguntas, temperatura 0 e mesmas configurações:

| Conjunto | De onde vem | O que responde |
|---|---|---|
| **Aprendeu?** | Paráfrases de pares do treino, rascunhadas pelo modelo e revisadas pela pessoa | O modelo sabe o que foi ensinado, em outras palavras? |
| **Sabe parar?** | Split `test`, por tipo | Inventa sobre o que não viu? Recusa quando não há resposta? Corrige premissa falsa? |
| **Continua bem?** | Conjunto pequeno e fixo de conhecimento geral, no idioma do projeto | O treino estragou o que ele já sabia (Especificação 013)? |

**Números, cada um separado, sempre com n e denominador (Especificação 008):**

- taxa de resposta;
- acerto quando responde;
- recusa correta quando não há resposta;
- recusa indevida quando há resposta.

A perplexidade do `--test` aparece só como detalhe técnico, nunca como nota. Não há nota única. Julgamento por modelo é apenas um sinal; quem decide é a pessoa. Conjunto ausente fica como "not measured", nunca como aprovado.

**Comparação cega.** Duas respostas lado a lado, em ordem sorteada e sem dizer de quem é cada uma: "Which one is better?", com `This one`, `Same`, `Both wrong`. Toda escolha pode ser desfeita na hora. Revela-se quem é quem só ao fim.

**Try it.** Um chat lado a lado, base e treinado, com a pergunta que a pessoa quiser. Pelo worker com `mlx_lm.load`, e nunca pelo `mlx_lm.server`, que o próprio projeto não recomenda em produção.

**Decisão em aberto: treinar com tudo.** Depois de escolher uma configuração, oferecer "Train with everything" usa também os pares de validação e teste. A execução final fica marcada: "Measured on run X, not on itself."

## 7. Interface

Menu: Files, Curate, Behaviors, Export, **Train**, **Compare**. Antes de exportar, Train diz o que falta e leva até lá.

**Train, parado.** Uma pergunta: "Which model should learn this?", com os modelos que cabem nesta máquina, e o botão **Start training**. Abaixo, em uma linha: quantos pares, tempo estimado (só depois de medido), e o que não dá para fazer enquanto treina. "More settings" fica fechado, com poucos números: épocas, lote, taxa. Mudar qualquer um mostra o padrão ao lado. O arquivo `run.yaml` e o comando exato ficam disponíveis para baixar.

**Train, rodando.** Gráfico da perda de treino e validação, sem as palavras "loss" ou "iteration" como rótulo principal: "How far off it still is", com legenda "Practice" e "Check". Abaixo: progresso, tempo restante, memória usada, **Stop**. O termo técnico aparece no tooltip.

**Train, terminado.** "Training finished. Is it better?", com o botão **Compare**. Se falhou: a causa e o que fazer.

**Compare.** Abre com a escolha cega; os números vêm depois, para não influenciar. "Try it" fica ao lado.

**Campo de texto da pessoa.** Editar uma paráfrase de "Aprendeu?" tem expansor, como todo texto escrito por pessoa.

**Saída da v1.** "Download your model" gera um zip com adapter, configuração e cartão: base e revisão, dataset e hash, números, e o que não foi medido. Nenhum caminho da máquina vai no zip: a configuração e o `adapter_config.json` saem sem caminhos absolutos, e a base é nomeada pelo repositório. O adapter sozinho não é uma publicação (Especificação 007). Publicar fica para depois.

## 8. Invariantes

1. Toda execução aponta para um `canonical_sha256`, um `rendered_sha256`, uma revisão da base, uma versão do motor, uma configuração e uma semente.
2. Nenhuma execução grava cópia do modelo base.
3. Nenhum número na tela existe sem evento ou medição correspondente.
4. A perda de validação decide o checkpoint. O conjunto de teste nunca decide nada durante o treino.
5. Base e adapter respondem às mesmas perguntas, com as mesmas configurações.
6. Rodar novamente com a mesma entrada é uma execução nova, e o resultado pode variar. A tela não promete reprodução exata.
7. Texto de fonte continua sendo dado, nunca instrução.

## 9. API e eventos

- `GET /projects/{id}/train/models`: modelos que cabem, com o motivo dos que não cabem.
- `POST /projects/{id}/train/preflight`: resultado do preflight, sem efeito colateral.
- `POST /projects/{id}/train/runs`, `GET .../runs`, `GET .../runs/{run}`.
- `GET .../runs/{run}/events?after=<seq>`: leitura de eventos, nova. A lista de execuções de `runs.py` não guarda histórico, e o gráfico precisa dele.
- `POST .../runs/{run}/stop`, `POST .../runs/{run}/continue`.
- `GET .../runs/{run}/download`: o zip.
- `POST .../runs/{run}/compare`, `POST .../compare/{item}/choice`, `DELETE` da escolha para desfazer.
- `POST .../runs/{run}/try`: uma pergunta, duas respostas.

## 10. Privacidade

Treino e comparação rodam na máquina. Nada sai dela. Rascunhar as paráfrases usa o modelo escolhido pela pessoa; se for externo, vale o aviso da ADR 017. O download da base vai ao Hugging Face; a tela mostra o tamanho e pergunta antes. Modelos que exigem aceite de licença mandam a pessoa aceitar no site: a Amelia não aceita por ela.

## 11. Semântica de falha

| Situação | O que a pessoa vê |
|---|---|
| Sem Apple Silicon | "Training needs a Mac with Apple silicon." |
| Base não baixada | Tamanho e botão de baixar; progresso; pode cancelar |
| Licença não aceita | Link para aceitar, e o que falta |
| Memória esgotada | "It ran out of memory at step N." Sugere lote menor |
| NaN | "Training went wrong at step N and stopped." Mantém o último checkpoint válido |
| Processo morreu | Última linha do erro, em detalhe recolhido |
| Validação piorando | Aviso no gráfico, sem parar sozinho |
| Dataset alterado depois | A execução continua apontando para o hash antigo, e a tela diz que há um dataset mais novo |
| Nenhuma melhora medida | "This didn't beat the base model on your questions.", dito sem rodeio |

## 12. Testes de aceitação

**Sem GPU, com um worker falso que emite eventos:**

1. Eventos válidos levam a `finished`, com o melhor checkpoint igual ao menor valor de validação recebido.
2. Worker que morre sem `result` leva a `failed`, sem perda inventada.
3. NaN na perda leva a `failed`, e o checkpoint anterior fica disponível.
4. Stop envia SIGTERM e depois SIGKILL nos prazos.
5. Linha que não é JSON vira `log`, sem derrubar a execução.
6. Preflight recusa dataset menor que o lote, manifesto antigo; avisa sobre par longo demais.
7. Segundo treino com um em andamento é recusado.
8. Backend reiniciado marca a execução órfã como `failed`.
9. Conjunto ausente aparece como "not measured".

**Com o modelo real, em teste marcado como lento:**

10. Treino curto em um modelo pequeno gera adapter que carrega e responde diferente da base.
11. O tamanho da pasta da execução não inclui os pesos da base.

**Com a interface, no navegador:**

12. Alguém que nunca viu a tela sabe o que clicar, do Export ao Compare, sem explicação.
13. A escolha cega não revela quem é quem antes do fim, e toda escolha desfaz.

## 13. Fora de escopo

DPO e ORPO com premissas falsas; QLoRA; fine-tune completo; fila de treinos; treino em outra máquina ou na nuvem; envio ao Hugging Face; publicação (Especificação 007) e a porta de qualidade completa (Especificação 008); busca de hiperparâmetros; Rust e Postgres.

## 14. Entrega e teste integrado (7 nov. 2026)

Implementação: `amelia_academy/training.py` supervisiona `app/trainer/worker.py` pelo Python do ambiente isolado. Usa callbacks do mlx-lm 0.32.2, JSONL, eventos persistidos, dados congelados e hashes conferidos, base/revisão fixas, LoRA rank 8 e camadas independentes. `gpu.py` coordena chamadas locais de geração com treino/comparação; cada reserva tem token próprio, para um finally antigo não liberar a execução seguinte. Nenhum peso base é copiado para a execução.

Amelia 3 foi relida: reaproveitados o subprocesso separado, a configuração por execução e a separação de dataset/treino. Não foram copiados o progresso extraído do texto do terminal, o número de perda padrão fictício, a validação desligada nem a confusão entre rank e número de camadas. O callback atual salva o último adapter para Continue e um adapter best separado no instante exato da menor validação observada; não escolhe pesos de uma etapa posterior à medição.

Na cópia do Comprimildo, export atual com 198 pares aprovados: 159 train, 20 validation, 19 test. Qwen3 4B, 20 passos, lote 4: 15,1 s, pico MLX 3,62 GB, melhor validação 1,9551 na etapa 19. Outro ensaio parou depois do primeiro checkpoint; uma geração pelo Ollama aguardou, voltou com HTTP 200 após Stop, e Continue terminou com melhor validação 1,8958. Adapter em zip: cerca de 27 MB, sem base. Estes números são testes de funcionamento, não prova de melhoria.

O renderer direct força `enable_thinking=False` igualmente no treino e na inferência. O preflight comprova que o prefixo mascarado coincide com o início da sequência completa, e que sobra resposta após o prefixo; nenhuma loss em user/system ou no canal vazio de controle. As opções de template e a máscara são registradas. O detalhe `return_dict=False` é obrigatório na versão fixada do tokenizer.

Compare tem perguntas do teste (limites), duas perguntas gerais fixas no idioma do projeto, perguntas livres (manual) e paráfrases dos pares de treino. O worker rascunha até três paráfrases, sem usar o teste; a pessoa confere o original, edita e escolhe se cada pergunta entra. Duas das três primeiras paráfrases reais vieram em outro idioma e ficaram propostas; o prompt passou a declarar o idioma explicitamente. Isso continua exigindo revisão. As respostas da base e do adapter ficam ocultas em ordem aleatória, com escolha e Undo; identificação só é oferecida depois de todas as escolhas. Eventos públicos não revelam os rótulos de respostas enquanto a comparação é cega.

As taxas de acerto/recusa da seção 6 continuam **not measured**: ainda não há avaliador automático. O produto oferece a leitura e a decisão humana, sem converter perda ou preferência em nota de factualidade. Um conjunto ausente não vira aprovado. Treinar com tudo continua sendo decisão em aberto, não implementada. Não há download de modelos pelo produto nesta entrega: a tela informa quando a base permitida falta no cache.

Reasoned continua bloqueado com explicação visível até verificar renderer e loss próprios (spec 016). Os checkpoints e logs antigos ficam no disco; Continue reinicia o otimizador e a ordem dos lotes, sem prometer reprodução exata; os passos seguem a numeração de onde parou. Recuperação de backend marca execuções órfãs como failed. O controle de GPU é por processo da Academy; rodar vários backends ou usar Ollama por outro app simultaneamente fica fora da coordenação atual.

### Ajustes de 7 nov. 2026, depois do primeiro treino na cópia

- **"I don't know." repetido.** O primeiro treino de 40 passos respondeu "I don't know." até a "17 times 3". A causa estava nos dados: 49 dos 198 pares aprovados tinham exatamente essa resposta, escrita pelo gemma4:12b. A correção está na Especificação 014, seção 12. Depois de reescrever as respostas e exportar de novo, o mesmo treino (40 passos, lote 4, taxa 1e-5) teve melhor validação 1,645 no passo 39 (antes 1,839). Na comparação, o treinado respondeu "17 times 3 is 51." e "Paris", e a recusa que deu nomeou o assunto. Ele ainda inventou detalhe em perguntas de teste; 40 passos não provam ganho de qualidade.
- **Perguntas de teste.** O Compare pega as 6 perguntas de teste alternando entre os tipos de par (lidos em `samples.jsonl`), em vez das 6 primeiras linhas. Assim um "não sei" aprendido demais aparece ao lado de perguntas que têm resposta.
- **Último passo.** O mlx-lm 0.32.2 valida antes de cada passo; o último passo de treino não é validado. O melhor adapter é sempre um que foi medido.

