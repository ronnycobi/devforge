# DevForge backend image.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ /app/backend/
WORKDIR /app/backend

EXPOSE 8000

# Dev default. Production overrides this with gunicorn (see docs/PRODUCT.md).
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
