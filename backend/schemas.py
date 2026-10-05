"""Pydantic 请求/响应模式。"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---- 作者 / 书版次 ----

class AuthorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    phone: str = ""


class AuthorOut(BaseModel):
    id: int
    name: str
    phone: str

    model_config = {"from_attributes": True}


class BookEditionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    edition: str = Field(min_length=1, max_length=50)
    isbn: str = ""


class BookEditionOut(BaseModel):
    id: int
    title: str
    edition: str
    isbn: str

    model_config = {"from_attributes": True}


# ---- 任务 ----

class TaskCreate(BaseModel):
    author_id: int
    edition_id: int
    required_qty: int = Field(gt=0)
    note: str = ""


class AddressConfirm(BaseModel):
    recipient: str = Field(min_length=1, max_length=100)
    phone: str = ""
    address: str = Field(min_length=1, max_length=300)


# ---- 出库 ----

class OutboundCreate(BaseModel):
    task_id: int
    qty: int = Field(gt=0)
    warehouse_note: str = ""


# ---- 签收 ----

class ReceiptCreate(BaseModel):
    parcel_id: int
    receipt_no: Optional[str] = Field(default=None, max_length=40)
    action: str = Field(pattern="^(signed|rejected)$")
    received_qty: int = Field(ge=0, default=0)
    damaged_qty: int = Field(ge=0, default=0)
    note: str = ""


# ---- 补寄 ----

class ReshipCreate(BaseModel):
    source_parcel_id: int
    reason_type: str = Field(pattern="^(shortage|damaged|rejected)$")
    qty: int = Field(gt=0)
    reason_detail: str = ""
    # 补寄出库地址：默认取原包裹快照，允许编辑在补寄前指定新地址
    recipient: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None


# ---- 改派 ----

class RedirectCreate(BaseModel):
    parcel_id: int
    new_recipient: str = Field(min_length=1, max_length=100)
    new_phone: str = ""
    new_address: str = Field(min_length=1, max_length=300)
    reason: str = ""


# ---- 输出 ----

class ReceiptOut(BaseModel):
    id: int
    receipt_no: str
    action: str
    received_qty: int
    shortage_qty: int
    damaged_qty: int
    note: str
    created_at: datetime
    duplicate: bool = False

    model_config = {"from_attributes": True}


class RedirectOut(BaseModel):
    id: int
    old_recipient: str
    old_phone: str
    old_address: str
    new_recipient: str
    new_phone: str
    new_address: str
    reason: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TrackingEventOut(BaseModel):
    id: int
    event_type: str
    description: str
    location: str
    occurred_at: datetime

    model_config = {"from_attributes": True}


class OutboundRecordOut(BaseModel):
    id: int
    edition_id: int
    qty: int
    is_reship: bool
    warehouse_note: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ReshipmentOut(BaseModel):
    id: int
    task_id: int
    source_parcel_id: int
    new_parcel_id: int
    reason_type: str
    reason_detail: str
    qty: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ParcelOut(BaseModel):
    id: int
    tracking_no: str
    task_id: int
    edition_id: int
    qty: int
    is_reship: bool
    recipient: str
    phone: str
    address: str
    state: str
    outbound_at: datetime
    outbound_record: Optional[OutboundRecordOut] = None
    receipts: list[ReceiptOut] = []
    redirects: list[RedirectOut] = []
    tracking_events: list[TrackingEventOut] = []
    # 该包裹有效实收（拒收不计；正常最多一条有效回执）
    received_qty: int = 0

    model_config = {"from_attributes": True}


class TaskOut(BaseModel):
    id: int
    code: str
    author_id: int
    edition_id: int
    required_qty: int
    confirmed_recipient: Optional[str]
    confirmed_phone: Optional[str]
    confirmed_address: Optional[str]
    address_confirmed_at: Optional[datetime]
    status: str
    note: str
    created_at: datetime
    parcels: list[ParcelOut] = []
    # 汇总
    original_shipped_qty: int = 0   # 原寄出库
    reship_shipped_qty: int = 0     # 补寄出库
    total_shipped_qty: int = 0
    received_qty: int = 0           # 实收合计（拒收为 0）
    shortage_total: int = 0
    damaged_total: int = 0
    rejected_count: int = 0
    in_transit_count: int = 0
    pending_days: Optional[float] = None  # 最早在途包裹已等待天数

    model_config = {"from_attributes": True}


class TodoItem(BaseModel):
    task: TaskOut
    priority_score: float
    reasons: list[str]
