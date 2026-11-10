# 021 — Versões de treino

## Problema

Cada treino já fica salvo (`train_runs` + pasta com os adapters), mas a pessoa só vê uma lista técnica ("mlx-community/Qwen3-4B-4bit · finished · data"). Quem treina mais de uma vez não sabe qual versão está testando, o que mudou entre elas, qual é a melhor, nem como apagar as que não quer.

## O que a pessoa vê

Cada treino terminado vira uma **versão**: "Version 1", "Version 2"… numeradas por projeto, na ordem em que começaram. A pessoa pode renomear (ex.: "Version 2 · more examples").

No passo **Teach** (spec 020 §8), o seletor "Training history" dá lugar a uma lista curta **"Your versions"**, a mais nova em cima. Cada linha mostra:

- nome + modelo base curto ("Qwen3 4B");
- quando foi treinada;
- o que aprendeu, numa frase: "917 examples · 204 approved pairs · answers by Qwen3 4B";
- resultado: "Best check 1.08" e, quando houver comparação respondida, "Better in 5 of 8".
- estado em palavras simples: Training…, Stopped, Failed (com o motivo), Ready.

Uma versão pode ser marcada como **"In use"** (a que a pessoa escolheu como a boa). Só uma por projeto. Por padrão é a última que terminou bem; a pessoa troca com "Use this one".

Abrir uma linha mostra o que já existe hoje (gráfico, Compare, Download), com o título da versão no topo: "Version 2 — Is it better?".

**Compare** mostra sempre qual versão está sendo comparada no topo ("Comparing Version 2 with the original model"). Se houver mais de uma versão pronta, um seletor simples "Compare which version?".

**Mudou algo desde a última versão?** Ao preparar um novo treino, se os pares aprovados ou os exemplos mudaram desde a versão em uso, o passo Teach diz: "{n} pairs changed since Version 2." Assim a pessoa sabe por que treinar de novo.

## Apagar

- Cada versão tem "Delete" num menu discreto (⋯). Apagar remove o registro, eventos, comparações, recall e a pasta com os adapters.
- Clicar é seguro: a versão some da lista e aparece na barra de atividade "Version 2 deleted · Undo" por ~10 s. Só depois desse tempo apaga de verdade (os arquivos). Se o servidor reiniciar nesse meio, a versão continua lá (nada é apagado sem confirmação do tempo).
- Não dá para apagar uma versão que está treinando; primeiro "Stop".
- Apagar a versão "In use" passa o "In use" para a mais nova que ficou pronta.
- Um "Delete all but the one in use" no rodapé da lista, com o mesmo Undo.
- Mostrar o espaço ocupado: "4 versions · 1.2 GB". Ajuda a decidir o que apagar.

## Backend

- `train_runs`: novas colunas `version INTEGER` (número sequencial por projeto, atribuído na criação; migração preenche os existentes por `created_at`), `name TEXT NOT NULL DEFAULT ''`, `in_use INTEGER NOT NULL DEFAULT 0`, `deleting_at TEXT` (marca de apagar pendente).
- O resumo de cada run inclui: `version`, `label` (nome ou "Version N"), `samples`, `pairs`, `answer_model` (do manifesto do dataset), `size_bytes` da pasta, `in_use`, e placar da comparação (`better`, `worse`, `same`, `total`) quando houver escolhas.
- `PATCH /projects/{p}/train/runs/{id}` com `{name?, in_use?}`.
- `DELETE /projects/{p}/train/runs/{id}` marca `deleting_at`; some das listas. `POST .../undo-delete` limpa a marca. Um passo de limpeza (no load da lista e no start do app) apaga de vez o que passou de 10 s. 409 se estiver treinando.
- `DELETE /projects/{p}/train/runs?keep=in_use` para o "apagar todas menos a em uso".
- Datasets exportados automaticamente pelo Teach (spec 020 §7) que só servem a versões apagadas também são apagados.
- `GET /projects/{p}/train/changes` → `{since_version, pairs_changed}` comparando os pares do dataset da versão em uso com os aprovados atuais.

## Regras (CLAUDE.md)

- Sem "run", "adapter", "checkpoint", "dataset id" na tela. É "version".
- Pergunta simples e resposta curta. Toda remoção tem Undo na hora pela barra de atividade (`notify`).
- Nenhuma opção extra: nome é opcional, "In use" já vem escolhido.

## Testes

- Numeração: duas runs no mesmo projeto → 1 e 2; outro projeto começa em 1; migração numera as antigas.
- In use: só uma; apagar a em uso passa para a mais nova pronta.
- Delete + undo antes do prazo mantém tudo; depois do prazo pasta e linhas somem. 409 ao apagar uma em treino.
- Resumo traz samples, pairs, answer_model, size_bytes e placar.
- `train/changes` conta pares novos e mudados.
