"""LF-9 standalone staff API. Owner/read-only DB logins are separate."""
import hmac
import os
from datetime import datetime
from fastapi import FastAPI, Body, Header, HTTPException, Depends
from center.collections import CollectionStore, CollectionError
from center.statistics import Statistics


def create_app(collections=None, statistics=None, staff_key=None, places=None):
    app = FastAPI(title="본센터 회수·통계", version="0.1")
    key = staff_key if staff_key is not None else os.environ.get("LF_STAFF_API_KEY", "")

    def authorize(x_staff_key: str = Header(default="")):
        if not key:
            raise HTTPException(503, "직원 접근 키가 설정되지 않았습니다")
        if not hmac.compare_digest(x_staff_key, key):
            raise HTTPException(403, "직원 인증이 필요합니다")

    def backend(store):
        if store is None:
            raise HTTPException(503, "DB 연결이 설정되지 않았습니다")
        return store

    @app.post("/collections", dependencies=[Depends(authorize)])
    def pickup(body: dict = Body(...)):
        try:
            return backend(collections).pickup(body.get("machine_id"), body.get("item_ids"), body.get("request_id"))
        except CollectionError as e:
            raise HTTPException(409, str(e)) from None

    @app.get("/collections/{collection_id}", dependencies=[Depends(authorize)])
    def get_collection(collection_id: int):
        try:
            return backend(collections).get(collection_id)
        except CollectionError as e:
            raise HTTPException(404, str(e)) from None

    @app.post("/collections/{collection_id}/arrivals", dependencies=[Depends(authorize)])
    def arrival(collection_id: int, body: dict = Body(...)):
        try:
            return backend(collections).arrive(collection_id, body.get("item_ids"))
        except CollectionError as e:
            raise HTTPException(409, str(e)) from None

    @app.post("/collections/overdue/check", dependencies=[Depends(authorize)])
    def overdue(body: dict = Body(...)):
        try:
            before = datetime.fromisoformat(body.get("before", ""))
            return {"queued": backend(collections).overdue(before)}
        except (ValueError, TypeError) as e:
            raise HTTPException(422, "시간대를 포함한 기준시각이 필요합니다") from e

    @app.post("/statistics/questions", dependencies=[Depends(authorize)])
    def ask(body: dict = Body(...)):
        try:
            return backend(statistics).ask(body.get("question"))
        except ValueError as e:
            raise HTTPException(422, str(e)) from None

    @app.get("/places", dependencies=[Depends(authorize)])
    def recommend(machine_id: str, offset: int = 0):
        try:
            return backend(places).recommend(machine_id, offset)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None

    @app.post("/places", dependencies=[Depends(authorize)])
    def put_place(body: dict = Body(...)):
        try:
            return backend(places).put(body.get("line"), body.get("station"), body.get("label"))
        except ValueError as e:
            raise HTTPException(422, str(e)) from None

    return app


def from_environment():
    def connect(name):
        dsn = os.environ.get(name)
        if not dsn:
            return None
        def open_connection():
            import psycopg
            return psycopg.connect(dsn, connect_timeout=5)
        return open_connection
    write, read = connect("DATABASE_URL"), connect("LF_STATS_DATABASE_URL")
    from center.places import Places
    return create_app(CollectionStore(write) if write else None, Statistics(read) if read else None,
                      places=Places(write) if write else None)


app = from_environment()
