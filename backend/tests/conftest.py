import os

os.environ["SAMPLESHIP_SKIP_SEED"] = "1"   # 测试不写入演示数据

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base, get_db
from backend.app.main import app


class Env:
    def __init__(self, client, session_local):
        self.client = client
        self.SessionLocal = session_local


@pytest.fixture()
def env(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/test.db",
                           connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield Env(c, TestingSessionLocal)
    app.dependency_overrides.clear()


# ------------------------------------------------------------ 构造助手

def make_author(client, name="林晚晴", with_address=True, confirm=True):
    r = client.post("/api/authors", json={"name": name})
    assert r.status_code == 201, r.text
    author_id = r.json()["id"]
    address_id = None
    if with_address:
        r = client.post(f"/api/authors/{author_id}/addresses", json={
            "recipient": name, "phone": "13800000001",
            "region": "浙江省 杭州市", "detail": "文三路 100 号"})
        assert r.status_code == 201, r.text
        address_id = r.json()["id"]
        if confirm:
            r = client.post(f"/api/addresses/{address_id}/confirm",
                            json={"confirmed_by": "编辑-测试"})
            assert r.status_code == 200, r.text
    return author_id, address_id


def make_book_with_editions(client, title="山海经营指南", editions=("第1版", "第2版")):
    r = client.post("/api/books", json={"title": title, "isbn": f"isbn-{title}"})
    assert r.status_code == 201, r.text
    book_id = r.json()["id"]
    ids = {}
    for no in editions:
        r = client.post(f"/api/books/{book_id}/editions",
                        json={"edition_no": no})
        assert r.status_code == 201, r.text
        ids[no] = r.json()["id"]
    return book_id, ids


def make_task(client, author_id, edition_id, qty):
    r = client.post("/api/tasks", json={
        "author_id": author_id, "edition_id": edition_id,
        "quantity_due": qty, "created_by": "编辑-测试"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def ship(client, task_id, qty):
    r = client.post(f"/api/tasks/{task_id}/packages",
                    json={"quantity": qty, "shipped_by": "仓库-测试"})
    assert r.status_code == 201, r.text
    return r.json()


def receipt(client, package_id, result, qty, key, note=""):
    return client.post(f"/api/packages/{package_id}/receipt", json={
        "result": result, "received_qty": qty, "note": note,
        "signed_by": "作者", "idempotency_key": key})


def task(client, task_id):
    r = client.get(f"/api/tasks/{task_id}")
    assert r.status_code == 200, r.text
    return r.json()
