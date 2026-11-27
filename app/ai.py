# 캡처로 상품 담기 (R20): 쇼핑 화면 캡처에서 상품 이름과 가격을 OpenAI로 읽는다
# 키(OPENAI_API_KEY)가 없으면 이 기능만 꺼진다. 캡처는 저장하지 않고 읽는 데만 쓴다
import base64
import json
import os
import urllib.error
import urllib.request

API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-6.1-terra"
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
    "search": "지금은 무신사를 찾지 못했어요. 잠시 뒤에 다시 물어봐 주세요",
    "plan": "지금은 계획을 짜지 못했어요. 잠시 뒤에 다시 물어봐 주세요",
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


# ---- 쇼핑 추천 (R21): OpenAI 웹 검색을 무신사(musinsa.com)로만 좁혀서 상품을 고른다 ----
RESPONSES_URL = "https://api.openai.com/v1/responses"
SHOP_DOMAIN = "musinsa.com"
MAX_PICKS = 4
SHOP_PROMPT = (
    "너는 대학생 가계부 앱 '지갑이'의 쇼핑 도우미야. 무신사(musinsa.com) 안에서만 웹 검색으로 상품을 찾아.\n"
    "- 사용자가 찾는 물건과 비슷한 상품을 최대 4개 골라. 캡처가 있으면 캡처 속 상품과 비슷한 걸 찾아.\n"
    "- 예산: {budget} 예산 안의 상품을 먼저 고르고, 넘는 상품은 넘는다고 말해.\n"
    "- 검색해서 실제로 본 무신사 상품 페이지만 추천하고, url은 그 상품 페이지 주소를 그대로 써. "
    "없는 상품이나 주소를 지어내지 마.\n"
    "- price는 페이지에 보이는 판매가(할인 적용)를 원 단위 정수로. 모르면 null.\n"
    "- reason은 고른 이유 한 줄(소재, 핏, 가격 등).\n"
    "- reply는 두 문장 이내, 친근한 '해요'체. 사지 말라고 훈계하지 말고 예산은 숫자로 짧게.\n"
    "- 쇼핑과 관계없는 부탁이면 items는 비우고, reply로 무신사에서 찾을 물건을 말해 달라고 해."
)
SHOP_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "items": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "price": {"type": ["integer", "null"]},
                           "url": {"type": "string"}, "reason": {"type": "string"}},
            "required": ["name", "price", "url", "reason"],
            "additionalProperties": False,
        }},
    },
    "required": ["reply", "items"],
    "additionalProperties": False,
}


def post_responses(payload):
    # OpenAI Responses API를 한 번 부른다 (웹 검색이 있어 오래 걸릴 수 있다)
    req = urllib.request.Request(
        RESPONSES_URL, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + os.getenv("OPENAI_API_KEY", "")},
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8"))


def page_key(url):
    # 주소 비교용: 'https://www.musinsa.com/products/1?x=1' -> 'musinsa.com/products/1'
    rest = str(url).split("://", 1)[-1].split("#", 1)[0].split("?", 1)[0]
    host, _, path = rest.partition("/")
    host = host.lower()
    for prefix in ("www.", "m."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    return host + "/" + path.rstrip("/")


def is_shop_url(url):
    # 무신사 주소인가 (하위 도메인 포함)
    url = str(url or "")
    if not url.startswith(("https://", "http://")):
        return False
    host = url.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0].lower()
    return host == SHOP_DOMAIN or host.endswith("." + SHOP_DOMAIN)


def shop_payload(text, budget_line, image_url=None):
    model = os.getenv("OPENAI_MODEL") or DEFAULT_MODEL
    content = [{"type": "input_text", "text": text}]
    if image_url:
        content.append({"type": "input_image", "image_url": image_url})
    payload = {
        "model": model,
        "instructions": SHOP_PROMPT.format(budget=budget_line),
        "input": [{"role": "user", "content": content}],
        "tools": [{"type": "web_search", "search_context_size": "low",
                   "filters": {"allowed_domains": [SHOP_DOMAIN]}}],
        "include": ["web_search_call.action.sources"],
        "text": {"format": {"type": "json_schema", "name": "picks", "strict": True, "schema": SHOP_SCHEMA}},
    }
    if model.startswith("gpt-5"):
        payload["reasoning"] = {"effort": "low"}  # 추론 모델만 받는 값
    return payload


def parse_picks(answer):
    # 답에서 (문장, 상품 카드)를 꺼낸다. 검색에서 실제로 본 무신사 페이지만 남긴다 (지어낸 상품 거르기)
    seen, text = set(), ""
    for out in answer.get("output") or []:
        if out.get("type") == "web_search_call":
            for source in (out.get("action") or {}).get("sources") or []:
                if source.get("url"):
                    seen.add(page_key(source["url"]))
        elif out.get("type") == "message":
            for part in out.get("content") or []:
                if part.get("type") == "output_text":
                    text += part.get("text") or ""
                    for note in part.get("annotations") or []:
                        if note.get("url"):
                            seen.add(page_key(note["url"]))
    data = json.loads(text)
    reply = " ".join(str(data.get("reply") or "").split())[:300]
    picks = []
    for it in data.get("items") or []:
        url = str(it.get("url") or "")
        if not is_shop_url(url) or (seen and page_key(url) not in seen):
            continue
        item = clean_item({"name": it.get("name"), "price": it.get("price")})
        if item["name"] is None:
            continue
        picks.append({"name": item["name"], "price": item["price"], "url": url[:500],
                      "reason": " ".join(str(it.get("reason") or "").split())[:120]})
        if len(picks) == MAX_PICKS:
            break
    return reply, picks


def recommend(text, budget_line, image=None, call=None):
    # (답 문장, 상품 카드 목록, None) 또는 (None, [], ERRORS의 키). call은 테스트에서 가짜로 바꿔 끼운다
    image_url = None
    if image is not None:
        mime = image_type(image)
        if mime is None:
            return None, [], "type"
        if len(image) > MAX_BYTES:
            return None, [], "size"
        image_url = "data:" + mime + ";base64," + base64.b64encode(image).decode("ascii")
    try:
        reply, picks = parse_picks((call or post_responses)(shop_payload(text, budget_line, image_url)))
    except urllib.error.HTTPError as e:
        print("쇼핑 추천 실패:", e.code, e.read()[:300])
        return None, [], "search"
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, TypeError, AttributeError, ValueError) as e:
        print("쇼핑 추천 실패:", repr(e))
        return None, [], "search"
    return reply, picks, None


# ---- 계획 도우미 (R22): 다음 돈 들어오는 날까지 어떻게 쓸지. 앱이 계산한 선택지 안에서만 고른다 ----
PLAN_PROMPT = (
    "너는 대학생 가계부 앱 '지갑이'의 계획 도우미야. 다음 돈 들어오는 날까지 어떻게 쓸지 물으면, "
    "아래 지갑 상태를 보고 두세 문장으로 친근한 '해요'체로 답해.\n"
    "- 계획을 바꾸려면 선택지 안에서만 골라. meal_days는 '도시락으로 바꿀 수 있는 날'에 있는 날짜(YYYY-MM-DD)만, "
    "save는 모아 둘 돈으로 0부터 '모아 둘 수 있는 최대'까지 1,000원 단위.\n"
    "- 바꾼 뒤의 하루 여유 같은 새 숫자는 말하지 마. 앱이 다시 계산해서 보여 줘. 상태에 있는 숫자는 써도 돼.\n"
    "- 끼니를 거르라는 말은 하지 마. 밖에서 사 먹을 점심을 도시락으로 바꾸는 것만 제안해.\n"
    "- 다가오는 약속이 있으면 그 전후로 어떻게 쓰면 좋을지 짧게 말해 줘.\n"
    "- 바꿀 필요가 없으면 meal_days는 비우고 save는 0.\n"
    "- '모자란 돈'이 있으면 물건을 사서 이번 기간 돈이 모자란 거야. 모아 두기는 0으로 두고, 도시락 날과 약속 줄이기(cuts)로 메울 방법을 골라.\n"
    "- 약속은 사용자가 줄여도 된다고 말한 것만 줄여 (예: 술자리는 1차만). 그대로 두겠다는 약속은 고르지 마. "
    "사용자가 약속에 대해 아무 말도 안 했으면 cuts는 비우고, 어떤 약속을 줄여도 되는지 물어봐.\n"
    "- cuts의 appt_id는 '줄일 수 있는 약속'에 있는 것만, amount는 그 약속의 '줄일 수 있는 최대' 안에서 1,000원 단위. "
    "그래도 남는 돈은 다시 짜기 화면에서 비상금으로 메운다고 알려 줘.\n"
    "지갑 상태와 선택지(JSON): {context}"
)
PLAN_SCHEMA = {
    "type": "object",
    "properties": {"reply": {"type": "string"},
                   "meal_days": {"type": "array", "items": {"type": "string"}},
                   "save": {"type": "integer"},
                   "cuts": {"type": "array", "items": {
                       "type": "object",
                       "properties": {"appt_id": {"type": "integer"}, "amount": {"type": "integer"}},
                       "required": ["appt_id", "amount"], "additionalProperties": False}}},
    "required": ["reply", "meal_days", "save", "cuts"],
    "additionalProperties": False,
}


def plan_reply(context, text, call=None):
    # (답 문장, {"meal_days", "save", "cuts"}, None) 또는 (None, None, "plan")
    model = os.getenv("OPENAI_MODEL") or DEFAULT_MODEL
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": PLAN_PROMPT.format(context=json.dumps(context, ensure_ascii=False))},
                     {"role": "user", "content": text}],
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "plan", "strict": True, "schema": PLAN_SCHEMA}},
    }
    if model.startswith("gpt-5"):
        payload["reasoning_effort"] = "low"
    try:
        answer = (call or post)(payload)
        data = json.loads(answer["choices"][0]["message"].get("content") or "{}")
        days = [str(d) for d in data.get("meal_days") or []]
        save = data.get("save") if isinstance(data.get("save"), int) and not isinstance(data.get("save"), bool) else 0
        cuts = [{"appt_id": int(c["appt_id"]), "amount": int(c["amount"])} for c in data.get("cuts") or []]
    except urllib.error.HTTPError as e:
        print("계획 도우미 실패:", e.code, e.read()[:300])
        return None, None, "plan"
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, TypeError, AttributeError, ValueError) as e:
        print("계획 도우미 실패:", repr(e))
        return None, None, "plan"
    return " ".join(str(data.get("reply") or "").split())[:300], {"meal_days": days, "save": save, "cuts": cuts}, None
