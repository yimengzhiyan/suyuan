FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 SUYUAN_PUBLIC=1 SUYUAN_CACHE_DIR=/app/.cache
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
RUN mkdir -p /app/.cache
EXPOSE 8601
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8601", "--proxy-headers"]
