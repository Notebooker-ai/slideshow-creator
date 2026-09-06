"""Editable-source contract: ``generate`` attaches the ``.qmd`` (role=source) and
the pre-rendered visuals (role=asset); ``render`` re-renders the deck from an
edited ``.qmd`` without an LLM and re-declares source + assets alongside outputs.

Quarto and the Node sidecar are stubbed so these run anywhere.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from open_notebook_creator_sdk import (
    ContentBundle,
    CreationRequest,
    ModelRole,
    RenderRequest,
    SourceDoc,
)
from open_notebook_creator_sdk.testing import assert_result_compliant

import slideshow_creator
from slideshow_creator import SlideshowCreator

_VALID_CHART = "infographic chart-column-simple\ndata\n  values\n    - label A\n      value 1"
_FAKE_SVG = '<svg xmlns="http://www.w3.org/2000/svg"><text>fake</text></svg>'
_FAKE_PNG_B64 = "iVBORw0KGgo="  # any base64 payload; nothing decodes it as an image here

_EXT = {"revealjs": "html", "pptx": "pptx", "beamer": "pdf"}


class _FakeLLM:
    def __init__(self, content: str):
        self._content = content

    async def ainvoke(self, _prompt):
        return type("Resp", (), {"content": self._content})()


class _FakeRole(ModelRole):
    payload: str = ""

    def create_language(self, **_):
        return _FakeLLM(self.payload)


def _gen_request(output_dir: str, slides, formats=None) -> CreationRequest:
    payload = json.dumps({"title": "My Deck", "subtitle": "A subtitle", "slides": slides})
    return CreationRequest(
        content=ContentBundle(text="Some research content.", token_count=4),
        config={"num_slides": 8, "theme": "auto", "formats": formats or ["html"]},
        models={"text": _FakeRole(provider="fake", model="fake", payload=payload)},
        output_dir=output_dir,
        artifact_id="artifact-test-1",
    )


@pytest.fixture
def stub_toolchain(monkeypatch):
    """Stub Quarto (copies the .qmd body into the output file so we can assert on it)
    and the AntV sidecar (returns one fake SVG+PNG per spec). Records quarto calls."""
    calls: list[tuple[str, str]] = []

    async def fake_quarto(output_dir: Path, to: str) -> None:
        qmd = (output_dir / "slideshow.qmd").read_text(encoding="utf-8")
        calls.append((to, qmd))
        (output_dir / f"slideshow.{_EXT[to]}").write_text(f"<rendered:{to}>\n{qmd}", encoding="utf-8")

    async def fake_specs(specs, _theme):
        return [{"svg": _FAKE_SVG, "png_b64": _FAKE_PNG_B64} for _ in specs]

    monkeypatch.setattr(slideshow_creator, "_quarto_render", fake_quarto)
    monkeypatch.setattr(slideshow_creator, "_render_specs", fake_specs)
    return calls


def _by_role(files, role):
    return [f for f in files if f.role == role]


def test_manifest_declares_editable_source():
    assert SlideshowCreator().manifest.editable_source is True


@pytest.mark.asyncio
async def test_generate_attaches_source_and_assets(stub_toolchain):
    slides = [
        {"type": "title", "title": "My Deck"},
        {"type": "bullets", "title": "Points", "bullets": ["One", "Two"]},
        {"type": "chart", "title": "Numbers", "caption": "the data", "spec": _VALID_CHART},
    ]
    with tempfile.TemporaryDirectory() as d:
        creator = SlideshowCreator()
        result = await creator.generate(_gen_request(d, slides, ["html", "pdf"]))
        assert result.status == "SUCCESS", (result.user_message, result.errors)
        assert_result_compliant(creator, result)

        outputs = _by_role(result.files, "output")
        assert [f.filename for f in outputs] == ["slideshow.html", "slideshow.pdf"]
        assert outputs[0].content_type == "text/html"

        sources = _by_role(result.files, "source")
        assert len(sources) == 1
        src = sources[0]
        assert (src.filename, src.path, src.content_type, src.label) == (
            "slideshow.qmd", "slideshow.qmd", "text/markdown", "Source"
        )

        assets = _by_role(result.files, "asset")
        svgs = [a for a in assets if a.content_type == "image/svg+xml"]
        assert [a.path for a in svgs] == ["assets/slide-2.svg"]
        # the PNG the pptx/beamer branches reference must travel with the SVG,
        # otherwise a re-render of static formats loses the visual
        pngs = [a for a in assets if a.content_type == "image/png"]
        assert [a.path for a in pngs] == ["assets/slide-2.png"]
        for a in assets:
            assert (Path(d) / a.path).is_file()


@pytest.mark.asyncio
async def test_generate_without_data_slides_has_no_assets(stub_toolchain):
    slides = [{"type": "title", "title": "My Deck"}, {"type": "section", "title": "One"}]
    with tempfile.TemporaryDirectory() as d:
        result = await SlideshowCreator().generate(_gen_request(d, slides))
        assert result.status == "SUCCESS"
        assert _by_role(result.files, "asset") == []
        assert [f.filename for f in _by_role(result.files, "source")] == ["slideshow.qmd"]


@pytest.mark.asyncio
async def test_render_rerenders_from_edited_source(stub_toolchain):
    slides = [
        {"type": "title", "title": "My Deck"},
        {"type": "bullets", "title": "Points", "bullets": ["One", "Two"]},
        {"type": "chart", "title": "Numbers", "caption": "the data", "spec": _VALID_CHART},
    ]
    with tempfile.TemporaryDirectory() as d:
        creator = SlideshowCreator()
        gen = await creator.generate(_gen_request(d, slides, ["html"]))
        assert gen.status == "SUCCESS"
        original_qmd = (Path(d) / "slideshow.qmd").read_text(encoding="utf-8")
        assert "- One" in original_qmd
        stub_toolchain.clear()

        # The user edits the source; the host writes it (and the assets) back
        # into output_dir and hands us the text.
        edited = original_qmd.replace("- One", "- Uno (edited)")
        req = RenderRequest(
            sources=[SourceDoc(filename="slideshow.qmd", content_type="text/markdown", content=edited)],
            config={"num_slides": 8, "theme": "auto", "formats": ["html", "pptx"]},
            data=gen.data,
            output_dir=d,
            artifact_id="artifact-test-1",
        )
        result = await creator.render(req)
        assert result.status == "SUCCESS", (result.user_message, result.errors)
        assert_result_compliant(creator, result)

        # deterministic: quarto ran once per configured format, on the edited text
        assert [to for to, _ in stub_toolchain] == ["revealjs", "pptx"]
        assert all("- Uno (edited)" in qmd for _, qmd in stub_toolchain)
        assert "- Uno (edited)" in (Path(d) / "slideshow.html").read_text(encoding="utf-8")

        outputs = _by_role(result.files, "output")
        assert [f.filename for f in outputs] == ["slideshow.html", "slideshow.pptx"]
        assert outputs[0].content_type == "text/html"

        # source + assets re-declared so the host keeps them for the next edit
        sources = _by_role(result.files, "source")
        assert [(s.filename, s.content_type, s.label) for s in sources] == [
            ("slideshow.qmd", "text/markdown", "Source")
        ]
        asset_paths = sorted(a.path for a in _by_role(result.files, "asset"))
        assert asset_paths == ["assets/slide-2.png", "assets/slide-2.svg"]
        for a in _by_role(result.files, "asset"):
            assert (Path(d) / a.path).is_file()

        # data carried forward, formats replaced with what actually rendered
        assert result.data["title"] == "My Deck"
        assert result.data["subtitle"] == "A subtitle"
        assert result.data["slides"] == gen.data["slides"]
        assert result.data["formats"] == ["html", "pptx"]


@pytest.mark.asyncio
async def test_render_picks_up_edited_front_matter_title(stub_toolchain):
    slides = [{"type": "title", "title": "My Deck"}, {"type": "section", "title": "One"}]
    with tempfile.TemporaryDirectory() as d:
        creator = SlideshowCreator()
        gen = await creator.generate(_gen_request(d, slides))
        edited = (Path(d) / "slideshow.qmd").read_text(encoding="utf-8").replace(
            'title: "My Deck"', 'title: "Renamed Deck"'
        )
        req = RenderRequest(
            sources=[SourceDoc(filename="slideshow.qmd", content_type="text/markdown", content=edited)],
            config={"formats": ["html"]},
            data=gen.data,
            output_dir=d,
            artifact_id="a",
        )
        result = await creator.render(req)
        assert result.status == "SUCCESS"
        assert result.data["title"] == "Renamed Deck"


@pytest.mark.asyncio
async def test_render_writes_sources_even_if_host_did_not(stub_toolchain):
    """render must not rely on the host having materialised the source."""
    with tempfile.TemporaryDirectory() as d:
        qmd = '---\ntitle: "Fresh"\nformat:\n  revealjs: default\n---\n\n## Only slide\n'
        req = RenderRequest(
            sources=[SourceDoc(filename="slideshow.qmd", content_type="text/markdown", content=qmd)],
            config={"formats": ["html"]},
            data={"title": "Fresh", "theme": "auto", "slides": [], "formats": ["html"]},
            output_dir=d,
            artifact_id="a",
        )
        result = await SlideshowCreator().render(req)
        assert result.status == "SUCCESS", (result.user_message, result.errors)
        assert (Path(d) / "slideshow.qmd").read_text(encoding="utf-8") == qmd
        assert _by_role(result.files, "asset") == []


@pytest.mark.asyncio
async def test_render_without_source_is_failure(stub_toolchain):
    with tempfile.TemporaryDirectory() as d:
        req = RenderRequest(
            sources=[SourceDoc(filename="notes.txt", content_type="text/plain", content="x")],
            config={"formats": ["html"]},
            data={"title": "T", "theme": "auto", "slides": [], "formats": ["html"]},
            output_dir=d,
            artifact_id="a",
        )
        result = await SlideshowCreator().render(req)
        assert result.status == "FAILURE"
        assert result.files == []
        assert result.user_message
        assert stub_toolchain == []  # nothing rendered


@pytest.mark.asyncio
async def test_render_all_formats_failing_is_failure(monkeypatch, stub_toolchain):
    async def broken_quarto(_output_dir, _to):
        raise RuntimeError("pandoc exploded")

    monkeypatch.setattr(slideshow_creator, "_quarto_render", broken_quarto)
    with tempfile.TemporaryDirectory() as d:
        req = RenderRequest(
            sources=[SourceDoc(filename="slideshow.qmd", content_type="text/markdown", content="## x\n")],
            config={"formats": ["html"]},
            data={"title": "T", "theme": "auto", "slides": [], "formats": ["html"]},
            output_dir=d,
            artifact_id="a",
        )
        result = await SlideshowCreator().render(req)
        assert result.status == "FAILURE"
        assert result.errors and result.errors[0].phase == "render"
