#!/bin/sh
set -e

# Ensure sounds, data, and logs directories exist and are writable
mkdir -p /app/sounds /app/data /app/logs
chown -R app:app /app/sounds /app/data /app/logs

cmd="$@"
exec su app -c "$cmd"
