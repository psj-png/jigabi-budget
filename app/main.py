from datetime import date

from fastapi import FastAPI, HTTPException, Request
from fastapi.templating import Jinja2Templates

from app.db import get_conn
from app.home import make_home

app = FastAPI()
templates = Jinja2Templates(directory="app/templates")


@app.get("/")
def home(request: Request, today: str = None):
    # ?today=2026-10-30 으로 오늘 날짜를 고정할 수 있다 (없으면 진짜 오늘)
    try:
        day = date.fromisoformat(today) if today else date.today()
    except ValueError:
        raise HTTPException(status_code=400, detail="today는 2026-10-30 모양이어야 해요")

    # 지금은 예시 사람(1번)만 보여줌
    conn = get_conn()
    try:
        data = make_home(conn, 1, day)
    finally:
        conn.close()
    return templates.TemplateResponse(request, "home.html", {"h": data})


@app.get("/wishes")
def wishes(request: Request):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT name, price, need_by FROM wish_items WHERE user_id = %s", (1,))
            items = cur.fetchall()
    finally:
        conn.close()
    return templates.TemplateResponse(request, "index.html", {"items": items})
