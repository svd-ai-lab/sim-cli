from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROBE = REPO_ROOT / "skills" / "spaceclaim" / "scripts" / "probe_spaceclaim.ps1"


def test_probe_script_has_concise_controls() -> None:
    text = PROBE.read_text(encoding="utf-8")

    assert "CommandNames" in text
    assert "ConvertTo-Json" in text
    assert "AllDocs" in text
    assert "latest_api_docs" in text
