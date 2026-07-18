# ---- Build stage: install dependencies into an isolated prefix ----
FROM python:3.12-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- Runtime stage: minimal image, non-root user ----
FROM python:3.12-slim
RUN useradd --create-home --shell /usr/sbin/nologin pitchside
WORKDIR /srv/pitchside
COPY --from=builder /install /usr/local
COPY app/ app/
COPY main.py .
USER pitchside
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 2 --threads 4 --timeout 120 main:app"]
