#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "[1/5] Python tests"
cd "$ROOT_DIR"
uv run pytest -q

echo "[2/5] Desktop lint"
cd "$ROOT_DIR/apps/desktop"
npm run lint

echo "[3/5] Desktop build"
npm run build

echo "[4/5] Rust tests"
if [[ -f "$HOME/.cargo/env" ]]; then
  # shellcheck disable=SC1091
  source "$HOME/.cargo/env"
fi
cd "$ROOT_DIR/apps/desktop/src-tauri"
cargo test -q

echo "[5/5] Tauri app bundle (debug)"
cd "$ROOT_DIR/apps/desktop"
npm run tauri:build:app -- --debug

echo "All checks passed."
