"""FastAPI 入口：REST API + 前端静态资源托管 + 演示数据初始化。

启动：
    uvicorn backend.main:app --host 0.0.0.0 --port 8000
或一条命令：
    ./run.sh
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models, services
from .database import Base, engine, get_db
from .schemas import (
    AddressConfirm,
    AuthorCreate,
    AuthorOut,
    BookEditionCreate,
    BookEditionOut,
    OutboundCreate,
    ParcelOut,
    ReceiptCreate,
    ReceiptOut,
    RedirectCreate,
    ReshipCreate,
    ReshipmentOut,
    TaskCreate,
    TaskOut,
    TodoItem,
    TrackingEventOut,
)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db(seed=os.environ.get("SEED_DEMO", "1") == "1")
    yield


app = FastAPI(
    title="样书寄送与作者签收系统",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------ 序列化辅助

def _parcel_out(parcel: models.Parcel) -> dict:
    return {
        "id": parcel.id,
        "tracking_no": parcel.tracking_no,
        "task_id": parcel.task_id,
        "edition_id": parcel.edition_id,
        "qty": parcel.qty,
        "is_reship": parcel.is_reship,
        "recipient": parcel.recipient,
        "phone": parcel.phone,
        "address": parcel.address,
        "state": parcel.state,
        "outbound_at": parcel.outbound_at,
        "outbound_record": parcel.outbound_record,
        "receipts": list(parcel.receipts),
        "redirects": list(parcel.redirects),
        "tracking_events": list(parcel.tracking_events),
        "received_qty": services.parcel_received_qty(parcel),
    }


def _task_out(task: models.ShippingTask) -> dict:
    summary = services.summarize_task(task)
    data = {
        "id": task.id,
        "code": task.code,
        "author_id": task.author_id,
        "edition_id": task.edition_id,
        "required_qty": task.required_qty,
        "confirmed_recipient": task.confirmed_recipient,
        "confirmed_phone": task.confirmed_phone,
        "confirmed_address": task.confirmed_address,
        "address_confirmed_at": task.address_confirmed_at,
        "status": task.status,
        "note": task.note,
        "created_at": task.created_at,
        "parcels": [_parcel_out(p) for p in sorted(task.parcels, key=lambda p: p.id)],
    }
    data.update(summary)
    return data


def _svc_error(exc: services.ServiceError) -> HTTPException:
    return HTTPException(status_code=exc.code, detail=exc.message)


# ------------------------------------------------------------ 基础资料

@app.post("/api/authors", response_model=AuthorOut, tags=["基础资料"])
def create_author(payload: AuthorCreate, db: Session = Depends(get_db)):
    author = models.Author(name=payload.name, phone=payload.phone)
    db.add(author)
    db.commit()
    db.refresh(author)
    return author


@app.get("/api/authors", response_model=list[AuthorOut], tags=["基础资料"])
def list_authors(db: Session = Depends(get_db)):
    return list(db.scalars(select(models.Author).order_by(models.Author.id)))


@app.post("/api/editions", response_model=BookEditionOut, tags=["基础资料"])
def create_edition(payload: BookEditionCreate, db: Session = Depends(get_db)):
    exists = db.scalar(select(models.BookEdition).where(
        models.BookEdition.title == payload.title,
        models.BookEdition.edition == payload.edition,
    ))
    if exists:
        raise _svc_error(services.ServiceError("该版次已存在", 409))
    edition = models.BookEdition(
        title=payload.title, edition=payload.edition, isbn=payload.isbn)
    db.add(edition)
    db.commit()
    db.refresh(edition)
    return edition


@app.get("/api/editions", response_model=list[BookEditionOut], tags=["基础资料"])
def list_editions(db: Session = Depends(get_db)):
    return list(db.scalars(select(models.BookEdition).order_by(
        models.BookEdition.title, models.BookEdition.id)))


# ------------------------------------------------------------ 任务 / 待办

@app.post("/api/tasks", response_model=TaskOut, tags=["任务"])
def create_task(payload: TaskCreate, db: Session = Depends(get_db)):
    try:
        task = services.create_task(
            db, payload.author_id, payload.edition_id,
            payload.required_qty, payload.note)
    except services.ServiceError as e:
        raise _svc_error(e)
    return _task_out(task)


@app.get("/api/tasks", response_model=list[TaskOut], tags=["任务"])
def list_tasks(db: Session = Depends(get_db)):
    tasks = list(db.scalars(select(models.ShippingTask).order_by(
        models.ShippingTask.id.desc())))
    return [_task_out(t) for t in tasks]


@app.get("/api/tasks/{task_id}", response_model=TaskOut, tags=["任务"])
def get_task(task_id: int, db: Session = Depends(get_db)):
    task = db.get(models.ShippingTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _task_out(task)


@app.post("/api/tasks/{task_id}/confirm-address", response_model=TaskOut,
          tags=["任务"])
def confirm_address(task_id: int, payload: AddressConfirm,
                    db: Session = Depends(get_db)):
    try:
        task = services.confirm_address(
            db, task_id, payload.recipient, payload.phone, payload.address)
    except services.ServiceError as e:
        raise _svc_error(e)
    return _task_out(task)


@app.get("/api/todos", response_model=list[TodoItem], tags=["待办"])
def get_todos(db: Session = Depends(get_db)):
    items = services.todo_list(db)
    return [
        {"task": _task_out(item["task"]),
         "priority_score": item["priority_score"],
         "reasons": item["reasons"]}
        for item in items
    ]


# ------------------------------------------------------------ 出库

@app.post("/api/outbound", response_model=ParcelOut, tags=["仓库"])
def outbound(payload: OutboundCreate, db: Session = Depends(get_db)):
    try:
        parcel = services.outbound_original(
            db, payload.task_id, payload.qty, payload.warehouse_note)
    except services.ServiceError as e:
        raise _svc_error(e)
    return _parcel_out(parcel)


@app.post("/api/parcels/{parcel_id}/advance-tracking",
          response_model=ParcelOut, tags=["仓库"])
def advance_tracking(parcel_id: int, db: Session = Depends(get_db)):
    try:
        parcel = services.advance_tracking(db, parcel_id)
    except services.ServiceError as e:
        raise _svc_error(e)
    return _parcel_out(parcel)


@app.post("/api/parcels/{parcel_id}/redirect", response_model=ParcelOut,
          tags=["仓库"])
def redirect_address(parcel_id: int, payload: RedirectCreate,
                     db: Session = Depends(get_db)):
    if payload.parcel_id != parcel_id:
        raise HTTPException(status_code=400, detail="包裹编号不一致")
    try:
        parcel = services.redirect_address(
            db, parcel_id, payload.new_recipient, payload.new_phone,
            payload.new_address, payload.reason)
    except services.ServiceError as e:
        raise _svc_error(e)
    return _parcel_out(parcel)


# ------------------------------------------------------------ 签收 / 补寄

@app.post("/api/receipts", response_model=ReceiptOut, tags=["签收"])
def submit_receipt(payload: ReceiptCreate, db: Session = Depends(get_db)):
    try:
        _parcel, receipt, duplicate = services.submit_receipt(
            db, payload.parcel_id,
            payload.receipt_no or services._gen_receipt_no(),
            payload.action,
            payload.received_qty, payload.damaged_qty, payload.note)
    except services.ServiceError as e:
        raise _svc_error(e)
    out = ReceiptOut.model_validate(receipt).model_copy(update={"duplicate": duplicate})
    return out


@app.post("/api/reshipments", response_model=ReshipmentOut, tags=["补寄"])
def create_reshipment(payload: ReshipCreate, db: Session = Depends(get_db)):
    try:
        _new_parcel, reship = services.create_reshipment(
            db, payload.source_parcel_id, payload.reason_type, payload.qty,
            payload.reason_detail, payload.recipient, payload.phone,
            payload.address)
    except services.ServiceError as e:
        raise _svc_error(e)
    return reship


# ------------------------------------------------------------ 初始化

def init_db(seed: bool = True) -> None:
    Base.metadata.create_all(bind=engine)
    if seed:
        from .seed import seed_demo_data
        seed_demo_data()


FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


# ------------------------------------------------------------ 前端静态资源

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"),
              name="assets")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        # API 未命中仍走 FastAPI 的 404
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        target = FRONTEND_DIST / full_path
        if target.is_file():
            return FileResponse(target)
        return FileResponse(FRONTEND_DIST / "index.html")
