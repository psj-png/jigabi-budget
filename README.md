# 지갑이 (jigabi)

사기 전에 '이거 사면 이번 달 내 생활'을 보여주고, 산 뒤엔 남은 날을 다시 짜주는 대학생 생활비 웹앱

## 왜 만들었나

겨울옷처럼 여러 개를 한 번에 사고 나면, 그 달이 얼마나 빠듯해질지는 산 뒤에야 알게 된다.
지갑이는 사기 전에 남은 날의 하루 여유가 어떻게 바뀌는지 보여주고, 산 뒤에도 밥값과 교통비(최소 생활비)는 지키도록 남은 날을 다시 짠다.

## 주요 기능

1. 장바구니 미리보기: 사고 싶은 것을 담고 빼면 하루 여유와 지갑이 단계가 바로 바뀐다.
2. 나눠 사기: 한 번에 사면 최소 생활비를 건드릴 때, 알바비가 들어오는 날에 맞춰 나눠 살 날짜를 추천한다.
3. 다시 짜기: 산 뒤 모자라면 반품 → 약속 줄이기 → 비상금 순서로 남은 날을 다시 짠다.

## 데모

준비 중 (미리보기, 나눠 사기, 다시 짜기 GIF)

## 실행 방법

Docker가 설치되어 있어야 한다.

```bash
cp .env.example .env
docker compose up --build
```

브라우저에서 http://localhost:8000 을 연다.
http://localhost:8000/demo 를 열면 예시 사람(seed)으로 둘러볼 수 있다.

DB는 처음 실행할 때 `db/schema.sql`, `db/seed.sql`이 자동으로 들어간다. 테이블을 처음부터 다시 만들려면 `docker compose down -v` 후 다시 실행한다.

## 기술 스택

- FastAPI, Jinja2
- MySQL 8.4 (PyMySQL로 SQL을 직접 작성)
- Docker Compose

## 폴더 구조

```
app/    서버 코드와 화면
db/     테이블(schema.sql), 예시 데이터(seed.sql)
docs/   계산 규칙
```

## DB 설계

준비 중 (ERD 그림)

테이블 10개: users, routines, routine_days, incomes, fixed_costs, appointments, wish_items, balance_logs, periods, loans

## 계산 규칙

[docs/rules.md](docs/rules.md)

## 참고한 코드·자료

- 

## 라이선스

[MIT](LICENSE)
