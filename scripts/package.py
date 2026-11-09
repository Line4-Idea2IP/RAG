"""Build a source ZIP with explicit exclusions and verify every entry."""

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def main():
    root = Path(__file__).resolve().parents[1]
    excluded = {".venv", ".git", "__pycache__", ".pytest_cache", ".ruff_cache", "build", "dist"}
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and not any(
            part in excluded or part.endswith(".egg-info") for part in path.relative_to(root).parts
        )
        and path.name != ".env"
        and path.suffix not in {".pyc", ".zip", ".whl"}
    )
    manifest_path = root / "docs" / "FILE_MANIFEST.json"
    hashes = {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in files
        if p != manifest_path
    }
    manifest_path.write_text(json.dumps(hashes, indent=2), encoding="utf-8")
    files = [p for p in files if p != manifest_path] + [manifest_path]
    archive = root.parent / "idea2ip-ai-starter.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as output:
        for path in files:
            output.write(path, arcname=root.name + "/" + path.relative_to(root).as_posix())
    with ZipFile(archive) as result:
        if result.testzip() is not None:
            raise RuntimeError("ZIP integrity failure")
        for relative, expected in hashes.items():
            if hashlib.sha256(result.read(root.name + "/" + relative)).hexdigest() != expected:
                raise RuntimeError("Manifest mismatch: " + relative)
        if any(name.endswith("/.env") for name in result.namelist()):
            raise RuntimeError("Unexpected environment secrets file")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(
        digest + "  " + archive.name + "\n", encoding="utf-8"
    )
    print(json.dumps({"archive": str(archive), "files": len(files), "sha256": digest}))


if __name__ == "__main__":
    main()
