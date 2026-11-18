# 캡처로 상품 담기 (R20): 쇼핑 화면 캡처에서 상품 이름과 가격을 OpenAI로 읽는다
# 키(OPENAI_API_KEY)가 없으면 이 기능만 꺼진다. 캡처는 저장하지 않고 읽는 데만 쓴다
import base64
import json
import os
import urllib.error
import urllib.request

API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-5-mini"
MAX_BYTES = 5 * 1024 * 1024  # 캡처는 5MB까지
MAX_PRICE = 1_000_000_000
PROMPT = (
    "쇼핑 앱이나 쇼핑몰의 상품 화면을 캡처한 이미지예요. 사려는 상품의 이름과 지금 내야 하는 가격을 읽어 주세요.\n"
    "- 가격은 할인이 있으면 할인된 최종 가격으로, 배송비는 빼고, 원 단위 정수로.\n"
    "- 상품이 여러 개 보이면 가장 크게 보이는 하나만.\n"
    "- 이름은 화면에 적힌 상품명을 60자 안으로.\n"
    "- 상품 화면이 아니거나 읽을 수 없는 값은 null."
)
# 답은 이 모양으로만 받는다 (structured outputs)
SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": ["string", "null"]}, "price": {"type": ["integer", "null"]}},
    "required": ["name", "price"],
    "additionalProperties": False,
}
# 화면에 보여줄 안내 (주소에는 짧은 이름만 싣는다)
ERRORS = {
    "type": "이미지 파일만 읽을 수 있어요 (png, jpg, webp)",
    "size": "캡처가 너무 커요. 5MB까지 올릴 수 있어요",
    "fail": "캡처를 읽지 못했어요. 이름과 가격을 직접 적어 주세요",
    "none": "캡처에서 상품 이름이나 가격을 찾지 못했어요. 직접 적어 주세요",
}


def enabled():
    return bool(os.getenv("OPENAI_API_KEY"))


def image_type(data):
    # 파일 앞부분으로 형식을 본다 (브라우저가 알려 준 형식은 믿지 않는다)
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def clean_item(raw):
    # AI가 돌려준 값 정리: 이름은 공백을 줄여 60자까지, 가격은 1원~10억 원 정수. 아니면 None
    if not isinstance(raw, dict):
        raw = {}
    name, price = raw.get("name"), raw.get("price")
    name = " ".join(str(name).split())[:60] if name else None
    if isinstance(price, str):
        digits = "".join(ch for ch in price if ch.isdigit())
        price = int(digits) if digits else None
    if isinstance(price, float):
        price = int(price)
    if isinstance(price, bool) or not isinstance(price, int) or not 1 <= price <= MAX_PRICE:
        price = None
    return {"name": name or None, "price": price}


def post(payload):
    # OpenAI Chat Completions를 한 번 부른다 (표준 라이브러리만 쓴다)
    req = urllib.request.Request(
        API_URL, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + os.getenv("OPENAI_API_KEY", "")},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def read_item(data, call=None):
    # 캡처 -> ({"name", "price"}, None) 또는 (None, ERRORS의 키). call은 테스트에서 가짜로 바꿔 끼운다
    mime = image_type(data)
    if mime is None:
        return None, "type"
    if len(data) > MAX_BYTES:
        return None, "size"
    image = "data:" + mime + ";base64," + base64.b64encode(data).decode("ascii")
    payload = {
        "model": os.getenv("OPENAI_MODEL") or DEFAULT_MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url", "image_url": {"url": image}},
        ]}],
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "item", "strict": True, "schema": SCHEMA}},
    }
    try:
        answer = (call or post)(payload)
        item = clean_item(json.loads(answer["choices"][0]["message"].get("content") or "{}"))
    except urllib.error.HTTPError as e:
        # 키가 틀렸거나 모델 이름이 없을 때: 원인은 서버 로그에만 남긴다
        print("캡처 읽기 실패:", e.code, e.read()[:300])
        return None, "fail"
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError) as e:
        print("캡처 읽기 실패:", repr(e))
        return None, "fail"
    if item["name"] is None and item["price"] is None:
        return None, "none"
    return item, None
