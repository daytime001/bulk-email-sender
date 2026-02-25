import json
from pathlib import Path

import pytest

from bulk_email_sender.runtime_smoke import prepare_local_runtime_smoke


def test_prepare_local_runtime_smoke_outputs_bundle_and_manifest(tmp_path: Path) -> None:
    result = prepare_local_runtime_smoke(
        output_dir=tmp_path / "smoke",
        target="macos-aarch64",
        python_version="3.11.8",
    )

    assert result.runtime_root.exists()
    assert (result.runtime_root / "bin" / "python3").exists()
    assert result.bundle_path.exists()
    assert result.manifest_path.exists()

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    bundles = manifest.get("bundles", [])
    assert len(bundles) == 1
    assert bundles[0]["target"] == "macos-aarch64"
    assert bundles[0]["url"].startswith("file://")
    assert len(bundles[0]["sha256"]) == 64


def test_prepare_local_runtime_smoke_rejects_empty_target(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        prepare_local_runtime_smoke(
            output_dir=tmp_path / "smoke",
            target="",
            python_version="3.11.8",
        )
