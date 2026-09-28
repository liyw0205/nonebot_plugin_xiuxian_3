#!/bin/sh
set -eu

cd /app
mkdir -p /app/data

# A mounted empty data volume must still receive the installed content pack.
if [ ! -f /app/data/内容清单.json ]; then
    cp -R /opt/xiuxian3/data/. /app/data/
fi

exec "$@"
