# slideshow-creator

An [Open Notebook](https://open-notebook.ai) **creator** plugin: turns notebook
content into a **slide deck**. The LLM designs a sequence of typed slides; Quarto
renders one reveal.js source to self-contained **HTML**, **PowerPoint (PPTX)**, and
**PDF**.

- Emits the `slideshow.v1` artifact schema (substance in `CreationResult.files`).
- Data slides (`chart` / `infographic`) carry an [AntV Infographic](https://infographic.antv.vision/)
  DSL; a small **Node sidecar** pre-renders each to a static SVG (and PNG via `sharp`)
  so the visuals appear in PPTX/PDF too.
- Implements the [`open-notebook-creator-sdk`](https://github.com/Notebooker-ai/open-notebook-creator-sdk) `BaseCreator` contract; registers under `open_notebook.creators`.

## Requirements

- The [`quarto`](https://quarto.org) CLI (PDF via the bundled `tectonic` engine).
- `node` + `npm`, with the sidecar's dependencies installed:
  ```bash
  cd src/slideshow_creator/sidecar && npm ci --omit=dev
  ```
  (`sharp` ships a platform-specific native binary, so install it on the target
  platform — do not vendor `node_modules` across OS/arch.)

If `node`/the sidecar or `quarto` is unavailable, the creator degrades gracefully:
data slides fall back to text, and a missing `quarto` yields a clear failure.

## Model roles

| role | kind | requires |
|------|------|----------|
| `text` | language | `structured_json` |

## Config

| field | default | notes |
|-------|---------|-------|
| `num_slides` | 12 | 3–40 (approximate) |
| `theme` | "auto" | auto/light/dark/serif/moon/solarized/night/league (reveal.js theme) |
| `formats` | ["html","pptx","pdf"] | output formats |

## Dev

```bash
uv sync --extra dev
uv run pytest
```

MIT licensed.
