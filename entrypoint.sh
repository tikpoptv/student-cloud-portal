#!/bin/sh
set -eu
# PORTAL_MODE defaults to preview (app.py). Production sets it explicitly (hosted-live-env: PORTAL_MODE=live,
# see LIVE-ACTIVATION.md), so the preview worker below only ever runs in preview.
# The preview worker only simulates group activation and never calls cloud APIs. In live mode real provisioning
# is done by the private provisioner service (LIVE_WORKER=1) handling Cloud Tasks at /internal/provision.
if [ "${PORTAL_MODE:-preview}" = preview ]; then
  python app.py --worker &
fi
exec gunicorn --bind "0.0.0.0:${PORT:-8080}" --workers 1 --threads 4 --timeout "${GUNICORN_TIMEOUT:-90}" wsgi:application
