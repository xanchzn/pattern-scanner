# Single-service Railway deployment: Next.js + Python scanner in one container.
FROM node:22-bookworm-slim AS frontend-build
WORKDIR /build
COPY frontend/package*.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim-bookworm
ENV PYTHONUNBUFFERED=1 NODE_ENV=production PORT=3000 DATABASE_PATH=/data/scanner.sqlite BACKEND_URL=http://127.0.0.1:8000
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl && rm -rf /var/lib/apt/lists/*
COPY --from=frontend-build /usr/local/bin/node /usr/local/bin/node
COPY --from=frontend-build /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm
WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt
COPY backend/ /app/backend/
COPY --from=frontend-build /build /app/frontend
COPY start-railway.sh /app/start-railway.sh
RUN chmod +x /app/start-railway.sh && mkdir -p /data
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s CMD curl -fsS http://localhost:3000/ >/dev/null || exit 1
CMD ["/app/start-railway.sh"]
