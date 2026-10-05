#!/usr/bin/env bash
# 一条命令启动完整项目：准备 Python 虚拟环境 → 安装后端依赖 →
# 构建前端（Vue3 + Vite）→ 初始化 SQLite 与演示数据 → 启动 FastAPI。
#
# 用法：
#   ./run.sh            # 生产模式：构建前端后由 FastAPI 托管，访问 http://localhost:8000
#   ./run.sh dev        # 开发模式：同时启动 Vite(5173) 热更新与 FastAPI(8000)
#   PORT=9000 ./run.sh  # 自定义端口
set -euo pipefail

cd "$(dirname "$0")"
PORT="${PORT:-8000}"
MODE="${1:-serve}"

# ---------- 1. Python 虚拟环境 ----------
if [ ! -d ".venv" ]; then
  echo "▶ 创建 Python 虚拟环境 .venv"
  python3 -m venv .venv
fi
# 某些精简系统 venv 不带 pip，做一次引导兜底
if [ ! -x ".venv/bin/pip" ]; then
  echo "▶ venv 中没有 pip，尝试引导安装"
  WHEEL="$(ls -t /tmp/pip-*-py3-none-any.whl 2>/dev/null | head -1 || true)"
  if [ -z "${WHEEL}" ]; then
    WHEEL="/tmp/pip-bootstrap.whl"
    curl -fsSL --retry 5 -o "$WHEEL" \
      "https://files.pythonhosted.org/packages/f3/6e/1736e5b4ae2b778ef2f81c47d797de9f891d4d8acb047a24ca37a60294dd/pip-26.2.1-py3-none-any.whl"
  fi
  .venv/bin/python "$WHEEL/pip install" "$WHEEL"
fi
echo "▶ 安装/检查后端 Python 依赖"
.venv/bin/pip install -q --retries 5 -r backend/requirements.txt

# ---------- 2. 前端依赖与构建 ----------
if [ ! -d "frontend/node_modules" ]; then
  echo "▶ 安装前端依赖（npm install）"
  (cd frontend && npm install --no-audit --no-fund)
fi
if [ "$MODE" != "dev" ]; then
  echo "▶ 构建前端静态资源（vite build）"
  (cd frontend && npm run build)
fi

# ---------- 3. 启动 ----------
if [ "$MODE" = "dev" ]; then
  echo "▶ 开发模式：FastAPI http://localhost:${PORT} ｜ Vite http://localhost:5173"
  .venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port "${PORT}" &
  API_PID=$!
  (cd frontend && npm run dev) &
  WEB_PID=$!
  trap 'kill ${API_PID} ${WEB_PID} 2>/dev/null || true' EXIT
  wait
else
  echo "▶ 启动服务：请访问 http://localhost:${PORT}（API 文档 /docs）"
  exec .venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port "${PORT}"
fi
