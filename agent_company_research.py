"""
Agent that drives company_research_mcp.py through four research steps then
enters an interactive chat loop so the user can ask follow-up questions.

Starts a local Flask server (dashboard_server.py) so the React-based
Prefab web.x64 dashboard can poll live status at http://localhost:5000.
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

client = Cerebras(api_key=os.getenv("CEREBRAS_API_KEY"))

MAX_ITERATIONS = 15

STEPS = [
    {"id": 1, "tool": "fetch_company_info",      "label": "Fetch company overview from Wikipedia", "status": "pending", "result": None},
    {"id": 2, "tool": "search_ticker",            "label": "Resolve company ticker symbol",          "status": "pending", "result": None},
    {"id": 3, "tool": "fetch_financial_data",     "label": "Fetch financial data (yfinance)",        "status": "pending", "result": None},
    {"id": 4, "tool": "crud_notes",               "label": "Save data to local JSON file",            "status": "pending", "result": None},
    {"id": 5, "tool": "render_prefab_dashboard",  "label": "Render Prefab dashboard",                "status": "pending", "result": None},
]


# ── Status helpers ────────────────────────────────────────────────────────────

_log_buffer: list[str] = []


def add_log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    _log_buffer.append(f"[{ts}] {msg}")
    if len(_log_buffer) > 200:
        _log_buffer.pop(0)


def write_status(steps: list, company_data=None, financial_data=None,
                 completed: bool = False, title: str = "Research Dashboard",
                 phase: str = "running", chat_messages: list | None = None) -> None:
    payload = {
        "phase": phase,
        "title": title,
        "steps": steps,
        "company_data": company_data,
        "financial_data": financial_data,
        "completed": completed,
        "chat_messages": chat_messages or [],
        "logs": list(_log_buffer),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(os.path.join(DATA_DIR, "status.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def set_step(steps: list, tool_name: str, status: str, result: str | None = None) -> None:
    for s in steps:
        if s["tool"] == tool_name:
            s["status"] = status
            if result is not None:
                s["result"] = result
            break


# ── Query watcher ────────────────────────────────────────────────────────────

async def wait_for_query() -> str:
    """Write 'waiting' status, then poll until the frontend POSTs a query."""
    query_file = os.path.join(DATA_DIR, "query.json")
    if os.path.exists(query_file):
        os.remove(query_file)
    write_status([], financial_data=None, phase="waiting", title="Ready — enter your query in the dashboard")
    print("Waiting for query at http://localhost:5000 …")
    while True:
        if os.path.exists(query_file):
            with open(query_file, encoding="utf-8") as fh:
                data = json.load(fh)
            os.remove(query_file)
            return data["query"]
        await asyncio.sleep(0.4)


# ── LLM helper ────────────────────────────────────────────────────────────────

async def llm(system_msg: str, user_msg: str, timeout: int = 120,
              max_tokens: int = 200) -> str:
    loop = asyncio.get_event_loop()
    response = await asyncio.wait_for(
        loop.run_in_executor(
            None,
            lambda: client.chat.completions.create(
                model="llama3.1-8b",
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user",   "content": user_msg},
                ],
                max_tokens=max_tokens,
            ),
        ),
        timeout=timeout,
    )
    return response.choices[0].message.content.strip()


# ── Argument parser ───────────────────────────────────────────────────────────

def parse_arguments(function_info: str, schema_properties: dict) -> dict:
    n_props = len(schema_properties)
    raw_parts = function_info.split("|", n_props)
    param_values = [p.strip() for p in raw_parts[1:]]

    arguments: dict = {}
    for idx, (param_name, param_info) in enumerate(schema_properties.items()):
        if idx >= len(param_values):
            break
        value = param_values[idx]
        if value == "":
            continue
        param_type = param_info.get("type", "string")
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


# ── Main loop ─────────────────────────────────────────────────────────────────

async def main() -> None:
    import copy
    steps = copy.deepcopy(STEPS)
    company_data = None
    financial_data = None

    # Start Prefab dashboard server and open browser
    add_log("Starting Prefab dashboard server on port 5000")
    dashboard_server.start(port=5000)
    time.sleep(0.8)
    webbrowser.open("http://localhost:5000")
    add_log("Browser opened → http://localhost:5000")
    print("Dashboard: http://localhost:5000")

    # Wait for the user to type a query in the browser
    user_query = await wait_for_query()
    add_log(f"Query received: {user_query}")
    print(f"\nQuery received: {user_query}\n")

    print("=" * 60)
    print("  Company Research Agent  (Prefab MCP Demo)")
    print("=" * 60)

    server_params = StdioServerParameters(
        command="python",
        args=["company_research_mcp.py"],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools_result = await session.list_tools()
            tools = tools_result.tools
            print(f"Tools: {[t.name for t in tools]}\n")

            tools_description = []
            for i, tool in enumerate(tools, 1):
                params = tool.inputSchema
                desc = getattr(tool, "description", "")
                name = getattr(tool, "name", f"tool_{i}")
                if "properties" in params:
                    param_str = ", ".join(f"{k}: {v.get('type','?')}" for k, v in params["properties"].items())
                else:
                    param_str = "no parameters"
                tools_description.append(f"{i}. {name}({param_str}) - {desc}")

            tools_block = "\n".join(tools_description)
            safe_filename = user_query.lower().replace(" ", "_")[:30].strip("_") + ".json"

            system_prompt = f"""You are a company research agent.
The user's query is: "{user_query}"

Complete ALL FIVE steps in order:

STEP 1 – Identify the main company/entity in the query and call:
   FUNCTION_CALL: fetch_company_info|<company name>

STEP 2 – Find the stock ticker for the company:
   FUNCTION_CALL: search_ticker|<company name>

STEP 3 – Fetch financial data using the ticker from Step 2:
   FUNCTION_CALL: fetch_financial_data|<ticker symbol from step 2>

STEP 4 – Save the Wikipedia result from Step 1 to a file:
   FUNCTION_CALL: crud_notes|create|{safe_filename}|<full JSON from step 1 on a single line>

STEP 5 – Render the dashboard:
   FUNCTION_CALL: render_prefab_dashboard|{user_query[:60]}|{safe_filename}|web.x64

Then give: FINAL_ANSWER: [done]

Available tools:
{tools_block}

Respond with EXACTLY ONE line: FUNCTION_CALL: ... or FINAL_ANSWER: [done]
No explanations."""

            add_log(f"MCP server ready — tools: {[t.name for t in tools]}")
            write_status(steps, title=user_query)

            iteration         = 0
            last_response     = None
            iteration_history = []
            current_query     = user_query

            while iteration < MAX_ITERATIONS:
                print(f"\n{'─'*50}  Iteration {iteration + 1}")

                user_msg = (
                    current_query if last_response is None
                    else user_query + "\n\nProgress:\n" + "\n".join(iteration_history) + "\n\nNext step?"
                )

                add_log(f"Iteration {iteration + 1}: calling LLM…")
                try:
                    response_text = await llm(system_prompt, user_msg)
                    add_log(f"LLM → {response_text[:120]}")
                    print(f"LLM → {response_text}")
                except TimeoutError:
                    add_log("LLM timed out; retrying…")
                    print("LLM timed out; retrying…")
                    iteration += 1
                    continue
                except Exception as exc:
                    add_log(f"LLM error: {exc}")
                    print(f"LLM error: {exc}")
                    break

                for line in response_text.splitlines():
                    line = line.strip()
                    if line.startswith("FUNCTION_CALL:") or line.startswith("FINAL_ANSWER:"):
                        response_text = line
                        break

                if response_text.startswith("FUNCTION_CALL:"):
                    _, function_info = response_text.split(":", 1)
                    function_info = function_info.strip()
                    func_name = function_info.split("|")[0].strip()

                    tool = next((t for t in tools if t.name == func_name), None)
                    if not tool:
                        print(f"Unknown tool: {func_name!r}")
                        iteration_history.append(f"Error: unknown tool '{func_name}'")
                        iteration += 1
                        continue

                    # Mark step as running and push to dashboard
                    add_log(f"→ calling {func_name}()")
                    set_step(steps, func_name, "running")
                    write_status(steps, company_data, financial_data)

                    schema_properties = tool.inputSchema.get("properties", {})
                    try:
                        arguments = parse_arguments(function_info, schema_properties)
                        print(f"Calling {func_name}({arguments})")
                        result = await session.call_tool(func_name, arguments=arguments)

                        result_str = (
                            " | ".join(item.text if hasattr(item, "text") else str(item) for item in result.content)
                            if hasattr(result, "content") and isinstance(result.content, list)
                            else str(result)
                        )
                        print(f"Result → {result_str[:300]}{'…' if len(result_str) > 300 else ''}")

                        # Extract typed data from tool results
                        if func_name == "fetch_company_info":
                            try:
                                company_data = json.loads(result_str)
                            except Exception:
                                pass
                        elif func_name == "fetch_financial_data":
                            try:
                                financial_data = json.loads(result_str)
                            except Exception:
                                pass

                        short_result = result_str[:120] + ("…" if len(result_str) > 120 else "")
                        add_log(f"✓ {func_name} done: {short_result[:80]}")
                        set_step(steps, func_name, "done", short_result)
                        write_status(steps, company_data, financial_data)

                        iteration_history.append(f"Called {func_name}({arguments}) → {result_str[:200]}")
                        last_response = result_str

                    except Exception as exc:
                        import traceback; traceback.print_exc()
                        add_log(f"✗ {func_name} error: {exc}")
                        set_step(steps, func_name, "error", str(exc)[:120])
                        write_status(steps, company_data, financial_data)
                        iteration_history.append(f"Error in {func_name}: {exc}")

                elif response_text.startswith("FINAL_ANSWER:"):
                    add_log("All steps complete — entering chat mode.")
                    chat_messages: list[dict] = []
                    write_status(steps, company_data, financial_data,
                                 completed=True, phase="chat",
                                 chat_messages=chat_messages)
                    print("\n" + "=" * 60)
                    print("  Research done — chat mode active at http://localhost:5000")
                    print("=" * 60)

                    fin_summary = ""
                    if financial_data and not financial_data.get("error"):
                        fin_summary = (
                            f"ticker={financial_data.get('ticker')}, "
                            f"market_cap={financial_data.get('market_cap')}, "
                            f"pe={financial_data.get('pe_ratio')}, "
                            f"eps={financial_data.get('eps')}, "
                            f"margin={financial_data.get('profit_margin')}, "
                            f"sector={financial_data.get('sector')}, "
                            f"revenue_trend={financial_data.get('revenue_trend')}"
                        )
                    wiki_summary = company_data.get("extract", "")[:200] if company_data else ""

                    chat_system = f"""You are a financial research assistant. Answer questions about the researched company.

Company: {company_data.get('title', '') if company_data else user_query}
Overview: {wiki_summary}
Financials: {fin_summary or 'N/A'}

Rules:
- Answer from the data above when possible: CHAT_RESPONSE: <answer>
- If user asks about a DIFFERENT company or missing metric, fetch it: FUNCTION_CALL: fetch_financial_data|<ticker>
- Keep answers to 2-3 sentences.
- Respond with ONE line only: CHAT_RESPONSE: ... or FUNCTION_CALL: ..."""

                    chat_input_file = os.path.join(DATA_DIR, "chat_input.json")

                    while True:
                        await asyncio.sleep(0.4)
                        if not os.path.exists(chat_input_file):
                            continue
                        try:
                            with open(chat_input_file, encoding="utf-8") as fh:
                                chat_payload = json.load(fh)
                            os.remove(chat_input_file)
                        except Exception:
                            continue

                        user_chat_msg = chat_payload.get("message", "").strip()
                        if not user_chat_msg:
                            continue

                        add_log(f"Chat: {user_chat_msg}")
                        chat_messages.append({"role": "user", "content": user_chat_msg,
                                              "ts": time.strftime("%H:%M:%S")})
                        write_status(steps, company_data, financial_data,
                                     completed=True, phase="chat",
                                     chat_messages=chat_messages)

                        # LLM decides: answer or call a tool
                        history_str = "\n".join(
                            f"{m['role'].upper()}: {m['content']}"
                            for m in chat_messages[-6:]  # last 3 turns
                        )
                        try:
                            chat_response = await llm(chat_system, history_str,
                                                      timeout=60, max_tokens=400)
                        except Exception as exc:
                            chat_response = f"CHAT_RESPONSE: Sorry, I encountered an error: {exc}"

                        add_log(f"Chat LLM → {chat_response[:100]}")

                        # Handle tool call inside chat
                        if chat_response.startswith("FUNCTION_CALL:"):
                            _, fn_info = chat_response.split(":", 1)
                            fn_info = fn_info.strip()
                            fn_name = fn_info.split("|")[0].strip()
                            tool = next((t for t in tools if t.name == fn_name), None)
                            if tool:
                                add_log(f"→ chat tool call: {fn_name}()")
                                try:
                                    args = parse_arguments(fn_info, tool.inputSchema.get("properties", {}))
                                    result = await session.call_tool(fn_name, arguments=args)
                                    result_str = (
                                        " | ".join(item.text if hasattr(item, "text") else str(item)
                                                   for item in result.content)
                                        if hasattr(result, "content") and isinstance(result.content, list)
                                        else str(result)
                                    )
                                    if fn_name == "fetch_financial_data":
                                        try:
                                            financial_data = json.loads(result_str)
                                        except Exception:
                                            pass
                                    add_log(f"✓ chat tool {fn_name} done")
                                    # Summarise the tool result as agent reply
                                    summary = await llm(
                                        "Summarise this financial data in 2-3 sentences for a non-expert.",
                                        result_str[:600], timeout=60, max_tokens=300,
                                    )
                                    agent_reply = summary
                                except Exception as exc:
                                    agent_reply = f"Tool call failed: {exc}"
                            else:
                                agent_reply = f"I don't have a tool called '{fn_name}'."
                        elif chat_response.startswith("CHAT_RESPONSE:"):
                            agent_reply = chat_response[len("CHAT_RESPONSE:"):].strip()
                        else:
                            agent_reply = chat_response  # pass through

                        chat_messages.append({"role": "agent", "content": agent_reply,
                                              "ts": time.strftime("%H:%M:%S")})
                        add_log(f"Agent replied: {agent_reply[:80]}")
                        write_status(steps, company_data, financial_data,
                                     completed=True, phase="chat",
                                     chat_messages=chat_messages)
                    break

                else:
                    print(f"Unexpected format: {response_text[:100]}")

                iteration += 1

            if iteration >= MAX_ITERATIONS:
                add_log(f"Reached max iterations ({MAX_ITERATIONS}).")
                print(f"Reached max iterations ({MAX_ITERATIONS}).")


if __name__ == "__main__":
    asyncio.run(main())
