from datetime import datetime

from sqlalchemy import (Boolean, Column, DateTime, ForeignKey, Integer, String,
                        UniqueConstraint)
from sqlalchemy.orm import relationship

from .database import Base

# 包裹状态
PKG_SHIPPED = "shipped"              # 已出库
PKG_IN_TRANSIT = "in_transit"        # 运输中
PKG_OUT_FOR_DELIVERY = "out_for_delivery"  # 派送中
PKG_RECEIVED = "received"            # 已签收(足额)
PKG_MISSING = "missing"              # 已签收但少件
PKG_DAMAGED = "damaged"              # 已签收但破损
PKG_REJECTED = "rejected"            # 拒收

TERMINAL_PKG_STATES = {PKG_RECEIVED, PKG_MISSING, PKG_DAMAGED, PKG_REJECTED}

# 签收结果
RESULT_RECEIVED = "received"
RESULT_MISSING = "missing"
RESULT_DAMAGED = "damaged"
RESULT_REJECTED = "rejected"
RECEIPT_RESULTS = {RESULT_RECEIVED, RESULT_MISSING, RESULT_DAMAGED, RESULT_REJECTED}

# 补寄原因
RESHIP_REASONS = {"missing", "damaged", "rejected", "other"}


class Author(Base):
    __tablename__ = "authors"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    pen_name = Column(String(100), default="")
    phone = Column(String(50), default="")
    email = Column(String(200), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    addresses = relationship("Address", back_populates="author",
                             order_by="Address.id")
    tasks = relationship("ShipmentTask", back_populates="author")


class Address(Base):
    __tablename__ = "addresses"

    id = Column(Integer, primary_key=True)
    author_id = Column(ForeignKey("authors.id"), nullable=False)
    recipient = Column(String(100), nullable=False)
    phone = Column(String(50), nullable=False)
    region = Column(String(200), default="")
    detail = Column(String(300), nullable=False)
    status = Column(String(20), default="pending")   # pending / confirmed
    is_current = Column(Boolean, default=False)
    confirmed_by = Column(String(100), default="")
    confirmed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    author = relationship("Author", back_populates="addresses")


class Book(Base):
    __tablename__ = "books"

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    isbn = Column(String(50), unique=True, nullable=False)

    editions = relationship("Edition", back_populates="book",
                            order_by="Edition.id")


class Edition(Base):
    __tablename__ = "editions"
    __table_args__ = (UniqueConstraint("book_id", "edition_no"),)

    id = Column(Integer, primary_key=True)
    book_id = Column(ForeignKey("books.id"), nullable=False)
    edition_no = Column(String(50), nullable=False)   # 第1版 / 第2版 ...
    note = Column(String(200), default="")

    book = relationship("Book", back_populates="editions")


class ShipmentTask(Base):
    """寄送任务: 编辑为某作者、某版次创建的应寄计划。
    应寄/实收严格按 (任务 -> 版次) 归集, 旧版数量不会抵扣新版。"""

    __tablename__ = "shipment_tasks"

    id = Column(Integer, primary_key=True)
    task_no = Column(String(40), unique=True, nullable=False)
    author_id = Column(ForeignKey("authors.id"), nullable=False)
    edition_id = Column(ForeignKey("editions.id"), nullable=False)
    quantity_due = Column(Integer, nullable=False)     # 应寄数量
    note = Column(String(300), default="")
    created_by = Column(String(100), default="")       # 编辑
    created_at = Column(DateTime, default=datetime.utcnow)

    author = relationship("Author", back_populates="tasks")
    edition = relationship("Edition")
    packages = relationship("Package", back_populates="task",
                            order_by="Package.id")


class Package(Base):
    """包裹: 仓库按版次出库生成。地址为出库时快照, 之后不可变;
    地址变化只追加 Reroute 改派记录。补寄包裹通过 parent_package_id
    挂在原包裹下, task_id 与原包裹相同, 并保留缺件原因。"""

    __tablename__ = "packages"

    id = Column(Integer, primary_key=True)
    package_no = Column(String(40), unique=True, nullable=False)
    tracking_no = Column(String(40), unique=True, nullable=False)
    task_id = Column(ForeignKey("shipment_tasks.id"), nullable=False)
    parent_package_id = Column(ForeignKey("packages.id"), nullable=True)
    reship_reason = Column(String(20), default="")     # missing/damaged/rejected/other
    reship_note = Column(String(300), default="")      # 缺件原因说明
    quantity = Column(Integer, nullable=False)         # 本包出库份数
    # ---- 出库时地址快照(不可变) ----
    address_recipient = Column(String(100), nullable=False)
    address_phone = Column(String(50), nullable=False)
    address_region = Column(String(200), default="")
    address_detail = Column(String(300), nullable=False)
    # ---- 出库记录(不可变) ----
    shipped_by = Column(String(100), default="")
    shipped_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20), default=PKG_SHIPPED)
    created_at = Column(DateTime, default=datetime.utcnow)

    task = relationship("ShipmentTask", back_populates="packages")
    parent = relationship("Package", remote_side=[id])
    receipt = relationship("Receipt", back_populates="package", uselist=False)
    reroutes = relationship("Reroute", back_populates="package",
                            order_by="Reroute.id")
    tracking_events = relationship("TrackingEvent", back_populates="package",
                                   order_by="TrackingEvent.id")


class Receipt(Base):
    """签收回执: 每个包裹至多一条有效回执(package_id 唯一),
    idempotency_key 唯一保证重复提交幂等, 不会重复累加实收数量。"""

    __tablename__ = "receipts"

    id = Column(Integer, primary_key=True)
    package_id = Column(ForeignKey("packages.id"), unique=True, nullable=False)
    idempotency_key = Column(String(80), unique=True, nullable=False)
    result = Column(String(20), nullable=False)   # received/missing/damaged/rejected
    received_qty = Column(Integer, nullable=False, default=0)  # 实收份数(拒收恒为0)
    note = Column(String(300), default="")
    signed_by = Column(String(100), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    package = relationship("Package", back_populates="receipt")


class Reroute(Base):
    """改派记录: 只追加, 不修改原包裹地址快照与出库记录。"""

    __tablename__ = "reroutes"

    id = Column(Integer, primary_key=True)
    package_id = Column(ForeignKey("packages.id"), nullable=False)
    recipient = Column(String(100), nullable=False)
    phone = Column(String(50), nullable=False)
    region = Column(String(200), default="")
    detail = Column(String(300), nullable=False)
    reason = Column(String(300), default="")
    created_by = Column(String(100), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    package = relationship("Package", back_populates="reroutes")


class TrackingEvent(Base):
    """快递轨迹(本地模拟)。"""

    __tablename__ = "tracking_events"

    id = Column(Integer, primary_key=True)
    package_id = Column(ForeignKey("packages.id"), nullable=False)
    status = Column(String(30), nullable=False)
    description = Column(String(300), default="")
    location = Column(String(100), default="")
    occurred_at = Column(DateTime, default=datetime.utcnow)

    package = relationship("Package", back_populates="tracking_events")
