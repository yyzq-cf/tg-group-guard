FROM python:3.11-slim

LABEL maintainer="ywsj"
LABEL description="Telegram Group Guard Bot - 群组管理机器人"

# Version injected by CI (build-arg)
ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION}

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/

EXPOSE 8080
CMD ["python", "-m", "app"]
