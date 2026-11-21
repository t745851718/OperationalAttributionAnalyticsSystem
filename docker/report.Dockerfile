FROM python:3.12-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 fonts-noto-cjk poppler-utils \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir weasyprint==70.0
ENV PYTHONDONTWRITEBYTECODE=1 HOME=/tmp XDG_CACHE_HOME=/tmp
USER 65534:65534
ENTRYPOINT ["weasyprint", "-", "-"]
