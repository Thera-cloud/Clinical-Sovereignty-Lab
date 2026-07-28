from pathlib import Path

def test_nocache():
    text = Path('broken/nginx.conf').read_text()
    assert "no-cache" in text
    assert "max-age=14400" not in text
