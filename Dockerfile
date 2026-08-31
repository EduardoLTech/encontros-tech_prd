FROM python:3.12-slim AS builder

WORKDIR /build

COPY src/requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


FROM python:3.12-slim AS runtime

RUN groupadd --system app && useradd --system --gid app --create-home app

WORKDIR /app

COPY --from=builder /root/.local /home/app/.local
# gunicorn.conf.py fica fora de /app: em dev o bind mount de ./src cobre
# /app inteiro, e um arquivo dentro dele desapareceria do container.
COPY gunicorn.conf.py /etc/gunicorn.conf.py
COPY src/ /app/

ENV PATH=/home/app/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc

RUN mkdir -p "$PROMETHEUS_MULTIPROC_DIR" \
    && chown -R app:app /app "$PROMETHEUS_MULTIPROC_DIR"

USER app

EXPOSE 8000

CMD ["gunicorn", "-c", "/etc/gunicorn.conf.py", "main:app"]
