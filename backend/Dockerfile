ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}

ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MALLOC_ARENA_MAX=2 \
    TZ=Asia/Shanghai

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -i ${PIP_INDEX_URL} -r requirements.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

EXPOSE 8000

# 2C2G 默认单 async worker（约省 160MB 内存，协程轻松承载百级并发 SSE）；4G+ 可通过 UVICORN_WORKERS=2 扩展
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-1} --limit-concurrency ${UVICORN_MAX_CONCURRENCY:-120} --timeout-keep-alive 30 --no-access-log"]
