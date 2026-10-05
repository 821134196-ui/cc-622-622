"""ORM 模型：作者、书版次、寄送任务、包裹、出库记录、签收回执、补寄、改派、快递轨迹。

关键不变量：
- Parcel.address/recipient/phone 是出库时的地址快照，任何后续操作都不允许修改；
  地址变化只追加 AddressRedirect。
- OutboundRecord 是不可变出库流水，与包裹一一对应。
- Receipt（回执）按 receipt_no 幂等，重复回执不新增、不改变实收数量。
- Reshipment 永远挂在原 ShippingTask 下，并快照缺件原因。
- 任务绑定唯一 BookEdition，旧版样书在结构上不可能抵扣新版应寄份数。
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---- 基础资料 ----

class Author(Base):
    __tablename__ = "authors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(30), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    tasks: Mapped[list["ShippingTask"]] = relationship(back_populates="author")


class BookEdition(Base):
    """书的某个版次，例如《诗集》第 2 版。版次之间相互独立。"""

    __tablename__ = "book_editions"
    __table_args__ = (UniqueConstraint("title", "edition", name="uq_book_title_edition"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    edition: Mapped[str] = mapped_column(String(50), nullable=False)  # 如 "第1版" / "第2版"
    isbn: Mapped[str] = mapped_column(String(20), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---- 寄送任务 ----

# 任务状态
TASK_PENDING_ADDRESS = "pending_address"   # 编辑尚未确认地址
TASK_READY = "ready"                       # 地址已确认，待仓库出库
TASK_SHIPPING = "shipping"                 # 有包裹在途
TASK_COMPLETED = "completed"               # 包裹全部了结且实收达标
TASK_ABNORMAL = "abnormal"                 # 包裹全部了结但数量不一致

# 包裹状态
PARCEL_IN_TRANSIT = "in_transit"
PARCEL_SIGNED = "signed"
PARCEL_REJECTED = "rejected"

# 补寄原因
RESHIP_SHORTAGE = "shortage"   # 少件
RESHIP_DAMAGED = "damaged"     # 破损
RESHIP_REJECTED = "rejected"   # 拒收后重寄


class ShippingTask(Base):
    """一次“按版次向作者寄送若干份样书”的任务，原寄与所有补寄都挂在它下面。"""

    __tablename__ = "shipping_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    author_id: Mapped[int] = mapped_column(ForeignKey("authors.id"), nullable=False)
    edition_id: Mapped[int] = mapped_column(ForeignKey("book_editions.id"), nullable=False)
    required_qty: Mapped[int] = mapped_column(Integer, nullable=False)  # 应寄份数（该版次）

    # 编辑确认后的收件信息（任务级；包裹出库时再做不可变快照）
    confirmed_recipient: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confirmed_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    confirmed_address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    address_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    status: Mapped[str] = mapped_column(String(20), default=TASK_PENDING_ADDRESS, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    author: Mapped[Author] = relationship(back_populates="tasks")
    edition: Mapped[BookEdition] = relationship()
    parcels: Mapped[list["Parcel"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class Parcel(Base):
    """仓库出库生成的包裹。原寄、补寄各生成一个包裹。

    recipient/phone/address/edition_id/qty 均为出库那一刻的不可变快照，
    地址改派只写 AddressRedirect，绝不回改本行。
    """

    __tablename__ = "parcels"

    id: Mapped[int] = mapped_column(primary_key=True)
    tracking_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    task_id: Mapped[int] = mapped_column(ForeignKey("shipping_tasks.id"), nullable=False)
    edition_id: Mapped[int] = mapped_column(ForeignKey("book_editions.id"), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)          # 出库份数（不可变）
    is_reship: Mapped[bool] = mapped_column(Boolean, default=False)

    # —— 出库时冻结的地址快照 ——
    recipient: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(30), nullable=False)
    address: Mapped[str] = mapped_column(String(300), nullable=False)

    state: Mapped[str] = mapped_column(String(20), default=PARCEL_IN_TRANSIT, nullable=False)
    outbound_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    task: Mapped[ShippingTask] = relationship(back_populates="parcels")
    edition: Mapped[BookEdition] = relationship()
    outbound_record: Mapped["OutboundRecord"] = relationship(
        back_populates="parcel", uselist=False, cascade="all, delete-orphan"
    )
    receipts: Mapped[list["Receipt"]] = relationship(
        back_populates="parcel", cascade="all, delete-orphan"
    )
    redirects: Mapped[list["AddressRedirect"]] = relationship(
        back_populates="parcel", cascade="all, delete-orphan",
        order_by="AddressRedirect.id",
    )
    tracking_events: Mapped[list["TrackingEvent"]] = relationship(
        back_populates="parcel", cascade="all, delete-orphan",
        order_by="TrackingEvent.occurred_at",
    )


class OutboundRecord(Base):
    """不可变出库流水：谁、何时、按哪个版次、发了多少份。"""

    __tablename__ = "outbound_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    parcel_id: Mapped[int] = mapped_column(ForeignKey("parcels.id"), unique=True, nullable=False)
    edition_id: Mapped[int] = mapped_column(ForeignKey("book_editions.id"), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    is_reship: Mapped[bool] = mapped_column(Boolean, default=False)
    warehouse_note: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    parcel: Mapped[Parcel] = relationship(back_populates="outbound_record")


class Receipt(Base):
    """作者签收回执。

    - action=signed 时 received_qty 为实收份数（<= 包裹出库份数）；
    - action=rejected 表示拒收，received_qty 恒为 0，不计入任何实收统计；
    - receipt_no 全局唯一，重复提交同一回执编号直接返回原记录，不产生新增、不加数量。
    回执一经写入不可修改。
    """

    __tablename__ = "receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    parcel_id: Mapped[int] = mapped_column(ForeignKey("parcels.id"), nullable=False)
    receipt_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)  # signed / rejected
    received_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    shortage_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    damaged_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    parcel: Mapped[Parcel] = relationship(back_populates="receipts")


class Reshipment(Base):
    """补寄记录：挂在原任务下，关联触发补寄的原包裹与补寄包裹，原因在此快照冻结。"""

    __tablename__ = "reshipments"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("shipping_tasks.id"), nullable=False)
    source_parcel_id: Mapped[int] = mapped_column(ForeignKey("parcels.id"), nullable=False)
    new_parcel_id: Mapped[int] = mapped_column(ForeignKey("parcels.id"), nullable=False)
    reason_type: Mapped[str] = mapped_column(String(20), nullable=False)
    reason_detail: Mapped[str] = mapped_column(String(300), default="")
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AddressRedirect(Base):
    """地址改派记录：只能追加。old_* 字段冗余留痕，原 Parcel 快照保持不变。"""

    __tablename__ = "address_redirects"

    id: Mapped[int] = mapped_column(primary_key=True)
    parcel_id: Mapped[int] = mapped_column(ForeignKey("parcels.id"), nullable=False)
    old_recipient: Mapped[str] = mapped_column(String(100), nullable=False)
    old_phone: Mapped[str] = mapped_column(String(30), default="")
    old_address: Mapped[str] = mapped_column(String(300), nullable=False)
    new_recipient: Mapped[str] = mapped_column(String(100), nullable=False)
    new_phone: Mapped[str] = mapped_column(String(30), default="")
    new_address: Mapped[str] = mapped_column(String(300), nullable=False)
    reason: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    parcel: Mapped[Parcel] = relationship(back_populates="redirects")


class TrackingEvent(Base):
    """快递轨迹（本地模拟，无外部快递公司依赖）。只追加。"""

    __tablename__ = "tracking_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    parcel_id: Mapped[int] = mapped_column(ForeignKey("parcels.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    location: Mapped[str] = mapped_column(String(100), default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    parcel: Mapped[Parcel] = relationship(back_populates="tracking_events")
