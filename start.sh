#!/usr/bin/env bash
# 一条命令启动完整项目: 后端(FastAPI+SQLite) + 前端(Vue 构建产物)
set -e
cd "$(dirname "$0")"

PORT="${PORT:-8000}"

# ---- 1. Python 虚拟环境(部分系统缺少 ensurepip, 自动回退 get-pip) ----
if [ ! -x .venv/bin/python ]; then
  echo "==> 创建 Python 虚拟环境"
  python3 -m venv .venv 2>/dev/null || python3 -m venv --without-pip .venv
fi
if [ ! -x .venv/bin/pip ]; then
  echo "==> 引导 pip"
  curl -sSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
  ./.venv/bin/python /tmp/get-pip.py -q
fi

# ---- 2. 后端依赖 ----
if [ ! -f .venv/.deps-ok ] || [ backend/requirements.txt -nt .venv/.deps-ok ]; then
  echo "==> 安装后端依赖"
  ./.venv/bin/pip install -q -r backend/requirements.txt
  touch .venv/.deps-ok
fi

# ---- 3. 前端构建 ----
if [ ! -d frontend/dist ] || [ frontend/src -nt frontend/dist ]; then
  echo "==> 构建前端"
  (cd frontend && npm install --no-audit --no-fund && npm run build)
fi

# ---- 4. 启动(后端同时托管 API 与前端静态文件) ----
echo "==> 启动完成: http://localhost:${PORT}  (API 文档: http://localhost:${PORT}/docs)"
exec ./.venv/bin/python -m uvicorn backend.app.main:app --host 0.0.0.0 --port "${PORT}"
