# looksee-mcp

Vision + Search, one MCP server.

[中文](README.md)

## Environment

| Component | Requirement                                 |
| :-------- | :------------------------------------------ |
| OS        | macOS (`vision_clipboard` needs `pngpaste`) |
| Editor    | VSCode + Claude Code extension              |
| Python    | 3.9+                                        |

> **Windows / Linux**: `vision_file`, `vision_dir`, and `web_search` work fine. Only `vision_clipboard` requires macOS.

## Why looksee-mcp

- **Zero dependencies** — pure Python stdlib, PIL optional (auto-compresses large images by 90%)
- **Any OpenAI-compatible endpoint** — GPT-4o, Grok, Kimi, Qwen-VL, MiniMax, vLLM all work. Swap APIs by changing one URL
- **Vision + Search in one process** — no need for multiple MCP servers
- **Paste & analyze** — clipboard images auto-detected on macOS, zero extra clicks
- **Minimal config** — 4 environment variables, ready in one minute

## Quick Start

**1. Install**

```bash
git clone https://github.com/zaoann8/looksee-mcp.git
cd looksee-mcp
pip install .
brew install pngpaste   # macOS clipboard support
```

**2. Register with Claude Code**

Open VSCode → Cmd+Shift+P → `Claude: Open Settings`, or edit `~/.claude.json`:

```json
{
  "mcpServers": {
    "looksee-mcp": {
      "command": "python3",
      "args": ["/actual/path/looksee-mcp/src/looksee_mcp/server.py"],
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

**3. Restart Claude Code**

Cmd+Shift+P → `Developer: Reload Window`, or type `/mcp` in Claude Code to verify `looksee-mcp ✔ connected · 4 tools`.

**4. Start using**

- Screenshot/copy an image → paste into chat → "Analyze this image" → auto-detected
- Drop images into your project folder → "Analyze all images in images/"
- "Search for XXX" → AI-powered web search

## Tools

| Tool               | What it does                          | When to use                           |
| :----------------- | :------------------------------------ | :------------------------------------ |
| `vision_clipboard` | Reads image from system clipboard     | Screenshot then paste into chat       |
| `vision_file`      | Reads image from file path            | Image files already in your project   |
| `vision_dir`       | Batch reads all images in a directory | Dropped multiple images into a folder |
| `web_search`       | AI-powered web search                 | Real-time information lookup          |

## Configuration

| Variable               | Description                        | Default                     |
| :--------------------- | :--------------------------------- | :-------------------------- |
| `LOOKSEE_BASE_URL`     | OpenAI-compatible API base URL     | `https://api.openai.com/v1` |
| `LOOKSEE_API_KEY`      | API key                            | —                           |
| `LOOKSEE_VISION_MODEL` | Vision model (must support images) | `gpt-4o`                    |
| `LOOKSEE_SEARCH_MODEL` | Search model                       | `gpt-4o-mini`               |

## License

Apache 2.0 — see [LICENSE](LICENSE)

---

🏅 Recognized by the [LINUX DO](https://linux.do/) community.
