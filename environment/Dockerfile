FROM python:3.12-slim@sha256:cb33f7f771ecec2ef1225cf39b159591a040391bd73e4c01f00fdfc4c47611d2
WORKDIR /app
COPY solve.py /app/solve.py
RUN python -m pip install --no-cache-dir pytest==8.4.2
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
