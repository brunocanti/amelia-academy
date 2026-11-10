# Relações entre pares de QA — desenho de referência

**Status:** referência, nada construído. Não é decisão. O Easy Dataset já foi testado e não será embutido: os pares vêm do próprio Amelia (spec 011). Onde este texto cita o Easy Dataset, leia pares do Amelia.

## Ideia

O Amelia gera os pares. O Curate acrescenta relações tipadas entre eles. O grafo curado serve de conhecimento para um modelo ou de export para fine-tuning.

## Fluxo

1. **Importar** os pares com chave estável: ID do Easy Dataset, se for estável; senão, hash de pergunta + resposta. Editar um par devolve as relações dele para revisão.
2. **Achar candidatos** no mesmo tema e nos outros. A busca só escolhe o que comparar.
3. **Julgar:** o modelo lê os dois pares, com respostas e trecho de origem, e escolhe um tipo ou "nenhuma".
4. **Checar por código:** sem ciclo na hierarquia, sem par ligado a si mesmo, sem `EQUIVALENT_TO` e `CONTRADICTS` no mesmo par.
5. **Curar:** aprovar, rejeitar ou inverter a direção. Toda relação nasce proposta.
6. **Exportar** conforme a tabela abaixo. Pares ligados caem na mesma divisão, para não vazar conteúdo entre treino e teste.

```text
qa_relations(id, project, from_id, to_id, type, status, why, model, created_at)
status: proposed | approved | rejected
```

## Relações

| Relação | O que faz | Opinião |
| --- | --- | --- |
| `EQUIVALENT_TO` | Exporta só um representante, sem apagar o outro | Começar |
| `SPECIALIZES` | Monta a hierarquia pai/filho | Começar, com botão de inverter |
| `CONTRADICTS` | Bloqueia os dois no treino até a pessoa resolver | Começar |
| `GENERALIZES` | Inverso de `SPECIALIZES` | Não guardar: é a mesma aresta |
| `PART_OF` | Liga a parte ao todo | Depois: pode ser confundida com `SPECIALIZES` |
| `SUPPORTS` | Um par é evidência do outro | Depois, se o grafo virar memória |
| `SUPERSEDES` | Exporta só o mais novo | Depois: exige versão ou data dos documentos |
| `RELATED_TO` | Nada de concreto | Cortar: foi o ruído da busca por embedding no piloto |

`depends` (precisa entender A antes de B) não está na lista e não é o mesmo que `SUPPORTS`.

## Indícios do piloto

Poucos dados, sem gabarito.

- `gemma4:12b` inverteu pai e filho nos dois usos reais.
- 136 comparações parciais: 114 "nenhuma", 21 "mesma", 1 "contradição". A contradição parece falsa e alguns "mesma" são duvidosos; não foram conferidos um a um.
- Agente sobre lista de perguntas perdeu relações entre temas. Embedding top-5 achou mais, com ruído.
