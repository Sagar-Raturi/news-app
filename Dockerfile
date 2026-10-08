FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Static files are collected into the image (WhiteNoise serves them with
# hashed names). The settings only need throwaway values to import here.
RUN DJANGO_DEBUG=0 DJANGO_SECRET_KEY=collectstatic-only python manage.py collectstatic --noinput

# Run as an unprivileged user; it owns the media folder (a volume in Compose).
RUN useradd --create-home --uid 1000 app && mkdir -p /app/media && chown -R app:app /app/media
USER app

EXPOSE 8000
ENTRYPOINT ["sh", "docker/entrypoint.sh"]
# Production server: gunicorn managing uvicorn (ASGI) workers, so the live
# activity feed can stream. Development overrides this in docker-compose.yml.
CMD ["gunicorn", "config.asgi:application", "-c", "docker/gunicorn.conf.py"]
