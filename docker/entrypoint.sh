#!/bin/sh
set -eu

cd /app
mkdir -p /app/data

# Use the same fingerprint migration and rollback as Linux/Windows installs.
python /app/install-tools/install_plugin_source.py --data-only \
    --data-source /app/content-data --target /app --validate-after-install

exec "$@"
