"""
MCP server exposing five tools for the company research agent:
  1. fetch_company_info     – Wikipedia REST API
  2. crud_notes             – local JSON file CRUD
  3. search_ticker          – yfinance ticker lookup
  4. fetch_financial_data   – yfinance financials + revenue trend
  5. render_prefab_dashboard – write populated Prefab HTML asset
"""

from mcp.server.fastmcp import FastMCP
import sys
import json
import os
import urllib.request
import urllib.parse
import time
import yfinance as yf

mcp_server = FastMCP("CompanyResearch")

BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
PREFAB_PKG_DIR = os.path.join(BASE_DIR, "prefab-dashboard-ui")
DATA_DIR       = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)


# ─── Tool 1: Wikipedia ───────────────────────────────────────────────────────

@mcp_server.tool()
def fetch_company_info(company_name: str) -> str:
    """Fetch a company summary from Wikipedia (title, description, extract, URL).
    Returns compact JSON string."""
    print(f"[MCP] fetch_company_info({company_name!r})")
    try:
        encoded = urllib.parse.quote(company_name.replace(" ", "_"))
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "MCP-CompanyResearch/1.0 (educational project)"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = json.loads(resp.read().decode())

        return json.dumps({
            "title":       raw.get("title", company_name),
            "description": raw.get("description", ""),
            "extract":     raw.get("extract", "")[:600],
            "url":         raw.get("content_urls", {}).get("desktop", {}).get("page", ""),
            "fetched_at":  time.strftime("%Y-%m-%d %H:%M:%S"),
        })
    except Exception as exc:
        return json.dumps({"error": str(exc), "title": company_name})


# ─── Tool 2: File CRUD ────────────────────────────────────────────────────────

@mcp_server.tool()
def crud_notes(operation: str, filename: str, content: str = "", key: str = "") -> str:
    """CRUD on a local JSON file in the data/ directory.

    operation : 'create' | 'read' | 'update' | 'delete'
    filename  : bare filename, e.g. 'apple_inc.json'
    content   : JSON string to write (create / update)
    key       : top-level key to remove (delete operation only)
    """
    print(f"[MCP] crud_notes({operation!r}, {filename!r})")
    file_path = os.path.join(DATA_DIR, filename)
    try:
        if operation == "create":
            parsed = json.loads(content) if content.strip() else {}
            with open(file_path, "w", encoding="utf-8") as fh:
                json.dump(parsed, fh, indent=2)
            return f"Created {filename}"

        elif operation == "read":
            if not os.path.exists(file_path):
                return json.dumps({"error": f"{filename} not found"})
            with open(file_path, encoding="utf-8") as fh:
                return fh.read()

        elif operation == "update":
            existing: dict = {}
            if os.path.exists(file_path):
                with open(file_path, encoding="utf-8") as fh:
                    existing = json.load(fh)
            existing.update(json.loads(content) if content.strip() else {})
            with open(file_path, "w", encoding="utf-8") as fh:
                json.dump(existing, fh, indent=2)
            return f"Updated {filename}"

        elif operation == "delete":
            if key:
                if os.path.exists(file_path):
                    with open(file_path, encoding="utf-8") as fh:
                        stored = json.load(fh)
                    stored.pop(key, None)
                    with open(file_path, "w", encoding="utf-8") as fh:
                        json.dump(stored, fh, indent=2)
                    return f"Deleted key '{key}' from {filename}"
                return f"{filename} not found"
            else:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    return f"Deleted {filename}"
                return f"{filename} not found"

        return f"Unknown operation '{operation}'. Use create|read|update|delete."
    except Exception as exc:
        return f"crud_notes error: {exc}"


# ─── Tool 3: Ticker lookup ────────────────────────────────────────────────────

@mcp_server.tool()
def search_ticker(company_name: str) -> str:
    """Resolve a company name to its stock ticker symbol using yfinance Search.
    Returns JSON with ticker, full name, exchange, and quote type."""
    print(f"[MCP] search_ticker({company_name!r})")
    try:
        search_results = yf.Search(company_name, max_results=5)
        quotes = getattr(search_results, "quotes", [])
        if not quotes:
            return json.dumps({"error": "No ticker found", "query": company_name})
        top = quotes[0]
        return json.dumps({
            "ticker":   top.get("symbol", ""),
            "name":     top.get("longname") or top.get("shortname", ""),
            "exchange": top.get("exchange", ""),
            "type":     top.get("quoteType", ""),
        })
    except Exception as exc:
        return json.dumps({"error": str(exc), "query": company_name})


# ─── Tool 4: Financial data ───────────────────────────────────────────────────

@mcp_server.tool()
def fetch_financial_data(company_name: str) -> str:
    """Fetch financial data for a company using yfinance.

    Accepts a company name or ticker symbol. Returns JSON with:
    ticker, sector, market_cap, pe_ratio, eps, profit_margin,
    revenue_growth, revenue_trend (last 4 years), profit_breakdown, currency.
    """
    print(f"[MCP] fetch_financial_data({company_name!r})")

    # Resolve name → ticker dynamically
    ticker_sym = company_name.strip()
    try:
        search_results = yf.Search(company_name, max_results=3)
        quotes = getattr(search_results, "quotes", [])
        if quotes:
            ticker_sym = quotes[0].get("symbol", company_name)
    except Exception:
        pass

    try:
        ticker = yf.Ticker(ticker_sym)
        info   = ticker.info or {}

        revenue_trend    = []
        profit_breakdown = None

        try:
            financials = ticker.financials
            if financials is not None and not financials.empty:

                def _get_value(row_name: str, col) -> int | None:
                    if row_name not in financials.index:
                        return None
                    v = financials.loc[row_name, col]
                    return int(v) if v and not (isinstance(v, float) and v != v) else None

                revenue_row = financials.loc["Total Revenue"] if "Total Revenue" in financials.index else None
                if revenue_row is not None:
                    for col in list(revenue_row.index)[:4]:
                        val = revenue_row[col]
                        if val and not (isinstance(val, float) and val != val):
                            revenue_trend.append({"year": str(col)[:4], "revenue": int(val)})

                if revenue_trend:
                    latest_col = list(financials.columns)[0]
                    total_rev  = _get_value("Total Revenue",   latest_col)
                    cost_rev   = _get_value("Cost Of Revenue", latest_col)
                    net_income = _get_value("Net Income",      latest_col)
                    if total_rev and cost_rev and net_income:
                        op_expenses = total_rev - cost_rev - net_income
                        profit_breakdown = {
                            "year":               str(latest_col)[:4],
                            "cost_of_revenue":    abs(cost_rev),
                            "operating_expenses": abs(op_expenses) if op_expenses > 0 else 0,
                            "net_income":         abs(net_income),
                        }
        except Exception:
            pass

        return json.dumps({
            "ticker":          ticker_sym,
            "sector":          info.get("sector", "N/A"),
            "industry":        info.get("industry", "N/A"),
            "market_cap":      info.get("marketCap"),
            "pe_ratio":        info.get("trailingPE"),
            "eps":             info.get("trailingEps"),
            "profit_margin":   info.get("profitMargins"),
            "revenue_growth":  info.get("revenueGrowth"),
            "currency":        info.get("currency", "USD"),
            "revenue_trend":   revenue_trend,
            "profit_breakdown": profit_breakdown,
            "fetched_at":      time.strftime("%Y-%m-%d %H:%M:%S"),
        })
    except Exception as exc:
        return json.dumps({"error": str(exc), "ticker": ticker_sym})


# ─── Tool 5: Prefab UI render ─────────────────────────────────────────────────

@mcp_server.tool()
def render_prefab_dashboard(title: str, data_file: str, platform: str = "web.x64") -> str:
    """Populate and save the Prefab HTML dashboard for the given platform.

    Reads the template from prefab-dashboard-ui/modules/dashboard/assets/<platform>/,
    injects title and data placeholders, writes the result to output/.

    title     : heading shown in the dashboard
    data_file : filename inside data/ (e.g. 'apple_inc.json')
    platform  : Prefab platform target — 'web.x64' or 'chrome.v3'
    """
    print(f"[MCP] render_prefab_dashboard({title!r}, {data_file!r}, {platform!r})")

    data_file_path = os.path.join(DATA_DIR, data_file)
    if not os.path.exists(data_file_path):
        return f"Data file '{data_file}' not found."

    template_path = os.path.join(
        PREFAB_PKG_DIR, "modules", "dashboard", "assets", platform, "index.html"
    )
    if not os.path.exists(template_path):
        return f"Prefab template not found: {template_path}"

    with open(data_file_path, encoding="utf-8") as fh:
        payload = json.load(fh)

    with open(template_path, encoding="utf-8") as fh:
        html = fh.read()

    html = (html
        .replace("__DASHBOARD_TITLE__", title)
        .replace("__DASHBOARD_DATA__",  json.dumps(payload, ensure_ascii=False))
        .replace("__DATA_FILE__",        data_file)
        .replace("__PLATFORM__",         platform))

    output_dir  = os.path.join(PREFAB_PKG_DIR, "output")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{platform.replace('.', '_')}_dashboard.html")
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(html)

    return f"Dashboard rendered → {output_path}"


# ─── MCP resource ─────────────────────────────────────────────────────────────

@mcp_server.resource("data://{filename}")
def get_saved_data_file(filename: str) -> str:
    """Expose a saved research file as an MCP resource."""
    file_path = os.path.join(DATA_DIR, filename)
    if os.path.exists(file_path):
        with open(file_path, encoding="utf-8") as fh:
            return fh.read()
    return json.dumps({"error": f"{filename} not found"})


if __name__ == "__main__":
    print("Starting CompanyResearch MCP Server")
    if len(sys.argv) > 1 and sys.argv[1] == "dev":
        mcp_server.run()
    else:
        mcp_server.run(transport="stdio")
