#!/usr/bin/with-contenv bash
set -euo pipefail

source /usr/lib/bashio/bashio.sh

message="$(bashio::config 'message')"
if [[ -z "${message}" ]]; then
  message="Hello from the test add-on!"
fi
echo "[test-addon] ${message}"

while true; do
  sleep 60
done
