"""业务逻辑层: 所有寄送/签收/补寄/改派规则都在这里, API 层只做参数校验。"""
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models as m


class BizError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ---------------------------------------------------------------- 编号

def _next_no(db: Session, model, column, prefix: str) -> str:
    count = db.query(func.count()).select_from(model).scalar() or 0
    no = f"{prefix}{count + 1:06d}"
    n = count + 1
    while db.query(model).filter(column == no).first() is not None:
        n += 1
        no = f"{prefix}{n:06d}"
    return no


# ---------------------------------------------------------------- 作者/地址

def create_author(db: Session, data) -> m.Author:
    author = m.Author(name=data.name, pen_name=data.pen_name,
                      phone=data.phone, email=data.email)
    db.add(author)
    db.commit()
    db.refresh(author)
    return author


def add_address(db: Session, author_id: int, data) -> m.Address:
    _get_author(db, author_id)
    addr = m.Address(author_id=author_id, recipient=data.recipient,
                     phone=data.phone, region=data.region, detail=data.detail)
    db.add(addr)
    db.commit()
    db.refresh(addr)
    return addr


def confirm_address(db: Session, address_id: int, confirmed_by: str) -> m.Address:
    """编辑确认地址: 置为作者当前地址, 其余地址取消当前标记。"""
    addr = db.get(m.Address, address_id)
    if addr is None:
        raise BizError("地址不存在", 404)
    (db.query(m.Address)
       .filter(m.Address.author_id == addr.author_id)
       .update({m.Address.is_current: False}))
    addr.status = "confirmed"
    addr.is_current = True
    addr.confirmed_by = confirmed_by
    addr.confirmed_at = datetime.utcnow()
    db.commit()
    db.refresh(addr)
    return addr


def current_address(db: Session, author_id: int):
    return (db.query(m.Address)
              .filter(m.Address.author_id == author_id,
                      m.Address.is_current.is_(True),
                      m.Address.status == "confirmed")
              .first())


# ---------------------------------------------------------------- 图书/版次

def create_book(db: Session, data) -> m.Book:
    if db.query(m.Book).filter(m.Book.isbn == data.isbn).first():
        raise BizError("ISBN 已存在", 409)
    book = m.Book(title=data.title, isbn=data.isbn)
    db.add(book)
    db.commit()
    db.refresh(book)
    return book


def create_edition(db: Session, book_id: int, data) -> m.Edition:
    book = db.get(m.Book, book_id)
    if book is None:
        raise BizError("图书不存在", 404)
    dup = (db.query(m.Edition)
             .filter(m.Edition.book_id == book_id,
                     m.Edition.edition_no == data.edition_no)
             .first())
    if dup:
        raise BizError("该图书下版次已存在", 409)
    ed = m.Edition(book_id=book_id, edition_no=data.edition_no, note=data.note)
    db.add(ed)
    db.commit()
    db.refresh(ed)
    return ed


# ---------------------------------------------------------------- 任务

def _get_author(db: Session, author_id: int) -> m.Author:
    author = db.get(m.Author, author_id)
    if author is None:
        raise BizError("作者不存在", 404)
    return author


def _get_task(db: Session, task_id: int) -> m.ShipmentTask:
    task = db.get(m.ShipmentTask, task_id)
    if task is None:
        raise BizError("寄送任务不存在", 404)
    return task


def _get_package(db: Session, package_id: int) -> m.Package:
    pkg = db.get(m.Package, package_id)
    if pkg is None:
        raise BizError("包裹不存在", 404)
    return pkg


def create_task(db: Session, data) -> m.ShipmentTask:
    _get_author(db, data.author_id)
    if db.get(m.Edition, data.edition_id) is None:
        raise BizError("版次不存在", 404)
    task = m.ShipmentTask(
        task_no=_next_no(db, m.ShipmentTask, m.ShipmentTask.task_no, "T"),
        author_id=data.author_id, edition_id=data.edition_id,
        quantity_due=data.quantity_due, note=data.note,
        created_by=data.created_by)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


# ---------------------------------------------------------------- 出库

def _add_tracking(db: Session, pkg: m.Package, status: str,
                  description: str, location: str = ""):
    db.add(m.TrackingEvent(package_id=pkg.id, status=status,
                           description=description, location=location))


def ship_package(db: Session, task_id: int, quantity: int,
                 shipped_by: str, parent: m.Package = None,
                 reship_reason: str = "", reship_note: str = "") -> m.Package:
    """仓库出库: 以作者当前已确认地址生成不可变快照。"""
    task = _get_task(db, task_id)
    if quantity <= 0:
        raise BizError("出库数量必须大于 0")
    addr = current_address(db, task.author_id)
    if addr is None:
        raise BizError("作者没有已确认的当前地址, 请先由编辑确认地址", 409)
    pkg = m.Package(
        package_no=_next_no(db, m.Package, m.Package.package_no, "PKG"),
        tracking_no=_next_no(db, m.Package, m.Package.tracking_no, "TRK"),
        task_id=task.id,
        parent_package_id=parent.id if parent else None,
        reship_reason=reship_reason,
        reship_note=reship_note,
        quantity=quantity,
        address_recipient=addr.recipient, address_phone=addr.phone,
        address_region=addr.region, address_detail=addr.detail,
        shipped_by=shipped_by, shipped_at=datetime.utcnow(),
        status=m.PKG_SHIPPED)
    db.add(pkg)
    db.flush()
    kind = "补寄包裹已出库" if parent else "包裹已出库"
    _add_tracking(db, pkg, m.PKG_SHIPPED,
                  f"{kind}, 数量 {quantity}, 运单号 {pkg.tracking_no}", "出版社仓库")
    db.commit()
    db.refresh(pkg)
    return pkg


# ---------------------------------------------------------------- 签收

def submit_receipt(db: Session, package_id: int, data) -> m.Receipt:
    """作者签收。规则:
    - 同一 idempotency_key 重复提交 -> 返回原回执(幂等, 不重复计数);
    - 包裹已有回执, 不同 key 再次提交 -> 409, 实收数量不变;
    - 拒收(rejected)实收份数强制为 0, 不计入签收数量。
    """
    pkg = _get_package(db, package_id)
    if data.result not in m.RECEIPT_RESULTS:
        raise BizError(f"非法签收结果: {data.result}")

    key = data.idempotency_key or f"pkg-{pkg.id}-receipt"
    existing = (db.query(m.Receipt)
                  .filter(m.Receipt.idempotency_key == key).first())
    if existing is not None:
        return existing                      # 幂等重放: 直接返回原回执
    if pkg.receipt is not None:
        raise BizError("该包裹已有签收回执, 重复回执不会累加实收数量", 409)

    received_qty = data.received_qty
    if data.result == m.RESULT_REJECTED:
        received_qty = 0                     # 拒收不算签收
    elif received_qty > pkg.quantity:
        raise BizError("实收数量不能大于出库数量")

    receipt = m.Receipt(package_id=pkg.id, idempotency_key=key,
                        result=data.result, received_qty=received_qty,
                        note=data.note, signed_by=data.signed_by)
    db.add(receipt)

    if data.result == m.RESULT_REJECTED:
        pkg.status = m.PKG_REJECTED
        _add_tracking(db, pkg, m.PKG_REJECTED, "作者拒收包裹")
    elif data.result == m.RESULT_MISSING:
        pkg.status = m.PKG_MISSING
        _add_tracking(db, pkg, m.PKG_MISSING,
                      f"签收但少件: 实收 {received_qty}/{pkg.quantity}")
    elif data.result == m.RESULT_DAMAGED:
        pkg.status = m.PKG_DAMAGED
        _add_tracking(db, pkg, m.PKG_DAMAGED,
                      f"签收但破损: 实收 {received_qty}/{pkg.quantity}")
    else:
        pkg.status = m.PKG_RECEIVED
        _add_tracking(db, pkg, m.PKG_RECEIVED,
                      f"包裹已签收, 实收 {received_qty}/{pkg.quantity}")
    db.commit()
    db.refresh(receipt)
    return receipt


# ---------------------------------------------------------------- 补寄

def reship(db: Session, package_id: int, data) -> m.Package:
    """补寄: 新包裹挂在原任务下(task_id 不变), 记录父包裹与缺件原因。"""
    orig = _get_package(db, package_id)
    if orig.receipt is None:
        raise BizError("原包裹尚未签收, 不能补寄", 409)
    default_reason = orig.receipt.result
    reason = data.reason or default_reason
    if reason not in m.RESHIP_REASONS:
        raise BizError(f"非法补寄原因: {reason}")
    shortage = orig.quantity - orig.receipt.received_qty
    quantity = data.quantity if data.quantity is not None else max(shortage, 0)
    if quantity <= 0:
        raise BizError("补寄数量必须大于 0")
    note = data.note or f"原包裹 {orig.package_no} {default_reason}, " \
                        f"实收 {orig.receipt.received_qty}/{orig.quantity}"
    return ship_package(db, orig.task_id, quantity, data.shipped_by,
                        parent=orig, reship_reason=reason, reship_note=note)


# ---------------------------------------------------------------- 改派

def reroute(db: Session, package_id: int, data) -> m.Reroute:
    """地址改派: 只追加记录, 不修改原包裹地址快照与出库记录。"""
    pkg = _get_package(db, package_id)
    if pkg.status in m.TERMINAL_PKG_STATES:
        raise BizError("包裹已签收/拒收, 不能改派", 409)
    rec = m.Reroute(package_id=pkg.id, recipient=data.recipient,
                    phone=data.phone, region=data.region, detail=data.detail,
                    reason=data.reason, created_by=data.created_by)
    db.add(rec)
    _add_tracking(db, pkg, "reroute",
                  f"地址改派: {data.region}{data.detail} ({data.recipient})")
    db.commit()
    db.refresh(rec)
    return rec


# ---------------------------------------------------------------- 轨迹模拟

_SIM_FLOW = [
    (m.PKG_IN_TRANSIT, "运输中: 快件已到达分拨中心", "分拨中心"),
    (m.PKG_IN_TRANSIT, "运输中: 快件已发出, 下一站派送网点", "运输途中"),
    (m.PKG_OUT_FOR_DELIVERY, "派送中: 快递员正在派送", "派送网点"),
]


def advance_tracking(db: Session, package_id: int) -> m.Package:
    """本地模拟快递轨迹推进一步。"""
    pkg = _get_package(db, package_id)
    if pkg.status in m.TERMINAL_PKG_STATES:
        raise BizError("包裹已签收/拒收, 轨迹终止", 409)
    simulated = sum(1 for e in pkg.tracking_events
                    if e.status in (m.PKG_IN_TRANSIT, m.PKG_OUT_FOR_DELIVERY))
    if simulated >= len(_SIM_FLOW):
        raise BizError("轨迹已到派送阶段, 请录入签收回执", 409)
    status, desc, loc = _SIM_FLOW[simulated]
    pkg.status = status
    _add_tracking(db, pkg, status, desc, loc)
    db.commit()
    db.refresh(pkg)
    return pkg


# ---------------------------------------------------------------- 对账/汇总

def _received_of(pkg: m.Package) -> int:
    return pkg.receipt.received_qty if pkg.receipt else 0


def task_summary(db: Session, task: m.ShipmentTask) -> dict:
    """按任务(=作者×版次)归集 应寄/已寄/实收。版次之间互不相抵。"""
    shipped = sum(p.quantity for p in task.packages)
    received = sum(_received_of(p) for p in task.packages)
    all_terminal = bool(task.packages) and all(
        p.status in m.TERMINAL_PKG_STATES for p in task.packages)
    if received >= task.quantity_due:
        status = "completed"
    elif not task.packages:
        status = "pending"
    elif not all_terminal:
        status = "shipping"
    else:
        status = "mismatch"      # 全部包裹已终结但实收不足: 数量不一致
    return {
        "id": task.id, "task_no": task.task_no,
        "author_id": task.author_id, "author_name": task.author.name,
        "edition_id": task.edition_id,
        "book_title": task.edition.book.title,
        "edition_no": task.edition.edition_no,
        "quantity_due": task.quantity_due,
        "quantity_shipped": shipped,
        "quantity_received": received,
        "outstanding": max(task.quantity_due - received, 0),
        "status": status,
        "note": task.note, "created_by": task.created_by,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }


def author_reconciliation(db: Session, author_id: int) -> list:
    """作者维度对账: 按版次逐行列出 应寄/已寄/实收/差额。
    每一行独立归集 —— 旧版样书不会抵扣新版应寄份数。"""
    _get_author(db, author_id)
    rows = []
    tasks = (db.query(m.ShipmentTask)
               .filter(m.ShipmentTask.author_id == author_id)
               .order_by(m.ShipmentTask.id).all())
    for t in tasks:
        s = task_summary(db, t)
        rows.append({k: s[k] for k in (
            "id", "task_no", "book_title", "edition_no", "quantity_due",
            "quantity_shipped", "quantity_received", "outstanding", "status")})
    return rows


def todo_list(db: Session, unsigned_days: int = 7) -> list:
    """待办: 优先展示 [数量不一致/拒收] 与 [长时间未签收] 的包裹。"""
    now = datetime.utcnow()
    items = []
    tasks = db.query(m.ShipmentTask).all()
    summaries = {t.id: task_summary(db, t) for t in tasks}
    pkgs = db.query(m.Package).order_by(m.Package.id).all()
    for pkg in pkgs:
        s = summaries[pkg.task_id]
        age_days = (now - pkg.shipped_at).days if pkg.shipped_at else 0
        base = {
            "package_id": pkg.id, "package_no": pkg.package_no,
            "tracking_no": pkg.tracking_no, "task_id": pkg.task_id,
            "task_no": s["task_no"], "author_name": s["author_name"],
            "book_title": s["book_title"], "edition_no": s["edition_no"],
            "package_status": pkg.status,
            "quantity": pkg.quantity,
            "received_qty": _received_of(pkg),
            "task_due": s["quantity_due"],
            "task_received": s["quantity_received"],
            "age_days": age_days,
            "shipped_at": pkg.shipped_at.isoformat() if pkg.shipped_at else None,
        }
        if pkg.status in (m.PKG_MISSING, m.PKG_DAMAGED, m.PKG_REJECTED) \
                and s["status"] != "completed":
            reason = {"missing": "少件", "damaged": "破损",
                      "rejected": "拒收"}[pkg.status]
            items.append({**base, "kind": "mismatch",
                          "reason": f"数量不一致: {reason}, "
                                    f"实收 {base['received_qty']}/{pkg.quantity}",
                          "priority": 10000 + age_days})
        elif pkg.status not in m.TERMINAL_PKG_STATES \
                and age_days >= unsigned_days:
            items.append({**base, "kind": "overdue",
                          "reason": f"长时间未签收: 已出库 {age_days} 天",
                          "priority": age_days})
    items.sort(key=lambda x: x["priority"], reverse=True)
    return items
