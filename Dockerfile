FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    TZ=Asia/Shanghai \
    XIUXIAN3_DATA_DIR=/app/data

WORKDIR /app
COPY requirements.txt /tmp/xiuxian3-requirements.txt
COPY nonebot_plugin_xiuxian_3 /app/src/plugins/nonebot_plugin_xiuxian_3
COPY data /app/content-data
COPY docker/pyproject.toml /app/pyproject.toml
RUN python -m pip install --no-cache-dir -r /tmp/xiuxian3-requirements.txt \
    && nb --cwd /app --python "$(command -v python)" adapter install --no-restrict-version QQ \
    && nb --cwd /app --python "$(command -v python)" adapter install --no-restrict-version "OneBot V11" \
    && nb --cwd /app --python "$(command -v python)" driver install FastAPI \
    && nb --cwd /app --python "$(command -v python)" driver install HTTPX \
    && nb --cwd /app --python "$(command -v python)" driver install websockets \
    && nb --cwd /app --python "$(command -v python)" driver install AIOHTTP \
    && mkdir -p /app/data /app/runtime \
    && cp -R /app/content-data/. /app/data/ \
    && rm -f /tmp/xiuxian3-requirements.txt

COPY docker/bot.py /app/bot.py
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

VOLUME ["/app/data", "/app/runtime"]
EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
CMD ["nb", "run"]
