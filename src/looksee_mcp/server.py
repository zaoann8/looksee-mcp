#!/usr/bin/env python3
"""looksee-mcp — vision + search MCP server.
Routes to any OpenAI-compatible endpoint.
Zero deps beyond stdlib. PIL optional (auto-compress large images).

Usage:
  python server.py          # MCP stdio mode
  LOOKSEE_BASE_URL=... LOOKSEE_API_KEY=... python server.py
"""
import base64, json, subprocess, sys, urllib.request, urllib.error, os

BASE_URL = os.environ.get("LOOKSEE_BASE_URL", "https://api.openai.com/v1")
API_KEY = os.environ.get("LOOKSEE_API_KEY", "")
VISION_MODEL = os.environ.get("LOOKSEE_VISION_MODEL", "gpt-4o")
SEARCH_MODEL = os.environ.get("LOOKSEE_SEARCH_MODEL", "gpt-4o-mini")
UA = "Mozilla/5.0 Chrome/136.0.0.0 Safari/537.36"

IMGBYPS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"}


def _compress(raw, source_path):
    if len(raw) <= 50 * 1024:
        ext = os.path.splitext(source_path)[1].lower()
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "webp": "image/webp", "gif": "image/gif"}.get(ext, "image/png")
        return raw, mime
    try:
        from io import BytesIO
        import PIL.Image as _Image
        im = _Image.open(source_path)
        im.thumbnail((768, 768), _Image.LANCZOS)
        buf = BytesIO()
        im.convert("RGB").save(buf, format="JPEG", quality=65, optimize=True)
        return buf.getvalue(), "image/jpeg"
    except ImportError:
        ext = os.path.splitext(source_path)[1].lower()
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "webp": "image/webp", "gif": "image/gif"}.get(ext, "image/png")
        return raw, mime


def _from_clipboard():
    tmp = "/tmp/_looksee_clipboard.png"
    r = subprocess.run(["pngpaste", tmp], capture_output=True)
    if r.returncode == 127 or (r.returncode != 0 and not os.path.exists(tmp)):
        return None, "pngpaste 未安装，请执行 brew install pngpaste（仅 macOS）"
    if not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
        return None, "剪贴板无图片"
    with open(tmp, "rb") as f:
        raw = f.read()
    return _compress(raw, tmp)


def _from_file(path):
    p = os.path.expanduser(path)
    if not os.path.exists(p):
        return None, None
    with open(p, "rb") as f:
        raw = f.read()
    return _compress(raw, p)


def _scan_dir(path):
    p = os.path.expanduser(path)
    if not os.path.isdir(p):
        return []
    return sorted(os.path.join(p, f) for f in os.listdir(p)
                  if os.path.splitext(f)[1].lower() in IMGBYPS)


def _chat(model, messages, max_tokens=1536):
    if not API_KEY:
        return {"error": "LOOKSEE_API_KEY 未设置，请在 MCP 配置的 env 中设置"}
    payload = {"model": model, "stream": False,
               "max_tokens": max_tokens, "messages": messages}
    req = urllib.request.Request(
        f"{BASE_URL.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {API_KEY}",
                 "Content-Type": "application/json", "User-Agent": UA},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return {"text": json.loads(resp.read())["choices"][0]["message"]["content"]}
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode()[:300]}"}
    except Exception as e:
        return {"error": str(e)}


def vision(raw, mime, prompt):
    b64 = base64.b64encode(raw).decode()
    return _chat(VISION_MODEL, [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
    ]}])


SEARCH_SYSTEM = "你是联网搜索助手。请基于搜索结果回答，附上信息来源链接，不确定的内容注明。"

def search(query):
    return _chat(SEARCH_MODEL, [
        {"role": "system", "content": SEARCH_SYSTEM},
        {"role": "user", "content": query},
    ], max_tokens=2048)


# ── MCP stdio ─────────────────────────────────────────────────
TOOLS = [
    {"name": "vision_clipboard", "description": "分析剪贴板中的图片。当对话中出现 [Unsupported Image] 或图片无法识别时使用。读取系统剪贴板图片发送给视觉模型分析并返回文字描述。", "inputSchema": {
        "type": "object", "properties": {"prompt": {"type": "string", "description": "分析提示词"}},
        "required": ["prompt"]}},
    {"name": "vision_file", "description": "分析指定路径的图片文件", "inputSchema": {
        "type": "object", "properties": {
            "path": {"type": "string", "description": "图片文件绝对路径"},
            "prompt": {"type": "string", "description": "分析提示词"}},
        "required": ["path", "prompt"]}},
    {"name": "vision_dir", "description": "批量分析目录下的所有图片", "inputSchema": {
        "type": "object", "properties": {
            "path": {"type": "string", "description": "图片目录绝对路径"},
            "prompt": {"type": "string", "description": "分析提示词"}},
        "required": ["path", "prompt"]}},
    {"name": "web_search", "description": "通过 AI 进行联网搜索", "inputSchema": {
        "type": "object", "properties": {"query": {"type": "string", "description": "搜索关键词或问题"}},
        "required": ["query"]}},
]


def serve():
    for line in sys.stdin:
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid, method = r.get("id"), r.get("method")
        if method == "initialize":
            resp = {"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                "serverInfo": {"name": "looksee-mcp", "version": "1.0.0"}}}
        elif method == "notifications/initialized":
            continue
        elif method == "prompts/list":
            resp = {"jsonrpc": "2.0", "id": rid, "result": {"prompts": [{
                "name": "vision-guide",
                "description": "当出现 [Unsupported Image] 时使用 vision_clipboard 分析图片"
            }]}}
        elif method == "prompts/get":
            resp = {"jsonrpc": "2.0", "id": rid, "result": {
                "messages": [{"role": "user", "content": {
                    "type": "text",
                    "text": "当用户粘贴图片但模型无法识别（显示 [Unsupported Image]）时，你必须立即调用 vision_clipboard 工具分析图片。不要告诉用户你无法看到图片——直接用工具读取剪贴板。"
                }}]
            }}
        elif method == "tools/list":
            resp = {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
        elif method == "tools/call":
            name = r["params"]["name"]
            args = r["params"].get("arguments", {})
            if name == "vision_clipboard":
                raw, mime = _from_clipboard()
                if not raw:
                    result = {"error": mime or "剪贴板无图片"}
                else:
                    result = vision(raw, mime, args.get("prompt", "描述图片"))
            elif name == "vision_file":
                raw, mime = _from_file(args["path"])
                result = vision(raw, mime, args.get("prompt", "描述图片")) if raw else {"error": f"文件不存在: {args['path']}"}
            elif name == "vision_dir":
                files = _scan_dir(args["path"])
                result = {"error": f"目录无图片: {args['path']}"} if not files else {
                    "text": "\n\n---\n\n".join(
                        f"**{os.path.basename(f)}**: {vision(*_from_file(f), args.get('prompt', '描述图片')).get('text', '?')}"
                        for f in files
                    )}
            elif name == "web_search":
                result = search(args.get("query", ""))
            else:
                resp = {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"unknown: {name}"}}
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                sys.stdout.flush(); continue
            resp = {"jsonrpc": "2.0", "id": rid, "result": {"content": [
                {"type": "text", "text": result.get("text", result.get("error", "?"))}
            ]}}
        else:
            resp = {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"unknown method"}}
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    serve()
