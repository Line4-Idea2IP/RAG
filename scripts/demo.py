"""Exercise the full mock flow in-process without a running HTTP server or database."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from idea2ip.config import Settings
from idea2ip.main import create_app


def main():
    context = json.loads(Path("samples/project.json").read_text(encoding="utf-8"))
    client = TestClient(create_app(Settings(_env_file=None, mode="mock", retrieval="none")))
    root = "/v1/projects/" + context["project_id"]
    output = {}
    for endpoint, payload in [
        ("questions", {"context": context, "target_field": "human_edit"}),
        ("answers/analyze", context),
        ("contributions", context),
        ("brief", context),
    ]:
        response = client.post(root + "/" + endpoint, json=payload)
        response.raise_for_status()
        output[endpoint] = response.json()
    folder = Path("build")
    folder.mkdir(exist_ok=True)
    (folder / "demo-output.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("Mock flow succeeded: build/demo-output.json")


if __name__ == "__main__":
    main()
