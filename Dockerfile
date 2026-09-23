# 多阶段构建：先构建前端（Vue 3 + Vite），再打包后端（FastAPI）并托管前端产物。
FROM node:24-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim AS backend
WORKDIR /app

# 后端依赖
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 后端源码
COPY backend/ ./backend/

# 前端构建产物（由上一阶段复制）
COPY --from=frontend /build/dist ./frontend/dist

# 数据库持久化目录（运行时挂载卷）
ENV SEA_FREIGHT_DB=/app/data/sea_freight.db
RUN mkdir -p /app/data

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
