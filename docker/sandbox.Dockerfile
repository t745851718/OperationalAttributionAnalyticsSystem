FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir duckdb==2.0.1 scipy==1.18.1 numpy==2.5.5
COPY backend/__init__.py backend/catalog.py backend/sandbox_worker.py /app/backend/
ENV PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
USER 65534:65534
ENTRYPOINT ["python", "-m", "backend.sandbox_worker"]
