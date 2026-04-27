FROM python:3.11-alpine

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY Container/controller.py /app/controller.py
COPY Container/static /app/static
COPY Container/settings.example.json /app/default-settings.json

EXPOSE 8080 9777

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.getenv('WEB_PORT', '8080')}/health\", timeout=3)"

CMD ["python", "/app/controller.py"]
