from typing import Optional

from pydantic import BaseModel, Field


class AuthorIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    pen_name: str = ""
    phone: str = ""
    email: str = ""


class AddressIn(BaseModel):
    recipient: str = Field(min_length=1, max_length=100)
    phone: str = Field(min_length=1, max_length=50)
    region: str = ""
    detail: str = Field(min_length=1, max_length=300)


class AddressConfirmIn(BaseModel):
    confirmed_by: str = Field(default="编辑", max_length=100)


class BookIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    isbn: str = Field(min_length=1, max_length=50)


class EditionIn(BaseModel):
    edition_no: str = Field(min_length=1, max_length=50)
    note: str = ""


class TaskIn(BaseModel):
    author_id: int
    edition_id: int
    quantity_due: int = Field(gt=0)
    note: str = ""
    created_by: str = Field(default="编辑", max_length=100)


class ShipIn(BaseModel):
    quantity: int = Field(gt=0)
    shipped_by: str = Field(default="仓库", max_length=100)


class ReceiptIn(BaseModel):
    result: str                      # received / missing / damaged / rejected
    received_qty: int = Field(ge=0)
    note: str = ""
    signed_by: str = ""
    idempotency_key: Optional[str] = None   # 不传则由服务端按包裹生成


class ReshipIn(BaseModel):
    quantity: Optional[int] = Field(default=None, gt=0)  # 缺省=缺口数量
    reason: Optional[str] = None     # 缺省沿用原回执结果
    note: str = ""
    shipped_by: str = Field(default="仓库", max_length=100)


class RerouteIn(BaseModel):
    recipient: str = Field(min_length=1, max_length=100)
    phone: str = Field(min_length=1, max_length=50)
    region: str = ""
    detail: str = Field(min_length=1, max_length=300)
    reason: str = ""
    created_by: str = Field(default="编辑", max_length=100)
