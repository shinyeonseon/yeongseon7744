#!/usr/bin/env bash
# EC2 bootstrap for the Toss investment AI (analysis-only).
# Idempotent: safe to re-run to update deps or refresh the service.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/tossai}"
ENV_DIR="/etc/tossai"
REPO_URL="${REPO_URL:-}"        # optional: git URL to clone if APP_DIR is empty
BRANCH="${BRANCH:-claude/toss-securities-investment-ai-0lus7s}"
PY="${PY:-python3.11}"
INSTALL_FUNDAMENTALS="${INSTALL_FUNDAMENTALS:-1}"  # 1 = also install pykrx/yfinance

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
# Ensure we are on the intended branch (best-effort; ignore if already there).
git checkout "$BRANCH" 2>/dev/null || true
git pull --ff-only 2>/dev/null || true

echo "==> Creating virtualenv"
"$PY" -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt
./.venv/bin/pip install -e .
if [ "$INSTALL_FUNDAMENTALS" = "1" ]; then
  echo "==> Installing fundamentals extra (pykrx/yfinance for value/quality strategies)"
  ./.venv/bin/pip install -e ".[fundamentals]" || \
    echo "    -> fundamentals extra failed to install; value/quality strategies will skip."
fi

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

echo "==> Installing systemd units (timer + oneshot + Slack server)"
sudo cp deploy/tossai.service /etc/systemd/system/tossai.service
sudo cp deploy/tossai.timer   /etc/systemd/system/tossai.timer
sudo cp deploy/tossai-daily.service /etc/systemd/system/tossai-daily.service
sudo cp deploy/tossai-daily.timer   /etc/systemd/system/tossai-daily.timer
sudo cp deploy/tossai-serve.service /etc/systemd/system/tossai-serve.service
sudo systemctl daemon-reload
sudo systemctl enable --now tossai.timer
sudo systemctl enable --now tossai-daily.timer
# Enable the Slack server only if SLACK_ENABLED=true is set in /etc/tossai/.env
if grep -qiE '^SLACK_ENABLED=true' "$ENV_DIR/.env" 2>/dev/null; then
  sudo systemctl enable --now tossai-serve
  echo "    -> tossai-serve started. Put nginx+TLS in front for Slack's public HTTPS."
else
  echo "    -> SLACK_ENABLED is not true; skipping tossai-serve."
  echo "       Set it (and SLACK_* keys) then: sudo systemctl enable --now tossai-serve"
fi

echo "==> Done. Smoke test with:"
echo "    cd $APP_DIR && ./.venv/bin/python -m tossai doctor"
