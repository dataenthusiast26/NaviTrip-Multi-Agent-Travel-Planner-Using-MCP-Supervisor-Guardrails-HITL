import os
import sys
from pathlib import Path
import threading
import asyncio

from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient


# ==========================================
# Environment configuration
# ==========================================

load_dotenv()

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
AVIATION_STACK_API_KEY = os.getenv(
    "AVIATIONSTACK_API_KEY"
)
OPENWEATHER_API_KEY = os.getenv(
    "OPENWEATHER_API_KEY"
)
GROQ_API_KEY = os.getenv("GROQ_API_KEY")


# ==========================================
# Project paths
# ==========================================

PROJECT_DIR = Path(__file__).resolve().parent

WEATHER_SERVER_PATH = (
    PROJECT_DIR / "custom_weather_mcp_server.py"
)


# ==========================================
# Environment for local MCP servers
# ==========================================

# Start with the current environment.
AVIATION_ENV = os.environ.copy()
WEATHER_ENV = os.environ.copy()

# Pass the required API keys to the
# corresponding MCP servers.

AVIATION_ENV["AVIATION_STACK_API_KEY"] = ( AVIATION_STACK_API_KEY or "")

WEATHER_ENV["OPENWEATHER_API_KEY"] = ( OPENWEATHER_API_KEY or "")


# ==========================================
# MCP Client
# ==========================================

client = MultiServerMCPClient(
    {
        # ----------------------------------
        # Tavily MCP
        # ----------------------------------

        "tavily": {
            # Tavily MCP is a remote MCP server.
            "transport": "streamable_http",

            "url": (
                "https://mcp.tavily.com/mcp/"
                f"?tavilyApiKey={TAVILY_API_KEY}"
            )
        },


        # ----------------------------------
        # AviationStack MCP
        # ----------------------------------

        "aviationstack": {
            # AviationStack MCP runs locally
            # through STDIO.
            "transport": "stdio",

            # uvx runs the AviationStack MCP
            # package.
            "command": "uvx",

            "args": [
                "aviationstack-mcp"
            ],

            # Pass AviationStack API key
            # to the MCP server.
            "env": AVIATION_ENV
        },


        # ----------------------------------
        # Weather MCP
        # ----------------------------------

        "weather": {
            # Our custom Weather MCP server
            # runs locally.
            "transport": "stdio",

            # Use the same Python environment
            # running this MCP client.
            "command": sys.executable,

            # Start the custom Weather MCP server.
            "args": [
                str(WEATHER_SERVER_PATH)
            ],

            # Pass OpenWeather API key
            # to the MCP server.
            "env": WEATHER_ENV
        }
    }
)

def run_async(coro):
    """
    Run an async MCP operation from synchronous code.

    If an event loop is already running (for example inside FastAPI),
    execute the coroutine in a separate thread with its own event loop.
    Otherwise, run it directly.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result = []
    error = []

    def runner():
        try:
            result.append(asyncio.run(coro))
        except Exception as exc:
            error.append(exc)

    thread = threading.Thread(target=runner)
    thread.start()
    thread.join()

    if error:
        raise error[0]

    return result[0]


# ==========================================
# Discover Tavily MCP tools
# ==========================================

async def get_tavily_tools():
    """
    Discover tools provided by Tavily MCP.
    """

    tools = await client.get_tools( server_name="tavily" )

    print("\nAvailable Tavily MCP tools:")

    for tool in tools:
        print(tool.name)

    return tools


# ==========================================
# Discover AviationStack MCP tools
# ==========================================

async def get_aviation_tools():
    """
    Discover tools provided by AviationStack MCP.
    """

    tools = await client.get_tools( server_name="aviationstack" )

    print("\nAvailable AviationStack MCP tools:")

    for tool in tools:
        print(tool.name)

    return tools


# ==========================================
# Discover Weather MCP tools
# ==========================================

async def get_weather_tools():
    """
    Discover tools provided by Weather MCP.
    """

    tools = await client.get_tools( server_name="weather" )

    print("\nAvailable Weather MCP tools:")

    for tool in tools:
        print(tool.name)

    return tools


# ==========================================
# Discover ALL MCP tools
# ==========================================

async def get_all_tools():
    """
    Discover tools from all configured
    MCP servers.
    """

    all_tools = []


    # ----------------------------------
    # Tavily
    # ----------------------------------

    try:
        tools = await client.get_tools( server_name="tavily")

        all_tools.extend(tools)

        print( "\nAvailable tools from tavily MCP:")

        for tool in tools:
            print(tool.name)

    except Exception as error:
        print( f"\nCould not connect to tavily MCP:\n{error}\n")


    # ----------------------------------
    # AviationStack
    # ----------------------------------

    try:
        tools = await client.get_tools( server_name="aviationstack")

        all_tools.extend(tools)

        print( "\nAvailable tools from  aviationstack MCP:" )

        for tool in tools:
            print(tool.name)

    except Exception as error:
        print(f"\nCould not connect to aviationstack MCP:\n{error}\n")


    # ----------------------------------
    # Weather
    # ----------------------------------

    try:
        tools = await client.get_tools( server_name="weather" )

        all_tools.extend(tools)

        print(
            "\nAvailable tools from "
            "weather MCP:"
        )

        for tool in tools:
            print(tool.name)

    except Exception as error:
        print(
            "\nCould not connect to "
            f"weather MCP:\n{error}\n"
        )

    return all_tools


# ==========================================
# Tavily MCP
# ==========================================

search_tool = None


async def initialize_tavily_tools():
    """
    Discover and store the Tavily search tool.
    """

    global search_tool

    if search_tool is not None:
        return

    tools = await client.get_tools(
        server_name="tavily"
    )

    tools_by_name = {
        tool.name: tool
        for tool in tools
    }

    search_tool = tools_by_name.get(
        "tavily_search"
    )

    if search_tool is None:

        available_tools = ", ".join(
            tools_by_name.keys()
        )

        raise RuntimeError(
            "Tavily MCP connected, but the "
            "'tavily_search' tool was not found. "
            f"Available tools: "
            f"{available_tools or 'none'}"
        )


def tavily_mcp_search(query: str):
    return run_async(
        _tavily_mcp_search(query)
    )


async def _tavily_mcp_search(query: str):
    await initialize_tavily_tools()

    return await search_tool.ainvoke(
        {"query": query}
    )


# ==========================================
# AviationStack MCP
# ==========================================

aviation_tools = {}


async def initialize_aviation_tools():
    """
    Discover and store AviationStack MCP tools.
    """

    global aviation_tools

    if aviation_tools:
        return

    tools = await client.get_tools(
        server_name="aviationstack"
    )

    aviation_tools = {
        tool.name: tool
        for tool in tools
    }

    if not aviation_tools:
        raise RuntimeError(
            "AviationStack MCP connected "
            "but returned no tools."
        )


def aviation_mcp_call(
    tool_name: str,
    tool_args: dict = None
):
    return run_async(
        _aviation_mcp_call(
            tool_name,
            tool_args
        )
    )


async def _aviation_mcp_call(
    tool_name: str,
    tool_args: dict = None
):
    await initialize_aviation_tools()

    tool = aviation_tools.get(tool_name)

    if tool is None:
        available_tools = ", ".join(
            sorted(aviation_tools.keys())
        )

        raise ValueError(
            f"AviationStack tool "
            f"'{tool_name}' was not found. "
            f"Available tools: "
            f"{available_tools or 'none'}"
        )

    return await tool.ainvoke(
        tool_args or {}
    )

# ==========================================
# Weather MCP
# ==========================================

weather_tool = None
forecast_tool = None


async def initialize_weather_tools():
    """
    Discover and store the Weather MCP tools.
    """

    global weather_tool, forecast_tool

    if (
        weather_tool is not None
        and forecast_tool is not None
    ):
        return

    tools = await client.get_tools(
        server_name="weather"
    )

    tools_by_name = {
        tool.name: tool
        for tool in tools
    }

    weather_tool = tools_by_name.get(
        "get_current_weather"
    )

    forecast_tool = tools_by_name.get(
        "get_forecast"
    )

    missing_tools = []

    if weather_tool is None:
        missing_tools.append(
            "get_current_weather"
        )

    if forecast_tool is None:
        missing_tools.append(
            "get_forecast"
        )

    if missing_tools:

        available_tools = ", ".join(
            tools_by_name.keys()
        )

        raise RuntimeError(
            "Missing Weather MCP tools: "
            f"{', '.join(missing_tools)}. "
            f"Available tools: "
            f"{available_tools or 'none'}"
        )


def weather_mcp_search(city: str):
    return run_async(
        _weather_mcp_search(city)
    )


async def _weather_mcp_search(city: str):
    await initialize_weather_tools()

    return await weather_tool.ainvoke(
        {"city": city}
    )


def forecast_mcp_search(city: str):
    return run_async(
        _forecast_mcp_search(city)
    )


async def _forecast_mcp_search(city: str):
    await initialize_weather_tools()

    return await forecast_tool.ainvoke(
        {"city": city}
    )

# ==========================================
# Extract destination
# ==========================================

from langchain_groq import ChatGroq


llm = ChatGroq(
    model="openai/gpt-oss-20b",
    api_key=GROQ_API_KEY,
)


def extract_destination(query: str):
    """
    Extract only the destination city or country
    from the user's travel request.
    """

    prompt = f"""
    Extract only the destination city or country.

    Query:
    {query}

    Return only the destination name.
    """

    response = llm.invoke(prompt)

    return response.content.strip()