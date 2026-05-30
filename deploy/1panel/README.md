# 在 1Panel 上用「编排」部署 OpenWebUI-Proxy-Relay

本目录提供一套可直接在 1Panel「容器 → 编排」中使用的部署模板。

| 文件 | 说明 |
| --- | --- |
| `docker-compose.yml` | 编排主文件，从 GitHub 源码自动构建镜像 |
| `.env.example` | 环境变量模板，复制为 `.env` 后填写 |

---

## 一、前置条件

- 1Panel 已安装，并在「容器」里已启用 Docker / Docker Compose。
- 服务器能访问 GitHub（用于拉取源码构建镜像）。国内服务器若拉取慢/失败，见文末「本地构建」。

> ⚠️ 模板默认构建 `main` 分支的**当前代码**。请确保仓库已推送最新提交，否则构建出来的是旧版本。

## 二、部署步骤

1. **创建编排**
   1Panel → 容器 → 编排 → 创建编排。
   - 名称：例如 `owui-proxy`
   - 来源：选「编辑」，把 `docker-compose.yml` 的内容整段粘贴进去。

2. **创建 `.env`**
   编排目录默认在 `/opt/1panel/docker/compose/owui-proxy/`。
   在该目录新建 `.env`（可用 1Panel「文件」管理器），参考 `.env.example` 填写。
   生成密钥：
   ```bash
   openssl rand -hex 32   # 分别为 SESSION_SECRET、JWT_SECRET 各生成一个
   ```
   至少填：`SESSION_SECRET`、`JWT_SECRET`、`DEFAULT_ADMIN_PASSWORD`。

3. **启动**
   保存并启动编排。首次会构建镜像，耗时取决于网络与机器性能。

4. **访问后台**
   浏览器打开 `http://<服务器IP>:8080`（端口即 `.env` 里的 `APP_PORT`），
   用 `DEFAULT_ADMIN_EMAIL` / `DEFAULT_ADMIN_PASSWORD` 登录，添加反代账号与 API 密钥。

## 三、（可选）网站反代 + HTTPS

用 1Panel 的 OpenResty 给它套域名和证书：

- **按端口反代（简单）**：网站 → 创建网站 → 反向代理 → 目标填 `http://127.0.0.1:8080`。
  这种方式可把 `.env` 的端口映射改成只监听本机更安全：把 compose 里
  `- "${APP_PORT:-8080}:8000"` 改为 `- "127.0.0.1:${APP_PORT:-8080}:8000"`。
- **按容器名反代**：取消 `docker-compose.yml` 末尾 `networks` 的注释，让容器加入
  `1panel-network`，反代目标填 `http://openwebui-proxy-relay:8000`（无需对外映射端口）。

之后在网站设置里申请/部署证书即可启用 HTTPS。

## 四、数据与备份

- SQLite 数据库位于编排目录 `./data/proxy.db`。
- 用 1Panel「计划任务 → 备份目录」备份整个 `data` 目录即可。
- ⚠️ 反代账号的密码以加密形式存库，密钥来自 `SESSION_SECRET`（或 `ENCRYPTION_KEY`）。
  **添加账号后不要再改这两个值**，否则旧密码无法解密。

## 五、更新版本

源码更新后，在编排里「重新构建 / 拉取并重建」即可（1Panel 编排详情页有重建按钮）。
要固定版本，把 compose 里的 `#main` 换成某个 tag 或 commit，例如
`...OpenWebUI-Proxy-Relay.git#v1.0.0`。

## 六、本地构建（GitHub 拉取困难时）

如果服务器访问 GitHub 不稳定，改用本地源码构建：

1. 把整个项目源码上传/克隆到编排目录（与 `.env` 同级）。
2. 将 `docker-compose.yml` 里的 `build` 段改为：
   ```yaml
   build:
     context: .
     dockerfile: Dockerfile
   ```
3. 其余步骤相同。

> 也可配置 Docker 的代理/镜像加速来直接用 Git 构建上下文。
