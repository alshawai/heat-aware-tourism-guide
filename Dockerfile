FROM node:22-bookworm-slim@sha256:83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5 AS frontend-build

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN npm ci --prefix frontend
COPY frontend ./frontend
RUN npm run build --prefix frontend

FROM python:3.12-slim@sha256:09f7da3bc104798d0afb40bc08d23ab2da20a76130cec1f2ef170848f5d85217 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
RUN python -m venv .venv \
    && .venv/bin/python -m pip install --no-cache-dir --no-deps . \
    && .venv/bin/python -m pip install --no-cache-dir \
        annotated-doc==0.0.5 \
        annotated-types==0.8.0 \
        anyio==4.14.2 \
        astral==3.2 \
        certifi==2026.7.22 \
        click==8.5.0 \
        fastapi==0.141.1 \
        h11==0.16.0 \
        idna==3.19 \
        numpy==2.5.2 \
        pydantic==2.13.5 \
        pydantic-core==2.46.5 \
        pyproj==3.7.2 \
        shapely==2.1.2 \
        starlette==1.6.0 \
        typing-extensions==4.16.0 \
        typing-inspection==0.4.4 \
        uvicorn==0.35.0

RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

COPY fixtures ./fixtures
COPY --from=frontend-build /build/frontend/dist ./frontend/dist

EXPOSE 8000
USER appuser
CMD ["sh", "-c", "exec python -m uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8000}\" --workers 1"]
