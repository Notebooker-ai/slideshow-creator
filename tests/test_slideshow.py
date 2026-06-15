"""generate() tests with a fake LLM. The Node sidecar (AntV pre-render) and Quarto
render run for real when available; otherwise the creator degrades data slides to text
and we still assert the .qmd was assembled/sanitized.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest
from open_notebook_creator_sdk import ContentBundle, CreationRequest, ModelRole
from open_notebook_creator_sdk.testing import assert_creator_compliant

from slideshow_creator import SlideshowCreator, _SIDECAR_DIR

HAS_QUARTO = shutil.which("quarto") is not None
HAS_SIDECAR = (_SIDECAR_DIR / "node_modules" / "@antv" / "infographic").exists()

_VALID_CHART = "infographic chart-column-simple\ndata\n  values\n    - label A\n      value 1\n    - label B\n      value 2"


class _FakeLLM:
    def __init__(self, content: str):
        self._content = content

    async def ainvoke(self, _prompt):
        return type("Resp", (), {"content": self._content})()


def _slides_payload(slides):
    return json.dumps({"title": "My Deck", "subtitle": "A subtitle", "slides": slides})


class _FakeRole(ModelRole):
    payload: str = ""

    def create_language(self, **_):
        return _FakeLLM(self.payload)


def _request(output_dir: str, slides, formats=None) -> CreationRequest:
    return CreationRequest(
        content=ContentBundle(text="Some research content about a topic.", token_count=6),
        config={"num_slides": 8, "theme": "auto", "formats": formats or ["html"]},
        models={"text": _FakeRole(provider="fake", model="fake", payload=_slides_payload(slides))},
        output_dir=output_dir,
        artifact_id="artifact-test-1",
    )


def test_static_compliance():
    assert_creator_compliant(SlideshowCreator())


@pytest.mark.asyncio
async def test_assembles_qmd_text_slides_and_degrades_invalid_spec():
    slides = [
        {"type": "title", "title": "My Deck"},
        {"type": "section", "title": "Part One"},
        {"type": "bullets", "title": "Key points", "bullets": ["Alpha 🎉", "Beta"], "notes": "say this"},
        {"type": "image_text", "title": "Detail", "body": "A short explanation."},
        {"type": "infographic", "title": "Broken", "caption": "shown as text", "spec": "not a valid spec"},
    ]
    with tempfile.TemporaryDirectory() as d:
        await SlideshowCreator().generate(_request(d, slides, ["html"]))
        qmd = (Path(d) / "slideshow.qmd").read_text(encoding="utf-8")
        # front matter: all three formats declared from one source
        assert 'title: "My Deck"' in qmd
        assert "revealjs:" in qmd and "pptx: default" in qmd and "beamer:" in qmd
        assert "theme: default" in qmd  # auto -> default
        # section divider + bullets + speaker notes
        assert "# Part One" in qmd
        assert "## Key points" in qmd and "- Alpha" in qmd
        assert "::: {.notes}" in qmd
        # emoji sanitized
        assert "🎉" not in qmd
        # invalid-spec data slide degraded to a bullets slide with its caption
        assert "## Broken" in qmd and "- shown as text" in qmd
        # the deck's own title slide is not duplicated as a body heading
        assert "# My Deck" not in qmd


@pytest.mark.asyncio
async def test_no_text_role_is_failure():
    with tempfile.TemporaryDirectory() as d:
        req = CreationRequest(content=ContentBundle(text="x"), output_dir=d, artifact_id="a")
        result = await SlideshowCreator().generate(req)
        assert result.status == "FAILURE"
        assert result.errors[0].phase == "setup"


@pytest.mark.asyncio
async def test_failure_when_no_slides():
    with tempfile.TemporaryDirectory() as d:
        result = await SlideshowCreator().generate(_request(d, []))
        assert result.status == "FAILURE"


@pytest.mark.skipif(not HAS_SIDECAR, reason="sidecar node_modules not installed")
@pytest.mark.asyncio
async def test_valid_chart_prerenders_to_svg():
    slides = [
        {"type": "title", "title": "My Deck"},
        {"type": "chart", "title": "Numbers", "caption": "the data", "spec": _VALID_CHART},
    ]
    with tempfile.TemporaryDirectory() as d:
        await SlideshowCreator().generate(_request(d, slides, ["html"]))
        qmd = (Path(d) / "slideshow.qmd").read_text(encoding="utf-8")
        # data slide became a format-conditional image, not a bullets fallback
        assert 'content-visible when-format="revealjs"' in qmd
        svgs = list((Path(d) / "assets").glob("*.svg"))
        assert svgs and svgs[0].read_text().startswith("<")


@pytest.mark.skipif(not (HAS_QUARTO and HAS_SIDECAR), reason="quarto and/or sidecar unavailable")
@pytest.mark.asyncio
async def test_renders_html_deck():
    slides = [
        {"type": "title", "title": "My Deck"},
        {"type": "bullets", "title": "Points", "bullets": ["One", "Two"]},
        {"type": "chart", "title": "Numbers", "caption": "the data", "spec": _VALID_CHART},
    ]
    with tempfile.TemporaryDirectory() as d:
        result = await SlideshowCreator().generate(_request(d, slides, ["html"]))
        assert result.status in ("SUCCESS", "PARTIAL"), (result.user_message, result.errors)
        assert result.schema_id == "slideshow.v1"
        assert "html" in result.data["formats"]
        assert (Path(d) / "slideshow.html").stat().st_size > 0
        assert result.files[0].content_type == "text/html"
