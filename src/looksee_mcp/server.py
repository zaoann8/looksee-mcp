#!/usr/bin/env python3
"""looksee-mcp — vision + search + fetch MCP server.
Routes to any OpenAI-compatible endpoint.
Zero deps beyond stdlib. PIL optional (auto-compress large images).

Usage:
  python server.py          # MCP stdio mode
  LOOKSEE_BASE_URL=... LOOKSEE_API_KEY=... python server.py
"""
import base64, json, subprocess, sys, urllib.request, urllib.error, os
import html.parser, uuid, time, ssl
from collections import deque

BASE_URL = os.environ.get("LOOKSEE_BASE_URL", "https://api.openai.com/v1")
API_KEY = os.environ.get("LOOKSEE_API_KEY", "")

# ── Shared HTTPS connection pool (keep-alive) ──────────────────
_HTTPS_HANDLER = urllib.request.HTTPSHandler(context=ssl.create_default_context())
_HTTP_OPENER = urllib.request.build_opener(_HTTPS_HANDLER)
_HTTP_OPENER.addheaders = [("Connection", "keep-alive")]
VISION_MODEL = os.environ.get("LOOKSEE_VISION_MODEL", "gpt-4o")
SEARCH_MODEL = os.environ.get("LOOKSEE_SEARCH_MODEL", "gpt-4o-mini")
FETCH_MODEL = os.environ.get("LOOKSEE_FETCH_MODEL", "")  # 可选，用于阅读网页的模型
UA = "Mozilla/5.0 Chrome/136.0.0.0 Safari/537.36"

IMGBYPS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"}

# ── Source cache (session_id → list of sources, LRU) ─────────────
_source_cache = {}
_cache_order = deque()
_CACHE_MAX = 100


def _cache_set(session_id, sources):
    if session_id in _source_cache:
        try:
            _cache_order.remove(session_id)
        except ValueError:
            pass
    _source_cache[session_id] = sources
    _cache_order.append(session_id)
    while len(_cache_order) > _CACHE_MAX:
        old = _cache_order.popleft()
        _source_cache.pop(old, None)


def _cache_get(session_id):
    return _source_cache.get(session_id)


# ── HTML stripper (stdlib, no deps) ──────────────────────────────
class _HTMLStripper(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self._skip = 0
        self._skip_tags = {"script", "style", "noscript", "iframe", "svg", "head"}

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self._skip_tags:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag.lower() in self._skip_tags and self._skip > 0:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            text = data.strip()
            if text:
                self.parts.append(text)


def _strip_html(html_text):
    s = _HTMLStripper()
    try:
        s.feed(html_text)
    except Exception:
        pass
    return "\n".join(s.parts)


# ── Image helpers ────────────────────────────────────────────────
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


# ── API call ─────────────────────────────────────────────────────
def _chat(model, messages, max_tokens=1536, retries=3):
    if not API_KEY:
        return {"error": "LOOKSEE_API_KEY 未设置，请在 MCP 配置的 env 中设置"}
    payload = {"model": model, "stream": False,
               "max_tokens": max_tokens, "messages": messages}
    last_error = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                f"{BASE_URL.rstrip('/')}/chat/completions",
                data=json.dumps(payload).encode(),
                headers={"Authorization": f"Bearer {API_KEY}",
                         "Content-Type": "application/json", "User-Agent": UA},
                method="POST")
            with _HTTP_OPENER.open(req, timeout=120) as resp:
                return {"text": json.loads(resp.read())["choices"][0]["message"]["content"]}
        except urllib.error.HTTPError as e:
            retryable = e.code in (429, 502, 503, 504)
            last_error = f"HTTP {e.code}"
            if not retryable or attempt == retries:
                try:
                    body = e.read().decode()[:200]
                    return {"error": f"HTTP {e.code}: {body}", "retryable": False}
                except Exception:
                    return {"error": f"HTTP {e.code}", "retryable": False}
            time.sleep(2 ** attempt)
        except Exception as e:
            last_error = str(e)
            retryable = "timeout" in last_error.lower() or "connection" in last_error.lower()
            if attempt == retries:
                return {"error": str(e), "retryable": retryable}
            time.sleep(2 ** attempt)
    return {"error": last_error or "未知错误", "retryable": False}


def vision(raw, mime, prompt):
    b64 = base64.b64encode(raw).decode()
    return _chat(VISION_MODEL, [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
    ]}])


# ── Web Search ───────────────────────────────────────────────────
SEARCH_SYSTEM = "你是联网搜索助手。请基于搜索结果回答，附上信息来源链接，不确定的内容注明。"


def web_search(query, *, recency_days=None, include_domains=None, exclude_domains=None, response_format=None):
    """返回 {text, session_id}，session_id 用于 get_sources 翻页。

    可选参数（对齐 GrokSearch-rs）：
    - recency_days: 限制来源为最近 N 天发布的内容
    - include_domains: 限定域名，如 ["github.com", "stackoverflow.com"]
    - exclude_domains: 排除域名，如 ["csdn.net"]
    - response_format: "concise" 简短+来源, "detailed" 详尽分析
    """
    system = SEARCH_SYSTEM
    user = query

    directives = []
    if recency_days and recency_days > 0:
        directives.append(f"\n\nRestrict evidence to sources published within the last {int(recency_days)} day(s).")
    if include_domains:
        directives.append(f"\n\nPrefer sources from: {', '.join(str(d) for d in include_domains)}")
    if exclude_domains:
        directives.append(f"\n\nDo not cite sources from: {', '.join(str(d) for d in exclude_domains)}")

    if directives:
        user = f"{query}{''.join(directives)}"

    if response_format == "concise":
        system += " 请给出精炼回答，保留关键信息和代码示例，附上信息来源链接。"
    elif response_format == "detailed":
        system += " 请给出详尽全面的分析，尽可能覆盖多方面信息。"

    result = _chat(SEARCH_MODEL, [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ])
    session_id = uuid.uuid4().hex[:12]
    _cache_set(session_id, [{"title": "搜索: " + query[:80], "url": "",
                              "content": result.get("text", result.get("error", "?"))}])
    return {"text": result.get("text", result.get("error", "?")), "session_id": session_id}


# ── Web Fetch ────────────────────────────────────────────────────
_FETCH_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "Upgrade-Insecure-Requests": "1",
}


def _fetch_via_urllib(url):
    """urllib + 完整浏览器头，返回 (text, content_type) 或异常"""
    req = urllib.request.Request(url, headers=_FETCH_HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        ct = resp.headers.get("Content-Type", "")
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            import gzip
            raw = gzip.decompress(raw)
        charset = "utf-8"
        if "charset=" in ct:
            charset = ct.split("charset=")[-1].split(";")[0].strip()
        try:
            text = raw.decode(charset)
        except (UnicodeDecodeError, LookupError):
            text = raw.decode("utf-8", errors="replace")
        return text, ct


def _fetch_via_curl_cffi(url):
    """curl_cffi 模拟标准浏览器 TLS（可选依赖），返回 (text, content_type) 或异常"""
    from curl_cffi import requests as curl_requests
    resp = curl_requests.get(url, impersonate="chrome", timeout=30,
                             headers=_FETCH_HEADERS)
    resp.raise_for_status()
    return resp.text, resp.headers.get("Content-Type", "")


def _looks_like_block_page(text):
    """检测响应是否为拦截/验证页面（验证码、访问限制等）"""
    lower = text[:3000].lower()
    # 验证页常见特征
    block_signals = [
        "验证", "captcha", "challenge", "请完成以下验证",
        "访问拒绝", "请求被拦截",
        "blocked", "access denied",
    ]
    if len(text) > 500 and len(_strip_html(text)) < 100:
        return True
    for s in block_signals:
        if s in lower:
            return True
    return False


def web_fetch(url, max_chars=None):
    """抓取 URL，返回清洗后文本。

    三级递进：
    1. urllib + 标准浏览器请求头
    2. curl_cffi 模拟浏览器 TLS（HTTP 403 或访问受限时）
    3. 返回错误及响应片段供 AI 判断
    """
    text = ""
    ct = ""
    errors = []

    # Level 1: urllib
    try:
        text, ct = _fetch_via_urllib(url)
        # urllib 可能拿到 200 但实际是验证页
        if _looks_like_block_page(text):
            errors.append("urllib 疑似被拦截（验证页）")
            text = ""
    except urllib.error.HTTPError as e:
        errors.append(f"urllib HTTP {e.code}")
        # 读响应体片段
        try:
            body = e.read().decode(errors="replace")[:300]
            if body:
                errors.append(f"响应片段: {body}")
        except Exception:
            pass
    except Exception as e:
        errors.append(f"urllib: {e}")

    # Level 2: curl_cffi
    if not text:
        try:
            text, ct = _fetch_via_curl_cffi(url)
            if _looks_like_block_page(text):
                errors.append("curl_cffi 疑似被拦截（验证页）")
                text = ""
            else:
                errors = []
        except Exception as e2:
            errors.append(f"curl_cffi: {e2}")

    if not text:
        return {"error": f"抓取失败: {' | '.join(errors)}"}

    # 检测验证/拦截页
    head = text[:2000].lower()
    is_html = "<html" in head or "<!doctype" in head or ct.startswith("text/html")
    if is_html:
        stripped = _strip_html(text)
        if len(stripped) < 100 and len(text) > 500:
            return {"error": f"疑似访问限制页面，响应片段: {text[:400]}"}
        text = stripped

    original_length = len(text)
    truncated = False
    if max_chars and len(text) > max_chars:
        truncated = True

    # 如果有 FETCH_MODEL，用完整内容（上限 16000 字）生成 AI 摘要
    summary = ""
    if FETCH_MODEL and text:
        try:
            r = _chat(FETCH_MODEL, [
                {"role": "system", "content": "你是网页内容提取助手。用中文总结网页关键内容，保留重要细节和数据，保留原文链接。"},
                {"role": "user", "content": text[:16000]},
            ], max_tokens=1024)
            if "text" in r:
                summary = r["text"]
        except Exception:
            pass

    # 有 AI 摘要时优先返回摘要，否则返回截断原文
    result = {"url": url, "original_length": original_length}
    if summary:
        result["summary"] = summary
        if truncated:
            result["note"] = f"原文 {original_length} 字，已通过 AI 提取关键内容"
    else:
        if truncated:
            text = text[:max_chars]
        result["content"] = text
        result["truncated"] = truncated
    return result


# ── Get Sources ──────────────────────────────────────────────────
def get_sources(session_id, offset=0, limit=None):
    """返回之前 web_search 缓存的源列表，支持分页"""
    sources = _cache_get(session_id)
    if sources is None:
        return {"error": f"会话 {session_id} 不存在或已过期"}
    total = len(sources)
    start = offset
    end = min(total, offset + limit) if limit else total
    page = sources[start:end]
    return {
        "session_id": session_id,
        "total_sources": total,
        "offset": offset,
        "next_offset": end if end < total else None,
        "sources": page,
    }


# ── Doctor ───────────────────────────────────────────────────────
def doctor():
    """诊断后端连通性"""
    results = {
        "base_url": BASE_URL,
        "vision_model": VISION_MODEL,
        "search_model": SEARCH_MODEL,
        "fetch_model": FETCH_MODEL or "(未设置, web_fetch 不启用 AI 摘要)",
        "api_key_set": bool(API_KEY),
    }
    if API_KEY:
        try:
            req = urllib.request.Request(
                f"{BASE_URL.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {API_KEY}", "User-Agent": UA})
            with urllib.request.urlopen(req, timeout=10) as resp:
                results["api"] = f"OK (HTTP {resp.status})"
                models = json.loads(resp.read())
                model_ids = [m.get("id", "") for m in (models.get("data", []) or [])]
                results["available_models"] = model_ids[:20]
        except Exception as e:
            results["api"] = f"FAIL: {e}"
        # 测试搜索模型
        try:
            r = _chat(SEARCH_MODEL, [{"role": "user", "content": "回复 OK"}], max_tokens=5)
            results["search_model_test"] = "OK" if "text" in r else f"FAIL: {r.get('error','?')}"
        except Exception as e:
            results["search_model_test"] = f"FAIL: {e}"
        # 测试视觉模型
        if VISION_MODEL != SEARCH_MODEL:
            try:
                r = _chat(VISION_MODEL, [{"role": "user", "content": "回复 OK"}], max_tokens=5)
                results["vision_model_test"] = "OK" if "text" in r else f"FAIL: {r.get('error','?')}"
            except Exception as e:
                results["vision_model_test"] = f"FAIL: {e}"
        results["cache_sessions"] = len(_source_cache)
    return {"text": json.dumps(results, ensure_ascii=False, indent=2)}


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
    {"name": "web_search", "description": "通过 AI 进行联网搜索，返回搜索结果和 session_id 供 get_sources 翻页。支持时效过滤、域名限定、输出格式控制。", "inputSchema": {
        "type": "object", "required": ["query"], "properties": {
            "query": {"type": "string", "description": "搜索关键词或问题"},
            "recency_days": {"type": "integer", "minimum": 1, "description": "限制来源为最近 N 天内的内容"},
            "include_domains": {"type": "array", "items": {"type": "string"}, "description": "限定域名，如 ['github.com', 'stackoverflow.com']"},
            "exclude_domains": {"type": "array", "items": {"type": "string"}, "description": "排除域名，如 ['csdn.net']"},
            "response_format": {"type": "string", "enum": ["concise", "detailed"], "description": "concise=简短+来源链接, detailed=详尽分析"}}}},
    {"name": "web_fetch", "description": "抓取指定 URL 的网页内容，自动清洗 HTML 返回纯文本。适合阅读文章、文档、GitHub 等。可选 max_chars 参数限制长度，可选启用 AI 摘要（设 LOOKSEE_FETCH_MODEL）。", "inputSchema": {
        "type": "object", "required": ["url"], "properties": {
            "url": {"type": "string", "description": "要抓取的网页 URL"},
            "max_chars": {"type": "integer", "minimum": 1, "description": "内容最大字符数，超出截断"}}}},
    {"name": "get_sources", "description": "取回之前 web_search 缓存的搜索结果，支持分页（offset/limit）。session_id 来自 web_search 的返回值。", "inputSchema": {
        "type": "object", "required": ["session_id"], "properties": {
            "session_id": {"type": "string", "description": "web_search 返回的 session_id"},
            "offset": {"type": "integer", "minimum": 0, "default": 0},
            "limit": {"type": "integer", "minimum": 1}}}},
    {"name": "doctor", "description": "诊断后端连通性 — 检查 API 端点、搜索模型、视觉模型是否可用。", "inputSchema": {
        "type": "object", "properties": {}}},
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
                "serverInfo": {"name": "looksee-mcp", "version": "1.1.0"}}}
        elif method == "notifications/initialized":
            continue
        elif method == "prompts/list":
            resp = {"jsonrpc": "2.0", "id": rid, "result": {"prompts": [{
                "name": "vision-guide",
                "description": "当对话中出现 [Unsupported Image] 或模型无法处理图片时，必须调用 vision_clipboard 工具读取剪贴板并分析图片。用户无需额外操作，只需粘贴图片即可。"
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
                    result = {"error": mime or "剪贴板无图片，请重新截图/复制后重试，或将图片保存为文件后使用 vision_file"}
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
                result = web_search(args.get("query", ""),
                                    recency_days=args.get("recency_days"),
                                    include_domains=args.get("include_domains"),
                                    exclude_domains=args.get("exclude_domains"),
                                    response_format=args.get("response_format"))
            elif name == "web_fetch":
                result = web_fetch(args.get("url", ""),
                                   args.get("max_chars"))
            elif name == "get_sources":
                result = get_sources(args.get("session_id", ""),
                                     args.get("offset", 0),
                                     args.get("limit"))
            elif name == "doctor":
                result = doctor()
            else:
                resp = {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"unknown: {name}"}}
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                sys.stdout.flush(); continue
            # 结构化结果（web_fetch/get_sources/doctor）序列化为 JSON
            if "text" in result:
                text = result["text"]
            elif "error" in result:
                text = result["error"]
            else:
                text = json.dumps(result, ensure_ascii=False, indent=2)
            resp = {"jsonrpc": "2.0", "id": rid, "result": {"content": [
                {"type": "text", "text": text}
            ]}}
        else:
            resp = {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"unknown method"}}
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    serve()
