import json
import zipfile
from pathlib import Path

import pytest

from bulk_email_sender.runtime_packager import (
    RuntimeBundleEntry,
    build_runtime_bundle,
    calculate_sha256,
    upsert_manifest_bundle,
)
from bulk_email_sender.runtime_smoke import create_mock_runtime


def test_build_runtime_bundle_and_sha256(tmp_path: Path) -> None:
    runtime_root = create_mock_runtime(runtime_root=tmp_path / "runtime_root", python_version="3.11.8")
    (runtime_root / "lib" / "site.py").write_text("print('ok')\n", encoding="utf-8")

    bundle_path = tmp_path / "python-runtime-macos-aarch64.zip"
    written_path = build_runtime_bundle(runtime_root=runtime_root, bundle_path=bundle_path)

    assert written_path == bundle_path
    assert bundle_path.exists()
    assert len(calculate_sha256(bundle_path)) == 64

    with zipfile.ZipFile(bundle_path, "r") as archive:
        names = sorted(archive.namelist())
    assert "bin/python3" in names
    assert "lib/site.py" in names


def test_build_runtime_bundle_rejects_missing_python_executable(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime_root"
    (runtime_root / "lib").mkdir(parents=True)
    (runtime_root / "lib" / "site.py").write_text("print('ok')\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Python 可执行文件"):
        build_runtime_bundle(
            runtime_root=runtime_root,
            bundle_path=tmp_path / "python-runtime-macos-aarch64.zip",
        )


def test_build_runtime_bundle_rejects_low_python_version(tmp_path: Path) -> None:
    runtime_root = create_mock_runtime(runtime_root=tmp_path / "runtime_root", python_version="3.8.18")

    with pytest.raises(ValueError, match="版本过低"):
        build_runtime_bundle(
            runtime_root=runtime_root,
            bundle_path=tmp_path / "python-runtime-macos-aarch64.zip",
        )


def test_upsert_manifest_bundle_replaces_same_target(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "bundles": [
                    {
                        "target": "macos-aarch64",
                        "url": "https://old.example.com/runtime.zip",
                        "sha256": "old",
                    },
                    {
                        "target": "windows-x86_64",
                        "url": "https://win.example.com/runtime.zip",
                        "sha256": "win",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    updated = upsert_manifest_bundle(
        manifest_path=manifest_path,
        entry=RuntimeBundleEntry(
            target="macos-aarch64",
            url="https://new.example.com/runtime.zip",
            sha256="new",
            urls=["https://mirror1.example.com/runtime.zip"],
        ),
    )

    assert updated["bundles"][0]["target"] == "windows-x86_64"
    assert updated["bundles"][1]["target"] == "macos-aarch64"
    assert updated["bundles"][1]["url"] == "https://new.example.com/runtime.zip"
    assert updated["bundles"][1]["urls"] == ["https://mirror1.example.com/runtime.zip"]
