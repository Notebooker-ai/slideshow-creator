"""Regression for the five-step diagram whose labels collided in the QA batch."""
from slideshow_creator import _degrade, _normalize_slide


def test_dense_horizontal_process_preserves_every_step_as_readable_text():
    labels = ["Set Goal", "Close Notes", "Check Source", "Correct Gaps", "Schedule Next"]
    spec = "infographic sequence-color-snake-steps-horizontal-icon-line\ndata\n  sequences\n" + "\n".join(
        f"    - label {label}\n      desc Explanation for {label}" for label in labels
    )
    slide = _normalize_slide({"type": "infographic", "title": "Recall cycle", "spec": spec, "caption": "Five steps", "notes": "Keep the notes"})
    assert slide["type"] == "bullets"
    assert len(slide["bullets"]) == 5
    assert all(label in bullet for label, bullet in zip(labels, slide["bullets"]))
    assert slide["notes"] == "Keep the notes"
    assert slide["caption"] == "Five steps"
    assert "spec" not in slide


def test_render_failure_preserves_process_content_instead_of_only_caption():
    slide = _degrade({"title": "Cycle", "caption": "Practice", "spec": "infographic x\ndata\n  sequences\n    - label Recall\n      desc Close notes\n    - label Check\n      desc Verify answer"})
    assert slide["bullets"] == ["Recall: Close notes", "Check: Verify answer"]
