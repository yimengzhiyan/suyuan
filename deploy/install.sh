#!/usr/bin/env bash
# 一键部署（在项目目录执行，需要 sudo）：bash deploy/install.sh 你的域名
# 做的事：1) 以 systemd 运行 Streamlit（公开模式，监听本机 8501）
#        2) 安装 Caddy 做 HTTPS 反代，自动申请证书
#        3) 防火墙放行 80/443（如果启用了 firewalld）
set -euo pipefail
DOMAIN="${1:?用法: bash deploy/install.sh 你的域名}"
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_USER="$(id -un)"

echo "==> 1/4 检查虚拟环境"
[ -x "$APP_DIR/.venv/bin/streamlit" ] || { python3 -m venv "$APP_DIR/.venv"; "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"; }
mkdir -p "$APP_DIR/.cache"

echo "==> 2/4 写入 systemd 服务 suyuan.service"
sudo tee /etc/systemd/system/suyuan.service >/dev/null <<UNIT
[Unit]
Description=Suyuan rumor verification web app
After=network.target

[Service]
User=$RUN_USER
WorkingDirectory=$APP_DIR
Environment=SUYUAN_PUBLIC=1
Environment=SUYUAN_CACHE_DIR=$APP_DIR/.cache
ExecStart=$APP_DIR/.venv/bin/streamlit run app.py --server.headless=true --server.address=127.0.0.1 --server.port=8501 --browser.gatherUsageStats=false
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now suyuan
sleep 5
curl -sf http://127.0.0.1:8501/_stcore/health >/dev/null && echo "    应用已启动" || { echo "应用启动失败，看 journalctl -u suyuan"; exit 1; }

echo "==> 3/4 安装 Caddy"
if ! command -v caddy >/dev/null; then
  ARCH=$(uname -m); case "$ARCH" in x86_64) A=amd64;; aarch64) A=arm64;; *) echo "未知架构 $ARCH"; exit 1;; esac
  VER=$(curl -fsSL https://api.github.com/repos/caddyserver/caddy/releases/latest | grep -oE "\"tag_name\": *\"v[0-9.]+\"" | grep -oE "[0-9.]+")
  curl -fsSL "https://github.com/caddyserver/caddy/releases/download/v${VER}/caddy_${VER}_linux_${A}.tar.gz" | tar -xzC /tmp caddy
  sudo install -m 755 /tmp/caddy /usr/local/bin/caddy
  sudo setcap 'cap_net_bind_service=+ep' /usr/local/bin/caddy || true
fi
sudo mkdir -p /etc/caddy /var/lib/caddy
id caddy >/dev/null 2>&1 || sudo useradd --system --home /var/lib/caddy --shell /usr/sbin/nologin caddy
sudo chown -R caddy:caddy /var/lib/caddy
sudo tee /etc/caddy/Caddyfile >/dev/null <<CADDY
$DOMAIN {
    reverse_proxy 127.0.0.1:8501
}
CADDY
sudo tee /etc/systemd/system/caddy.service >/dev/null <<UNIT
[Unit]
Description=Caddy
After=network.target

[Service]
User=caddy
Group=caddy
Environment=HOME=/var/lib/caddy XDG_DATA_HOME=/var/lib/caddy XDG_CONFIG_HOME=/var/lib/caddy
ExecStart=/usr/local/bin/caddy run --config /etc/caddy/Caddyfile
ExecReload=/usr/local/bin/caddy reload --config /etc/caddy/Caddyfile
Restart=always
AmbientCapabilities=CAP_NET_BIND_SERVICE
LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now caddy

echo "==> 4/4 防火墙"
if systemctl is-active --quiet firewalld; then
  sudo firewall-cmd --permanent --add-service=http --add-service=https >/dev/null && sudo firewall-cmd --reload >/dev/null && echo "    firewalld 已放行 80/443"
else
  echo "    未启用 firewalld，跳过（云控制台的安全组仍需放行 80/443）"
fi

echo
echo "完成。确认域名 $DOMAIN 的 A 记录已指向本机公网 IP 后，访问 https://$DOMAIN"
echo "查看日志：journalctl -u suyuan -f    journalctl -u caddy -f"
