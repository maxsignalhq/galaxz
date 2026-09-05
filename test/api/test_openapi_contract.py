import json
from pathlib import Path

from services.andromeda_service import app


CONTRACT_PATH = Path(__file__).parents[1] / "contracts" / "andromeda-openapi.json"


def test_andromeda_openapi_matches_regression_contract() -> None:
    expected = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    assert app.openapi() == expected, (
        "The public HTTP API changed. If the change is intentional, review it and run "
        "`.venv/bin/python -m scripts.export_openapi_contract` to update the contract."
    )
