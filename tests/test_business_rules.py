"""端到端业务规则测试（FastAPI TestClient + 临时 SQLite）。

覆盖验收点：
1. 拒收不会被算作签收；
2. 少件补寄归入原任务，并保留缺件原因；
3. 地址改派只追加记录，不改原包裹地址和出库记录；
4. 重复签收回执不增加实收数量；
5. 旧版样书不能抵扣新版应寄份数；
6. 待办排序：长时间未签收、数量不一致优先；
7. 破损补寄、拒收重寄流程正确；
8. 出库记录不可变（改派/补寄不影响原出库流水）。
"""
import os
import sys
import tempfile
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

# 每个测试会话使用独立临时数据库
_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP.name}"
os.environ["SEED_DEMO"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import Base, SessionLocal, engine  # noqa: E402
from backend import models, services  # noqa: E402
from backend.main import app, init_db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _setup():
    Base.metadata.drop_all(bind=engine)
    init_db(seed=False)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


# ------------------------------------------------------------ 辅助

def _make_author_edition(client, name="测试作者", title="测试书", edition="第1版"):
    a = client.post("/api/authors", json={"name": name}).json()
    e = client.post("/api/editions", json={
        "title": title, "edition": edition, "isbn": ""}).json()
    return a, e


def _create_confirmed_task(client, author_id, edition_id, qty, addr="测试地址 1 号"):
    t = client.post("/api/tasks", json={
        "author_id": author_id, "edition_id": edition_id,
        "required_qty": qty}).json()
    client.post(f"/api/tasks/{t['id']}/confirm-address", json={
        "recipient": "本人", "phone": "13900000000", "address": addr})
    return client.get(f"/api/tasks/{t['id']}").json()


def _outbound(client, task_id, qty):
    return client.post("/api/outbound", json={
        "task_id": task_id, "qty": qty}).json()


# ============================================================ 1. 拒收

def test_rejection_not_counted_as_signed(client):
    a, e = _make_author_edition(client, name="拒收作者", title="拒收书")
    t = _create_confirmed_task(client, a["id"], e["id"], 4)
    p = _outbound(client, t["id"], 4)

    r = client.post("/api/receipts", json={
        "parcel_id": p["id"], "receipt_no": "RT-REJ-01",
        "action": "rejected", "note": "不要了"}).json()
    assert r["action"] == "rejected"
    assert r["received_qty"] == 0

    t2 = client.get(f"/api/tasks/{t['id']}").json()
    p2 = next(x for x in t2["parcels"] if x["id"] == p["id"])
    assert p2["state"] == "rejected"
    assert p2["received_qty"] == 0            # 拒收不计入包裹实收
    assert t2["received_qty"] == 0            # 不计入任务实收
    assert t2["rejected_count"] == 1
    # 全部包裹了结但实收 0 < 应寄 4 => 数量异常，而不是已完成
    assert t2["status"] == "abnormal"


# ============================================================ 2. 少件补寄归原任务

def test_shortage_reship_stays_under_original_task(client):
    a, e = _make_author_edition(client, name="少件作者", title="少件书")
    t = _create_confirmed_task(client, a["id"], e["id"], 8)
    p = _outbound(client, t["id"], 8)

    client.post("/api/receipts", json={
        "parcel_id": p["id"], "receipt_no": "RT-SHORT-01",
        "action": "signed", "received_qty": 6, "damaged_qty": 0,
        "note": "少 2 本"})

    rs = client.post("/api/reshipments", json={
        "source_parcel_id": p["id"], "reason_type": "shortage",
        "qty": 2, "reason_detail": "签收少件 2 份"}).json()
    assert rs["task_id"] == t["id"]               # 挂在原任务下
    assert rs["source_parcel_id"] == p["id"]
    assert rs["reason_type"] == "shortage"
    assert rs["qty"] == 2

    t2 = client.get(f"/api/tasks/{t['id']}").json()
    assert len(t2["parcels"]) == 2
    new_p = next(x for x in t2["parcels"] if x["id"] == rs["new_parcel_id"])
    assert new_p["is_reship"] is True
    # 补寄包裹与原寄同版次
    assert new_p["edition_id"] == e["id"]
    # 原寄 8 + 补寄 2 分开统计；实收暂为 6，补寄在途
    assert t2["original_shipped_qty"] == 8
    assert t2["reship_shipped_qty"] == 2
    assert t2["total_shipped_qty"] == 10
    assert t2["received_qty"] == 6
    assert t2["shortage_total"] == 2
    assert t2["status"] == "shipping"

    # 补寄签收后任务完成，实收 = 原 6 + 补 2 = 8
    client.post("/api/receipts", json={
        "parcel_id": new_p["id"], "receipt_no": "RT-SHORT-02",
        "action": "signed", "received_qty": 2})
    t3 = client.get(f"/api/tasks/{t['id']}").json()
    assert t3["received_qty"] == 8
    assert t3["status"] == "completed"


def test_reship_requires_matching_reason(client):
    """没有少件记录不能按少件补寄；破损同理。"""
    a, e = _make_author_edition(client, name="原因作者", title="原因书")
    t = _create_confirmed_task(client, a["id"], e["id"], 3)
    p = _outbound(client, t["id"], 3)
    client.post("/api/receipts", json={
        "parcel_id": p["id"], "receipt_no": "RT-OK-01",
        "action": "signed", "received_qty": 3})
    resp = client.post("/api/reshipments", json={
        "source_parcel_id": p["id"], "reason_type": "shortage", "qty": 1})
    assert resp.status_code == 422


# ============================================================ 3. 地址改派不改原记录

def test_redirect_appends_only(client, db):
    a, e = _make_author_edition(client, name="改派作者", title="改派书")
    t = _create_confirmed_task(client, a["id"], e["id"], 2, addr="旧地址 A")
    p = _outbound(client, t["id"], 2)

    original_snapshot = (p["recipient"], p["phone"], p["address"])

    rp = client.post(f"/api/parcels/{p['id']}/redirect", json={
        "parcel_id": p["id"], "new_recipient": "新收件人",
        "new_phone": "13700000000", "new_address": "新地址 B",
        "reason": "作者搬家"}).json()

    # 原包裹地址快照不变
    assert (rp["recipient"], rp["phone"], rp["address"]) == original_snapshot
    assert rp["address"] == "旧地址 A"
    assert len(rp["redirects"]) == 1
    rd = rp["redirects"][0]
    assert rd["old_address"] == "旧地址 A"
    assert rd["new_address"] == "新地址 B"
    assert rd["new_recipient"] == "新收件人"

    # 出库记录不可变：仍记录原 qty / 版次 / 非补寄
    db.expire_all()
    rec = db.scalar(select(models.OutboundRecord).where(
        models.OutboundRecord.parcel_id == p["id"]))
    assert rec.qty == 2
    assert rec.edition_id == e["id"]
    assert rec.is_reship is False

    # 轨迹中只追加改派事件
    types = [ev["event_type"] for ev in rp["tracking_events"]]
    assert "redirect" in types

    # 已了结包裹不允许改派
    client.post("/api/receipts", json={
        "parcel_id": p["id"], "receipt_no": "RT-RED-01",
        "action": "signed", "received_qty": 2})
    resp = client.post(f"/api/parcels/{p['id']}/redirect", json={
        "parcel_id": p["id"], "new_recipient": "x",
        "new_address": "y"})
    assert resp.status_code == 409


# ============================================================ 4. 重复回执幂等

def test_duplicate_receipt_is_idempotent(client, db):
    a, e = _make_author_edition(client, name="重复作者", title="重复书")
    t = _create_confirmed_task(client, a["id"], e["id"], 5)
    p = _outbound(client, t["id"], 5)

    first = client.post("/api/receipts", json={
        "parcel_id": p["id"], "receipt_no": "RT-DUP-01",
        "action": "signed", "received_qty": 4,
        "note": "少 1 本"}).json()
    assert first["duplicate"] is False
    first_id = first["id"]

    # 同编号再交一次（哪怕内容不同）：必须返回原记录，不新增、不加数量
    again = client.post("/api/receipts", json={
        "parcel_id": p["id"], "receipt_no": "RT-DUP-01",
        "action": "signed", "received_qty": 5}).json()
    assert again["duplicate"] is True
    assert again["id"] == first_id
    assert again["received_qty"] == 4

    db.expire_all()
    parcel = db.get(models.Parcel, p["id"])
    receipts = parcel.receipts
    assert len(receipts) == 1                  # 只有一条回执
    assert services.parcel_received_qty(parcel) == 4

    t2 = client.get(f"/api/tasks/{t['id']}").json()
    assert t2["received_qty"] == 4
    # 包裹已签收，换新回执号再签也应被拒
    resp = client.post("/api/receipts", json={
        "parcel_id": p["id"], "receipt_no": "RT-DUP-02",
        "action": "signed", "received_qty": 1})
    assert resp.status_code == 409


# ============================================================ 5. 版次隔离

def test_old_edition_does_not_credit_new_edition(client):
    a, e1 = _make_author_edition(client, name="版次作者", title="版次书", edition="第1版")
    e2 = client.post("/api/editions", json={
        "title": "版次书", "edition": "第2版", "isbn": ""}).json()

    # 旧版任务：寄 5 收 5，已完成
    t_old = _create_confirmed_task(client, a["id"], e1["id"], 5, addr="旧版地址")
    p_old = _outbound(client, t_old["id"], 5)
    client.post("/api/receipts", json={
        "parcel_id": p_old["id"], "receipt_no": "RT-ED-OLD",
        "action": "signed", "received_qty": 5})

    # 新版任务：应寄 6，旧版已完成不产生任何抵扣
    t_new = _create_confirmed_task(client, a["id"], e2["id"], 6, addr="新版地址")
    p_new = _outbound(client, t_new["id"], 6)

    # 即便新版只收到 4（少件），任务状态仍按新版自身核对
    client.post("/api/receipts", json={
        "parcel_id": p_new["id"], "receipt_no": "RT-ED-NEW",
        "action": "signed", "received_qty": 4})

    t_old2 = client.get(f"/api/tasks/{t_old['id']}").json()
    t_new2 = client.get(f"/api/tasks/{t_new['id']}").json()
    assert t_old2["status"] == "completed"
    assert t_old2["received_qty"] == 5
    assert t_new2["status"] == "abnormal"      # 4 < 6，不因旧版完成而达标
    assert t_new2["received_qty"] == 4
    assert t_new2["required_qty"] == 6
    # 两任务的包裹各自只属于自己的版次
    assert all(x["edition_id"] == e2["id"] for x in t_new2["parcels"])
    assert all(x["edition_id"] == e1["id"] for x in t_old2["parcels"])


# ============================================================ 6. 待办优先级

def test_todo_priorities(client, db):
    a, e = _make_author_edition(client, name="待办作者", title="待办书")
    # 在途 10 天的包裹
    t1 = _create_confirmed_task(client, a["id"], e["id"], 3, addr="地址 X")
    p1 = _outbound(client, t1["id"], 3)
    db.expire_all()
    parcel = db.get(models.Parcel, p1["id"])
    parcel.outbound_at -= timedelta(days=10)
    for ev in parcel.tracking_events:
        ev.occurred_at -= timedelta(days=10)
    db.commit()

    # 数量异常任务（全部了结但少收）
    a2, e2b = _make_author_edition(client, name="待办作者2", title="待办书2")
    t2 = _create_confirmed_task(client, a2["id"], e2b["id"], 5, addr="地址 Y")
    p2 = _outbound(client, t2["id"], 5)
    client.post("/api/receipts", json={
        "parcel_id": p2["id"], "receipt_no": "RT-TODO-01",
        "action": "signed", "received_qty": 2})

    todos = client.get("/api/todos").json()
    ids = [item["task"]["id"] for item in todos]
    assert t2["id"] in ids and t1["id"] in ids
    # 数量不一致（基准 100+）必须排在单纯在途滞留前面
    assert ids.index(t2["id"]) < ids.index(t1["id"])
    item_t2 = next(i for i in todos if i["task"]["id"] == t2["id"])
    assert any("数量不一致" in r for r in item_t2["reasons"])

    # 已完成任务不应出现在待办
    t_done = _create_confirmed_task(client, a["id"], e["id"], 1, addr="地址 Z")
    # 同作者+同版次可建多个任务；完成它
    p3 = _outbound(client, t_done["id"], 1)
    client.post("/api/receipts", json={
        "parcel_id": p3["id"], "receipt_no": "RT-TODO-DONE",
        "action": "signed", "received_qty": 1})
    todos2 = client.get("/api/todos").json()
    assert t_done["id"] not in [i["task"]["id"] for i in todos2]


# ============================================================ 7. 破损 + 拒收重寄

def test_damaged_and_rejected_reship(client):
    a, e = _make_author_edition(client, name="破损作者", title="破损书")
    t = _create_confirmed_task(client, a["id"], e["id"], 5)
    p = _outbound(client, t["id"], 5)
    # 签 3，破损 1，少件 1
    client.post("/api/receipts", json={
        "parcel_id": p["id"], "receipt_no": "RT-DMG-01",
        "action": "signed", "received_qty": 3, "damaged_qty": 1,
        "note": "一本泡水"})
    t2 = client.get(f"/api/tasks/{t['id']}").json()
    assert t2["damaged_total"] == 1
    assert t2["shortage_total"] == 1

    rs = client.post("/api/reshipments", json={
        "source_parcel_id": p["id"], "reason_type": "damaged",
        "qty": 1, "reason_detail": "封面泡水 1 本"}).json()
    assert rs["reason_type"] == "damaged"

    # 超收校验：实收+破损不得超过出库数
    a2, e2 = _make_author_edition(client, name="超收作者", title="超收书")
    tt = _create_confirmed_task(client, a2["id"], e2["id"], 2)
    pp = _outbound(client, tt["id"], 2)
    bad = client.post("/api/receipts", json={
        "parcel_id": pp["id"], "receipt_no": "RT-OVER-01",
        "action": "signed", "received_qty": 2, "damaged_qty": 2})
    assert bad.status_code == 422


def test_rejected_then_reship_and_sign(client):
    a, e = _make_author_edition(client, name="拒收重寄作者", title="拒收重寄书")
    t = _create_confirmed_task(client, a["id"], e["id"], 4)
    p = _outbound(client, t["id"], 4)
    client.post("/api/receipts", json={
        "parcel_id": p["id"], "receipt_no": "RT-RR-01",
        "action": "rejected", "note": "拒收"})
    # 非拒收状态原因不能用 rejected
    rs = client.post("/api/reshipments", json={
        "source_parcel_id": p["id"], "reason_type": "rejected",
        "qty": 4, "reason_detail": "拒收重寄"}).json()
    assert rs["task_id"] == t["id"]
    t2 = client.get(f"/api/tasks/{t['id']}").json()
    assert t2["reship_shipped_qty"] == 4
    new_p = next(x for x in t2["parcels"] if x["is_reship"])
    client.post("/api/receipts", json={
        "parcel_id": new_p["id"], "receipt_no": "RT-RR-02",
        "action": "signed", "received_qty": 4})
    t3 = client.get(f"/api/tasks/{t['id']}").json()
    # 拒收的 4 不计，只有重寄签收的 4
    assert t3["received_qty"] == 4
    assert t3["rejected_count"] == 1
    assert t3["status"] == "completed"


# ============================================================ 8. 流程闸门

def test_workflow_guards(client):
    a, e = _make_author_edition(client, name="闸门作者", title="闸门书")
    t = client.post("/api/tasks", json={
        "author_id": a["id"], "edition_id": e["id"],
        "required_qty": 3}).json()
    # 未确认地址不能出库
    resp = client.post("/api/outbound", json={"task_id": t["id"], "qty": 3})
    assert resp.status_code == 409
    # 原寄只能一次
    client.post(f"/api/tasks/{t['id']}/confirm-address", json={
        "recipient": "本人", "address": "某地"})
    p = _outbound(client, t["id"], 3)
    resp = client.post("/api/outbound", json={"task_id": t["id"], "qty": 3})
    assert resp.status_code == 409
    # 在途包裹不能补寄
    resp = client.post("/api/reshipments", json={
        "source_parcel_id": p["id"], "reason_type": "shortage", "qty": 1})
    assert resp.status_code == 409
