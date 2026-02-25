#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urljoin

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="构建 Python runtime 压缩包并更新 manifest（用于 Tauri 首启自动安装）")
    parser.add_argument("--runtime-root", required=True, help="待打包的 runtime 目录")
    parser.add_argument("--target", required=True, help="目标平台标识，例如 macos-aarch64")
    parser.add_argument("--url-prefix", required=True, help="主下载前缀，例如 https://cdn.example.com/python-runtime/")
    parser.add_argument(
        "--mirror-prefix",
        action="append",
        default=[],
        help="镜像下载前缀，可重复传入",
    )
    parser.add_argument("--output-dir", default="dist/runtime", help="runtime zip 输出目录")
    parser.add_argument("--bundle-name", help="zip 文件名，默认 python-runtime-<target>.zip")
    parser.add_argument("--manifest-path", default="dist/runtime/manifest.json", help="manifest 文件路径")
    return parser.parse_args()


def main() -> None:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from bulk_email_sender.runtime_packager import (
        RuntimeBundleEntry,
        build_runtime_bundle,
        calculate_sha256,
        upsert_manifest_bundle,
    )

    args = parse_args()
    target = args.target.strip()
    bundle_name = args.bundle_name or f"python-runtime-{target}.zip"

    runtime_root = Path(args.runtime_root).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = output_dir / bundle_name

    build_runtime_bundle(runtime_root=runtime_root, bundle_path=bundle_path)
    sha256 = calculate_sha256(bundle_path)

    primary_url = join_url(args.url_prefix, bundle_name)
    mirror_urls = [join_url(prefix, bundle_name) for prefix in args.mirror_prefix if prefix.strip()]
    entry = RuntimeBundleEntry(
        target=target,
        url=primary_url,
        sha256=sha256,
        urls=mirror_urls or None,
    )
    manifest_path = Path(args.manifest_path).expanduser().resolve()
    manifest = upsert_manifest_bundle(manifest_path=manifest_path, entry=entry)

    print(
        json.dumps(
            {
                "bundle_path": str(bundle_path),
                "bundle_size_bytes": bundle_path.stat().st_size,
                "sha256": sha256,
                "manifest_path": str(manifest_path),
                "bundle_count": len(manifest.get("bundles", [])),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def join_url(prefix: str, filename: str) -> str:
    normalized = prefix.strip()
    if not normalized:
        raise ValueError("url prefix 不能为空")
    if not normalized.endswith("/"):
        normalized = normalized + "/"
    return urljoin(normalized, filename)


if __name__ == "__main__":
    main()
