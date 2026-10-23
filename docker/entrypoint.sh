#!/bin/sh
# The engine version recorded at build time (see Dockerfile), for scenario cache keys.
set -e
GLACIES_ENGINE_COMMIT="$(cat /app/ENGINE_COMMIT)"
GLACIES_ENGINE_DIRTY="$(cat /app/ENGINE_DIRTY)"
export GLACIES_ENGINE_COMMIT GLACIES_ENGINE_DIRTY
exec "$@"
