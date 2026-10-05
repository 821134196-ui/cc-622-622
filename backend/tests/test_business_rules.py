"""业务规则验证:
1. 拒收不会被算作签收
2. 少件补寄归入原任务, 且保留缺件原因
3. 地址改派只追加记录, 不改原包裹地址与出库记录
4. 重复签收回执不增加实收数量
5. 旧版样书不能抵扣新版应寄份数
6. 待办优先显示长时间未签收与数量不一致的包裹
"""
from datetime import datetime, timedelta

from backend.app import models as m
from backend.tests.conftest import (make_author, make_book_with_editions,
                                    make_task, receipt, ship, task)


# ---------------------------------------------------------- 1. 拒收不算签收

def test_rejection_not_counted_as_signed(env):
    c = env.client
    author_id, _ = make_author(c)
    _, eds = make_book_with_editions(c)
    task_id = make_task(c, author_id, eds["第2版"], 5)
    pkg = ship(c, task_id, 5)

    r = receipt(c, pkg["id"], "rejected", 0, key="k-rej-1", note="作者拒收")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["result"] == "rejected"
    assert body["received_qty"] == 0          # 拒收实收恒为 0

    s = task(c, task_id)
    assert s["quantity_received"] == 0        # 不计入签收数量
    assert s["status"] != "completed"
    assert s["outstanding"] == 5
    assert s["packages"][0]["status"] == "rejected"

    # 即使回执里误填实收数量, 拒收也强制归零
    author2, _ = make_author(c, name="陈默")
    task2 = make_task(c, author2, eds["第2版"], 3)
    pkg2 = ship(c, task2, 3)
    r = receipt(c, pkg2["id"], "rejected", 3, key="k-rej-2")
    assert r.status_code == 201, r.text
    assert r.json()["received_qty"] == 0
    assert task(c, task2)["quantity_received"] == 0


# -------------------------------------------- 2. 少件补寄归入原任务并保留缺件原因

def test_missing_reshipment_attached_to_original_task(env):
    c = env.client
    author_id, _ = make_author(c)
    _, eds = make_book_with_editions(c)
    task_id = make_task(c, author_id, eds["第1版"], 5)
    pkg = ship(c, task_id, 5)

    r = receipt(c, pkg["id"], "missing", 3, key="k-mis-1", note="少 2 册")
    assert r.status_code == 201, r.text
    s = task(c, task_id)
    assert s["quantity_received"] == 3
    assert s["status"] == "mismatch"          # 包裹终结但实收不足

    # 补寄: 挂在原任务下
    r = c.post(f"/api/packages/{pkg['id']}/reship",
               json={"quantity": 2, "reason": "missing",
                     "note": "少件 2 册补寄", "shipped_by": "仓库-测试"})
    assert r.status_code == 201, r.text
    reship_pkg = r.json()
    assert reship_pkg["task_id"] == task_id           # 归入原任务
    assert reship_pkg["parent_package_id"] == pkg["id"]
    assert reship_pkg["reship_reason"] == "missing"   # 保留缺件原因
    assert "少件" in reship_pkg["reship_note"]

    # 补寄包裹签收后, 原任务实收合并统计并完成
    r = receipt(c, reship_pkg["id"], "received", 2, key="k-mis-2")
    assert r.status_code == 201, r.text
    s = task(c, task_id)
    assert s["quantity_shipped"] == 7          # 原寄 5 + 补寄 2
    assert s["quantity_received"] == 5         # 3 + 2
    assert s["status"] == "completed"
    kinds = {(p["id"], p["parent_package_id"]) for p in s["packages"]}
    assert (reship_pkg["id"], pkg["id"]) in kinds

    # 未签收不能补寄
    pkg3 = ship(c, task_id, 1)
    r = c.post(f"/api/packages/{pkg3['id']}/reship", json={"quantity": 1})
    assert r.status_code == 409


# -------------------------------------- 3. 地址改派不改原包裹地址与出库记录

def test_reroute_keeps_original_package_and_shipment(env):
    c = env.client
    author_id, _ = make_author(c)
    _, eds = make_book_with_editions(c)
    task_id = make_task(c, author_id, eds["第1版"], 2)
    pkg = ship(c, task_id, 2)
    orig_addr = dict(pkg["address"])
    orig_shipped_at = pkg["shipped_at"]
    orig_qty = pkg["quantity"]

    # 包裹出库后地址变化: 追加改派记录
    r = c.post(f"/api/packages/{pkg['id']}/reroute", json={
        "recipient": "林晚晴(新)", "phone": "13900000009",
        "region": "上海市 徐汇区", "detail": "漕溪北路 1 号",
        "reason": "作者搬家", "created_by": "编辑-测试"})
    assert r.status_code == 201, r.text

    after = c.get(f"/api/packages/{pkg['id']}").json()
    assert after["address"] == orig_addr               # 原地址快照不变
    assert after["shipped_at"] == orig_shipped_at      # 出库记录不变
    assert after["quantity"] == orig_qty
    assert len(after["reroutes"]) == 1                 # 只有一条追加的改派记录
    assert after["reroutes"][0]["detail"] == "漕溪北路 1 号"
    assert any(e["status"] == "reroute" for e in after["tracking_events"])

    # 作者确认新地址后, 原包裹快照依然不变
    r = c.post(f"/api/authors/{author_id}/addresses", json={
        "recipient": "林晚晴(新)", "phone": "13900000009",
        "region": "上海市 徐汇区", "detail": "漕溪北路 1 号"})
    new_addr_id = r.json()["id"]
    c.post(f"/api/addresses/{new_addr_id}/confirm", json={})
    after2 = c.get(f"/api/packages/{pkg['id']}").json()
    assert after2["address"] == orig_addr

    # 已签收包裹不允许改派
    receipt(c, pkg["id"], "received", 2, key="k-rer-1")
    r = c.post(f"/api/packages/{pkg['id']}/reroute", json={
        "recipient": "x", "phone": "1", "detail": "y"})
    assert r.status_code == 409


# -------------------------------------------- 4. 重复签收回执不增加实收数量

def test_duplicate_receipt_does_not_inflate_received(env):
    c = env.client
    author_id, _ = make_author(c)
    _, eds = make_book_with_editions(c)
    task_id = make_task(c, author_id, eds["第1版"], 4)
    pkg = ship(c, task_id, 4)

    # 同一幂等键重复提交 -> 同一条回执, 实收不翻倍
    r1 = receipt(c, pkg["id"], "received", 4, key="k-dup-1")
    assert r1.status_code == 201, r1.text
    r2 = receipt(c, pkg["id"], "received", 4, key="k-dup-1")
    assert r2.status_code == 201, r2.text
    assert r2.json()["id"] == r1.json()["id"]
    assert task(c, task_id)["quantity_received"] == 4

    # 不同幂等键对已签收包裹再次回执 -> 409, 实收不变
    r3 = receipt(c, pkg["id"], "received", 4, key="k-dup-2")
    assert r3.status_code == 409
    s = task(c, task_id)
    assert s["quantity_received"] == 4
    assert s["status"] == "completed"
    assert len([p for p in s["packages"] if p["receipt"]]) == 1  # 仍只有一条回执


# ------------------------------------------ 5. 旧版样书不能抵扣新版应寄份数

def test_old_edition_does_not_offset_new_edition(env):
    c = env.client
    author_id, _ = make_author(c)
    _, eds = make_book_with_editions(c)

    # 第1版任务: 应寄 2, 全部签收完成
    t_old = make_task(c, author_id, eds["第1版"], 2)
    pkg_old = ship(c, t_old, 2)
    receipt(c, pkg_old["id"], "received", 2, key="k-ed-1")
    assert task(c, t_old)["status"] == "completed"

    # 第2版任务: 应寄 3 —— 旧版已签收的数量不能抵扣
    t_new = make_task(c, author_id, eds["第2版"], 3)
    s_new = task(c, t_new)
    assert s_new["quantity_received"] == 0
    assert s_new["outstanding"] == 3
    assert s_new["status"] == "pending"

    # 作者维度对账: 两个版次各自独立归集
    recon = c.get(f"/api/authors/{author_id}").json()["reconciliation"]
    by_ed = {row["edition_no"]: row for row in recon}
    assert by_ed["第1版"]["quantity_received"] == 2
    assert by_ed["第1版"]["outstanding"] == 0
    assert by_ed["第2版"]["quantity_received"] == 0
    assert by_ed["第2版"]["outstanding"] == 3


# -------------------------------- 6. 待办优先显示长时间未签收与数量不一致包裹

def test_todo_prioritizes_overdue_and_mismatch(env):
    c = env.client
    author_id, _ = make_author(c)
    _, eds = make_book_with_editions(c)

    # 包裹A: 出库 10 天未签收
    t1 = make_task(c, author_id, eds["第1版"], 2)
    pkg_a = ship(c, t1, 2)
    # 包裹B: 少件(数量不一致)
    t2 = make_task(c, author_id, eds["第2版"], 3)
    pkg_b = ship(c, t2, 3)
    receipt(c, pkg_b["id"], "missing", 1, key="k-todo-1")
    # 包裹C: 刚出库, 正常在途 —— 不应出现在待办
    t3 = make_task(c, author_id, eds["第1版"], 1)
    pkg_c = ship(c, t3, 1)

    # 把包裹A出库时间改到 10 天前(直接改库模拟时间流逝)
    db = env.SessionLocal()
    db.query(m.Package).filter_by(id=pkg_a["id"]).update(
        {m.Package.shipped_at: datetime.utcnow() - timedelta(days=10)})
    db.commit()
    db.close()

    r = c.get("/api/todos")
    assert r.status_code == 200, r.text
    todos = r.json()
    ids = [t["package_id"] for t in todos]
    assert pkg_a["id"] in ids                       # 长时间未签收 -> 上榜
    assert pkg_b["id"] in ids                       # 数量不一致 -> 上榜
    assert pkg_c["id"] not in ids                   # 正常在途 -> 不上榜

    by_pkg = {t["package_id"]: t for t in todos}
    assert by_pkg[pkg_a["id"]]["kind"] == "overdue"
    assert by_pkg[pkg_a["id"]]["age_days"] >= 10
    assert by_pkg[pkg_b["id"]]["kind"] == "mismatch"
    # 数量不一致排在最前
    assert todos[0]["package_id"] == pkg_b["id"]


# ------------------------------------------------ 附加: 出库前置校验

def test_ship_requires_confirmed_current_address(env):
    c = env.client
    author_id, _ = make_author(c, name="苏子航", confirm=False)  # 地址未确认
    _, eds = make_book_with_editions(c)
    task_id = make_task(c, author_id, eds["第1版"], 1)
    r = c.post(f"/api/tasks/{task_id}/packages",
               json={"quantity": 1, "shipped_by": "仓库-测试"})
    assert r.status_code == 409                     # 无已确认地址不能出库
