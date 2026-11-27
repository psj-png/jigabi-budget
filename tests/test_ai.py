# 캡처로 상품 담기 (R20): OpenAI는 부르지 않고 가짜 응답으로 확인한다
import json

from app import ai

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


def answer(content):
    return lambda payload: {"choices": [{"message": {"content": content}}]}


def test_캡처에서_이름과_가격을_읽는다(monkeypatch):
    sent = {}

    def fake(payload):
        sent.update(payload)
        return {"choices": [{"message": {"content": json.dumps({"name": " 오버핏  후드티 ", "price": 39000})}}]}

    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    assert ai.read_item(PNG, call=fake) == ({"name": "오버핏 후드티", "price": 39000}, None)
    # 캡처는 data URL로 보내고, 답은 json_schema(strict)로 받는다. 모델은 기본값
    image = sent["messages"][0]["content"][1]["image_url"]["url"]
    assert image.startswith("data:image/png;base64,")
    assert sent["model"] == ai.DEFAULT_MODEL
    assert sent["response_format"]["json_schema"]["strict"] is True
    monkeypatch.setenv("OPENAI_MODEL", "다른-모델")
    ai.read_item(PNG, call=fake)
    assert sent["model"] == "다른-모델"


def test_이미지가_아니거나_너무_크면_보내지_않는다():
    def boom(payload):
        raise AssertionError("부르면 안 된다")

    assert ai.read_item(b"%PDF-1.7 ...", call=boom) == (None, "type")
    assert ai.read_item(PNG + b"0" * ai.MAX_BYTES, call=boom) == (None, "size")
    assert ai.image_type(b"\xff\xd8\xff\xe0" + b"0" * 10) == "image/jpeg"
    assert ai.image_type(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"


def test_못_읽으면_직접_적게_한다():
    assert ai.read_item(PNG, call=answer(json.dumps({"name": None, "price": None}))) == (None, "none")
    assert ai.read_item(PNG, call=answer("JSON이 아닌 답")) == (None, "fail")

    def down(payload):
        raise TimeoutError()

    assert ai.read_item(PNG, call=down) == (None, "fail")
    assert set(ai.ERRORS) == {"type", "size", "fail", "none", "search"}


def test_읽은_값_정리():
    assert ai.clean_item({"name": "가" * 80, "price": "39,000원"}) == {"name": "가" * 60, "price": 39000}
    assert ai.clean_item({"name": "", "price": 0}) == {"name": None, "price": None}
    assert ai.clean_item({"name": "양말", "price": 2_000_000_000}) == {"name": "양말", "price": None}
    assert ai.clean_item({"name": "양말", "price": True}) == {"name": "양말", "price": None}
    assert ai.clean_item("이상한 값") == {"name": None, "price": None}


def test_키가_없으면_꺼진다(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert not ai.enabled()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert ai.enabled()
