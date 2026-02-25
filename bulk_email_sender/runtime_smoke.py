from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from bulk_email_sender.runtime_packager import (
    RuntimeBundleEntry,
    build_runtime_bundle,
    calculate_sha256,
    upsert_manifest_bundle,
)


@dataclass(frozen=True)
class LocalRuntimeSmokeResult:
    runtime_root: Path
    bundle_path: Path
    manifest_path: Path
    python_version: str
    target: str


def prepare_local_runtime_smoke(
    *,
    output_dir: Path,
    target: str,
    python_version: str,
    manifest_name: str = "local-manifest.json",
) -> LocalRuntimeSmokeResult:
    normalized_target = target.strip()
    if not normalized_target:
        raise ValueError("target 不能为空")

    base_dir = Path(output_dir).expanduser().resolve()
    base_dir.mkdir(parents=True, exist_ok=True)

    runtime_root = base_dir / "mock_runtime"
    create_mock_runtime(runtime_root=runtime_root, python_version=python_version)

    bundle_path = base_dir / f"python-runtime-{normalized_target}.zip"
    build_runtime_bundle(runtime_root=runtime_root, bundle_path=bundle_path)

    manifest_path = base_dir / manifest_name
    checksum = calculate_sha256(bundle_path)
    upsert_manifest_bundle(
        manifest_path=manifest_path,
        entry=RuntimeBundleEntry(
            target=normalized_target,
            url=bundle_path.resolve().as_uri(),
            sha256=checksum,
        ),
    )

    return LocalRuntimeSmokeResult(
        runtime_root=runtime_root,
        bundle_path=bundle_path,
        manifest_path=manifest_path,
        python_version=python_version,
        target=normalized_target,
    )


def create_mock_runtime(*, runtime_root: Path, python_version: str) -> Path:
    output_root = Path(runtime_root).expanduser().resolve()
    bin_dir = output_root / "bin"
    lib_dir = output_root / "lib"
    bin_dir.mkdir(parents=True, exist_ok=True)
    lib_dir.mkdir(parents=True, exist_ok=True)

    launcher_content = build_launcher_script(python_version)
    python3_path = bin_dir / "python3"
    python_path = bin_dir / "python"

    python3_path.write_text(launcher_content, encoding="utf-8")
    python_path.write_text(launcher_content, encoding="utf-8")
    os.chmod(python3_path, 0o755)
    os.chmod(python_path, 0o755)

    (lib_dir / "MOCK_RUNTIME.txt").write_text(
        "This is a mock runtime for installation smoke tests.\n",
        encoding="utf-8",
    )
    return output_root


def build_launcher_script(version: str) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

if [[ "${{1:-}}" == "--version" ]]; then
  echo "Python {version}"
  exit 0
fi

exec /usr/bin/env python3 "$@"
"""
