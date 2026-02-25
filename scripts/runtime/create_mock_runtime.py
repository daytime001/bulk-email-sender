#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成本地 mock Python runtime（用于首启自动安装链路验收）")
    parser.add_argument(
        "--output-root",
        default="dist/runtime/mock_runtime",
        help="输出 runtime 根目录",
    )
    parser.add_argument(
        "--python-version",
        default="3.11.8",
        help="`python3 --version` 返回值中的版本号",
    )
    return parser.parse_args()


def main() -> None:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from bulk_email_sender.runtime_smoke import create_mock_runtime

    args = parse_args()
    output_root = create_mock_runtime(
        runtime_root=Path(args.output_root),
        python_version=args.python_version,
    )
    python3_path = output_root / "bin" / "python3"
    python_path = output_root / "bin" / "python"

    print(
        json.dumps(
            {
                "runtime_root": str(output_root),
                "python3": str(python3_path),
                "python": str(python_path),
                "python_version": args.python_version,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
