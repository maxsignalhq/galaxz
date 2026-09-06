from pathlib import Path

def test_quickstart_documents_five_minute_path():
    text = Path("examples/quickstart.md").read_text()
    assert "five-minute" in text.lower()
    assert "sample repository" in text.lower()
