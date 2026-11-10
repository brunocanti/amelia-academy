# Amelia Academy — fatia que roda

O desenho desta fatia está em `docs/architecture/estado-atual.md`. Stack: Python/FastAPI + SQLite + React (Vite). Rust e PostgreSQL continuam o alvo, por troca gradual (`docs/adr/001`, `docs/architecture/system-design.md`).

Fluxo na interface: criar o projeto (um dataset por assunto, com máximo de temas) → subir arquivo (cada passagem dá três grupos: Known, False premise, Not known) → rodar o Challenge, opcional, que aponta o que não se sustenta → curar pares por tema e pilar, na lista ou no grafo → exportar dataset JSONL, memória (`memory.jsonl`) e wiki OKF. Comportamento é opcional: uma ficha aprovada escreve conversas que entram na mesma curadoria.

## Rodar

```
# modelo local
ollama serve            # e ollama pull qwen3:14b, se ainda não tiver

# backend
cd app/backend && python3 -m venv .venv && ./.venv/bin/pip install fastapi uvicorn httpx pytest
./.venv/bin/uvicorn amelia_academy.api:app --port 8000

# UI
cd app/ui && npm install && npm run dev     # http://localhost:5173, proxy /api → 8000
```

## Testes

```
cd app/backend && PYTHONPATH=. ./.venv/bin/pytest -q
```

Os testes ao vivo usam o modelo real. Se o Ollama não estiver de pé, eles aparecem como `skipped` com o motivo; isso não é aprovação.

## Regras que não podem ser contornadas

- Par gerado nasce `proposed`; só clique humano muda o status. Editar o texto devolve a `proposed`.
- Par de arquivo cita um trecho verbatim da passagem. Sem citação válida, é descartado e contado.
- Um arquivo só usa temas da lista fechada ou `Outros`, dentro do máximo do projeto.
- Ficha de comportamento só gera conversa depois de aprovada.
- Falha de modelo fica visível; não há troca silenciosa.
- O Challenge só compara e abre conflitos; quem resolve é a pessoa.
- Dataset exporta só pares `approved`.

## Modelos

- `AMELIA_ACADEMY_MODEL` (padrão `qwen3:14b`), sempre com saída estruturada (schema). A interface lista os modelos instalados no Ollama e guarda uma escolha só.
- Modelos online rodam pelo CLI da ferramenta (`claude`, `codex`, `agy`), já instalado e logado, nunca por API direta (ADR 017). Sem CLI instalado, nada aparece; com CLI sem login, a interface diz o que rodar. O padrão continua local.
- Figuras usam o modelo escolhido, e só quando ele vê imagens: no Ollama, quando ele marca o modelo com visão; online, Claude e Codex veem e Antigravity não.

## Projetos

Tudo vive dentro de um projeto (`/projects/{project_id}/...`); não existe rota sem escopo. Um projeto tem idioma de conteúdo, máximo de temas e status (`active` ou `archived`).

- Acesso a uma entidade de outro projeto responde 404.
- Projeto arquivado continua legível e recusa qualquer escrita (409).
- O banco fica em `app/var/academy.sqlite3`.
