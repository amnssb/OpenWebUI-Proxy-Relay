# 在 1Panel 上用「编排」部署 OpenWebUI-Proxy-Relay

本目录的 `docker-compose.yml` 是可直接粘进 1Panel「容器 → 编排」的模板。
**密钥与密码全部内联在 `environment` 里**，不依赖 `.env`，因此不会再出现
`required variable SESSION_SECRET is missing a value` 这类校验报错。

---

## 一、前置条件

- 1Panel 已安装，并在「容器」里启用了 Docker / Docker Compose。
- 服务器能访问 GitHub（用于拉取源码构建镜像）。拉取困难见文末「本地构建」。

> ⚠️ 模板构建 `main` 分支的**当前代码**。请确保仓库已推送最新提交，否则构建的是旧版本。

## 二、部署步骤

1. **创建编排**
   1Panel → 容器 → 编排 → 创建编排，名称如 `owui-proxy`，来源选「编辑」，
   粘贴 `docker-compose.yml` 全文。

2. **改密钥（关键）**
   直接在编排内容的 `environment:` 段把下面几项改成你自己的值：
   - `SESSION_SECRET`、`JWT_SECRET`：各填一串随机值，可在服务器终端生成：
     ```bash
     openssl rand -hex 32
     ```
   - `DEFAULT_ADMIN_PASSWORD`：管理员登录密码（仅首次启动写入数据库）。
   - 端口不想用 8080，就改 `ports` 左边的数字。

3. **启动**
   保存并启动。首次会构建镜像，耗时取决于网络与机器性能。

4. **访问后台**
   浏览器打开 `http://<服务器IP>:8080`，用 `DEFAULT_ADMIN_EMAIL` /
   `DEFAULT_ADMIN_PASSWORD` 登录，添加反代账号与 API 密钥。

## 三、（可选）网站反代 + HTTPS

用 1Panel 的 OpenResty 套域名和证书：

- **按端口反代（简单）**：网站 → 创建网站 → 反向代理 → 目标 `http://127.0.0.1:8080`。
  想更安全可只监听本机：把 compose 里 `- "8080:8000"` 改成 `- "127.0.0.1:8080:8000"`。
- **按容器名反代**：取消 compose 末尾 `networks` 注释让容器加入 `1panel-network`，
  反代目标填 `http://openwebui-proxy-relay:8000`（无需对外映射端口）。

之后在网站设置里申请/部署证书即可启用 HTTPS。

## 四、数据与备份

- SQLite 数据库位于编排目录 `./data/proxy.db`，用 1Panel「计划任务 → 备份目录」备份 `data` 即可。
- ⚠️ 反代账号密码以加密形式存库，密钥来自 `SESSION_SECRET`（或 `ENCRYPTION_KEY`）。
  **添加账号后不要再改这两个值**，否则旧密码无法解密。

## 五、更新版本

源码更新后，在编排详情页「重新构建」即可。要固定版本，把 compose 里的 `#main`
换成某个 tag 或 commit，例如 `...OpenWebUI-Proxy-Relay.git#v1.0.0`。

## 六、本地构建（GitHub 拉取困难时）

1. 把整个项目源码上传/克隆到编排目录（与 compose 同级）。
2. 将 `build` 段改为：
   ```yaml
   build:
     context: .
     dockerfile: Dockerfile
   ```
3. 其余步骤相同。
