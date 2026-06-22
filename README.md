# looksee-mcp

看图 + 搜索，一个 MCP 搞定。

[English](README.en.md)

## 适用环境

| 组件     | 要求                                        |
| :------- | :------------------------------------------ |
| 操作系统 | macOS（`vision_clipboard` 依赖 `pngpaste`） |
| 编辑器   | VSCode + Claude Code 插件                   |
| 语言     | Python 3.9+                                 |

> **Windows / Linux**：仅 `vision_clipboard` 不可用，`vision_file`、`vision_dir`、`web_search` 正常工作。

## 为什么选 looksee-mcp

- **零外部依赖** — 纯 Python 标准库，PIL 可选（自动压缩大图，体积减少 90%）
- **任意 OpenAI 兼容端点** — GPT-4o、Grok、Kimi、Qwen-VL、MiniMax、vLLM 都能用，换 API 只改一个 URL
- **搜图合一** — 一个 MCP 进程同时提供视觉理解和联网搜索，不需要装多个 MCP
- **粘贴即分析** — macOS 下截图/复制图片后自动读取剪贴板，零额外操作
- **极简配置** — 5 个环境变量，一分钟上手
- **curl_cffi 可选** — 模拟标准浏览器 TLS，提高页面抓取成功率

## 快速开始

**1. 安装**

```bash
git clone https://github.com/zaoann8/looksee-mcp.git
cd looksee-mcp
pip install .
brew install pngpaste   # macOS 剪贴板读取
```

**2. 注册到 Claude Code**

打开 VSCode → Cmd+Shift+P → `Claude: Open Settings`，或者直接编辑 `~/.claude.json`：

```json
{
  "mcpServers": {
    "looksee-mcp": {
      "command": "python3",
      "args": ["实际路径/looksee-mcp/src/looksee_mcp/server.py"],
      "env": {
        "LOOKSEE_BASE_URL": "https://your-api.com/v1",
        "LOOKSEE_API_KEY": "sk-your-key",
        "LOOKSEE_VISION_MODEL": "gpt-4o",
        "LOOKSEE_SEARCH_MODEL": "gpt-4o-mini"
      }
    }
  }
}
```

**3. 重启 Claude Code**

Cmd+Shift+P → `Developer: Reload Window`，或在 Claude Code 面板输入 `/mcp` 确认 `looksee-mcp ✔ connected · 7 tools`。

**4. 开始使用**

- 截图/复制图片 → 粘贴到对话框 → "分析这张图片" → 自动识别
- 拖图片到项目文件夹 → "分析 images/ 下所有图片"
- "帮我搜一下 XXX" → 联网搜索
- "抓一下 https://xxx 这篇文章" → 自动抓取网页，AI 提取摘要
- "检查下后端通不通" → 一键诊断 API 连通性

## 工具

| 工具               | 做什么                                     | 什么时候用             |
| :----------------- | :----------------------------------------- | :--------------------- |
| `vision_clipboard` | 读取系统剪贴板图片                         | 截图后直接粘贴到对话框 |
| `vision_file`      | 读取指定路径图片                           | 图片文件在项目里       |
| `vision_dir`       | 批量读取目录下所有图片                     | 拖了一堆图到文件夹     |
| `web_search`       | AI 联网搜索，返回 session_id 供翻页        | 搜索实时信息           |
| `web_fetch`        | 抓取网页 URL，自动洗 HTML，AI 提炼摘要     | 阅读文章/文档          |
| `get_sources`      | 取回上次搜索的源，支持分页（offset/limit） | 翻页查看更多搜索结果   |
| `doctor`           | 诊断 API 端点、视觉/搜索模型连通性         | 排查问题、验证配置     |

## 配置参考

| 环境变量               | 说明                                   | 默认值                      |
| :--------------------- | :------------------------------------- | :-------------------------- |
| `LOOKSEE_BASE_URL`     | OpenAI 兼容 API 地址                   | `https://api.openai.com/v1` |
| `LOOKSEE_API_KEY`      | API 密钥                               | —                           |
| `LOOKSEE_VISION_MODEL` | 视觉模型（需支持图片）                 | `gpt-4o`                    |
| `LOOKSEE_SEARCH_MODEL` | 搜索模型                               | `gpt-4o-mini`               |
| `LOOKSEE_FETCH_MODEL`  | 网页摘要模型（可选，不设则无 AI 摘要） | —                           |

> 提示：安装 `curl_cffi`（`pip install curl_cffi`）后，web_fetch 可模拟标准浏览器 TLS 指纹，提高页面抓取成功率。

## License

Apache 2.0 — 详见 [LICENSE](LICENSE)

---

🏅 此项目已获 [LINUX DO](https://linux.do/) 社区链接认可。
