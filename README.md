# Unlocking Prefab MCP

An MCP (Model Context Protocol) project that demonstrates agentic tool use across three domains — internet fetch, local file CRUD, and UI rendering — using Google's [Prefab](https://google.github.io/prefab/) package format to distribute the dashboard UI.

---

## What it does

An AI agent (Cerebras `llama3.1-8b`) is given a research task. It autonomously calls three MCP tools in sequence:

1. **Fetches** company data from the Wikipedia REST API
2. **Saves** the data to a local JSON file via CRUD operations
3. **Renders** the data on a dashboard built as a Prefab UI package and opens it in the browser

---

## Project structure

```
unlocking_prefab_mcp/
│
├── agent_company_research.py       # Orchestrating agent — entry point
├── company_research_mcp.py         # MCP server exposing the 3 tools
│
├── prefab-dashboard-ui/            # Prefab UI package (schema_version 2)
│   ├── prefab.json                 # Package metadata
│   └── modules/
│       └── dashboard/
│           ├── module.json         # Module metadata + platform declarations
│           └── assets/
│               ├── web.x64/        # Full-page browser dashboard template
│               │   └── index.html
│               └── chrome.v3/     # Chrome extension popup template
│                   └── index.html
│
├── talk2mcp.py                     # Original math agent (Gemini + MCP demo)
├── example2.py                     # MCP server for talk2mcp (math + Paint tools)
├── example_mcp_server.py           # Earlier version of the math MCP server
├── decorator.py                    # Standalone decorator pattern demo
│
├── data/                           # Created at runtime — stores saved JSON files
├── prefab-dashboard-ui/output/     # Created at runtime — populated HTML dashboards
├── venv/                           # Python virtual environment (uv-managed)
├── .env                            # API keys (not committed)
└── .gitignore
```

---

## MCP tools

Defined in [`company_research_mcp.py`](company_research_mcp.py):

| Tool | Parameters | Description |
|------|-----------|-------------|
| `fetch_company_info` | `company_name: str` | Hits the Wikipedia REST API; returns title, description, extract, and URL as compact JSON |
| `crud_notes` | `operation, filename, content, key` | Create / Read / Update / Delete on local JSON files in `data/` |
| `render_prefab_dashboard` | `title, data_file, platform` | Injects data into the Prefab module template and opens it in the browser |

---

## The Prefab connection

[`prefab-dashboard-ui/`](prefab-dashboard-ui/) mirrors the [Prefab package format](https://google.github.io/prefab/#package-structure) from Google's prefab-master — but instead of shipping prebuilt C++ libraries, the package ships prebuilt HTML/JS dashboard assets per target platform.

| Prefab (C++ libs) | This project (UI assets) |
|-------------------|--------------------------|
| `prefab.json` | same — package metadata, `schema_version: 2` |
| `modules/<name>/module.json` | same — module metadata |
| `libs/<platform>.<id>/libfoo.so` | `assets/<platform>.<id>/index.html` |
| `android.arm64-v8a` | `web.x64`, `chrome.v3` |

---

## Setup

**1. Activate the virtual environment**
```powershell
.\venv\Scripts\activate.bat
```

**2. Install dependencies**
```powershell
uv pip install mcp google-genai python-dotenv cerebras-cloud-sdk
```

**3. API keys** — already configured in `.env` (not committed to git)
```
GEMINI_API_KEY=AIzaSyDwhZMKh6QqfOfB9bUkhH9WebbG8VlyLPk
MISTRAL_API_KEY=yMCtvmD61R1iP0GnpwXbgqsXjVgck9M3
CEREBRAS_API_KEY=csk-h8n493rxkr4rhfe442nj3frr3vne9jtdn6vnh85pckf6w5xc
```

---

## Running

| Script | Command | Notes |
|--------|---------|-------|
| Company research agent | `python agent_company_research.py` | Entry point — spawns the MCP server automatically |
| Math agent | `python talk2mcp.py` | Gemini + MCP loop; `example2.py` is spawned automatically |
| Decorator demo | `python decorator.py` | No dependencies — runs standalone |

After running the agent, check:
- `data/tata_sons.json` — saved research data
- `prefab-dashboard-ui/output/web_x64_dashboard.html` — populated dashboard (also auto-opens in browser)

---

## Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) — `winget install astral-sh.uv`
- Cerebras API key — [cloud.cerebras.ai](https://cloud.cerebras.ai)
