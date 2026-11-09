import json
from pathlib import Path

from idea2ip.config import Settings
from idea2ip.main import create_app

if __name__ == "__main__":
    app = create_app(Settings(_env_file=None))
    Path("docs/openapi.json").write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("docs/openapi.json")
