# Especificação 008 — Avaliações e gates

**Status:** normativa v1.

## Propósito e escopo

Define suites versionadas, execuções reproduzíveis, resultados por caso e gates determinísticos usados para promover releases.

## Entidades e tipos

- `EvaluationSuite`: dimensões, casos, rubric, comparadores e versão.
- `EvaluationRun`: projeto, candidatos, suite, seed, runtime e estado.
- `CaseResult`: saída, métricas, evidência, erro e avaliação humana opcional.
- `Gate`: predicado versionado, severidade, conjunto, limiar e política de ausência.
- `GateResult`: `pass|fail|blocked`, observações, denominador e hashes de entrada.

## Máquina de estados

Run: `queued → running → completed|failed|cancelled`.
Gate: `pending → pass|fail|blocked`. Resultado terminal é imutável; recalcular cria nova execução.

## Invariantes

1. Resultado DEVE mostrar conjunto, período/versão, `n`, denominador e definição.
2. Média agregada NÃO pode ocultar regressão de gate crítico ou caso individual.
3. Gate obrigatório ausente resulta `blocked`, nunca `pass`.
4. Suite, model release candidate, runtime, template e seeds são fixados por versão/hash.
5. Avaliação humana registra ator e, quando possível, é cega.
6. Reasoning bruto não é evidência pública.
7. Release só é publishable se todos os gates obrigatórios passarem.

## API e eventos

- `POST /evaluation-runs`, `GET /evaluation-runs/{id}`.
- `POST /evaluation-runs/{id}:cancel`, `GET /evaluation-runs/{id}/gate-results`.
- Eventos: `evaluation.started`, `case.completed`, `gate.evaluated`, `evaluation.completed`.

## Autorização e privacidade

Casos privados permanecem no projeto; exports omitem prompts sensíveis por padrão. Avaliadores humanos recebem apenas escopo necessário. Modelos-juízes não podem aprovar publicação; apenas produzem sinais para gates definidos.

## Semântica de falha

Caso não executado conta como ausente, não como zero silencioso. Falha parcial pode concluir run somente se a suite declarar tolerância e o gate considerar cobertura. Hash ou template divergente invalida o run. Cancelamento nunca produz gate aprovado.

## Testes de aceitação

1. Regressão crítica bloqueia release apesar de média global maior.
2. Gate sem casos retorna `blocked`.
3. Reexecução com mesmas entradas preserva identidade de inputs e registra nova run.
4. Resultado exibe contagem e denominador.
5. Release com run de outro projeto ou outro hash é rejeitado.

## Fora de escopo

Escolha definitiva de modelo, validade científica universal, benchmark público como certificado e autoaprovação por LLM.
