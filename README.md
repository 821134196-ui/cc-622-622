# 样书寄送与作者签收系统

小型出版社内部系统：编辑确认作者地址，仓库按**书的版次**出库生成包裹；作者签收时
填写实收份数，可反馈**少件 / 破损 / 拒收**；补寄记录继续挂在原寄送任务下。
待办页优先暴露长时间未签收与数量不一致的包裹。

技术栈：**Python 3.11 + FastAPI + SQLAlchemy 2 + SQLite + Vue 3 (Vite)**，
快递轨迹本地模拟，无需任何外部服务。

## 一条命令启动

```bash
./run.sh          # 构建前端并由 FastAPI 统一托管 → http://localhost:8000
./run.sh dev      # 开发模式：FastAPI :8000 + Vite 热更新 :5173
PORT=9000 ./run.sh
```

脚本会自动：创建 `.venv` → 安装后端依赖 → `npm install` → `vite build` →
初始化 SQLite（`sample_books.db`）并写入演示数据 → 启动 uvicorn。

- 首页：http://localhost:8000
- API 文档（Swagger）：http://localhost:8000/docs

首次启动已有演示数据：6 天未签收的在途包裹、少件补寄在途、拒收后重寄、
同书新旧版次独立（旧版已寄达不抵扣新版）。

重置演示数据：删除 `sample_books.db` 后重新启动。

## 测试

```bash
.venv/bin/python -m pytest tests/ -v
```

10 个端到端用例（TestClient + 临时 SQLite）全部覆盖以下验收点。

## 核心业务规则与实现位置

| 规则 | 实现 |
| --- | --- |
| **拒收不算签收**：拒收回执 `received_qty=0`，不计入包裹/任务实收，任务判为数量异常 | `backend/services.py` `submit_receipt` |
| **少件/破损补寄归原任务**：补寄包裹与补寄记录都挂原 `ShippingTask`，缺件原因（类型+详情）冻结留痕，且必须与原回执记录对得上 | `backend/services.py` `create_reshipment`、`models.Reshipment` |
| **地址改派只追加**：出库后地址变化新增 `AddressRedirect`（含新旧地址快照），`Parcel` 地址字段与 `OutboundRecord` 永不修改 | `backend/services.py` `redirect_address` |
| **重复回执幂等**：回执号 `receipt_no` 唯一；重复提交原样返回（`duplicate=true`），不新增回执、不增加实收 | `backend/services.py` `submit_receipt` |
| **旧版不抵扣新版**：任务绑定唯一版次，补寄强制继承任务版次；所有数量汇总只在同任务同版次内进行，结构上无法跨版次抵扣 | `models.ShippingTask.edition_id`、`_outbound`、`summarize_task` |
| **待办优先级**：数量不一致（含拒收未补齐）权重最高；在途包裹按未签收天数加权，滞留越久越靠前 | `backend/services.py` `todo_list` |
| **不可变出库流水**：包裹与出库记录 1:1，记录版次、份数、是否补寄，后续任何操作不改写 | `models.OutboundRecord` |
| **快递轨迹本地模拟**：出库生成初始轨迹，可逐节点推进；签收/拒收/改派/补寄自动追加事件 | `services._seed_outbound_tracking` / `advance_tracking` |

## 数量核对口径（任务详情页直观展示）

- **应寄**：该版次约定份数 `required_qty`
- **原寄出库 / 补寄出库**：分别统计，合计 `total_shipped`
- **作者实收**：只统计 `signed` 回执的 `received_qty`；**拒收恒为 0**
- **少件 / 破损 / 拒收包裹 / 在途**：独立计数
- 全部包裹了结后：实收 ≥ 应寄 → `completed`，否则 → `abnormal`

## 页面

- **待办**：高优待办卡片（数量异常红边、滞留在途黄边），显示原因与优先级分。
- **全部任务**：左侧任务列表，右侧任务详情 —— 数量核对指标、地址确认、原寄出库、
  每个包裹的地址快照/改派留痕/回执/补寄表单/模拟轨迹时间线。
- **新建 / 资料**：新建任务（作者 + 版次 + 应寄份数）、维护作者与书版次。

## API 摘要

```
POST /api/authors | /api/editions | /api/tasks
POST /api/tasks/{id}/confirm-address        编辑确认地址
POST /api/outbound                          仓库原寄出库（生成包裹+出库记录+初始轨迹）
POST /api/parcels/{id}/redirect             追加改派（不改原记录）
POST /api/parcels/{id}/advance-tracking     模拟快递推进
POST /api/receipts                          签收/拒收（receipt_no 幂等）
POST /api/reshipments                       补寄（挂原任务，带原因）
GET  /api/todos                             待办（按优先级）
GET  /api/tasks | /api/tasks/{id}           任务与数量汇总
```

## 目录结构

```
backend/   models.py / schemas.py / services.py(业务规则) / main.py(API) / seed.py
frontend/  Vue3 + Vite（src/App.vue、src/components/TaskDetail.vue）
tests/     test_business_rules.py
run.sh     一条命令启动
```
