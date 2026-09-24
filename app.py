# Used for working with file and folder paths
from pathlib import Path

# Used to print detailed error information
import traceback

# Used to run the FastAPI application
import uvicorn

# FastAPI creates the API; Request accesses incoming HTTP requests
from fastapi import FastAPI, Request

# Used to control HTTP responses and return JSON data
from fastapi.responses import HTMLResponse, JSONResponse

# Serves CSS, JavaScript, and other static files
from fastapi.staticfiles import StaticFiles

# Loads HTML templates from the templates folder
from fastapi.templating import Jinja2Templates

# Validates data received from API requests
from pydantic import BaseModel

# Imports our LangGraph travel workflow
from backend import run_travel_agent, resume_travel_agent

# Gets the absolute path of the project directory
BASE_DIR = Path(__file__).resolve().parent


# Creates the FastAPI application
app = FastAPI(
    title="NaviTrip AI",
    description="Multi-Agent AI Travel Decision and Planning System",
    version="1.0.0"
)


# Makes files inside static/ available to the frontend
app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "static")),
    name="static"
)


# Tells FastAPI where our HTML templates are stored
templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates")
)


# Defines the structure of a travel API request
class TravelRequest(BaseModel):
    message: str
    thread_id: str | None = None
    
# Handles requests to the home page
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={}
    )
    
# Handles travel planning requests from the frontend
@app.post("/api/travel")
async def travel_planner(request_data: TravelRequest):
    try:
        # Get the user's message and remove extra spaces
        user_message = request_data.message.strip()

        # Reject an empty request
        if not user_message:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": "Message cannot be empty."
                }
            )

        # Send the user's request to our LangGraph workflow
        result = run_travel_agent(
            user_input=user_message,
            thread_id=request_data.thread_id
        )

        # Send the complete workflow result back to the frontend
        return JSONResponse(
            content={
                "success": True,

                # Workflow identification
                "thread_id": result["thread_id"],

                # Final/draft answer
                "answer": result["answer"],

                # Guardrail
                "guardrail_allowed": result["guardrail_allowed"],
                "guardrail_reason": result["guardrail_reason"],

                # Supervisor
                "selected_agents": result["selected_agents"],
                "trip_constraints": result["trip_constraints"],
                "supervisor_reasoning": result["supervisor_reasoning"],

                # Specialist results
                "flight_results": result["flight_results"],
                "hotel_results": result["hotel_results"],
                "weather_results": result["weather_results"],
                "budget": result["budget"],
                "budget_results": result["budget_results"],
                "itinerary": result["itinerary"],

                # Human-in-the-loop
                "requires_approval": result["requires_approval"],
                "approval_request": result["approval_request"],
                "approved": result["approved"],
                "human_feedback": result["human_feedback"],

                # Tracking
                "llm_calls": result["llm_calls"],
            }
        )

    except Exception as e:
        # Print the error in the terminal for debugging
        print("ERROR:", e)
        traceback.print_exc()

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )
        
# Handles human approval or revision feedback
@app.post("/api/travel/review")
async def travel_review(request_data: dict):
    try:
        thread_id = request_data.get("thread_id")
        approved = bool(request_data.get("approved", False))
        feedback = str(request_data.get("feedback", "")).strip()

        if not thread_id:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": "thread_id is required."
                }
            )

        # Resume the paused LangGraph workflow
        result = resume_travel_agent(
            thread_id=thread_id,
            approved=approved,
            feedback=feedback
        )

        return JSONResponse(
            content={
                "success": True,
                "thread_id": result["thread_id"],
                "answer": result["answer"],

                # Guardrail
                "guardrail_allowed": result["guardrail_allowed"],
                "guardrail_reason": result["guardrail_reason"],

                # Supervisor
                "selected_agents": result["selected_agents"],
                "trip_constraints": result["trip_constraints"],
                "supervisor_reasoning": result["supervisor_reasoning"],

                # Specialist results
                "flight_results": result["flight_results"],
                "hotel_results": result["hotel_results"],
                "weather_results": result["weather_results"],
                "budget": result["budget"],
                "budget_results": result["budget_results"],
                "itinerary": result["itinerary"],

                # HITL
                "requires_approval": result["requires_approval"],
                "approval_request": result["approval_request"],
                "approved": result["approved"],
                "human_feedback": result["human_feedback"],

                # Tracking
                "llm_calls": result["llm_calls"],
            }
        )

    except Exception as e:
        print("REVIEW ERROR:", e)
        traceback.print_exc()

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )

        
# Checks whether the API is running
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "message": "NaviTrip AI API is running"
    }

# Handles requests for the browser tab icon
@app.get("/favicon.ico")
async def favicon():
    return JSONResponse(content={})


# Starts the FastAPI server when this file is run directly
# Only start the server if we directly run app.py
if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="127.0.0.1",
        port=8000,
        reload=True
    )

'''
Frontend
   ↓
POST /api/travel
   ↓
TravelRequest
   ↓
run_travel_agent()
   ↓
LangGraph
   ↓
Input Guardrail
   ↓
Supervisor
   ↓
Dynamic Specialist Agents
   ├── Flight
   ├── Hotel
   ├── Weather
   ├── Budget
   └── Itinerary
   ↓
Human-in-the-Loop
   ├── Approve
   │     ↓
   │   Final Agent
   │
   └── Request Changes
         ↓
      Supervisor
         ↓
      Relevant Agents
         ↓
      Itinerary
         ↓
       HITL again
   ↓
JSONResponse
   ↓
Frontend
'''