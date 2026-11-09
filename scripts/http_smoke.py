"""Start a temporary loopback server, call a real HTTP API, and always stop it."""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx


def main():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, IDEA2IP_MODE="mock", IDEA2IP_RETRIEVAL="none", IDEA2IP_SERVICE_TOKEN="")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "idea2ip.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", timeout=3, trust_env=False
        ) as client:
            for _ in range(60):
                if process.poll() is not None:
                    raise RuntimeError("uvicorn exited before becoming ready")
                try:
                    if client.get("/health/live").status_code == 200:
                        break
                except httpx.RequestError:
                    pass
                time.sleep(0.2)
            else:
                raise RuntimeError("uvicorn startup timeout")
            context = json.loads(Path("samples/project.json").read_text(encoding="utf-8"))
            response = client.post(f"/v1/projects/{context['project_id']}/brief", json=context)
            response.raise_for_status()
            if len(response.json()["sections"]) != 5:
                raise RuntimeError("Brief section contract failed")
            print("Real HTTP smoke: health=200, brief=200, sections=5, mode=mock")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    main()
