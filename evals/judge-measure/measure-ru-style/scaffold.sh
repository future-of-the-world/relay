#!/usr/bin/env bash
# Copies the composed replies (written by make.py) into the run folder; each grader judges one of them.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd -P)"
cp -R "$here/judged" judged
