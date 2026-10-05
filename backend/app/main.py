import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import models as m
from . import schemas as sc
from . import services as sv
from .database import Base, engine, get_db
from .seed import seed_if_empty

Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not os.environ.get("SAMPLESHIP_SKIP_SEED"):
        db = next(get_db())
        try:
            seed_if_empty(db)
        finally:
            db.close()
    yield


app = FastAPI(title="出版社样书寄送与作者签收系统", lifespan=lifespan)


@app.exception_handler(sv.BizError)
def biz_error_handler(request, exc: sv.BizError):
    return JSONResponse(status_code=exc.status_code,
                        content={"detail": exc.message})


# ---------------------------------------------------------------- 作者/地址

@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/authors")
def list_authors(db: Session = Depends(get_db)):
    out = []
    for a in db.query(m.Author).order_by(m.Author.id).all():
        cur = sv.current_address(db, a.id)
        out.append({
            "id": a.id, "name": a.name, "pen_name": a.pen_name,
            "phone": a.phone, "email": a.email,
            "current_address": _addr_dict(cur) if cur else None,
            "addresses": [_addr_dict(x) for x in a.addresses],
        })
    return out


@app.post("/api/authors", status_code=201)
def create_author(data: sc.AuthorIn, db: Session = Depends(get_db)):
    a = sv.create_author(db, data)
    return {"id": a.id, "name": a.name}


@app.get("/api/authors/{author_id}")
def get_author(author_id: int, db: Session = Depends(get_db)):
    a = db.get(m.Author, author_id)
    if a is None:
        raise sv.BizError("作者不存在", 404)
    return {
        "id": a.id, "name": a.name, "pen_name": a.pen_name,
        "phone": a.phone, "email": a.email,
        "addresses": [_addr_dict(x) for x in a.addresses],
        "reconciliation": sv.author_reconciliation(db, a.id),
    }


@app.post("/api/authors/{author_id}/addresses", status_code=201)
def add_address(author_id: int, data: sc.AddressIn,
                db: Session = Depends(get_db)):
    addr = sv.add_address(db, author_id, data)
    return _addr_dict(addr)


@app.post("/api/addresses/{address_id}/confirm")
def confirm_address(address_id: int, data: sc.AddressConfirmIn,
                    db: Session = Depends(get_db)):
    return _addr_dict(sv.confirm_address(db, address_id, data.confirmed_by))


def _addr_dict(a: m.Address) -> dict:
    return {
        "id": a.id, "recipient": a.recipient, "phone": a.phone,
        "region": a.region, "detail": a.detail, "status": a.status,
        "is_current": a.is_current, "confirmed_by": a.confirmed_by,
        "confirmed_at": a.confirmed_at.isoformat() if a.confirmed_at else None,
    }


# ---------------------------------------------------------------- 图书/版次

@app.get("/api/books")
def list_books(db: Session = Depends(get_db)):
    return [{
        "id": b.id, "title": b.title, "isbn": b.isbn,
        "editions": [{"id": e.id, "edition_no": e.edition_no, "note": e.note}
                     for e in b.editions],
    } for b in db.query(m.Book).order_by(m.Book.id).all()]


@app.post("/api/books", status_code=201)
def create_book(data: sc.BookIn, db: Session = Depends(get_db)):
    b = sv.create_book(db, data)
    return {"id": b.id, "title": b.title, "isbn": b.isbn}


@app.post("/api/books/{book_id}/editions", status_code=201)
def create_edition(book_id: int, data: sc.EditionIn,
                   db: Session = Depends(get_db)):
    e = sv.create_edition(db, book_id, data)
    return {"id": e.id, "edition_no": e.edition_no}


@app.get("/api/editions")
def list_editions(db: Session = Depends(get_db)):
    return [{"id": e.id, "edition_no": e.edition_no,
             "book_id": e.book_id, "book_title": e.book.title}
            for e in db.query(m.Edition).order_by(m.Edition.id).all()]


# ---------------------------------------------------------------- 任务

@app.get("/api/tasks")
def list_tasks(db: Session = Depends(get_db)):
    tasks = db.query(m.ShipmentTask).order_by(m.ShipmentTask.id.desc()).all()
    return [sv.task_summary(db, t) for t in tasks]


@app.post("/api/tasks", status_code=201)
def create_task(data: sc.TaskIn, db: Session = Depends(get_db)):
    task = sv.create_task(db, data)
    return sv.task_summary(db, task)


@app.get("/api/tasks/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_db)):
    task = sv._get_task(db, task_id)
    return {**sv.task_summary(db, task),
            "packages": [_pkg_dict(db, p) for p in task.packages]}


# ---------------------------------------------------------------- 包裹

@app.post("/api/tasks/{task_id}/packages", status_code=201)
def ship_package(task_id: int, data: sc.ShipIn, db: Session = Depends(get_db)):
    pkg = sv.ship_package(db, task_id, data.quantity, data.shipped_by)
    return _pkg_dict(db, pkg)


@app.get("/api/packages/{package_id}")
def get_package(package_id: int, db: Session = Depends(get_db)):
    return _pkg_dict(db, sv._get_package(db, package_id))


@app.post("/api/packages/{package_id}/receipt", status_code=201)
def submit_receipt(package_id: int, data: sc.ReceiptIn,
                   db: Session = Depends(get_db)):
    r = sv.submit_receipt(db, package_id, data)
    return _receipt_dict(r)


@app.post("/api/packages/{package_id}/reship", status_code=201)
def reship(package_id: int, data: sc.ReshipIn, db: Session = Depends(get_db)):
    pkg = sv.reship(db, package_id, data)
    return _pkg_dict(db, pkg)


@app.post("/api/packages/{package_id}/reroute", status_code=201)
def reroute(package_id: int, data: sc.RerouteIn, db: Session = Depends(get_db)):
    rec = sv.reroute(db, package_id, data)
    return {"id": rec.id, "package_id": rec.package_id,
            "recipient": rec.recipient, "phone": rec.phone,
            "region": rec.region, "detail": rec.detail, "reason": rec.reason,
            "created_by": rec.created_by,
            "created_at": rec.created_at.isoformat()}


@app.post("/api/packages/{package_id}/tracking/advance")
def advance_tracking(package_id: int, db: Session = Depends(get_db)):
    pkg = sv.advance_tracking(db, package_id)
    return _pkg_dict(db, pkg)


# ---------------------------------------------------------------- 待办

@app.get("/api/todos")
def todos(unsigned_days: int = Query(default=7, ge=0),
          db: Session = Depends(get_db)):
    return sv.todo_list(db, unsigned_days)


# ---------------------------------------------------------------- 序列化

def _receipt_dict(r: m.Receipt) -> dict:
    return {
        "id": r.id, "package_id": r.package_id,
        "idempotency_key": r.idempotency_key, "result": r.result,
        "received_qty": r.received_qty, "note": r.note,
        "signed_by": r.signed_by,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _pkg_dict(db: Session, p: m.Package) -> dict:
    return {
        "id": p.id, "package_no": p.package_no, "tracking_no": p.tracking_no,
        "task_id": p.task_id, "parent_package_id": p.parent_package_id,
        "reship_reason": p.reship_reason, "reship_note": p.reship_note,
        "quantity": p.quantity, "status": p.status,
        "address": {"recipient": p.address_recipient, "phone": p.address_phone,
                    "region": p.address_region, "detail": p.address_detail},
        "shipped_by": p.shipped_by,
        "shipped_at": p.shipped_at.isoformat() if p.shipped_at else None,
        "receipt": _receipt_dict(p.receipt) if p.receipt else None,
        "reroutes": [{
            "id": r.id, "recipient": r.recipient, "phone": r.phone,
            "region": r.region, "detail": r.detail, "reason": r.reason,
            "created_by": r.created_by,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in p.reroutes],
        "tracking_events": [{
            "id": e.id, "status": e.status, "description": e.description,
            "location": e.location,
            "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
        } for e in p.tracking_events],
    }


# ---------------------------------------------------------------- 前端静态文件

FRONTEND_DIST = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "frontend", "dist"))

if os.path.isdir(FRONTEND_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")),
              name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        if full_path.startswith("api/"):
            raise sv.BizError("Not Found", 404)
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))
