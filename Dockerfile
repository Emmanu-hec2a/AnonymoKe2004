FROM python:3.12-slim-trixie AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential libgdal-dev libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml .
COPY manage.py .
COPY apps ./apps
COPY config ./config

RUN python -m pip install --upgrade pip \
    && python -m pip wheel --no-cache-dir --wheel-dir /wheels .


FROM python:3.12-slim-trixie AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install --no-install-recommends -y gdal-bin libgdal-dev libpq5 ffmpeg libglib2.0-0t64 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /usr/sbin/nologin anonymoke

WORKDIR /app
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir /wheels/*.whl \
    && rm -rf /wheels

COPY --chown=anonymoke:anonymoke . .

# Check the actual Redis transport without opening a broker connection. This
# catches dependency mismatches before either the API or worker is deployed.
RUN python -m pip check
RUN python -c "from importlib.metadata import version; from kombu.transport.redis import Channel; Channel.__new__(Channel)._get_client(); print('Celery Redis transport compatible:', {name: version(name) for name in ('celery', 'kombu', 'redis')})"

# Check native GIS support and migration parity before this image can be deployed.
RUN python -c "import sys; from django.contrib.gis.gdal import GDAL_VERSION; print('GDAL version:', GDAL_VERSION); sys.exit(0 if GDAL_VERSION >= (3, 9) else 'GDAL >= 3.9 is required')"
RUN DJANGO_SETTINGS_MODULE=config.settings.dev DATABASE_URL=sqlite://:memory: \
    python manage.py makemigrations --check --dry-run --noinput

USER anonymoke

EXPOSE 8000
CMD ["sh", "-c", "exec daphne -b 0.0.0.0 -p ${PORT:-8000} config.asgi:application"]

