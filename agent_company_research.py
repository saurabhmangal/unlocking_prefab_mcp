"""
Company Research Agent
Drives company_research_mcp.py through five sequential steps,
then keeps the Prefab dashboard server alive for browsing.

Steps:
  1. fetch_company_info     – Wikipedia overview
  2. search_ticker          – resolve stock ticker
  3. fetch_financial_data   – yfinance metrics + charts
  4. crud_notes             – persist data to local JSON
  5. render_prefab_dashboard – write populated Prefab HTML asset
"""

import os
import json
import time
import asyncio
import webbrowser
from concurrent.futures import TimeoutError
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from cerebras.cloud.sdk import Cerebras
import dashboard_server

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

cerebras_client = Cerebras(api_key=os.getenv("CEREBRAS_API_KEY"))

MAX_AGENT_ITERATIONS = 15

RESEARCH_STEPS = [
    {"id": 1, "tool": "fetch_company_info",     "label": "Fetch company overview from Wikipedia", "status": "pending", "result": None},
    {"id": 2, "tool": "search_ticker",           "label": "Resolve company ticker symbol",          "status": "pending", "result": None},
    {"id": 3, "tool": "fetch_financial_data",    "label": "Fetch financial data (yfinance)",        "status": "pending", "result": None},
    {"id": 4, "tool": "crud_notes",              "label": "Save data to local JSON file",            "status": "pending", "result": None},
    {"id": 5, "tool": "render_prefab_dashboard", "label": "Render Prefab dashboard",                "status": "pending", "result": None},
]


# ── Logging ───────────────────────────────────────────────────────────────────

_agent_logs: list[str] = []


def append_log(message: str) -> None:
    _agent_logs.append(f"[{time.strftime('%H:%M:%S')}] {message}")
    if len(_agent_logs) > 200:
        _agent_logs.pop(0)


# ── Dashboard status writer ───────────────────────────────────────────────────

def publish_status(steps: list, company_data=None, financial_data=None,
                   completed: bool = False, title: str = "Research Dashboard",
                   phase: str = "running") -> None:
    payload = {
        "phase":          phase,
        "title":          title,
        "steps":          steps,
        "company_data":   company_data,
        "financial_data": financial_data,
        "completed":      completed,
        "logs":           list(_agent_logs),
        "updated_at":     time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(os.path.join(DATA_DIR, "status.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def update_step_status(steps: list, tool_name: str, status: str, result: str | None = None) -> None:
    for step in steps:
        if step["tool"] == tool_name:
            step["status"] = status
            if result is not None:
                step["result"] = result
            break


# ── Query listener ────────────────────────────────────────────────────────────

async def wait_for_user_query() -> str:
    """Write 'waiting' phase, then poll until the frontend POSTs a query."""
    query_file = os.path.join(DATA_DIR, "query.json")
    if os.path.exists(query_file):
        os.remove(query_file)
    publish_status([], phase="waiting", title="Ready — enter your query in the dashboard")
    print("Waiting for query at http://localhost:5000 …")
    while True:
        if os.path.exists(query_file):
            with open(query_file, encoding="utf-8") as fh:
                data = json.load(fh)
            os.remove(query_file)
            return data["query"]
        await asyncio.sleep(0.4)


# ── LLM call ─────────────────────────────────────────────────────────────────

async def call_llm(system_prompt: str, user_message: str,
                   timeout: int = 120, max_tokens: int = 200) -> str:
    loop = asyncio.get_event_loop()
    response = await asyncio.wait_for(
        loop.run_in_executor(
            None,
            lambda: cerebras_client.chat.completions.create(
                model="llama3.1-8b",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_message},
                ],
                max_tokens=max_tokens,
            ),
        ),
        timeout=timeout,
    )
    return response.choices[0].message.content.strip()


# ── Tool argument parser ──────────────────────────────────────────────────────

def parse_tool_arguments(raw_call: str, schema_properties: dict) -> dict:
    """Parse a pipe-delimited FUNCTION_CALL string into a typed arguments dict."""
    parts       = raw_call.split("|", len(schema_properties))
    raw_values  = [p.strip() for p in parts[1:]]
    arguments: dict = {}

    for idx, (param_name, param_schema) in enumerate(schema_properties.items()):
        if idx >= len(raw_values) or raw_values[idx] == "":
            continue
        value      = raw_values[idx]
        param_type = param_schema.get("type", "string")
        if param_type == "integer":
            arguments[param_name] = int(value)
        elif param_type == "number":
            arguments[param_name] = float(value)
        elif param_type == "array":
            if isinstance(value, str):
                value = value.strip("[]").split(",")
            arguments[param_name] = [v.strip() for v in value]
        else:
            arguments[param_name] = str(value)

    return arguments


# ── Agent entry point ─────────────────────────────────────────────────────────

async def run_research_agent() -> None:
    import copy
    steps          = copy.deepcopy(RESEARCH_STEPS)
    company_data   = None
    financial_data = None

    append_log("Starting Prefab dashboard server on port 5000")
    dashboard_server.start_server(port=5000)
    time.sleep(0.8)
    webbrowser.open("http://localhost:5000")
    append_log("Browser opened → http://localhost:5000")
    print("Dashboard: http://localhost:5000")

    user_query = await wait_for_user_query()
    append_log(f"Query received: {user_query}")
    print(f"\nQuery received: {user_query}\n")
    print("=" * 60)
    print("  Company Research Agent  (Prefab MCP Demo)")
    print("=" * 60)

    mcp_server_params = StdioServerParameters(
        command="python",
        args=["company_research_mcp.py"],
    )

    async with stdio_client(mcp_server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            available_tools = (await session.list_tools()).tools
            print(f"Tools available: {[t.name for t in available_tools]}\n")

            tools_description = "\n".join(
                f"{i}. {t.name}({', '.join(f'{k}: {v.get(\"type\",\"?\")}' for k, v in t.inputSchema.get('properties', {}).items()) or 'no parameters'}) - {getattr(t, 'description', '')}"
                for i, t in enumerate(available_tools, 1)
            )

            output_filename = user_query.lower().replace(" ", "_")[:30].strip("_") + ".json"

            agent_system_prompt = f"""You are a company research agent.
The user's query is: "{user_query}"

Complete ALL FIVE steps in order:

STEP 1 – Identify the main company/entity and call:
   FUNCTION_CALL: fetch_company_info|<company name>

STEP 2 – Find the stock ticker:
   FUNCTION_CALL: search_ticker|<company name>

STEP 3 – Fetch financial data using the ticker from Step 2:
   FUNCTION_CALL: fetch_financial_data|<ticker symbol>

STEP 4 – Save the Wikipedia result from Step 1:
   FUNCTION_CALL: crud_notes|create|{output_filename}|<full JSON from step 1 on a single line>

STEP 5 – Render the dashboard:
   FUNCTION_CALL: render_prefab_dashboard|{user_query[:60]}|{output_filename}|web.x64

Then give: FINAL_ANSWER: [done]

Available tools:
{tools_description}

Respond with EXACTLY ONE line: FUNCTION_CALL: ... or FINAL_ANSWER: [done]
No explanations."""

            append_log(f"MCP server ready — {len(available_tools)} tools loaded")
            publish_status(steps, title=user_query)

            iteration        = 0
            last_tool_result = None
            tool_call_history: list[str] = []

            while iteration < MAX_AGENT_ITERATIONS:
                print(f"\n{'─' * 50}  Iteration {iteration + 1}")

                user_message = (
                    user_query if last_tool_result is None
                    else user_query + "\n\nProgress:\n" + "\n".join(tool_call_history) + "\n\nNext step?"
                )

                append_log(f"Iteration {iteration + 1}: calling LLM…")
                try:
                    llm_response = await call_llm(agent_system_prompt, user_message)
                    append_log(f"LLM → {llm_response[:120]}")
                    print(f"LLM → {llm_response}")
                except TimeoutError:
                    append_log("LLM timed out; retrying…")
                    iteration += 1
                    continue
                except Exception as exc:
                    append_log(f"LLM error: {exc}")
                    print(f"LLM error: {exc}")
                    break

                # Extract the first valid directive line
                for line in llm_response.splitlines():
                    line = line.strip()
                    if line.startswith("FUNCTION_CALL:") or line.startswith("FINAL_ANSWER:"):
                        llm_response = line
                        break

                if llm_response.startswith("FUNCTION_CALL:"):
                    _, raw_call = llm_response.split(":", 1)
                    raw_call  = raw_call.strip()
                    tool_name = raw_call.split("|")[0].strip()

                    matched_tool = next((t for t in available_tools if t.name == tool_name), None)
                    if not matched_tool:
                        append_log(f"Unknown tool: {tool_name!r}")
                        tool_call_history.append(f"Error: unknown tool '{tool_name}'")
                        iteration += 1
                        continue

                    append_log(f"→ calling {tool_name}()")
                    update_step_status(steps, tool_name, "running")
                    publish_status(steps, company_data, financial_data)

                    try:
                        arguments  = parse_tool_arguments(raw_call, matched_tool.inputSchema.get("properties", {}))
                        print(f"Calling {tool_name}({arguments})")
                        tool_result = await session.call_tool(tool_name, arguments=arguments)

                        result_text = (
                            " | ".join(
                                item.text if hasattr(item, "text") else str(item)
                                for item in tool_result.content
                            )
                            if hasattr(tool_result, "content") and isinstance(tool_result.content, list)
                            else str(tool_result)
                        )
                        print(f"Result → {result_text[:300]}{'…' if len(result_text) > 300 else ''}")

                        if tool_name == "fetch_company_info":
                            try:
                                company_data = json.loads(result_text)
                            except Exception:
                                pass
                        elif tool_name == "fetch_financial_data":
                            try:
                                financial_data = json.loads(result_text)
                            except Exception:
                                pass

                        short_result = result_text[:120] + ("…" if len(result_text) > 120 else "")
                        append_log(f"✓ {tool_name} done: {short_result[:80]}")
                        update_step_status(steps, tool_name, "done", short_result)
                        publish_status(steps, company_data, financial_data)

                        tool_call_history.append(f"Called {tool_name}({arguments}) → {result_text[:200]}")
                        last_tool_result = result_text

                    except Exception as exc:
                        import traceback; traceback.print_exc()
                        append_log(f"✗ {tool_name} error: {exc}")
                        update_step_status(steps, tool_name, "error", str(exc)[:120])
                        publish_status(steps, company_data, financial_data)
                        tool_call_history.append(f"Error in {tool_name}: {exc}")

                elif llm_response.startswith("FINAL_ANSWER:"):
                    append_log("All steps complete — dashboard ready.")
                    publish_status(steps, company_data, financial_data, completed=True)
                    print("\n" + "=" * 60)
                    print("  Done — dashboard at http://localhost:5000")
                    print("=" * 60)
                    print("\nPress Ctrl+C to stop.\n")
                    try:
                        while True:
                            await asyncio.sleep(1)
                    except asyncio.CancelledError:
                        pass
                    break

                else:
                    print(f"Unexpected LLM response format: {llm_response[:100]}")

                iteration += 1

            if iteration >= MAX_AGENT_ITERATIONS:
                append_log(f"Reached max iterations ({MAX_AGENT_ITERATIONS}).")
                print(f"Reached max iterations ({MAX_AGENT_ITERATIONS}).")


if __name__ == "__main__":
    asyncio.run(run_research_agent())
