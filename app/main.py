from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates

from app.db import get_conn

app = FastAPI()
templates = Jinja2Templates(directory="app/templates")


@app.get("/")
def index(request: Request):
    # 지금은 예시 사람(1번)만 보여줌
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT name, price, need_by FROM wish_items WHERE user_id = %s", (1,))
            items = cur.fetchall()
    finally:
        conn.close()
    return templates.TemplateResponse(request, "index.html", {"items": items})
