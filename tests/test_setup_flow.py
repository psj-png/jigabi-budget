# 첫 설정을 브라우저처럼 눌러 보기: 각 화면의 칸(숨은 draft 포함)을 그대로 다음 요청에 보낸다
import json
import re
from html.parser import HTMLParser

from fastapi.testclient import TestClient

from app.main import app

TODAY = "2026-11-27"


class FormReader(HTMLParser):
    # 화면의 form에서 글자·숨은 칸, 체크된 체크박스, 버튼을 모은다
    def __init__(self):
        super().__init__()
        self.fields = []
        self.buttons = []
        self.in_form = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self.in_form = True
        if not self.in_form:
            return
        if tag == "input":
            kind = a.get("type", "text")
            if kind in ("checkbox", "radio"):
                if "checked" in a:
                    self.fields.append((a["name"], a.get("value", "on")))
            elif kind != "submit" and a.get("name"):
                self.fields.append((a["name"], a.get("value", "")))
        if tag == "button" and a.get("name"):
            self.buttons.append((a["name"], a.get("value", "")))

    def handle_endtag(self, tag):
        if tag == "form":
            self.in_form = False


def press(client, page, go, **change):
    # go 버튼을 누른다. change로 바꾼 칸이 있으면 그 값으로 보낸다
    reader = FormReader()
    reader.feed(page)
    assert ("go", go) in reader.buttons, f"{go} 버튼이 없다"
    data = {}
    for name, value in reader.fields:
        data.setdefault(name, []).append(value)
    data.update({k: [v] for k, v in change.items()})
    data["go"] = [go]
    r = client.post("/setup/step", data=data)
    assert r.status_code == 200
    return r.text


def draft_of(page):
    reader = FormReader()
    reader.feed(page)
    return json.loads(dict(reader.fields)["draft"])


def text_of(page):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))


def to_step4(client):
    # 1/5 잔액 500,000 → 2/5 → 3/5 → 4/5 요약
    page = client.get(f"/setup?today={TODAY}").text
    page = press(client, page, "next", balance="500000")
    page = press(client, page, "next")
    return press(client, page, "next")


def test_고치는_화면을_거쳐도_가는_곳이_남는다():
    client = TestClient(app)
    page = to_step4(client)
    page = press(client, page, "edit")    # 학교 카드를 누른다
    page = press(client, page, "back")    # 아무것도 안 바꾸고 < → 4/5 요약
    assert "이대로 할게요" in text_of(page)
    page = press(client, page, "back")    # 요약의 < → 3/5
    page = press(client, page, "next")    # 3/5 다음 → 4/5 요약
    assert [r["name"] for r in draft_of(page)["routines"]] == ["학교"]
    page = press(client, page, "next")    # 이대로 할게요 → 5/5
    text = text_of(page)
    assert "302,000원" in text            # 최소 생활비: 평일 20일 × 15,100
    assert "14,900원" in text and "빵빵" in text  # 하루 여유
    assert "30,000원" in text             # 오늘 쓸 수 있는 돈


def test_가는_곳이_없어요는_한_번_묻고_네를_눌러야_비운다():
    client = TestClient(app)
    page = to_step4(client)
    asked = press(client, page, "no_routine")
    assert "학교" in text_of(asked) and "빼고 계산할까요?" in text_of(asked)
    assert [r["name"] for r in draft_of(asked)["routines"]] == ["학교"]  # 아직 그대로
    kept = press(client, asked, "keep_routine")                           # 아니요
    assert "빼고 계산할까요?" not in text_of(kept) and "이대로 할게요" in text_of(kept)
    assert [r["name"] for r in draft_of(kept)["routines"]] == ["학교"]
    done = press(client, asked, "yes_no_routine")                         # 네
    assert draft_of(done)["routines"] == []
    assert "이렇게 계산할게요" in text_of(done)


def test_고치는_화면의_뒤로는_고친_내용을_담고_요약으로():
    client = TestClient(app)
    page = to_step4(client)
    page = press(client, page, "edit")
    page = press(client, page, "back", r_name="수업", r_fare="2500")
    text = text_of(page)
    assert "이대로 할게요" in text and "수업" in text and "2,500원" in text
    routines = draft_of(page)["routines"]
    assert [(r["name"], r["fare"]) for r in routines] == [("수업", "2500")]


def test_가는_곳_더하기_버튼은_하나():
    client = TestClient(app)
    page = to_step4(client)
    assert "알바도 있어요" not in text_of(page) and "가는 곳 더하기" in text_of(page)
    added = press(client, page, "add_routine")
    assert [r["name"] for r in draft_of(added)["routines"]] == ["학교", ""]
    assert 'placeholder="예: 알바, 학원"' in added
