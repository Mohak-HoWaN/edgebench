# Server image: the API, the job worker and the built web app in one process (the server serves web/dist itself).
# The heavy conversion toolchain (torch, ultralytics, OpenVINO...) is NOT in this image; it arrives with the converter in Phase 2.

FROM node:24-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim AS server
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    EDGEBENCH_HOST=0.0.0.0 \
    EDGEBENCH_DATA_DIR=/data \
    EDGEBENCH_WEB_DIST=/app/web/dist
WORKDIR /app
COPY server/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY server/edgebench ./edgebench
COPY --from=web /web/dist ./web/dist
RUN useradd --system --uid 10001 edgebench && mkdir /data && chown edgebench /data
USER edgebench
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).status == 200 else 1)"
CMD ["python", "-m", "edgebench"]
