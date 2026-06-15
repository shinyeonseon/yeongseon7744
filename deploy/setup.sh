#!/usr/bin/env bash
# EC2 bootstrap for the Toss investment AI (analysis-only).
# Idempotent: safe to re-run to update deps or refresh the service.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/tossai}"
ENV_DIR="/etc/tossai"
REPO_URL="${REPO_URL:-}"        # optional: git URL to clone if APP_DIR is empty
PY="${PY:-python3.11}"

echo "==> Installing system packages"
if command -v dnf >/dev/null 2>&1; then
  sudo dnf install -y python3.11 git || true
elif command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update -y && sudo apt-get install -y python3.11 python3.11-venv git
fi

echo "==> Preparing $APP_DIR"
sudo mkdir -p "$APP_DIR"
sudo chown "$USER" "$APP_DIR"
if [ -n "$REPO_URL" ] && [ ! -d "$APP_DIR/.git" ]; then
  git clone "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

echo "==> Creating virtualenv"
"$PY" -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt
./.venv/bin/pip install -e .

echo "==> Setting up secrets at $ENV_DIR/.env (chmod 600)"
sudo mkdir -p "$ENV_DIR"
if [ ! -f "$ENV_DIR/.env" ]; then
  sudo cp .env.example "$ENV_DIR/.env"
  sudo chmod 600 "$ENV_DIR/.env"
  echo "    -> Edit $ENV_DIR/.env and fill in TOSS_* and ANTHROPIC_API_KEY."
fi

echo "==> Creating runtime dirs"
mkdir -p "$APP_DIR/logs" "$APP_DIR/reports"
[ -f "$APP_DIR/config/universe.yaml" ] || cp config/universe.example.yaml config/universe.yaml

echo "==> Installing systemd units (timer + oneshot)"
sudo cp deploy/tossai.service /etc/systemd/system/tossai.service
sudo cp deploy/tossai.timer   /etc/systemd/system/tossai.timer
sudo systemctl daemon-reload
sudo systemctl enable --now tossai.timer

echo "==> Done. Smoke test with:"
echo "    cd $APP_DIR && ./.venv/bin/python -m tossai doctor"
