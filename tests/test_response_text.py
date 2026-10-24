from types import SimpleNamespace
import pytest
from slideshow_creator import _response_text


@pytest.mark.parametrize(
    "content",
    [
        '{"title":"A"}',
        [
            {"type": "text", "text": '{"title":"A"}'},
            {"type": "thinking", "thinking": "private"},
        ],
    ],
)
def test_json_text_is_identical_for_string_and_gemini_content_blocks(content):
    assert _response_text(SimpleNamespace(content=content)) == '{"title":"A"}'


def test_non_text_response_is_rejected():
    with pytest.raises(ValueError):
        _response_text(SimpleNamespace(content=None))
