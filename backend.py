import os
import asyncio
from dotenv import load_dotenv

load_dotenv()

from typing import Any, TypedDict, Annotated
import operator
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command , interrupt
from langchain_core.messages import (
    AnyMessage,
    HumanMessage,
    AIMessage,
    SystemMessage
)
import json

import uuid
import psycopg
from psycopg.rows import dict_row
from langgraph.checkpoint.postgres import PostgresSaver



# ==========================================
# MCP Tools
# ==========================================

from mcp_client import (
    tavily_mcp_search,
    aviation_mcp_call,
    weather_mcp_search,
    forecast_mcp_search,
    extract_destination,
)

# ============================================================
# DATABASE
# ============================================================

def get_database_url():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise ValueError(
            "DATABASE_URL is missing. "
            "Please add your Render PostgreSQL External Database URL to .env"
        )

    if "sslmode=" not in database_url:
        separator = "&" if "?" in database_url else "?"
        database_url = f"{database_url}{separator}sslmode=require"

    return database_url

# ============================================================
# LLM
# ============================================================


from langchain_groq import ChatGroq

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY is missing.")


llm = ChatGroq(
    model="openai/gpt-oss-20b",
    api_key=GROQ_API_KEY,
    max_tokens=2200,
)

# ============================================================
# TRAVEL STATE
# ============================================================

class TravelState(TypedDict, total=False):

    messages: Annotated[ list[AnyMessage], operator.add ]

    user_query: str

    # -------------------------
    # Guardrail
    # -------------------------

    guardrail_allowed: bool
    guardrail_reason: str

    # -------------------------
    # Supervisor
    # -------------------------

    selected_agents: list[str] # whatever agent will be used will be saved here
    trip_constraints: dict[str, Any]
    supervisor_reasoning: str

    # -------------------------
    # Specialist results
    # -------------------------

    flight_results: str
    hotel_results: str
    weather_results: str
    itinerary: str
    budget_results: str

    # -------------------------
    # HITL
    # -------------------------

    approval_request: str
    approved: bool
    human_feedback: str

    # -------------------------
    # Final
    # -------------------------

    final_response: str

    # -------------------------
    # Tracking
    # -------------------------

    llm_calls: int


# ============================================================
# AGENTS
# ============================================================

KNOWN_AGENTS = {
    "flight_agent",
    "hotel_agent",
    "weather_agent",
    "budget_agent",
    "itinerary_agent",
}


AGENT_ORDER = [
    "flight_agent",
    "hotel_agent",
    "weather_agent",
    "budget_agent",
    "itinerary_agent",
]


# ============================================================
# SHARED HELPERS
# ============================================================

def _llm_text( system_prompt: str, user_prompt: str) -> str:
    response = llm.invoke(
        [
            SystemMessage( content=system_prompt ),
            HumanMessage( content=user_prompt ),
        ]
    )
    return str(response.content)


def _json_from_llm( text: str) -> dict[str, Any]:
    """
    Extract the first complete JSON object
    returned by the model.
    """
    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end < start:
        raise ValueError("The model did not return a JSON object." )

    return json.loads( text[start:end + 1])


def _empty_constraints():
    return {
        "destination": "",
        "origin": "",
        "duration": "",
        "budget": "",
        "travel_style": "",
        "special_preferences": [],
    }


def _selected_agents( state: TravelState ) -> list[str]:
    selected = state.get( "selected_agents", [])

    return [
        agent
        for agent in AGENT_ORDER
        if agent in selected
    ]

# ============================================================
# INPUT GUARDRAIL
# ============================================================

def input_guardrail( state: TravelState ):

    print("\nINSIDE INPUT GUARDRAIL\n")

    query = state["user_query"]

    guardrail_prompt = f"""
Determine whether the following request belongs
to travel planning or travel information.

Valid requests can include:

- destinations
- flights
- hotels
- weather
- budgets
- visas
- transportation
- sightseeing
- food
- packing
- itineraries
- travel recommendations

Block clearly unrelated requests.

Block requests asking for harmful or illegal instructions.

Do not block a valid travel request merely because
some details are missing.

Return strict JSON only:

{{
    "allowed": true,
    "reason": ""
}}

User request:

{query}
"""

    llm_calls = state.get(
        "llm_calls",
        0,
    )

    try:

        guardrail_raw = _llm_text(
            (
                "You are the input guardrail for a "
                "travel-planning application. "
                "Return strict JSON only."
            ),
            guardrail_prompt,
        )

        guardrail_result = _json_from_llm( guardrail_raw)

        allowed = bool( guardrail_result.get( "allowed", True) )

        reason = str(guardrail_result.get("reason","",)).strip()

        llm_calls += 1

    except Exception as exc:

        print( f"Guardrail fallback used: {exc}",flush=True )

        # Preserve the reference behavior:
        # fail open on temporary model/parser errors.
        allowed = True

        reason = ("Guardrail validation fallback allowed the request.")

    print(f"GUARDRAIL: {'PASS' if allowed else 'BLOCK'}", flush=True )

    return {
        "guardrail_allowed": allowed,
        "guardrail_reason": reason,
        "llm_calls": llm_calls,
        "messages": [
            AIMessage(
                content=(f"Input Guardrail: {'PASS' if allowed else 'BLOCK'}"
                )
            )
        ],
    }


# ============================================================
# GUARDRAIL ROUTER
# ============================================================

def route_after_guardrail( state: TravelState ):

    if state.get("guardrail_allowed", False,):
        return "supervisor"

    return "guardrail_blocked"


# ============================================================
# GUARDRAIL BLOCKED
# ============================================================

def guardrail_blocked_agent( state: TravelState ):

    reason = (
        state.get("guardrail_reason")
        or
        "This request was blocked by the "
        "travel input guardrail."
    )

    return {
        "final_response": reason,
        "messages": [
            AIMessage( content=reason)
        ],
    }


# ============================================================
# SUPERVISOR AGENT
# ============================================================

def supervisor_agent( state: TravelState ):

    print("\nINSIDE SUPERVISOR AGENT\n")

    query = state["user_query"]

    llm_calls = state.get(
        "llm_calls",
        0,
    )

    human_feedback = state.get( "human_feedback", "", )

    feedback_section = ""

    if human_feedback:
        feedback_section = f"""

IMPORTANT:

A human reviewed the previous itinerary
and requested changes.

Human feedback:

{human_feedback}

Use this feedback to decide which specialist
agents need to run again.

Do NOT automatically run every agent.
Only select agents relevant to the requested changes.
"""

    supervisor_prompt = f"""
You are the Supervisor Agent of a
multi-agent travel-planning system.

Your job is to decide which specialist agents
are required for the user's request.

Available agents:

- flight_agent:
  flights, airports, airlines, routes,
  airfare, booking guidance

- hotel_agent:
  hotels, accommodation, neighborhoods,
  places to stay

- weather_agent:
  weather, climate, season, forecast,
  packing advice

- budget_agent:
  cost, affordability, price limits,
  budget feasibility

- itinerary_agent:
  creates the integrated travel plan

IMPORTANT:

- Select ONLY the agents actually needed.
- Do not select every agent automatically.
- Preserve the logical execution order.
- itinerary_agent must always be included
  for a complete travel-planning request.
- final_agent is NOT part of selected_agents.
- If human feedback requires changes,
  select only the relevant specialist agents
  before itinerary_agent runs again.

Return strict JSON only:

{{
    "selected_agents": [
        "flight_agent",
        "hotel_agent",
        "weather_agent",
        "budget_agent",
        "itinerary_agent"
    ],
    "trip_constraints": {{
        "destination": "",
        "origin": "",
        "duration": "",
        "budget": "",
        "travel_style": "",
        "special_preferences": []
    }},
    "reasoning": ""
}}

User request:

{query}

{feedback_section}
"""

    try:

        supervisor_raw = _llm_text(
            (
                "You route work to travel specialist "
                "agents. Return strict JSON only."
            ),
            supervisor_prompt,
        )

        parsed = _json_from_llm( supervisor_raw )

        requested_agents = parsed.get( "selected_agents", [] )

        selected_agents = [
            name
            for name in AGENT_ORDER
            if name in requested_agents
            and name in KNOWN_AGENTS
        ]

        # Itinerary is always required for the
        # integrated travel plan.
        if "itinerary_agent" not in selected_agents:

            selected_agents.append( "itinerary_agent" )

        constraints = _empty_constraints()

        parsed_constraints = parsed.get( "trip_constraints",{}, )

        if isinstance( parsed_constraints, dict,):

            constraints.update( parsed_constraints)

        reasoning = str( parsed.get( "reasoning", "", )).strip()

        llm_calls += 1

    except Exception as exc:

        print( f"Supervisor fallback used: {exc}",flush=True, )

        selected_agents = ( AGENT_ORDER.copy() )

        constraints = ( _empty_constraints() )

        reasoning = (
            "Supervisor parsing failed, so the "
            "original full travel workflow was "
            "selected as a safe fallback."
        )

    print( "SELECTED AGENTS:", selected_agents, flush=True )

    print( "TRIP CONSTRAINTS:", constraints, flush=True )

    print( "SUPERVISOR REASONING:", reasoning,flush=True )

    return {
        "selected_agents": selected_agents,
        "trip_constraints": constraints,
        "supervisor_reasoning": reasoning,
        "llm_calls": llm_calls,
        "messages": [
            AIMessage(content=("Supervisor created the agent plan." ))
        ],
    }


# ============================================================
# SUPERVISOR ROUTING
# ============================================================

ROUTE_MAP = {
    "guardrail_blocked": "guardrail_blocked",
    "flight_agent": "flight_agent",
    "hotel_agent": "hotel_agent",
    "weather_agent": "weather_agent",
    "budget_agent": "budget_agent",
    "itinerary_agent": "itinerary_agent",
    "human_approval": "human_approval",
    "final_agent": "final_agent",
}


def route_from_supervisor( state: TravelState):

    selected = _selected_agents( state )

    if not selected:
        return "itinerary_agent"

    return selected[0]


# ============================================================
# ROUTE AFTER SPECIALIST
# ============================================================

def route_after_agent( current_agent: str):

    def route( state: TravelState,) -> str:

        selected = _selected_agents( state )

        current_index = (AGENT_ORDER.index( current_agent ) )

        for next_agent in AGENT_ORDER[ current_index + 1: ]:

            if next_agent in selected:

                return next_agent

        # After all selected specialists,
        # go to itinerary if it has not run yet.
        if ( "itinerary_agent" in selected and current_agent != "itinerary_agent" ):
            return "itinerary_agent"

        return "human_approval"

    return route



# =========================
# Flight Agent Prompt
# =========================

FLIGHT_AGENT_PROMPT = """
You are a travel flight expert.

User Query:
{query}

Airport Information:
{airport_data}

Airline Information:
{airline_data}

Generate:

1. Likely departure airport
2. Likely arrival airport
3. Airlines serving this route
4. Typical flight duration
5. Estimated airfare range
6. Peak season pricing warning
7. Booking advice

Return concise travel guidance.
"""


# =========================
# Flight Agent
# =========================


def flight_agent(state: TravelState):

    print("\nINSIDE FLIGHT AGENT\n")

    query = state["user_query"]

    try:

        # aviation_mcp_call() already handles
        # async execution through mcp_client.run_async().
        # Do NOT wrap it with asyncio.run() here.

        airports = aviation_mcp_call("list_airports" )

        airlines = aviation_mcp_call("list_airlines" )

        print( "\nAIRPORTS:", airports)

        print( "\nAIRLINES:",airlines)

        prompt = FLIGHT_AGENT_PROMPT.format(
            query=query,
            airport_data=str(airports)[:3000],
            airline_data=str(airlines)[:3000]
        )

        response = llm.invoke([
            SystemMessage( content= "You are an expert travel flight planner."),
            HumanMessage(content=prompt)
        ])

        flight_data = response.content

    except Exception as e:
        print( f"FLIGHT AGENT ERROR: {type(e).__name__}: {e}", flush=True)

        flight_data = ( f"Flight information unavailable: {str(e)}")

    return {
        "flight_results":flight_data,
        "messages": [AIMessage(content= "Flight recommendations generated") ],
        "llm_calls": state.get("llm_calls", 0) + 1
    }
# =========================
# Hotel Agent
# =========================

def hotel_agent(state: TravelState):
    """
    Search for hotels using Tavily MCP.
    """

    query =  f"Best hotels for {state['user_query']}"

    try:
        hotel_results = asyncio.run( tavily_mcp_search(query))
        

    except Exception as exc:

        print( f"HOTEL AGENT MCP ERROR:  {type(exc).__name__}: {exc}", flush=True )

        hotel_results = (
            "Live hotel search is temporarily unavailable. "
            "Provide general accommodation and neighborhood "
            "guidance based on the destination and clearly "
            "label it as non-live advice."
        )

    return {
        "hotel_results": hotel_results,
        "messages": [
            AIMessage(
                content="Hotel information fetched."
            )
        ]
    }


# =========================
# Weather Agent
# =========================

def weather_agent(state: TravelState):
    """
    Get current weather and forecast for the
    destination using the Weather MCP server.
    """
    city = extract_destination( state["user_query"] )

    try:
        # Current weather
        weather_data = asyncio.run( weather_mcp_search(city))
        
        # Forecast
        forecast_data = asyncio.run( forecast_mcp_search(city) )
        

        weather_results = f"""
Current Weather:
{weather_data}

Forecast:
{forecast_data}
"""

    except Exception as exc:

        print(
            f"WEATHER AGENT MCP ERROR: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

        weather_results = (
            f"Live weather information for {city} is temporarily unavailable. "
            "Please verify the weather forecast before departure."
        )

    return {
        "weather_results": weather_results,
        "messages": [
            AIMessage(
                content="Weather information fetched."
            )
        ],
    }


# =========================
# Budget Agent
# =========================

def budget_agent(state: TravelState):
    """
    Creates a simple budget estimate from the
    available travel information.
    """

    prompt = f"""
Analyze whether this trip is realistic for the user's budget.

User Query:
{state['user_query']}

Trip Constraints:
{state.get('trip_constraints', {})}

Flight Results:
{state.get('flight_results', '')}

Hotel Results:
{state.get('hotel_results', '')}

Weather Results:
{state.get('weather_results', '')}

Return:
1. Estimated cost categories
2. Budget risk areas
3. Money-saving suggestions
4. Overall feasibility

If exact live prices are unavailable, clearly label estimates as approximate.
"""

    response = llm.invoke([
        SystemMessage( content="You are a practical travel budget estimator." ),
        HumanMessage(content=prompt)
    ])

    return {
        "budget_results": response.content,
        "messages": [
            AIMessage(content="Travel budget estimated.")
        ],
        "llm_calls": state.get("llm_calls", 0) + 1
    }
    
    
# =========================
# Itinerary Agent
# =========================
# we use the results already stored in state.

def itinerary_agent(state: TravelState):
    prompt = f"""
Create a complete travel itinerary.

User Query:
{state['user_query']}

Trip Constraints:
{state.get('trip_constraints', {})}

Flight Results:
{state.get('flight_results', '')}

Hotel Results:
{state.get('hotel_results', '')}

Weather Results:
{state.get('weather_results', '')}

Budget Results:
{state.get('budget_results', '')}

Make the itinerary practical, budget-aware, and easy to follow.
Create a clear draft that is ready for human review.
"""

    response = llm.invoke(
        [
            SystemMessage(content="You are an expert travel planner."),
            HumanMessage(content=prompt),
        ]
    )

    approval_request = (
        "Please review the generated draft itinerary. Approve it to create the "
        "final polished plan, or provide feedback for revision."
    )

    return {
        "itinerary": response.content,
        "approval_request": approval_request,
        "messages": [AIMessage(content="Draft itinerary created for human review.")],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }
    
        
#############################

'''
Flight Agent ──→ flight_results ──┐
                                  │
Hotel Agent ───→ hotel_results ───┤
                                  │
Weather Agent → weather_results ──┼──→ Itinerary Agent
                                  │
User ──────────→ user_query ──────┘

'''

# ============================================================
# HUMAN-IN-THE-LOOP
# ============================================================

def human_approval_agent( state: TravelState ):

    print(
        "\nINSIDE HUMAN-IN-THE-LOOP\n"
    )

    review = interrupt(
        {
            "question":"Do you approve this itinerary?",
            "draft_itinerary": state.get("itinerary", ""),
            "approval_request": state.get( "approval_request", ""),
            "selected_agents": state.get( "selected_agents", []),
            "supervisor_reasoning": state.get( "supervisor_reasoning", "" ),
            "expected_response": {
                "approved": True,
                "feedback": (
                    "Optional revision feedback"
                ),
            },
        }
    )

    approved = bool( review.get( "approved", False,))

    human_feedback = str(review.get( "feedback", "", )).strip()

    print( "HUMAN APPROVED:", approved, flush=True )

    print( "HUMAN FEEDBACK:", human_feedback, flush=True )

    return {
        "approved": approved,
        "human_feedback": human_feedback,
        "messages": [
            AIMessage(
                content=( "Human approval step completed.")
            )
        ],
    }


# ============================================================
# HITL ROUTER
# ============================================================

def route_after_human_approval( state: TravelState ):

    if state.get( "approved", False ):

        print( "HITL → FINAL AGENT", flush=True,)

        return "final_agent"

    print( "HITL → SUPERVISOR", flush=True)

    return "supervisor"


def final_agent(state: TravelState):
    if state.get("approved", False):
        review_instruction = (
            "The user approved the draft. Preserve its decisions while polishing it."
        )
    else:
        review_instruction = f"""
The user requested a revision. Apply this feedback carefully:
{state.get('human_feedback', '') or 'Improve the draft before finalizing it.'}
"""

    final_prompt = f"""
Generate the final travel response for the user.

Human Review:
{review_instruction}

User Request:
{state['user_query']}

Supervisor Constraints:
{state.get('trip_constraints', {})}

Flights:
{state.get('flight_results', '')}

Hotels:
{state.get('hotel_results', '')}

Weather:
{state.get('weather_results', '')}

Budget Analysis:
{state.get('budget_results', '')}

Draft Itinerary:
{state.get('itinerary', '')}

Format the final answer beautifully using these sections:
1. Trip Summary
2. Flight Information
3. Hotel Suggestions
4. Weather Information
5. Day-by-Day Itinerary
6. Estimated Budget
7. Final Recommendations

Important:
- Be clear and practical.
- Mention that live flight APIs may not provide ticket prices when pricing is unavailable.
- Include weather-based travel advice.
- Keep the response useful for real travel planning.
- Incorporate the human feedback when revision was requested.
"""

    response = llm.invoke(
        [
            SystemMessage( content="You are a professional AI travel booking assistant."),
            HumanMessage(content=final_prompt),
        ]
    )

    return {
        "final_response": response.content,
        "messages": [response],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }



# =========================
# Build Graph
# =========================

# This graph implements the Part 3 architecture:
# Input Guardrail → Supervisor → Dynamic Specialist Agents
# → Itinerary → Human Review → Final Response

graph = StateGraph(TravelState)

# -------------------------
# Guardrail + Supervisor
# -------------------------
graph.add_node("input_guardrail", input_guardrail)
graph.add_node("guardrail_blocked", guardrail_blocked_agent)
graph.add_node("supervisor", supervisor_agent)

# -------------------------
# Specialist Agents
# -------------------------
graph.add_node("flight_agent", flight_agent)
graph.add_node("hotel_agent", hotel_agent)
graph.add_node("weather_agent", weather_agent)
graph.add_node("budget_agent", budget_agent)
graph.add_node("itinerary_agent", itinerary_agent)

# -------------------------
# Human-in-the-Loop
# -------------------------
graph.add_node("human_approval", human_approval_agent)

# -------------------------
# Final Response
# -------------------------
graph.add_node("final_agent", final_agent)


# ============================================================
# START → INPUT GUARDRAIL
# ============================================================

graph.add_edge(  START, "input_guardrail")

# ============================================================
# INPUT GUARDRAIL → SUPERVISOR / BLOCK
# ============================================================

graph.add_conditional_edges(
    "input_guardrail",
    route_after_guardrail,
    {
        "supervisor": "supervisor",
        "guardrail_blocked": "guardrail_blocked"
    }
)


# ============================================================
# BLOCKED → END
# ============================================================

graph.add_edge( "guardrail_blocked", END)

# ============================================================
# SUPERVISOR → DYNAMIC AGENT
# ============================================================

graph.add_conditional_edges(
    "supervisor",
    route_from_supervisor,
    ROUTE_MAP
)


# ============================================================
# SPECIALIST AGENTS → NEXT SELECTED AGENT
# ============================================================

graph.add_conditional_edges(
    "flight_agent",
    route_after_agent("flight_agent"),
    ROUTE_MAP
)

graph.add_conditional_edges(
    "hotel_agent",
    route_after_agent("hotel_agent"),
    ROUTE_MAP
)
graph.add_conditional_edges(
    "weather_agent",
    route_after_agent("weather_agent"),
    ROUTE_MAP
)
graph.add_conditional_edges(
    "budget_agent",
    route_after_agent("budget_agent"),
    ROUTE_MAP
)


# ============================================================
# ITINERARY → HUMAN REVIEW
# ============================================================

graph.add_edge( "itinerary_agent", "human_approval")

# ============================================================
# HUMAN REVIEW → FINAL / SUPERVISOR
# ============================================================

graph.add_conditional_edges(
    "human_approval",
    route_after_human_approval,
    {
        "final_agent": "final_agent",
        "supervisor": "supervisor"
    }
)

# ============================================================
# FINAL → END
# ============================================================

graph.add_edge( "final_agent", END)


# =========================
# PostgreSQL Checkpointer
# =========================

DATABASE_URL = get_database_url()

_conn = psycopg.connect( DATABASE_URL, autocommit=True, row_factory=dict_row)

# Creates the LangGraph component responsible
# for saving graph state to PostgreSQL.
checkpointer = PostgresSaver( _conn)

# Sets up the tables/schema that LangGraph needs.
checkpointer.setup()

travel_graph = graph.compile( checkpointer=checkpointer)


# ============================================================
# Interrupt / Result Helpers
# ============================================================

def _interrupt_payload(result: dict[str, Any]) -> dict[str, Any] | None:
    """Return the LangGraph interrupt payload if the graph paused."""

    interrupts = result.get("__interrupt__", [])

    if not interrupts:
        return None

    first_interrupt = interrupts[0]

    payload = getattr(first_interrupt, "value", first_interrupt)

    if isinstance(payload, dict):
        return payload

    return {"value": payload}


def _content_to_text(content: Any) -> str:
    """Convert normal or structured LangChain content into plain text."""

    if isinstance(content, list):
        return "".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict)
            and item.get("type") == "text"
        )

    return str(content)


def _serialize_result(result: dict[str, Any],thread_id: str) -> dict[str, Any]:

    messages = result.get( "messages", [])

    last_message = (
        _content_to_text(messages[-1].content)
        if messages
        else ""
    )

    answer = (result.get("final_response")or last_message)

    interrupt_payload = _interrupt_payload(result)

    # When the graph pauses for HITL, the draft itinerary
    # is what the frontend should display for review.
    if interrupt_payload:
        answer = (
            interrupt_payload.get("draft_itinerary")
            or result.get("itinerary", "")
        )

    return {
        "thread_id": thread_id,
        "answer": answer,

        "requires_approval": (
            interrupt_payload is not None
        ),

        "approval_request": (
            interrupt_payload.get(
                "approval_request",
                ""
            )
            if interrupt_payload
            else result.get(
                "approval_request",
                ""
            )
        ),

        "flight_results": result.get( "flight_results", "" ),

        "hotel_results": result.get( "hotel_results", "" ),

        "weather_results": result.get( "weather_results", "" ),

        # Frontend expects "budget".
        # Internally the TravelState uses "budget_results".
        "budget": result.get( "budget_results", "" ),

        # Keep the internal name available as well.
        "budget_results": result.get( "budget_results", "" ),

        "itinerary": (
            interrupt_payload.get( "draft_itinerary", "")
            if interrupt_payload
            else result.get( "itinerary", "" )
        ),

        "selected_agents": result.get( "selected_agents", [] ),

        "trip_constraints": result.get( "trip_constraints", {} ),

        "supervisor_reasoning": result.get( "supervisor_reasoning", "" ),

        "guardrail_allowed": result.get( "guardrail_allowed", True ),

        "guardrail_reason": result.get( "guardrail_reason", "" ),

        "approved": result.get( "approved" ),

        "human_feedback": result.get( "human_feedback", "" ),

        "llm_calls": result.get( "llm_calls", 0 )
    }


# =========================
# Function for FastAPI
# =========================

def run_travel_agent( user_input: str, thread_id: str | None = None ):

    if not thread_id:

        # The thread_id identifies a particular
        # conversation/workflow execution.
        thread_id = (
            f"user_{uuid.uuid4().hex}"
        )

    # LangGraph needs to know which checkpoint
    # this execution belongs to.
    config = { "configurable": { "thread_id": thread_id } }

    result = travel_graph.invoke(
        {
            "messages": [ HumanMessage( content=user_input) ],

            "user_query": user_input,

            # -------------------------
            # Guardrail state
            # -------------------------
            "guardrail_allowed": False,
            "guardrail_reason": "",

            # -------------------------
            # Supervisor state
            # -------------------------
            "selected_agents": [],
            "trip_constraints": _empty_constraints(),
            "supervisor_reasoning": "",

            # -------------------------
            # Specialist state
            # -------------------------
            "flight_results": "",
            "hotel_results": "",
            "weather_results": "",
            "itinerary": "",
            "budget_results": "",

            # -------------------------
            # HITL state
            # -------------------------
            "approval_request": "",
            "approved": False,
            "human_feedback": "",

            # -------------------------
            # Final state
            # -------------------------
            "final_response": "",

            # -------------------------
            # Tracking
            # -------------------------
            "llm_calls": 0
        },
        config=config
    )

    return _serialize_result( result, thread_id)


# ============================================================
# Resume after Human Review
# ============================================================

def resume_travel_agent( thread_id: str, approved: bool, feedback: str = "" ):

    if not thread_id:
        raise ValueError("thread_id is required to resume a travel plan." )

    config = {"configurable": { "thread_id": thread_id } }

    # Resume the exact paused LangGraph execution.
    result = travel_graph.invoke(
        Command(
            resume={
                "approved": approved,
                "feedback": feedback.strip()
            }
        ),
        config=config
    )

    return _serialize_result(
        result,
        thread_id
    )
