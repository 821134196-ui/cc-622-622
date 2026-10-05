"""演示数据：覆盖待办场景的几种典型状态。

- 长时间未签收的在途包裹
- 少件签收后补寄在途
- 拒收包裹（不计签收）+ 拒收重寄
- 同书不同版次各自独立（旧版不抵扣新版）
幂等：已有数据时跳过。
"""
from datetime import timedelta

from sqlalchemy import select

from . import models, services
from .database import SessionLocal
from .models import utcnow


def _age_parcel(parcel, days: float) -> None:
    """把包裹及其轨迹整体前移 days 天，模拟滞留。"""
    delta = timedelta(days=days)
    parcel.outbound_at = parcel.outbound_at - delta
    for e in parcel.tracking_events:
        e.occurred_at = e.occurred_at - delta


def seed_demo_data() -> None:
    db = SessionLocal()
    try:
        if db.scalar(select(models.Author.id).limit(1)):
            return

        # ---- 基础资料 ----
        lu = models.Author(name="周树人", phone="13800000001")
        bing = models.Author(name="谢婉莹", phone="13800000002")
        lao = models.Author(name="舒庆春", phone="13800000003")
        mo = models.Author(name="管谟业", phone="13800000004")
        db.add_all([lu, bing, lao, mo])
        db.flush()

        stars1 = models.BookEdition(title="繁星", edition="第1版", isbn="978-1-0001")
        stars2 = models.BookEdition(title="繁星", edition="第2版", isbn="978-1-0002")
        zhaxia = models.BookEdition(title="茶馆", edition="第3版", isbn="978-2-0003")
        hongliang = models.BookEdition(title="红高粱家族", edition="第1版", isbn="978-3-0001")
        db.add_all([stars1, stars2, zhaxia, hongliang])
        db.flush()

        # 1) 旧版（繁星第1版）已寄达且数量完成
        t_old = services.create_task(db, bing.id, stars1.id, 5)
        services.confirm_address(db, t_old.id, "谢婉莹", "13800000002",
                                 "北京市海淀区中关村南大街 5 号")
        p_old = services.outbound_original(db, t_old.id, 5)
        services.submit_receipt(db, p_old.id, "RT-SEED-OLD-01", "signed", 5, 0, "如数收到")

        # 2) 新版（繁星第2版）刚建任务，地址待确认 —— 与旧版完全独立
        services.create_task(db, bing.id, stars2.id, 6, note="新版应寄 6 份，旧版不可抵扣")

        # 3) 周树人：包裹在途 6 天未签收（高优待办）
        t_lu = services.create_task(db, lu.id, hongliang.id, 10)
        services.confirm_address(db, t_lu.id, "周树人", "13800000001",
                                 "上海市虹口区四川北路 1 号")
        p_lu = services.outbound_original(db, t_lu.id, 10)
        _age_parcel(p_lu, 6)

        # 4) 舒庆春：原寄 8 份签收仅 6 份（少件 2），补寄包裹在途 2 天
        t_lao = services.create_task(db, lao.id, zhaxia.id, 8)
        services.confirm_address(db, t_lao.id, "舒庆春", "13800000002",
                                 "北京市东城区王府井大街 8 号")
        p_lao = services.outbound_original(db, t_lao.id, 8)
        services.submit_receipt(db, p_lao.id, "RT-SEED-LAO-01", "signed",
                                6, 0, "开箱只有 6 本，少 2 本")
        p_re, _ = services.create_reshipment(
            db, p_lao.id, "shortage", 2, "签收少件 2 份",
            None, None, None)
        _age_parcel(p_re, 2)

        # 5) 拒收场景：出库后地址变化先追加改派（原地址快照不动），
        #    派送时作者拒收（不计签收），随后按拒收原因重寄到新地址并签收
        t_mo = services.create_task(db, mo.id, hongliang.id, 4)
        services.confirm_address(db, t_mo.id, "管谟业", "13800000004",
                                 "山东省高密市平安路 12 号（旧地址）")
        p_mo = services.outbound_original(db, t_mo.id, 4, "首次出库")
        services.redirect_address(db, p_mo.id, "管谟业（家属代收）", "13800000004",
                                  "山东省青岛市市南区香港中路 66 号", "作者搬迁")
        services.submit_receipt(db, p_mo.id, "RT-SEED-MO-01", "rejected",
                                0, 0, "包裹仍送到旧地址，拒收")
        p_mo2, _ = services.create_reshipment(
            db, p_mo.id, "rejected", 4, "原包裹拒收，按新地址重寄",
            "管谟业（家属代收）", "13800000004",
            "山东省青岛市市南区香港中路 66 号")
        services.submit_receipt(db, p_mo2.id, "RT-SEED-MO-02", "signed", 4, 0, "已收到")

        db.commit()
    finally:
        db.close()
