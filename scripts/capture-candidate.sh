#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source_dir=workspace/stwo-zig
if [[ ! -d "$source_dir/.git" ]]; then
  printf 'Run ./setup.sh first.\n' >&2
  exit 1
fi
python3 scripts/refresh_cuda_manifests.py
git -C "$source_dir" add -N -- src/backends/cuda src/integrations/cairo_cuda src/integrations/circuit_cuda src/products/cairo_cuda src/products/circuit_recursion_cuda
mkdir -p candidate
git -C "$source_dir" diff --binary HEAD > candidate/changes.patch
python3 harness/source_policy.py --patch candidate/changes.patch --workspace "$source_dir" --already-applied
printf 'Captured %s bytes in candidate/changes.patch\n' "$(wc -c < candidate/changes.patch)"
