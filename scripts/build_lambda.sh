#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf build/lambda && mkdir -p build/lambda
pip install --quiet --target build/lambda \
  --platform manylinux2014_x86_64 --implementation cp --python-version 3.12 \
  --only-binary=:all: PyYAML
cp lambda/handler.py lambda/contract_validator.py build/lambda/
echo "Lambda package: build/lambda"
