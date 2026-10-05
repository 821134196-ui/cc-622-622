"""首次启动时写入演示数据, 让各页面开箱可见。"""
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from . import models as m
from . import services as sv
from .schemas import (AddressIn, AuthorIn, BookIn, EditionIn, ReceiptIn,
                      ReshipIn, TaskIn)


def seed_if_empty(db: Session):
    if db.query(m.Author).count() > 0:
        return

    # 图书与版次
    b1 = sv.create_book(db, BookIn(title="山海经营指南", isbn="978-7-01-000001-1"))
    sv.create_edition(db, b1.id, EditionIn(edition_no="第1版"))
    b1e2 = sv.create_edition(db, b1.id, EditionIn(edition_no="第2版"))
    b2 = sv.create_book(db, BookIn(title="星港往事", isbn="978-7-01-000002-8"))
    b2e1 = sv.create_edition(db, b2.id, EditionIn(edition_no="第1版"))
    b1e1 = db.query(m.Edition).filter_by(book_id=b1.id, edition_no="第1版").one()

    # 作者与地址
    a1 = sv.create_author(db, AuthorIn(name="林晚晴", pen_name="晚晴",
                                       phone="13800000001"))
    addr1 = sv.add_address(db, a1.id, AddressIn(
        recipient="林晚晴", phone="13800000001",
        region="浙江省 杭州市 西湖区", detail="文三路 100 号 3 幢 502 室"))
    sv.confirm_address(db, addr1.id, "编辑-周岚")

    a2 = sv.create_author(db, AuthorIn(name="陈默", phone="13800000002"))
    addr2 = sv.add_address(db, a2.id, AddressIn(
        recipient="陈默", phone="13800000002",
        region="四川省 成都市 武侯区", detail="桂溪街道 天府大道 88 号"))
    sv.confirm_address(db, addr2.id, "编辑-周岚")

    a3 = sv.create_author(db, AuthorIn(name="苏子航", phone="13800000003"))
    sv.add_address(db, a3.id, AddressIn(
        recipient="苏子航", phone="13800000003",
        region="广东省 深圳市 南山区", detail="科技园南路 12 号"))  # 未确认

    # 任务1: 林晚晴《山海经营指南》第2版 应寄 5 —— 少件后补寄, 演示完整闭环
    t1 = sv.create_task(db, TaskIn(author_id=a1.id, edition_id=b1e2.id,
                                   quantity_due=5, created_by="编辑-周岚",
                                   note="新版上市前样书"))
    p1 = sv.ship_package(db, t1.id, 5, "仓库-老赵")
    p1.status = m.PKG_OUT_FOR_DELIVERY
    sv.submit_receipt(db, p1.id, ReceiptIn(
        result="missing", received_qty=3, note="外箱完好, 内少 2 册",
        signed_by="林晚晴", idempotency_key="seed-rcpt-1"))
    p2 = sv.reship(db, p1.id, ReshipIn(quantity=2, reason="missing",
                                        shipped_by="仓库-老赵"))
    sv.submit_receipt(db, p2.id, ReceiptIn(
        result="received", received_qty=2, signed_by="林晚晴",
        idempotency_key="seed-rcpt-2"))

    # 任务2: 陈默《星港往事》第1版 应寄 3 —— 出库 10 天未签收(待办: 长时间未签收)
    t2 = sv.create_task(db, TaskIn(author_id=a2.id, edition_id=b2e1.id,
                                   quantity_due=3, created_by="编辑-周岚"))
    p3 = sv.ship_package(db, t2.id, 3, "仓库-老赵")
    p3.shipped_at = datetime.utcnow() - timedelta(days=10)
    p3.status = m.PKG_IN_TRANSIT

    # 任务3: 陈默《山海经营指南》第2版 应寄 2 —— 被拒收(待办: 数量不一致)
    t3 = sv.create_task(db, TaskIn(author_id=a2.id, edition_id=b1e2.id,
                                   quantity_due=2, created_by="编辑-周岚"))
    p4 = sv.ship_package(db, t3.id, 2, "仓库-老赵")
    sv.submit_receipt(db, p4.id, ReceiptIn(
        result="rejected", received_qty=0, note="作者称已搬家, 拒收",
        signed_by="快递网点", idempotency_key="seed-rcpt-3"))

    # 任务4: 林晚晴《星港往事》第1版 应寄 1 —— 正常在途
    t4 = sv.create_task(db, TaskIn(author_id=a1.id, edition_id=b2e1.id,
                                   quantity_due=1, created_by="编辑-周岚"))
    sv.ship_package(db, t4.id, 1, "仓库-老赵")

    db.commit()
