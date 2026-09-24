import os

import requests
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP


# ==========================================
# Environment configuration
# ==========================================

load_dotenv()

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")

if not OPENWEATHER_API_KEY:
    raise ValueError("OPENWEATHER_API_KEY is missing.")

# ==========================================
# Create MCP server
# ==========================================

mcp = FastMCP("Weather MCP Server")

# ==========================================
# Current Weather MCP Tool
# ==========================================

@mcp.tool()
def get_current_weather(city: str) -> str:
    """
    Get the current weather for a city.
    """

    url = "https://api.openweathermap.org/data/2.5/weather"

    params = {
        "q": city,
        "appid": OPENWEATHER_API_KEY,
        "units": "metric"
    }

    response = requests.get(url, params=params)

    response.raise_for_status()

    data = response.json()

    temperature = data["main"]["temp"]
    feels_like = data["main"]["feels_like"]
    humidity = data["main"]["humidity"]
    description = data["weather"][0]["description"]

    return (
        f"Weather in {city}:\n"
        f"Temperature: {temperature}°C\n"
        f"Feels like: {feels_like}°C\n"
        f"Humidity: {humidity}%\n"
        f"Condition: {description}"
    )
    
# ==========================================
# Weather Forecast MCP Tool
# ==========================================

@mcp.tool()
def get_forecast(city: str) -> str:
    """
    Get the weather forecast for a city.
    """

    url = "https://api.openweathermap.org/data/2.5/forecast"

    params = {
        "q": city,
        "appid": OPENWEATHER_API_KEY,
        "units": "metric"
    }

    response = requests.get(url, params=params)

    response.raise_for_status()

    data = response.json()

    forecast = []

    for item in data["list"][:5]:
        date_time = item["dt_txt"]
        temperature = item["main"]["temp"]
        description = item["weather"][0]["description"]

        forecast.append(
            f"{date_time}: "
            f"{temperature}°C, "
            f"{description}"
        )

    return "\n".join(forecast)


# ==========================================
# Start MCP server
# ==========================================

if __name__ == "__main__":
    mcp.run(transport="stdio")