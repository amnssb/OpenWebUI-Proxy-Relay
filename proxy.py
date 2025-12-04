from flask import Flask, request, Response
import requests
import sys
import time
import json
import urllib3 
import os
import argparse 

# -----------------------------------
# 强制设置标准输出流使用 UTF-8 编码，并抑制 SSL 警告
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass
# 抑制 urllib3 的 InsecureRequestWarning 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
# -----------------------------------

app = Flask(__name__)

# 定义全局变量，将在 __main__ 中初始化
TARGET_API_URL_BASE = ""
LISTEN_PORT = 0

def get_client_token(req):
    """从客户端请求中提取用户填写的 Token (作为 Bearer Token)"""
    auth_header = req.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header.split(' ', 1)[1].strip()
        print("✅ 提取 Token 来源: Authorization Header")
        return token
    
    api_key = req.headers.get('X-API-KEY')
    if api_key:
        print("✅ 提取 Token 来源: X-API-KEY Header")
        return api_key

    print("❌ 警告：客户端未发送有效的 Token Header。")
    return "" 


@app.route('/v1/chat/completions', methods=['POST'])
@app.route('/api/chat/completions', methods=['POST'])
def proxy_request():
    # 使用 global 关键字引用在 __main__ 中初始化的全局配置
    global TARGET_API_URL_BASE 
    
    print("-" * 60)
    print(f"收到请求: {request.path} | 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # --- 提取客户端 Token ---
    BEARER_TOKEN = get_client_token(request)
    if not BEARER_TOKEN:
        return Response(json.dumps({"error": {"message": "Client Token Missing or Invalid in Headers."}}), 
                        mimetype='application/json', status=401)
    
    # 动态构建转发 Headers
    FORGED_HEADERS = {
        "Authorization": f"Bearer {BEARER_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        # 伪装 Headers
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Origin": TARGET_API_URL_BASE,
        "Referer": f"{TARGET_API_URL_BASE}/",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Sec-Fetch-Mode": "cors"
    }

    target_path = "/api/chat/completions"
    target_url = TARGET_API_URL_BASE + target_path
    
    try:
        data = request.get_json(silent=True)
    except Exception:
        data = None
        
    client_model = data.get('model') if data else 'N/A'
    print(f"转发请求体中的模型: {client_model}")
        
    try:
        # 2. 转发请求，使用动态 Token
        target_response = requests.post(
            target_url,
            headers=FORGED_HEADERS,
            json=data,
            verify=False,
            stream=True
        )
        
        target_response.raise_for_status()
        print(f"--- 目标 API 响应成功 (Status: {target_response.status_code}) ---")

        # 3. 处理流式响应：强制进行严格的 SSE 格式化
        def generate_sse():
            for line_bytes in target_response.iter_lines():
                if line_bytes:
                    try:
                        line = line_bytes.decode('utf-8', errors='ignore').strip()
                    except:
                        continue
                        
                    if line.startswith("data:"):
                        # print(f"  > DEBUG_LINE: {line[:50]}...") # 打印太多，注释掉
                        yield (line + "\r\n\r\n").encode('utf-8')
                        
                    elif line == "[DONE]":
                        print("--- 收到 [DONE] 信号 ---")
                        yield "data: [DONE]\r\n\r\n".encode('utf-8')
                        break
        
        return Response(generate_sse(), 
                        mimetype='text/event-stream',
                        status=target_response.status_code)

    except requests.exceptions.RequestException as e:
        print(f"转发请求失败: {e}")
        status_code = getattr(e.response, 'status_code', 500)
        error_text = getattr(e.response, 'text', str(e))
        print(f"目标服务器响应内容: {error_text[:200]}...")
        
        error_payload = json.dumps({"error": {"message": f"Proxy Error: Status {status_code}. Details: {error_text}", "type": "proxy_network_error"}})
        
        return Response(f"data: {error_payload}\r\n\r\n".encode('utf-8'), 
                        mimetype='text/event-stream', 
                        status=status_code)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Open WebUI 通用 API 转发代理")
    
    # TARGET_API_URL_BASE 配置 - 必须提供
    parser.add_argument(
        '--target-url',
        type=str,
        default=os.environ.get('TARGET_URL'), 
        help="[必需] 目标 Open WebUI API 的基础 URL。例如：https://chat.example.com"
    )
    
    # LISTEN_PORT 配置 - 必须提供
    parser.add_argument(
        '--port',
        type=int,
        default=os.environ.get('LISTEN_PORT'), 
        help="[必需] 代理监听的本地端口号。例如: 8080"
    )

    args = parser.parse_args()

    # 显式检查参数是否被提供
    if not args.target_url:
        print("❌ 错误：启动失败。请通过 --target-url 参数或 TARGET_URL 环境变量指定目标 API 地址。")
        sys.exit(1)
        
    if args.port is None:
        print("❌ 错误：启动失败。请通过 --port 参数或 LISTEN_PORT 环境变量指定监听端口。")
        sys.exit(1)
        
    # 将解析的参数赋值给全局变量
    TARGET_API_URL_BASE = args.target_url
    LISTEN_PORT = args.port
    
    print(f"🚀 Python 代理启动中...")
    print(f"目标 API 地址: {TARGET_API_URL_BASE}")
    print(f"监听地址: http://0.0.0.0:{LISTEN_PORT} (已设置为监听所有接口)")
    print("----------------------------------------")
    
    # 修复了在 Windows Server 上只能监听 127.0.0.1 的问题
    app.run(host='0.0.0.0', port=LISTEN_PORT, threaded=True)