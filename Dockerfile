FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai \
    XIUXIAN3_DATA_DIR=/app/data

WORKDIR /app
COPY . /opt/xiuxian3
RUN python -m pip install --no-cache-dir "/opt/xiuxian3[nonebot,onebot,qq]" \
    && mkdir -p /app/data /app/runtime \
    && cp -R /opt/xiuxian3/data/. /app/data/

COPY docker/bot.py /app/bot.py
COPY docker/pyproject.toml /app/pyproject.toml
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

VOLUME ["/app/data", "/app/runtime"]
EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
CMD ["nb", "run"]
