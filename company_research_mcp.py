from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent
import sys
import json
import os
import urllib.request
import urllib.parse
import time
import yfinance as yf

mcp = FastMCP("CompanyResearch")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PREFAB_PKG_DIR = os.path.join(BASE_DIR, "prefab-dashboard-ui")
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)


# ─── Tool 1: Internet ────────────────────────────────────────────────────────

@mcp.tool()
def fetch_company_info(company_name: str) -> str:
    """Fetch a company summary from Wikipedia (title, description, extract, URL).
    Returns compact JSON string."""
    print(f"CALLED: fetch_company_info({company_name!r})")
    try:
        encoded = urllib.parse.quote(company_name.replace(" ", "_"))
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "MCP-CompanyResearch/1.0 (educational project)"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = json.loads(resp.read().decode())

        result = {
            "title": raw.get("title", company_name),
            "description": raw.get("description", ""),
            "extract": raw.get("extract", "")[:600],   # keep single-line safe
            "url": raw.get("content_urls", {}).get("desktop", {}).get("page", ""),
            "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        return json.dumps(result)   # compact — no newlines, safe as FUNCTION_CALL param
    except Exception as exc:
        return json.dumps({"error": str(exc), "title": company_name})


# ─── Tool 2: File CRUD ────────────────────────────────────────────────────────

@mcp.tool()
def crud_notes(operation: str, filename: str, content: str = "", key: str = "") -> str:
    """CRUD on a local JSON file in the data/ directory.

    operation : 'create' | 'read' | 'update' | 'delete'
    filename  : bare filename, e.g. 'tata_sons.json'
    content   : JSON string to write (create / update)
    key       : specific top-level key to delete (delete operation only)
    """
    print(f"CALLED: crud_notes({operation!r}, {filename!r})")
    filepath = os.path.join(DATA_DIR, filename)
    try:
        if operation == "create":
            data = json.loads(content) if content.strip() else {}
            with open(filepath, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            return f"Created {filename} successfully at {filepath}"

        elif operation == "read":
            if not os.path.exists(filepath):
                return json.dumps({"error": f"{filename} not found"})
            with open(filepath, encoding="utf-8") as fh:
                return fh.read()

        elif operation == "update":
            existing: dict = {}
            if os.path.exists(filepath):
                with open(filepath, encoding="utf-8") as fh:
                    existing = json.load(fh)
            new_data = json.loads(content) if content.strip() else {}
            existing.update(new_data)
            with open(filepath, "w", encoding="utf-8") as fh:
                json.dump(existing, fh, indent=2)
            return f"Updated {filename} successfully"

        elif operation == "delete":
            if key:
                if os.path.exists(filepath):
                    with open(filepath, encoding="utf-8") as fh:
                        data = json.load(fh)
                    data.pop(key, None)
                    with open(filepath, "w", encoding="utf-8") as fh:
                        json.dump(data, fh, indent=2)
                    return f"Deleted key '{key}' from {filename}"
                return f"{filename} not found"
            else:
                if os.path.exists(filepath):
                    os.remove(filepath)
                    return f"Deleted {filename}"
                return f"{filename} not found"

        else:
            return f"Unknown operation: '{operation}'. Use create|read|update|delete."
    except Exception as exc:
        return f"crud_notes error: {exc}"


# ─── Tool 3: Ticker search ────────────────────────────────────────────────────

@mcp.tool()
def search_ticker(company_name: str) -> str:
    """Resolve a company name to its stock ticker symbol using yfinance Search.

    Returns JSON with ticker, full name, exchange, and quote type.
    Use this before fetch_financial_data when you don't know the ticker.
    """
    print(f"CALLED: search_ticker({company_name!r})")
    try:
        results = yf.Search(company_name, max_results=5)
        quotes = getattr(results, "quotes", [])
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

@mcp.tool()
def fetch_financial_data(company_name: str) -> str:
    """Fetch financial data for a company using yfinance.

    Returns JSON with: ticker, sector, market_cap, pe_ratio, eps,
    profit_margin, revenue_trend (last 4 years), currency.
    """
    print(f"CALLED: fetch_financial_data({company_name!r})")

    # Resolve name → ticker dynamically
    ticker_sym = company_name.strip()
    try:
        results = yf.Search(company_name, max_results=3)
        quotes = getattr(results, "quotes", [])
        if quotes:
            ticker_sym = quotes[0].get("symbol", company_name)
    except Exception:
        pass

    try:
        ticker = yf.Ticker(ticker_sym)
        info = ticker.info or {}

        # Revenue trend from annual financials
        revenue_trend = []
        try:
            fin = ticker.financials
            if fin is not None and not fin.empty:
                rev_row = fin.loc["Total Revenue"] if "Total Revenue" in fin.index else None
                if rev_row is not None:
                    for col in list(rev_row.index)[:4]:
                        year = str(col)[:4]
                        val = rev_row[col]
                        if val and not (isinstance(val, float) and val != val):  # skip NaN
                            revenue_trend.append({"year": year, "revenue": int(val)})
        except Exception:
            pass

        result = {
            "ticker": ticker_sym,
            "sector": info.get("sector", "N/A"),
            "industry": info.get("industry", "N/A"),
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "eps": info.get("trailingEps"),
            "profit_margin": info.get("profitMargins"),
            "revenue_growth": info.get("revenueGrowth"),
            "currency": info.get("currency", "USD"),
            "revenue_trend": revenue_trend,
            "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc), "ticker": ticker_sym})


# ─── Tool 5: Prefab UI render ─────────────────────────────────────────────────

@mcp.tool()
def render_prefab_dashboard(title: str, data_file: str, platform: str = "web.x64") -> str:
    """Load a saved data file and render it via the Prefab UI package.

    Reads the HTML template from the Prefab module asset directory,
    injects the title and JSON data, writes the output, and opens it in the
    default browser.

    title     : heading text shown in the dashboard
    data_file : filename in data/ (e.g. 'tata_sons.json')
    platform  : Prefab platform identifier — 'web.x64' or 'chrome.v3'
    """
    print(f"CALLED: render_prefab_dashboard({title!r}, {data_file!r}, {platform!r})")

    data_filepath = os.path.join(DATA_DIR, data_file)
    if not os.path.exists(data_filepath):
        return f"Data file '{data_file}' not found. Run crud_notes('read', ...) first."

    with open(data_filepath, encoding="utf-8") as fh:
        data = json.load(fh)

    # Resolve Prefab module asset path  →  modules/dashboard/assets/<platform>/index.html
    template_path = os.path.join(
        PREFAB_PKG_DIR, "modules", "dashboard", "assets", platform, "index.html"
    )
    if not os.path.exists(template_path):
        return f"Prefab template not found at {template_path}"

    with open(template_path, encoding="utf-8") as fh:
        html = fh.read()

    # Inject dynamic values
    data_js = json.dumps(data, ensure_ascii=False)
    html = html.replace("__DASHBOARD_TITLE__", title)
    html = html.replace("__DASHBOARD_DATA__", data_js)
    html = html.replace("__DATA_FILE__", data_file)
    html = html.replace("__PLATFORM__", platform)

    # Write populated output file
    output_dir = os.path.join(PREFAB_PKG_DIR, "output")
    os.makedirs(output_dir, exist_ok=True)
    safe_name = platform.replace(".", "_")
    output_path = os.path.join(output_dir, f"{safe_name}_dashboard.html")
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(html)

    return f"Dashboard rendered → {output_path}"


# ─── Resources & prompts ──────────────────────────────────────────────────────

@mcp.resource("data://{filename}")
def read_data_resource(filename: str) -> str:
    """Expose a saved data file as an MCP resource."""
    filepath = os.path.join(DATA_DIR, filename)
    if os.path.exists(filepath):
        with open(filepath, encoding="utf-8") as fh:
            return fh.read()
    return json.dumps({"error": f"{filename} not found"})


if __name__ == "__main__":
    print("STARTING CompanyResearch MCP Server")
    if len(sys.argv) > 1 and sys.argv[1] == "dev":
        mcp.run()
    else:
        mcp.run(transport="stdio")
