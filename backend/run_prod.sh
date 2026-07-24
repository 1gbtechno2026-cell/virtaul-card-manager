#!/bin/bash
# Production start script for the VPS. Runs gunicorn serving app.py, which
# also auto-launches the headless browser and serves the built frontend
# (frontend/dist/) as static files -- one process, one command.
#
# --workers 1 is intentional, not a placeholder: this app keeps login
# sessions, card-creation progress, and the browser handle in in-memory
# Python state. Multiple worker PROCESSES would each have their own copy
# of that state, so requests could randomly land on a worker that doesn't
# know you're logged in. If you need more throughput later, that state
# has to move to Redis/the database first -- don't just bump this number.
#
# --timeout 300 because the ICICI login/OTP endpoints call into Playwright
# synchronously and can legitimately take a while; gunicorn's default 30s
# would kill those requests mid-flight.
#
# Binds to 127.0.0.1 only -- put nginx in front of this for the public
# port and HTTPS. Never expose 5000 (or 9222, the Chrome debug port)
# directly to the internet.

set -e
cd "$(dirname "$0")"

exec gunicorn \
  --workers 1 \
  --timeout 300 \
  --bind 127.0.0.1:5000 \
  app:app
