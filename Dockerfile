FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

RUN mkdir -p cache/apollo

EXPOSE 5050

CMD ["sh", "-c", "gunicorn server:app --bind 0.0.0.0:${PORT:-5050} --workers 2 --timeout 120 --access-logfile -"]
