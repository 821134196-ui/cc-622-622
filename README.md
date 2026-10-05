# 出版社样书寄送与作者签收系统

编辑与仓库按「作者 × 版次」核对应寄与实收数量的内部系统: 编辑确认作者地址并创建寄送任务,
仓库按版次出库生成包裹, 作者签收时填写实收份数, 少件/破损/拒收后的补寄记录挂在原任务下,
全流程可核对原寄、补寄与实际收到的数量。

## 一条命令启动

```bash
./start.sh
```

自动完成: 创建 Python 虚拟环境 → 安装后端依赖 → 构建 Vue 前端 → 启动服务。
打开 http://localhost:8000 (API 文档: http://localhost:8000/docs)。
首次启动会写入演示数据(两个图书版次、三位作者、四种状态的寄送任务)。

运行测试:

```bash
./run_tests.sh        # 或: .venv/bin/python -m pytest backend/tests -v
```

## 技术栈

- **后端**: Python + FastAPI + SQLAlchemy + SQLite(`data/sampleship.db`)
- **前端**: Vue 3 + Vue Router + Vite(构建产物由 FastAPI 托管, 同源无跨域)
- **快递轨迹**: 本地模拟(出库播种 → 「推进轨迹」逐步流转 → 签收/拒收终结)

## 核心业务规则

| 规则 | 实现 |
| --- | --- |
| 拒收不算签收 | 回执 `result=rejected` 时实收强制为 0, 任务不计完成 |
| 重复回执不加实收 | 回执按幂等键去重(同键重放返回原回执); 每包裹至多一条回执, 不同键重复提交返回 409 |
| 少件补寄归入原任务 | 补寄包裹 `task_id` 与原包裹相同, `parent_package_id` 指向原包裹, 保留缺件原因(`reship_reason`/`reship_note`) |
| 地址改派不改原记录 | 包裹地址为出库时快照、不可变; 改派只追加 `reroutes` 记录与轨迹事件 |
| 旧版不抵新版 | 应寄/实收严格按任务(作者×版次)归集, 作者对账页按版次逐行展示, 互不抵扣 |
| 待办优先 | 数量不一致(少件/破损/拒收)与超过 N 天未签收的包裹优先生成待办, 按优先级排序 |

## 页面

- **待办** `/todos`: 优先展示长时间未签收与数量不一致的包裹
- **寄送任务** `/tasks`: 创建任务、查看 应寄/已寄/实收/差额; 详情页出库、签收、补寄、改派、轨迹
- **作者与地址** `/authors`: 编辑确认地址(当前地址), 按版次对账
- **图书与版次** `/books`: 图书与版次维护

## 主要 API

```
POST /api/authors                      新建作者
POST /api/authors/{id}/addresses       新增地址
POST /api/addresses/{id}/confirm       编辑确认为当前地址
POST /api/tasks                        创建寄送任务(作者×版次×应寄数量)
POST /api/tasks/{id}/packages          仓库出库(地址快照 + 生成运单)
POST /api/packages/{id}/receipt        签收回执(幂等键, 拒收实收归零)
POST /api/packages/{id}/reship         补寄(挂原任务, 保留缺件原因)
POST /api/packages/{id}/reroute        地址改派(只追加记录)
POST /api/packages/{id}/tracking/advance  推进模拟轨迹
GET  /api/todos?unsigned_days=7        待办(未签收超时 + 数量不一致)
GET  /api/authors/{id}                 作者详情 + 按版次对账
```

## 目录结构

```
backend/
  app/
    main.py        FastAPI 路由与静态托管
    models.py      SQLAlchemy 模型(任务/包裹/回执/补寄/改派/轨迹)
    services.py    业务规则(出库/签收/补寄/改派/对账/待办)
    schemas.py     Pydantic 请求模型
    seed.py        演示数据
    database.py    引擎与会话
  tests/
    test_business_rules.py   业务规则验证(7 个用例)
frontend/
  src/views/       待办/任务/任务详情/作者/图书 五个页面
start.sh           一条命令启动
run_tests.sh       运行测试
```
