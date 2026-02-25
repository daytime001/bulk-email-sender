#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="根据本地 runtime zip 生成 manifest（file:// URL），用于自动安装本地验收"
    )
    parser.add_argument(
        "--bundle",
        action="append",
        required=True,
        help="target=zip_path，例如 macos-aarch64=dist/runtime/python-runtime-macos-aarch64.zip",
    )
    parser.add_argument(
        "--manifest-path",
        default="dist/runtime/local-manifest.json",
        help="输出 manifest 路径",
    )
    parser.add_argument(
        "--mirror",
        action="append",
        default=[],
        help="可选镜像，格式 target=zip_path，可重复传入",
    )
    return parser.parse_args()


def main() -> None:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from bulk_email_sender.runtime_packager import RuntimeBundleEntry, calculate_sha256, upsert_manifest_bundle

    args = parse_args()
    manifest_path = Path(args.manifest_path).expanduser().resolve()

    bundle_map = parse_target_single_mapping(args.bundle)
    mirror_map = parse_target_multi_mapping(args.mirror)

    final_manifest: dict | None = None
    for target, bundle_path in bundle_map.items():
        sha256 = calculate_sha256(bundle_path)
        mirrors = [path_to_file_url(path) for path in mirror_map.get(target, [])]
        final_manifest = upsert_manifest_bundle(
            manifest_path=manifest_path,
            entry=RuntimeBundleEntry(
                target=target,
                url=path_to_file_url(bundle_path),
                sha256=sha256,
                urls=mirrors or None,
            ),
        )

    print(
        json.dumps(
            {
                "manifest_path": str(manifest_path),
                "bundle_count": len((final_manifest or {}).get("bundles", [])),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def parse_target_single_mapping(items: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for item in items:
        raw = item.strip()
        if not raw:
            continue
        if "=" not in raw:
            raise ValueError(f"参数格式错误，需为 target=path: {raw}")
        target, path = raw.split("=", 1)
        target = target.strip()
        file_path = Path(path.strip()).expanduser().resolve()
        if not file_path.exists():
            raise ValueError(f"文件不存在: {file_path}")
        result[target] = file_path
    return result


def parse_target_multi_mapping(items: list[str]) -> dict[str, list[Path]]:
    result: dict[str, list[Path]] = {}
    for item in items:
        raw = item.strip()
        if not raw:
            continue
        if "=" not in raw:
            raise ValueError(f"参数格式错误，需为 target=path: {raw}")
        target, path = raw.split("=", 1)
        target = target.strip()
        file_path = Path(path.strip()).expanduser().resolve()
        if not file_path.exists():
            raise ValueError(f"文件不存在: {file_path}")
        result.setdefault(target, []).append(file_path)
    return result


def path_to_file_url(path: Path) -> str:
    return path.resolve().as_uri()


if __name__ == "__main__":
    main()
