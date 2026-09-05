"""Export the canonical Andromeda OpenAPI regression contract."""

import json
from pathlib import Path

from services.andromeda_service import app


CONTRACT_PATH = Path(__file__).parents[1] / "test" / "contracts" / "andromeda-openapi.json"


def main() -> None:
    CONTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    contract = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
    CONTRACT_PATH.write_text(contract, encoding="utf-8")
    print(f"Wrote {CONTRACT_PATH}")


if __name__ == "__main__":
    main()
