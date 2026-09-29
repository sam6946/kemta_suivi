#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="${1:-auto}"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example (local development defaults)."
fi

start_docker() {
  echo "Starting the complete Docker Compose stack…"
  docker compose up -d --build

  local web_id=""
  web_id="$(docker compose ps -q web)"
  if [[ -z "$web_id" ]]; then
    echo "The web container did not start." >&2
    docker compose ps >&2
    exit 1
  fi

  echo -n "Waiting for the API health check"
  local state="starting"
  for _ in $(seq 1 90); do
    state="$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$web_id" 2>/dev/null || true)"
    [[ "$state" == "healthy" ]] && break
    [[ "$state" == "exited" || "$state" == "dead" ]] && break
    echo -n "."
    sleep 2
  done
  echo
  if [[ "$state" != "healthy" ]]; then
    echo "API did not become healthy (state: ${state:-unknown}). Recent logs:" >&2
    docker compose logs --tail=80 web >&2
    exit 1
  fi

  docker compose exec -T web python manage.py seed_dev
  cat <<'EOF'

KEMTA SUIVI is running:
  Frontend: http://localhost:5173
  API:      http://localhost:8000/api/
  Health:   http://localhost:8000/api/health/
Stop the stack with: docker compose down
EOF
}

case "$MODE" in
  --docker)
    command -v docker >/dev/null || { echo "Docker is required for --docker." >&2; exit 1; }
    docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 is required." >&2; exit 1; }
    docker info >/dev/null 2>&1 || { echo "Docker daemon is not available." >&2; exit 1; }
    start_docker
    exit 0
    ;;
  auto)
    if command -v docker >/dev/null && docker compose version >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
      start_docker
      exit 0
    fi
    ;;
  --local)
    ;;
  *)
    echo "Usage: ./dev.sh [--local|--docker]" >&2
    exit 2
    ;;
esac

command -v python3 >/dev/null || { echo "Python 3 is required." >&2; exit 1; }
command -v node >/dev/null || { echo "Node.js is required for the frontend." >&2; exit 1; }
command -v npm >/dev/null || { echo "npm is required for the frontend." >&2; exit 1; }

VENV="$ROOT_DIR/backend/.venv"
if [[ ! -x "$VENV/bin/python" ]]; then
  python3 -m venv "$VENV"
fi
PYTHON="$VENV/bin/python"
if ! "$PYTHON" -c 'import django, rest_framework, celery' >/dev/null 2>&1; then
  "$PYTHON" -m pip install -r "$ROOT_DIR/backend/requirements-dev.txt"
fi

if [[ ! -x "$ROOT_DIR/frontend/node_modules/.bin/vite" ]]; then
  (cd "$ROOT_DIR/frontend" && npm ci)
fi

export DJANGO_SETTINGS_MODULE=config.settings
export DJANGO_ENV=local
export USE_SQLITE=true
export SQLITE_PATH="${SQLITE_PATH:-$ROOT_DIR/var/dev.sqlite3}"
export USE_LOCAL_CACHE=true
export CELERY_TASK_ALWAYS_EAGER=true
export ANTIVIRUS_REQUIRED=false
export MEDIA_ROOT="$ROOT_DIR/var/media"
export STATIC_ROOT="$ROOT_DIR/var/static"
mkdir -p "$ROOT_DIR/var/media" "$ROOT_DIR/var/static"

(
  cd "$ROOT_DIR/backend"
  "$PYTHON" manage.py migrate --noinput
  "$PYTHON" manage.py seed_dev
)

cleanup_done=0
cleanup() {
  [[ "$cleanup_done" == "1" ]] && return
  cleanup_done=1
  for pid in "${server_pids[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  for pid in "${server_pids[@]:-}"; do
    wait "$pid" 2>/dev/null || true
  done
}
server_pids=()
trap cleanup EXIT INT TERM

(
  cd "$ROOT_DIR/backend"
  exec "$PYTHON" manage.py runserver 0.0.0.0:8000 --noreload
) &
server_pids+=("$!")

(
  cd "$ROOT_DIR/frontend"
  export VITE_API_TARGET=http://127.0.0.1:8000
  exec ./node_modules/.bin/vite --host 0.0.0.0 --port 5173
) &
server_pids+=("$!")

cat <<'EOF'

KEMTA SUIVI is running in local mode:
  Frontend: http://localhost:5173
  API:      http://localhost:8000/api/
  Health:   http://localhost:8000/api/health/
Press Ctrl+C to stop both servers.
EOF

wait -n "${server_pids[@]}"
