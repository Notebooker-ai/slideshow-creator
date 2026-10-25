"""Unit tests use deterministic rendered files; live renderer has its own smoke test."""

import pytest
from open_notebook_creator_sdk import CreationFile


@pytest.fixture(autouse=True)
def remotion_toolchain(monkeypatch):
    import slideshow_creator

    async def render(output_dir, deck):
        for name in ("slideshow.html", "slideshow.mp4"):
            (output_dir / name).write_text("rendered " + deck["title"])
        return (
            [
                CreationFile(
                    filename="slideshow.html",
                    path="slideshow.html",
                    content_type="text/html",
                ),
                CreationFile(
                    filename="slideshow.mp4",
                    path="slideshow.mp4",
                    content_type="video/mp4",
                ),
            ],
            [],
            [],
            ["html", "mp4"],
        )

    monkeypatch.setattr(slideshow_creator, "render_remotion", render)
