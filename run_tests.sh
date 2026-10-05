#!/usr/bin/env bash
# 运行后端业务规则测试
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "请先运行 ./start.sh 初始化环境" >&2
  exit 1
fi
exec ./.venv/bin/python -m pytest backend/tests -v
