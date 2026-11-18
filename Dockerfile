FROM python:3.13-slim

# 날짜는 한국 시간으로 센다 (컨테이너 기본 UTC면 오전 9시 전에는 date.today()가 어제가 된다)
ENV TZ=Asia/Seoul
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /code
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
