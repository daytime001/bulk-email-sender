#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="一条命令生成本地 runtime 自动安装验收材料（mock runtime + zip + local manifest）"
    )
    parser.add_argument(
        "--output-dir",
        default="dist/runtime/local-smoke",
        help="输出目录",
    )
    parser.add_argument(
        "--target",
        default=f"{sys.platform}-aarch64" if sys.platform == "darwin" else f"{sys.platform}-x86_64",
        help="目标平台标识，例如 macos-aarch64",
    )
    parser.add_argument(
        "--python-version",
        default="3.11.8",
        help="mock runtime 的 python 版本",
    )
    parser.add_argument(
        "--manifest-name",
        default="local-manifest.json",
        help="manifest 文件名",
    )
    return parser.parse_args()


def main() -> None:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from bulk_email_sender.runtime_smoke import prepare_local_runtime_smoke

    args = parse_args()
    result = prepare_local_runtime_smoke(
        output_dir=Path(args.output_dir),
        target=args.target,
        python_version=args.python_version,
        manifest_name=args.manifest_name,
    )
    print(
        json.dumps(
            {
                "runtime_root": str(result.runtime_root),
                "bundle_path": str(result.bundle_path),
                "manifest_path": str(result.manifest_path),
                "manifest_url_for_ui": result.manifest_path.resolve().as_uri(),
                "target": result.target,
                "python_version": result.python_version,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
