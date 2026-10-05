"""业务规则层。所有核心不变量都在这里集中保证：

1. 拒收（rejected）不计入实收，包裹状态独立于签收。
2. 回执按 receipt_no 幂等：重复回执直接返回原记录（duplicate=True），不新增、不加数量。
3. 补寄永远挂在原 ShippingTask 下，版次强制继承原任务（旧版在结构上无法抵扣新版），
   并冻结缺件/破损/拒收原因。
4. 地址改派只追加 AddressRedirect，不修改 Parcel 的地址快照与出库记录。
5. 数量核对均在同一“任务 + 版次”内汇总：原寄、补寄、实收分开统计。
"""
import random
import string
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .models import (
    PARCEL_IN_TRANSIT,
    PARCEL_REJECTED,
    PARCEL_SIGNED,
    RESHIP_DAMAGED,
    RESHIP_REJECTED,
    RESHIP_SHORTAGE,
    TASK_ABNORMAL,
    TASK_COMPLETED,
    TASK_PENDING_ADDRESS,
    TASK_READY,
    TASK_SHIPPING,
    utcnow,
)


class ServiceError(Exception):
    def __init__(self, message: str, code: int = 400):
        self.message = message
        self.code = code
        super().__init__(message)


# ---------------------------------------------------------------- 编号生成

def _gen_tracking_no() -> str:
    return "SF" + "".join(random.choices(string.digits, k=12))


def _gen_task_code(db: Session) -> str:
    seq = db.scalar(select(models.ShippingTask.id).order_by(
        models.ShippingTask.id.desc()))
    return f"RW{(seq or 0) + 1:04d}"


def _gen_receipt_no() -> str:
    return "RT" + "".join(random.choices(string.ascii_uppercase + string.digits, k=10))


# ---------------------------------------------------------------- 轨迹模拟

_TRANSIT_STAGES = [
    ("transit", "包裹已到达中转站", "市级分拣中心"),
    ("transit", "包裹正在发往目的地城市", "干线运输"),
    ("delivery", "快递员已揽件，正在派送", "目的地营业部"),
]


def _add_event(db: Session, parcel: models.Parcel, event_type: str,
               description: str, location: str = "", at=None) -> models.TrackingEvent:
    event = models.TrackingEvent(
        parcel_id=parcel.id, event_type=event_type,
        description=description, location=location,
        occurred_at=at or utcnow(),
    )
    db.add(event)
    return event


def _seed_outbound_tracking(db: Session, parcel: models.Parcel) -> None:
    """出库时本地模拟初始轨迹。"""
    t0 = parcel.outbound_at
    _add_event(db, parcel, "created", "仓库已生成包裹，等待快递揽收",
               "出版社仓库", at=t0)
    _add_event(db, parcel, "picked_up", "快递已揽收，包裹发出",
               "出版社仓库", at=t0 + timedelta(hours=2))
    _add_event(db, parcel, "transit", "包裹到达始发分拣中心",
               "始发分拣中心", at=t0 + timedelta(hours=8))


def advance_tracking(db: Session, parcel_id: int) -> models.Parcel:
    """模拟快递向前推进一个节点（本地演示用）。已了结包裹不推进。"""
    parcel = db.get(models.Parcel, parcel_id)
    if parcel is None:
        raise ServiceError("包裹不存在", 404)
    if parcel.state != PARCEL_IN_TRANSIT:
        raise ServiceError("包裹已了结，轨迹不再更新", 409)
    existing_desc = {e.description for e in parcel.tracking_events}
    pending = [s for s in _TRANSIT_STAGES if s[1] not in existing_desc]
    if not pending:
        raise ServiceError("包裹已到最后派送阶段，等待签收", 409)
    event_type, desc, loc = pending[0]
    _add_event(db, parcel, event_type, desc, loc)
    db.commit()
    db.refresh(parcel)
    return parcel


# ---------------------------------------------------------------- 任务 / 地址

def create_task(db: Session, author_id: int, edition_id: int,
                required_qty: int, note: str = "") -> models.ShippingTask:
    if db.get(models.Author, author_id) is None:
        raise ServiceError("作者不存在", 404)
    if db.get(models.BookEdition, edition_id) is None:
        raise ServiceError("书版次不存在", 404)
    task = models.ShippingTask(
        code=_gen_task_code(db), author_id=author_id, edition_id=edition_id,
        required_qty=required_qty, note=note, status=TASK_PENDING_ADDRESS,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def confirm_address(db: Session, task_id: int, recipient: str,
                    phone: str, address: str) -> models.ShippingTask:
    task = db.get(models.ShippingTask, task_id)
    if task is None:
        raise ServiceError("任务不存在", 404)
    # 确认只更新任务级地址；已经出库的包裹快照不受影响。
    task.confirmed_recipient = recipient
    task.confirmed_phone = phone
    task.confirmed_address = address
    task.address_confirmed_at = utcnow()
    if task.status == TASK_PENDING_ADDRESS:
        task.status = TASK_READY
    db.commit()
    db.refresh(task)
    return task


def redirect_address(db: Session, parcel_id: int, new_recipient: str,
                     new_phone: str, new_address: str, reason: str) -> models.Parcel:
    """出库后地址变化：只追加改派记录，原包裹地址与出库记录保持不变。"""
    parcel = db.get(models.Parcel, parcel_id)
    if parcel is None:
        raise ServiceError("包裹不存在", 404)
    if parcel.state != PARCEL_IN_TRANSIT:
        raise ServiceError("仅在途包裹可以改派", 409)
    redirect = models.AddressRedirect(
        parcel_id=parcel.id,
        old_recipient=parcel.recipient,      # 冗余留痕，便于审计
        old_phone=parcel.phone,
        old_address=parcel.address,
        new_recipient=new_recipient,
        new_phone=new_phone,
        new_address=new_address,
        reason=reason,
    )
    db.add(redirect)
    _add_event(db, parcel, "redirect",
               f"地址改派：{new_recipient} / {new_address}", new_address)
    # 注意：parcel.recipient / phone / address 一律不修改
    db.commit()
    db.refresh(parcel)
    return parcel


# ---------------------------------------------------------------- 出库

def _outbound(db: Session, task: models.ShippingTask, qty: int,
              is_reship: bool, warehouse_note: str,
              recipient: str, phone: str, address: str) -> models.Parcel:
    parcel = models.Parcel(
        tracking_no=_gen_tracking_no(),
        task_id=task.id,
        edition_id=task.edition_id,   # 版次强制随任务，旧版样书无法混入抵扣
        qty=qty,
        is_reship=is_reship,
        recipient=recipient,         # 地址在出库这一刻冻结
        phone=phone,
        address=address,
        state=PARCEL_IN_TRANSIT,
    )
    db.add(parcel)
    db.flush()  # 取得 parcel.id

    record = models.OutboundRecord(
        parcel_id=parcel.id, edition_id=task.edition_id, qty=qty,
        is_reship=is_reship, warehouse_note=warehouse_note,
    )
    db.add(record)
    db.flush()
    _seed_outbound_tracking(db, parcel)

    task.status = TASK_SHIPPING
    return parcel


def outbound_original(db: Session, task_id: int, qty: int,
                      warehouse_note: str = "") -> models.Parcel:
    task = db.get(models.ShippingTask, task_id)
    if task is None:
        raise ServiceError("任务不存在", 404)
    if not task.address_confirmed_at:
        raise ServiceError("编辑尚未确认作者地址，不能出库", 409)
    exists = db.scalar(
        select(models.Parcel).where(
            models.Parcel.task_id == task.id,
            models.Parcel.is_reship.is_(False),
        )
    )
    if exists:
        raise ServiceError("原寄包裹已生成，缺件请走补寄流程", 409)
    parcel = _outbound(
        db, task, qty, is_reship=False, warehouse_note=warehouse_note,
        recipient=task.confirmed_recipient, phone=task.confirmed_phone,
        address=task.confirmed_address,
    )
    db.commit()
    db.refresh(parcel)
    return parcel


# ---------------------------------------------------------------- 签收

def submit_receipt(db: Session, parcel_id: int, receipt_no: str, action: str,
                   received_qty: int, damaged_qty: int, note: str):
    """提交签收回执。

    返回 (parcel, receipt, duplicate)。
    同一 receipt_no 重复提交：原样返回已有记录，duplicate=True，
    不改变包裹状态、不增加实收数量、不新增轨迹。
    """
    parcel = db.get(models.Parcel, parcel_id)
    if parcel is None:
        raise ServiceError("包裹不存在", 404)

    existing = db.scalar(
        select(models.Receipt).where(models.Receipt.receipt_no == receipt_no)
    )
    if existing is not None:
        # 幂等：重复回执必须与原包裹一致，否则是编号冲突
        if existing.parcel_id != parcel.id:
            raise ServiceError("回执编号已用于其他包裹", 409)
        return parcel, existing, True

    if parcel.state in (PARCEL_SIGNED, PARCEL_REJECTED):
        raise ServiceError("包裹已有终态回执，不能重复签收", 409)

    if action == "rejected":
        receipt = models.Receipt(
            parcel_id=parcel.id, receipt_no=receipt_no, action="rejected",
            received_qty=0, shortage_qty=0, damaged_qty=0, note=note,
        )
        parcel.state = PARCEL_REJECTED
        db.add(receipt)
        db.flush()
        _add_event(db, parcel, "rejected", f"作者拒收：{note or '未说明原因'}")
    else:
        if received_qty < 0 or damaged_qty < 0:
            raise ServiceError("数量不能为负")
        if received_qty + damaged_qty > parcel.qty:
            raise ServiceError(
                f"实收(含破损)不能超过出库份数 {parcel.qty}", 422
            )
        shortage_qty = parcel.qty - received_qty - damaged_qty
        receipt = models.Receipt(
            parcel_id=parcel.id, receipt_no=receipt_no, action="signed",
            received_qty=received_qty, shortage_qty=shortage_qty,
            damaged_qty=damaged_qty, note=note,
        )
        parcel.state = PARCEL_SIGNED
        db.add(receipt)
        db.flush()
        _add_event(db, parcel, "signed",
                   f"作者已签收，实收 {received_qty} 份"
                   + (f"，破损 {damaged_qty} 份" if damaged_qty else "")
                   + (f"，少件 {shortage_qty} 份" if shortage_qty else ""))

    _recompute_task_status(db, parcel.task)
    db.commit()
    db.refresh(parcel)
    db.refresh(receipt)
    return parcel, receipt, False


def _recompute_task_status(db: Session, task: models.ShippingTask) -> None:
    parcels = task.parcels
    if not parcels:
        task.status = (TASK_READY if task.address_confirmed_at
                       else TASK_PENDING_ADDRESS)
        return
    if any(p.state == PARCEL_IN_TRANSIT for p in parcels):
        task.status = TASK_SHIPPING
        return
    # 全部包裹已了结：按该版次实收与应寄核对
    received = sum(
        r.received_qty for p in parcels for r in p.receipts
        if r.action == "signed"
    )
    task.status = TASK_COMPLETED if received >= task.required_qty else TASK_ABNORMAL


# ---------------------------------------------------------------- 补寄

def create_reshipment(db: Session, source_parcel_id: int, reason_type: str,
                      qty: int, reason_detail: str,
                      recipient: str | None, phone: str | None,
                      address: str | None) -> tuple[models.Parcel, models.Reshipment]:
    source = db.get(models.Parcel, source_parcel_id)
    if source is None:
        raise ServiceError("原包裹不存在", 404)
    if source.state == PARCEL_IN_TRANSIT:
        raise ServiceError("原包裹尚在途，需先签收或拒收才能补寄", 409)

    if reason_type == RESHIP_SHORTAGE:
        signed = [r for r in source.receipts if r.action == "signed"]
        if not signed or sum(r.shortage_qty for r in signed) <= 0:
            raise ServiceError("该包裹没有少件记录，不能按少件补寄", 422)
    elif reason_type == RESHIP_DAMAGED:
        signed = [r for r in source.receipts if r.action == "signed"]
        if not signed or sum(r.damaged_qty for r in signed) <= 0:
            raise ServiceError("该包裹没有破损记录，不能按破损补寄", 422)
    elif reason_type == RESHIP_REJECTED:
        if source.state != PARCEL_REJECTED:
            raise ServiceError("仅被拒收的包裹可按拒收原因重寄", 422)
    else:
        raise ServiceError("未知补寄原因")

    task = source.task
    # 补寄地址：未指定则沿用原包裹出库时冻结的地址（改派不影响新包裹的默认取数，
    # 因为原快照刻意不变；编辑如需新地址可显式传入）。
    new_parcel = _outbound(
        db, task, qty, is_reship=True,
        warehouse_note=f"补寄（来源 {source.tracking_no}）",
        recipient=recipient or source.recipient,
        phone=phone if phone is not None else source.phone,
        address=address or source.address,
    )
    db.flush()
    reship = models.Reshipment(
        task_id=task.id,
        source_parcel_id=source.id,
        new_parcel_id=new_parcel.id,
        reason_type=reason_type,
        reason_detail=reason_detail,
        qty=qty,
    )
    db.add(reship)
    _add_event(db, source, "reship",
               f"已生成补寄包裹 {new_parcel.tracking_no}（{_reason_label(reason_type)} {qty} 份）")
    db.commit()
    db.refresh(new_parcel)
    db.refresh(reship)
    return new_parcel, reship


def _reason_label(reason_type: str) -> str:
    return {RESHIP_SHORTAGE: "少件", RESHIP_DAMAGED: "破损",
            RESHIP_REJECTED: "拒收重寄"}.get(reason_type, reason_type)


# ---------------------------------------------------------------- 汇总 / 待办

def parcel_received_qty(parcel: models.Parcel) -> int:
    """包裹有效实收：拒收恒为 0；只统计 signed 回执。"""
    return sum(r.received_qty for r in parcel.receipts if r.action == "signed")


def summarize_task(task: models.ShippingTask, now=None) -> dict:
    now = now or utcnow()
    parcels = list(task.parcels)
    original = sum(p.qty for p in parcels if not p.is_reship)
    reship = sum(p.qty for p in parcels if p.is_reship)
    signed_receipts = [r for p in parcels for r in p.receipts
                       if r.action == "signed"]
    received = sum(r.received_qty for r in signed_receipts)
    shortage = sum(r.shortage_qty for r in signed_receipts)
    damaged = sum(r.damaged_qty for r in signed_receipts)
    rejected = sum(1 for p in parcels if p.state == PARCEL_REJECTED)
    in_transit = [p for p in parcels if p.state == PARCEL_IN_TRANSIT]

    pending_days = None
    if in_transit:
        oldest = min(p.outbound_at for p in in_transit)
        if oldest.tzinfo is None:
            from datetime import timezone
            oldest = oldest.replace(tzinfo=timezone.utc)
        pending_days = round((now - oldest).total_seconds() / 86400, 1)

    return {
        "original_shipped_qty": original,
        "reship_shipped_qty": reship,
        "total_shipped_qty": original + reship,
        "received_qty": received,
        "shortage_total": shortage,
        "damaged_total": damaged,
        "rejected_count": rejected,
        "in_transit_count": len(in_transit),
        "pending_days": pending_days,
    }


def todo_list(db: Session) -> list[dict]:
    """待办：数量不一致的任务 + 长时间未签收的在途包裹任务，按紧迫程度排序。"""
    tasks = list(db.scalars(select(models.ShippingTask)).all())
    items = []
    for task in tasks:
        s = summarize_task(task)
        reasons: list[str] = []
        score = 0.0

        if task.status == TASK_ABNORMAL:
            gap = task.required_qty - s["received_qty"]
            reasons.append(f"数量不一致：应寄 {task.required_qty}，实收 {s['received_qty']}，差 {gap} 份")
            score += 100 + gap * 10
            if s["rejected_count"]:
                reasons.append(f"有 {s['rejected_count']} 个包裹被拒收")
                score += 20

        if s["in_transit_count"] > 0:
            days = s["pending_days"] or 0
            reasons.append(f"{s['in_transit_count']} 个包裹在途，最早已 {days} 天未签收")
            # 每滞留一天加权，超过 3 天额外加权
            score += days * 8 + (max(0, days - 3) * 6)

        if reasons:
            items.append({"task": task, "summary": s,
                          "priority_score": round(score, 1), "reasons": reasons})

    items.sort(key=lambda x: x["priority_score"], reverse=True)
    return items
