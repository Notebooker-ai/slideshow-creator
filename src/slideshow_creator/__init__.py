"""slideshow-creator: an Open Notebook creator that turns notebook content into a
**slide deck**, rendered by Quarto from a single reveal.js source to self-contained
HTML plus downloadable PPTX and PDF (emitted as ``slideshow.v1``).

The LLM designs a sequence of typed slides (title / section / bullets / image_text /
chart / infographic). Data slides carry an AntV Infographic DSL ``spec``; a small Node
sidecar pre-renders each to a static SVG (and PNG via sharp) so the visuals appear in
PPTX/PDF too. PDF uses Quarto's ``beamer`` format with the ``tectonic`` engine.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
from pathlib import Path
from typing import ClassVar, List, Literal

from ai_prompter import Prompter
from loguru import logger
from open_notebook_creator_sdk import (
    BaseCreator,
    CreationError,
    CreationFile,
    CreationRequest,
    CreationResult,
    CreatorManifest,
    ModelRoleSpec,
)
from open_notebook_creator_sdk.schemas import SlideshowV1
from pydantic import BaseModel, Field

from .sanitize import sanitize_markdown

__version__ = "0.1.0"

_PKG_DIR = Path(__file__).resolve().parent
_PROMPTS_DIR = _PKG_DIR / "prompts"
_SIDECAR_DIR = _PKG_DIR / "sidecar"

_QMD_NAME = "slideshow.qmd"
_QMD_STEM = "slideshow"

# config format key -> (quarto --to target, file extension, MIME type, UI label)
_FORMAT_META: dict[str, tuple[str, str, str, str]] = {
    "html": ("revealjs", "html", "text/html", "HTML"),
    "pptx": ("pptx", "pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation", "PowerPoint"),
    "pdf": ("beamer", "pdf", "application/pdf", "PDF"),
}

# Quarto reveal.js themes that are dark; used to pick the AntV theme for data slides.
_DARK_THEMES = {"dark", "moon", "night", "league", "blood"}

_RENDER_TIMEOUT_S = 600
_SIDECAR_TIMEOUT_S = 120

_SLIDE_TYPES = {"title", "section", "bullets", "image_text", "chart", "infographic"}


class SlideshowConfig(BaseModel):
    """Per-generation config; its JSON Schema drives the host's generate form."""

    num_slides: int = Field(default=12, ge=3, le=40, description="Approximate number of slides")
    theme: Literal[
        "auto", "light", "dark", "serif", "moon", "solarized", "night", "league"
    ] = Field(default="auto", description="reveal.js deck theme")
    formats: List[Literal["html", "pptx", "pdf"]] = Field(
        default=["html", "pptx", "pdf"], description="Output formats to render"
    )


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```$", "", text)
    return text.strip()


def _render_prompt(name: str, ctx: dict) -> str:
    template = (_PROMPTS_DIR / name).read_text()
    return Prompter(template_text=template).render(ctx)


def _reveal_theme(theme: str) -> str:
    return "default" if theme in ("auto", "light") else theme


def _antv_theme_for(theme: str) -> str:
    return "dark" if theme in _DARK_THEMES else "light"


def _valid_spec(spec: object) -> bool:
    if not isinstance(spec, str):
        return False
    for line in spec.splitlines():
        s = line.strip()
        if s:
            return s.startswith("infographic ")
    return False


def _normalize_slide(raw: object) -> dict | None:
    """Validate/normalize one slide; return None if unusable."""
    if not isinstance(raw, dict):
        return None
    stype = raw.get("type")
    if stype not in _SLIDE_TYPES:
        return None
    title = (raw.get("title") or "").strip() if isinstance(raw.get("title"), str) else ""
    if stype in ("title", "section") and not title:
        return None
    slide: dict = {"type": stype, "title": title}
    if isinstance(raw.get("subtitle"), str):
        slide["subtitle"] = raw["subtitle"].strip()
    if isinstance(raw.get("caption"), str):
        slide["caption"] = raw["caption"].strip()
    if isinstance(raw.get("notes"), str):
        slide["notes"] = raw["notes"].strip()
    if isinstance(raw.get("body"), str):
        slide["body"] = raw["body"].strip()
    bullets = raw.get("bullets")
    if isinstance(bullets, list):
        slide["bullets"] = [str(b).strip() for b in bullets if str(b).strip()]
    if stype in ("chart", "infographic"):
        spec = raw.get("spec")
        if not _valid_spec(spec):
            return None  # caller degrades to a bullets slide
        slide["spec"] = spec.strip()
    if stype == "bullets" and not slide.get("bullets"):
        return None
    return slide


def _degrade(slide: dict) -> dict:
    """Turn a data slide we couldn't render into a plain bullets slide."""
    caption = slide.get("caption") or "Visual could not be rendered."
    return {"type": "bullets", "title": slide.get("title") or "", "bullets": [caption]}


async def _render_specs(specs: List[str], antv_theme: str) -> List[dict]:
    """Pre-render AntV DSL specs to SVG+PNG via the Node sidecar. Raises on failure."""
    script = str(_SIDECAR_DIR / "render.mjs")
    proc = await asyncio.create_subprocess_exec(
        "node",
        script,
        cwd=str(_SIDECAR_DIR),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    payload = json.dumps({"theme": antv_theme, "specs": specs}).encode()
    out, err = await asyncio.wait_for(proc.communicate(payload), timeout=_SIDECAR_TIMEOUT_S)
    if proc.returncode != 0:
        detail = (err.decode(errors="replace") or "").strip()
        raise RuntimeError(detail[-2000:] or f"node sidecar exited {proc.returncode}")
    return json.loads(out)


async def _quarto_render(output_dir: Path, to: str) -> None:
    """Render ``slideshow.qmd`` to one Quarto format in-place. Raises on failure."""
    proc = await asyncio.create_subprocess_exec(
        "quarto",
        "render",
        _QMD_NAME,
        "--to",
        to,
        cwd=str(output_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(proc.communicate(), timeout=_RENDER_TIMEOUT_S)
    if proc.returncode != 0:
        detail = (err.decode(errors="replace") or out.decode(errors="replace")).strip()
        raise RuntimeError(detail[-2000:] or f"quarto exited {proc.returncode}")


def _build_front_matter(title: str, subtitle: str | None, theme: str) -> str:
    lines = ["---", f"title: {json.dumps(title)}"]
    if subtitle:
        lines.append(f"subtitle: {json.dumps(subtitle)}")
    lines += [
        "format:",
        "  revealjs:",
        f"    theme: {_reveal_theme(theme)}",
        "    embed-resources: true",
        "    slide-number: true",
        "  pptx: default",
        "  beamer:",
        "    pdf-engine: tectonic",
        "---",
    ]
    return "\n".join(lines)


def _slide_to_md(slide: dict, deck_title: str) -> str:
    stype = slide["type"]
    title = slide.get("title", "")

    if stype == "title":
        # The deck title slide is generated from front matter; only emit a distinct one.
        if not title or title.strip() == deck_title.strip():
            return ""
        out = [f"# {title}"]
        if slide.get("subtitle"):
            out.append("")
            out.append(sanitize_markdown(slide["subtitle"]))
        return "\n".join(out)

    if stype == "section":
        return f"# {title}"

    if stype == "bullets":
        out = [f"## {title}", ""]
        for b in slide.get("bullets", []):
            out.append(f"- {sanitize_markdown(b)}")
        if slide.get("notes"):
            out += ["", "::: {.notes}", sanitize_markdown(slide["notes"]), ":::"]
        return "\n".join(out)

    if stype == "image_text":
        out = [f"## {title}", ""]
        if slide.get("body"):
            out += [sanitize_markdown(slide["body"]), ""]
        for b in slide.get("bullets", []):
            out.append(f"- {sanitize_markdown(b)}")
        if slide.get("notes"):
            out += ["", "::: {.notes}", sanitize_markdown(slide["notes"]), ":::"]
        return "\n".join(out)

    # chart / infographic — format-conditional image (SVG for revealjs, PNG for static).
    cap = sanitize_markdown(slide.get("caption", "")) if slide.get("caption") else ""
    svg = slide.get("svg_path")
    png = slide.get("png_path") or svg
    out = [f"## {title}", ""]
    out += ['::: {.content-visible when-format="revealjs"}', f"![{cap}]({svg}){{fig-align=\"center\"}}", ":::"]
    out += ['::: {.content-visible unless-format="revealjs"}', f"![{cap}]({png}){{fig-align=\"center\"}}", ":::"]
    return "\n".join(out)


class SlideshowCreator(BaseCreator):
    config_model: ClassVar[type] = SlideshowConfig

    @property
    def manifest(self) -> CreatorManifest:
        return self.build_manifest(
            key="slideshows",
            name="Slideshows",
            version=__version__,
            description="LLM-designed slide deck (reveal.js) with AntV data slides, exported to HTML/PPTX/PDF via Quarto.",
            sdk_compat=">=0.2,<1",
            emits=["slideshow.v1"],
            model_roles=[
                ModelRoleSpec(
                    key="text",
                    kind="language",
                    requires=["structured_json"],
                    description="LLM that designs the slides.",
                )
            ],
            icon="presentation",
        )

    async def generate(self, request: CreationRequest) -> CreationResult:
        cfg = SlideshowConfig.model_validate(request.config)
        role = request.models.get("text")
        if role is None:
            return CreationResult(
                status="FAILURE",
                schema_id="slideshow.v1",
                data={},
                errors=[CreationError(phase="setup", message="missing 'text' model role")],
                user_message="No language model was provided for slideshow generation.",
            )

        warnings: List[str] = []
        errors: List[CreationError] = []

        # --- Phase B: design the slides (one structured-JSON call). ---
        antv_syntax = (_PROMPTS_DIR / "antv_syntax.md").read_text()
        prompt = _render_prompt(
            "slides.jinja",
            {
                "content": request.content.text,
                "num_slides": cfg.num_slides,
                "antv_syntax": antv_syntax,
                "instructions": request.instructions,
            },
        )
        llm = role.create_language(structured={"type": "json"}, max_tokens=8000)
        resp = await llm.ainvoke(prompt)
        raw = resp.content if hasattr(resp, "content") else str(resp)
        try:
            parsed = json.loads(_strip_fences(raw))
        except json.JSONDecodeError as e:
            logger.error(f"slideshow: non-JSON response: {e}")
            return CreationResult(
                status="FAILURE",
                schema_id="slideshow.v1",
                data={},
                errors=[CreationError(phase="parse", message=f"invalid JSON: {e}", retryable=True)],
                user_message="The model returned an unparseable response. Please retry.",
            )

        deck_title = (parsed.get("title") or "").strip() if isinstance(parsed, dict) else ""
        subtitle = parsed.get("subtitle") if isinstance(parsed, dict) else None
        subtitle = subtitle.strip() if isinstance(subtitle, str) and subtitle.strip() else None
        raw_slides = parsed.get("slides", []) if isinstance(parsed, dict) else []

        slides: List[dict] = []
        for raw_slide in raw_slides if isinstance(raw_slides, list) else []:
            norm = _normalize_slide(raw_slide)
            if norm is not None:
                slides.append(norm)
            elif isinstance(raw_slide, dict) and raw_slide.get("type") in ("chart", "infographic"):
                # invalid/missing spec — keep the slide as bullets so the deck survives
                slides.append(_degrade(raw_slide))
                warnings.append("A data slide had an invalid spec and was shown as text.")

        if not deck_title or not slides:
            return CreationResult(
                status="FAILURE",
                schema_id="slideshow.v1",
                data={},
                errors=[CreationError(phase="generate", message="no usable slides produced")],
                user_message="No slideshow could be generated from this content.",
            )

        # --- Phase C: pre-render data slides to static SVG/PNG via the Node sidecar. ---
        output_dir = Path(request.output_dir)
        data_idx = [i for i, s in enumerate(slides) if s["type"] in ("chart", "infographic")]
        if data_idx:
            assets = output_dir / "assets"
            assets.mkdir(exist_ok=True)
            try:
                results = await _render_specs(
                    [slides[i]["spec"] for i in data_idx], _antv_theme_for(cfg.theme)
                )
            except FileNotFoundError:
                results = None
                logger.error("slideshow: 'node' binary not found on PATH")
                warnings.append("Node is not installed; data slides were shown as text.")
                errors.append(CreationError(phase="render", message="node not installed"))
            except Exception as e:  # noqa: BLE001 - sidecar failure degrades, never fatal
                results = None
                logger.warning(f"slideshow: sidecar failed: {e}")
                warnings.append("Data slides could not be rendered and were shown as text.")
                errors.append(CreationError(phase="render", message=f"sidecar: {e}"))

            for n, i in enumerate(data_idx):
                res = results[n] if results and n < len(results) else None
                if not res or not res.get("svg"):
                    slides[i] = _degrade(slides[i])
                    if results is not None:
                        warnings.append("A data slide failed to render and was shown as text.")
                    continue
                svg_name = f"assets/slide-{i}.svg"
                (output_dir / svg_name).write_text(res["svg"], encoding="utf-8")
                slides[i]["svg_path"] = svg_name
                if res.get("png_b64"):
                    png_name = f"assets/slide-{i}.png"
                    (output_dir / png_name).write_bytes(base64.b64decode(res["png_b64"]))
                    slides[i]["png_path"] = png_name

        # --- Phase D: assemble the single reveal.js .qmd. ---
        parts = [_build_front_matter(deck_title, subtitle, cfg.theme), ""]
        for s in slides:
            md = _slide_to_md(s, deck_title)
            if md:
                parts.append(md)
                parts.append("")
        (output_dir / _QMD_NAME).write_text("\n".join(parts), encoding="utf-8")

        # --- Phase E: render each requested format (best-effort). ---
        files: List[CreationFile] = []
        rendered: List[str] = []
        for fmt in cfg.formats:
            to, ext, content_type, label = _FORMAT_META[fmt]
            out_name = f"{_QMD_STEM}.{ext}"
            try:
                await _quarto_render(output_dir, to)
                if not (output_dir / out_name).exists():
                    raise RuntimeError("quarto reported success but produced no output file")
                files.append(
                    CreationFile(filename=out_name, content_type=content_type, path=out_name, label=label)
                )
                rendered.append(fmt)
            except FileNotFoundError:
                logger.error("slideshow: 'quarto' binary not found on PATH")
                errors.append(CreationError(phase="render", message="quarto not installed"))
                warnings.append("Quarto is not installed on the server; cannot render the slideshow.")
                break
            except Exception as e:  # noqa: BLE001 - one format failing is non-fatal
                logger.warning(f"slideshow: {fmt} render failed: {e}")
                warnings.append(f"{label} export failed.")
                errors.append(CreationError(phase="render", message=f"{fmt}: {e}"))

        if not rendered:
            return CreationResult(
                status="FAILURE",
                schema_id="slideshow.v1",
                data={},
                warnings=warnings,
                errors=errors or [CreationError(phase="render", message="no formats rendered")],
                user_message="The slideshow could not be rendered to any format.",
            )

        files.sort(key=lambda f: 0 if f.content_type == "text/html" else 1)

        data = SlideshowV1(
            title=deck_title,
            subtitle=subtitle,
            theme=cfg.theme,
            slides=[{"type": s["type"], "title": s.get("title") or None} for s in slides],
            formats=rendered,
        ).model_dump()

        return CreationResult(
            status="PARTIAL" if errors else "SUCCESS",
            schema_id="slideshow.v1",
            data=data,
            files=files,
            warnings=warnings,
            errors=errors,
        )
