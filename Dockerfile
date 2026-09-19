FROM python:3.12-alpine

LABEL org.opencontainers.image.source="https://github.com/mlo-Tek/qbt-slowban-hotio"

RUN pip install --no-cache-dir requests

WORKDIR /app

COPY slowban.py /app/slowban.py
COPY runner.py /app/runner.py

RUN chmod +x /app/slowban.py /app/runner.py

CMD ["python", "/app/runner.py"]
