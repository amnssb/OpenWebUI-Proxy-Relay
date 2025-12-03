# 🚀 OpenWebUI-Proxy-Relay

**核心功能：** 这是一个用于逆向 Open WebUI Web 界面流量的通用 API 代理。通过该代理，您可以绕过目标服务器原生的 API 服务限制，获取一个可供第三方客户端（如 Cherry Studio AI、NextChat、Vercel Chat 等）使用的标准 OpenAI 格式 API 服务。

## ✨ 特性

- 动态 Token 注入：从第三方客户端的 API Key/Authorization Header 中自动提取您手动抓取的 Session Token (JWT)，无需重启代理。
- 浏览器 Header 伪装：模拟浏览器请求头，帮助通过目标 API 的安全检查。
- 路径修正：自动将标准的 `/v1/chat/completions` 路径映射到目标 Open WebUI 所需的 `/api/chat/completions`。
- 严格 SSE 格式：确保流式响应符合客户端所需的严格 Server-Sent Events (SSE) 格式。
- 灵活配置：通过命令行参数或环境变量配置目标 URL 和监听端口。

## ⚠️ 模型兼容性说明

目标服务器的 API 接口对模型 ID 具有严格的白名单校验，且部分模型（例如带“思考/Thinking”能力的模型）在非原生客户端调用时，可能因为请求参数缺失或模型 ID 未被服务器接受而导致响应为空或失败。请优先使用您实测可用的模型 ID。如果某个模型失败，这通常是目标服务器的限制，而非代理问题。

## ⚙️ 安装与运行

### 1. 前置条件

- Python 3.6+
- 您需要一个目标 Open WebUI/目标站点的有效 Session Token (JWT)。

### 2. 安装依赖

确保项目根目录存在 `requirements.txt`，然后运行：

```bash
pip install -r requirements.txt
```

### 3. 运行（必须配置目标地址与端口）

您必须通过命令行参数或环境变量来指定目标 API 地址和监听端口。

#### 配置项说明

| 配置项         | 命令行参数      | 环境变量      | 示例值                  |
| -------------- | --------------- | ------------- | ----------------------- |
| 目标 API URL   | --target-url    | TARGET_URL    | https://chat.breathai.top |
| 监听端口       | --port          | LISTEN_PORT   | 8080                    |

#### Bash/Linux/macOS 示例

```bash
# 替换 'YOUR_TARGET_URL' 和 'YOUR_PORT' 为实际值
export TARGET_URL="YOUR_TARGET_URL"
export LISTEN_PORT="YOUR_PORT"
python proxy.py
```

#### PowerShell/Windows 示例

```powershell
$env:TARGET_URL = "YOUR_TARGET_URL"
$env:LISTEN_PORT = "YOUR_PORT"
python proxy.py
```

#### 直接命令行参数运行

```bash
python proxy.py --target-url https://chat.breathai.top --port 8080
```

## 🔑 客户端配置

代理运行后，在第三方客户端中按以下方式配置：

- 基础 URL (Base URL)：填写代理监听的地址，例如 `http://127.0.0.1:8080`。
- API Key / 密钥框：粘贴您手动抓取的最新 BEARER_TOKEN（Session Token）。

## 🤝 贡献

欢迎任何形式的贡献！如果您发现 Bug 或有改进建议，请提交 Pull Request 或 Issue。