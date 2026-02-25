from __future__ import annotations

import hashlib
import json
import re
import subprocess
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PYTHON_MIN_MAJOR = 3
PYTHON_MIN_MINOR = 9


@dataclass(frozen=True)
class RuntimeBundleEntry:
    target: str
    url: str
    sha256: str
    urls: list[str] | None = None


def build_runtime_bundle(*, runtime_root: Path, bundle_path: Path) -> Path:
    source_root = Path(runtime_root)
    if not source_root.exists() or not source_root.is_dir():
        raise ValueError(f"runtime_root 不存在或不是目录: {source_root}")
    validate_runtime_root(source_root)

    target_path = Path(bundle_path)
    if target_path.suffix.lower() != ".zip":
        raise ValueError("bundle_path 必须是 .zip 文件")
    if target_path.parent != Path("."):
        target_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(target_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for file_path in sorted(source_root.rglob("*")):
            if not file_path.is_file():
                continue
            relative = file_path.relative_to(source_root)
            archive.write(file_path, arcname=relative.as_posix())

    return target_path


def validate_runtime_root(runtime_root: Path) -> Path:
    root = Path(runtime_root)
    if not root.exists() or not root.is_dir():
        raise ValueError(f"runtime_root 不存在或不是目录: {root}")

    candidates = [
        root / "bin" / "python3",
        root / "bin" / "python",
        root / "python.exe",
        root / "Scripts" / "python.exe",
        root / "Scripts" / "python",
    ]
    existing = [candidate for candidate in candidates if candidate.exists() and candidate.is_file()]
    if not existing:
        raise ValueError("runtime_root 中未找到 Python 可执行文件（bin/python3 或 Scripts/python.exe）")

    parsed_versions: list[tuple[Path, tuple[int, int, int]]] = []
    for candidate in existing:
        version = _probe_python_version(candidate)
        if version is None:
            continue
        if _is_supported_python_version(version):
            return candidate
        parsed_versions.append((candidate, version))

    if parsed_versions:
        printable = ", ".join(f"{path}={major}.{minor}.{patch}" for path, (major, minor, patch) in parsed_versions)
        raise ValueError(
            f"runtime_root 中 Python 版本过低（要求 >= {PYTHON_MIN_MAJOR}.{PYTHON_MIN_MINOR}）：{printable}"
        )
    raise ValueError("runtime_root 中 Python 可执行文件不可用（执行 --version 失败）")


def _probe_python_version(python_path: Path) -> tuple[int, int, int] | None:
    try:
        result = subprocess.run(
            [str(python_path), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if result.returncode != 0:
        return None
    line = (result.stdout.strip() or result.stderr.strip()).strip()
    matched = re.match(r"^Python\s+(\d+)\.(\d+)(?:\.(\d+))?", line)
    if not matched:
        return None
    major = int(matched.group(1))
    minor = int(matched.group(2))
    patch = int(matched.group(3) or "0")
    return major, minor, patch


def _is_supported_python_version(version: tuple[int, int, int]) -> bool:
    major, minor, _patch = version
    return major > PYTHON_MIN_MAJOR or (major == PYTHON_MIN_MAJOR and minor >= PYTHON_MIN_MINOR)


def calculate_sha256(file_path: Path) -> str:
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        raise ValueError(f"文件不存在: {path}")

    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def upsert_manifest_bundle(*, manifest_path: Path, entry: RuntimeBundleEntry) -> dict[str, Any]:
    path = Path(manifest_path)
    manifest = _load_manifest(path)
    bundles = manifest.get("bundles", [])
    retained = [item for item in bundles if item.get("target") != entry.target]

    new_item: dict[str, Any] = {
        "target": entry.target,
        "url": entry.url,
        "sha256": entry.sha256,
    }
    if entry.urls:
        new_item["urls"] = entry.urls
    retained.append(new_item)

    manifest["bundles"] = retained
    manifest["generated_at"] = datetime.now(timezone.utc).isoformat()

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"bundles": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("manifest 必须是 JSON 对象")
    bundles = payload.get("bundles")
    if bundles is None:
        payload["bundles"] = []
    elif not isinstance(bundles, list):
        raise ValueError("manifest.bundles 必须是数组")
    return payload
