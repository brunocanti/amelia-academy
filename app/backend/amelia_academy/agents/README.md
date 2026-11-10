# Agents

Each folder is one job of the model. The words the model receives live here; the code only reads them.

```
agents/
  figure_reader/
    AGENT.md       who it is: name, nickname, what the console says it is doing, its place in the console table
    figure.md      a prompt, plain text with $names to fill in
  shared/          sentences more than one agent uses
```

## Changing a prompt

Edit the `.md` file. It counts from the next call, with no restart. The console shows the exact text each call received.

The small lists read when the server starts need a restart: `fields.md`, `variations.md`, `shapes.md`, and every `AGENT.md`.

- `$name` is filled in by the code. Write `${name}` when a letter follows it, and `$$` for a real dollar sign.
- Braces need no escaping, so JSON examples are written as they are.
- A `$name` the code does not send, or a value the file does not use, is an error at the call. Nothing goes to the model with a gap.
- The last line break of a file is not sent.
- No keys or passwords here: these files are in Git, and Git is the history of each prompt.

## What stays in the code

- How data is laid out inside a prompt (`[F1] Q: ...`), because the checks read those same marks.
- The JSON shape each agent must return, and the checks on what comes back.
- What runs next. No agent chooses that.

## Adding an agent

Create the folder with its `AGENT.md`, then call `agents.prompt("folder", "file", name=value)` inside `console.acting("folder")`.
