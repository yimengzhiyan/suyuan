# 部署

公开部署时请设置环境变量 `SUYUAN_PUBLIC=1`：页面不再读取服务器上的任何 key，访问者在侧栏填自己的元宝搜索 Key 和大模型 Key，只保存在各自的浏览器会话里。

## 方式一：Docker + Caddy（推荐，自动 HTTPS）

```bash
git clone https://github.com/yimengzhiyan/suyuan.git /opt/suyuan && cd /opt/suyuan/deploy
docker compose up -d --build          # 应用监听 127.0.0.1:8601
# 安装 caddy 后，把 Caddyfile 里的域名改成你的，复制到 /etc/caddy/Caddyfile，然后
systemctl reload caddy
```

域名解析：在域名服务商处给你的域名加一条 A 记录指向服务器公网 IP。Caddy 会自动申请并续期证书。

## 方式二：nginx + certbot

应用照样用 `docker compose up -d`，或者按 `suyuan.service` 以 systemd 运行；把 `nginx.conf` 改好域名放到 `/etc/nginx/conf.d/suyuan.conf`，然后 `certbot --nginx -d 你的域名`。

## 注意

- 核查进度走 SSE 长连接，nginx 需要 `proxy_buffering off`，Caddy 默认即可。
- 服务器在中国大陆的话，域名需要完成 ICP 备案才能通过 80/443 端口访问；海外服务器不需要。
- 搜索缓存在容器内 `/app/.cache`，已挂成卷，重启不丢。
