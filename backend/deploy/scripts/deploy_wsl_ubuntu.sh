#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/mnt/d/HT_project/HT_project/backend"
SERVICE_NAME="ai-contract-backend.service"
ENV_TARGET="/etc/ai-contract/backend.env"
SYSTEMD_TARGET="/etc/systemd/system/${SERVICE_NAME}"
NGINX_TARGET="/etc/nginx/sites-available/api.xxx.com.conf"
NGINX_LINK="/etc/nginx/sites-enabled/api.xxx.com.conf"

echo "[1/7] Installing runtime packages"
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip nginx certbot python3-certbot-nginx

echo "[2/7] Creating app virtual environment"
cd "$APP_DIR"
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "[3/7] Installing environment file"
sudo mkdir -p /etc/ai-contract
if [[ ! -f "$ENV_TARGET" ]]; then
  sudo cp "$APP_DIR/deploy/env/backend.env.example" "$ENV_TARGET"
  echo "Please edit $ENV_TARGET before starting production service."
fi

echo "[4/7] Installing systemd service"
sudo cp "$APP_DIR/deploy/systemd/${SERVICE_NAME}" "$SYSTEMD_TARGET"
sudo systemctl daemon-reload
sudo systemctl enable ai-contract-backend

echo "[5/7] Installing nginx config"
sudo cp "$APP_DIR/deploy/nginx/api.xxx.com.conf" "$NGINX_TARGET"
sudo ln -sf "$NGINX_TARGET" "$NGINX_LINK"
sudo nginx -t
sudo systemctl enable nginx
sudo systemctl restart nginx

echo "[6/7] Starting backend service"
sudo systemctl restart ai-contract-backend
sudo systemctl status ai-contract-backend --no-pager

echo "[7/7] Next steps"
echo "1. Replace api.xxx.com in nginx config with your real API domain."
echo "2. Edit $ENV_TARGET with the real DeepSeek key."
echo "3. Run: sudo certbot --nginx -d api.xxx.com"
echo "4. Verify: curl https://api.xxx.com/health"
