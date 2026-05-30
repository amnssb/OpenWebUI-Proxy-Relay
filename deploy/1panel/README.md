# 在 1Panel 上部署 OpenWebUI-Proxy-Relay

## 为什么会报 `open Dockerfile: no such file or directory`

1Panel 把编排放在它自己的目录（如 `/opt/1panel/docker/compose/ow2api/`）里，
在那里执行构建。如果编排里写了 `build:`（无论本地 `.` 还是 `git#main`），而该目录
**没有源码/Dockerfile**，就会报这个错。很多环境里 `build.context: <git-url>` 不被当作
远程仓库克隆，而是当成本地路径，于是找不到 Dockerfile。

**解决思路：面板里不构建，改为先在终端把镜像构建好，编排只引用镜像。**
本目录的 `docker-compose.yml` 已是这种「镜像引用版」。

> ⚠️ 前提：`git clone` 拉到的是 GitHub `main` 的当前代码。请先把本地修复
> **commit & push** 到 `main`，否则构建出来的镜像还是旧版本。

---

## 方式 A（推荐）：终端构建镜像 + 面板引用

1. **构建镜像（服务器终端，仅需一次；代码更新后重做即可）**
   ```bash
   git clone https://github.com/amnssb/OpenWebUI-Proxy-Relay.git
   cd OpenWebUI-Proxy-Relay
   docker build -t openwebui-proxy-relay:latest .
   ```

2. **创建编排**
   1Panel → 容器 → 编排 → 创建编排 → 来源选「编辑」，粘贴本目录的
   `docker-compose.yml`（它用 `image: openwebui-proxy-relay:latest`，**没有 build**）。

3. **改密钥**
   把 `environment:` 里的 `SESSION_SECRET`、`JWT_SECRET`、`DEFAULT_ADMIN_PASSWORD`
   改成你自己的值（`openssl rand -hex 32` 生成随机串）。

4. **启动 → 访问**
   `http://<服务器IP>:8080`，用管理员账号登录。

更新版本：重新 `git pull` 后 `docker build -t openwebui-proxy-relay:latest .`，
再在编排详情页重建容器即可。

## 方式 B：源码放进编排目录，用根目录 compose 构建

适合想让 1Panel 直接构建的人——关键是让**源码和 Dockerfile 就在编排目录里**。

1. 终端把仓库克隆成编排目录：
   ```bash
   cd /opt/1panel/docker/compose
   git clone https://github.com/amnssb/OpenWebUI-Proxy-Relay.git ow2api
   cd ow2api
   ```
2. 编辑根目录 `docker-compose.yml`，把 `SESSION_SECRET` 等改成你的值
   （它用 `build: .`，此时上下文就是当前目录，能找到 Dockerfile）。
3. 启动：
   ```bash
   docker compose up -d --build
   ```
   之后在 1Panel → 容器 → 编排 里即可看到并管理 `ow2api`。

---

## 网站反代 + HTTPS（可选）

用 1Panel OpenResty：网站 → 创建网站 → 反向代理 → 目标 `http://127.0.0.1:8080`，
再申请证书启用 HTTPS。想更安全可把 compose 的 `- "8080:8000"` 改为
`- "127.0.0.1:8080:8000"`，只允许本机访问、仅由反代对外。

## 数据与备份

- SQLite 数据库在编排目录 `./data/proxy.db`，用 1Panel「计划任务 → 备份目录」备份 `data`。
- ⚠️ 反代账号密码加密存储，密钥来自 `SESSION_SECRET`（或 `ENCRYPTION_KEY`）。
  **添加账号后不要再改这两个值**，否则旧密码无法解密。
