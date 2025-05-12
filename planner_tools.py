# --- START OF FILE planner_tools.py ---
import os
import sys
import json
import requests
import traceback
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta

from langchain_core.tools import tool, ToolException
from pydantic.v1 import BaseModel, Field # Using pydantic v1 for compatibility if needed

# Tool imports for web search dependency
from brave_search_api import BraveSearchManual
# Config import
from config import VERBOSE # Assuming VERBOSE is defined in config.py

# --- Load Environment Variables ---
from dotenv import load_dotenv
load_dotenv()

OPEN_WEATHER_API_KEY = os.getenv("OPEN_WEATHER_API_KEY")
OPEN_ROUTE_SERVICE_API_KEY = os.getenv("OPEN_ROUTE_SERVICE_API_KEY")
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY") # Needed for general_web_search

# --- Helper Functions (Internal) ---

# NEW: Helper to parse coordinate strings robustly
def _parse_coordinates_from_string(loc_str: str) -> Optional[Tuple[float, float]]:
    """
    Tries to parse 'lat,lon' or 'lon,lat' string into (latitude, longitude) tuple.
    Returns None if parsing fails or values are out of standard range.
    """
    if ',' not in loc_str:
        return None
    parts = loc_str.split(',')
    if len(parts) == 2:
        try:
            val1 = float(parts[0].strip())
            val2 = float(parts[1].strip())
            # Check typical lat/lon ranges to infer order
            is_val1_lat = -90 <= val1 <= 90
            is_val1_lon = -180 <= val1 <= 180
            is_val2_lat = -90 <= val2 <= 90
            is_val2_lon = -180 <= val2 <= 180

            if is_val1_lat and is_val2_lon: # Order is lat,lon
                return val1, val2
            elif is_val1_lon and is_val2_lat: # Order is lon,lat
                 if VERBOSE: print(f"--- Planner Tools Info: Parsed '{loc_str}' as lon,lat. Storing as (lat,lon). ---", file=sys.stderr)
                 return val2, val1 # Store consistently as (lat, lon)
            elif is_val1_lat and is_val2_lat and is_val1_lon and is_val2_lon:
                # Ambiguous case (e.g., 40, 40) - Assume lat,lon based on OWM common usage
                if VERBOSE: print(f"--- Planner Tools Warning: Coordinate string '{loc_str}' is ambiguous (fits both lat,lon and lon,lat). Assuming lat,lon. ---", file=sys.stderr)
                return val1, val2
            else: # Values out of range
                if VERBOSE: print(f"--- Planner Tools Warning: Parsed values from '{loc_str}' ({val1}, {val2}) fall outside standard lat/lon ranges. Cannot use. ---", file=sys.stderr)
                return None
        except ValueError:
             # Failed to convert to float
            return None
    return None # Not two parts after split

# UPDATED: Geocoding helper using the new parser
def _get_coordinates_owm(location: str, api_key: Optional[str]) -> Optional[Tuple[float, float]]:
    """
    Gets coordinates (latitude, longitude) for a location.
    Tries parsing direct 'lat,lon' or 'lon,lat' first. If that fails,
    attempts to geocode the location name using OpenWeatherMap.
    Returns (latitude, longitude) tuple or None if resolution fails.
    """
    if not isinstance(location, str) or not location.strip():
        if VERBOSE: print(f"--- Planner Tools Info: Invalid location input for coordinate resolution: '{location}' ---", file=sys.stderr)
        return None

    # 1. Try parsing as direct coordinates
    parsed_coords = _parse_coordinates_from_string(location)
    if parsed_coords:
        if VERBOSE: print(f"--- Planner Tools: Using directly parsed coordinates for '{location}': {parsed_coords} (lat,lon) ---", file=sys.stderr)
        return parsed_coords # Returns (lat, lon)

    # 2. If not direct coordinates, proceed with geocoding (requires API key)
    if not api_key:
        print("--- Planner Tools Error: OpenWeatherMap API Key not configured. Cannot geocode city name '{location}'. ---", file=sys.stderr)
        return None

    # Use the original string for geocoding API, it's usually robust enough
    city_name_to_geocode = location.strip()

    geo_url = f"http://api.openweathermap.org/geo/1.0/direct?q={city_name_to_geocode}&limit=1&appid={api_key}"
    try:
        response = requests.get(geo_url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data and isinstance(data, list) and len(data) > 0 and 'lat' in data[0] and 'lon' in data[0]:
            lat, lon = data[0]['lat'], data[0]['lon']
            if VERBOSE: print(f"--- Planner Tools: Geocoded '{city_name_to_geocode}' to ({lat}, {lon}) ---", file=sys.stderr)
            return lat, lon # Returns (lat, lon)
        else:
            if VERBOSE: print(f"--- Planner Tools Warning: OWM Geocoding found no results for '{city_name_to_geocode}'. Response: {data} ---", file=sys.stderr)
            return None
    except requests.exceptions.RequestException as e:
        error_detail = e.response.text if e.response else str(e)
        print(f"--- Planner Tools Error: OWM Geocoding request failed for '{city_name_to_geocode}': {e}. Detail: {error_detail[:200]}... ---", file=sys.stderr)
        return None
    except Exception as e:
        print(f"--- Planner Tools Error: Unexpected error during OWM geocoding for '{city_name_to_geocode}': {e} ---", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return None

# --- Tool Definitions ---

# 1. Weather Tool (No changes needed here)
class WeatherInput(BaseModel):
    city: str = Field(description="The city name for which to get the weather forecast.")
    days: int = Field(default=5, description="Number of days for the forecast (max 5 with this free API endpoint).")

@tool("get_weather_forecast_daily", args_schema=WeatherInput)
def get_weather_forecast_daily(city: str, days: int = 5) -> str:
    """
    Retrieves the daily weather forecast for a specified city for up to 5 days.
    Requires the city name as input. It first attempts to find the geographical
    coordinates (latitude, longitude) for the city using OpenWeatherMap's geocoding API.
    If successful, it then uses these coordinates to fetch the 5-day forecast data
    (provided in 3-hour intervals) from OpenWeatherMap.
    The function processes this data to provide a daily summary including
    temperature range (min/max Celsius), general weather description, and average wind speed.
    Returns a string summarizing the forecast or an error message if coordinates
    cannot be found or the forecast cannot be fetched.
    """
    if not OPEN_WEATHER_API_KEY:
        return "Error: OpenWeatherMap API Key is not configured. Cannot provide weather forecast."

    coordinates = _get_coordinates_owm(city, OPEN_WEATHER_API_KEY) # Uses the improved helper
    if not coordinates:
        return f"Error: Could not retrieve coordinates for the city '{city}'. Please ensure it's a valid city name or format like 'lat,lon'."

    lat, lon = coordinates
    days = min(max(1, days), 5)

    forecast_url = f"http://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={OPEN_WEATHER_API_KEY}&units=metric"

    try:
        forecast_response = requests.get(forecast_url, timeout=15)
        forecast_response.raise_for_status()
        forecast_data = forecast_response.json()

        daily_summary = {}
        target_dates = [datetime.now().date() + timedelta(days=i) for i in range(days)]

        for entry in forecast_data.get('list', []):
            dt_txt = entry.get('dt_txt')
            if not dt_txt: continue
            try:
                entry_datetime = datetime.strptime(dt_txt, '%Y-%m-%d %H:%M:%S')
                entry_date = entry_datetime.date()
            except ValueError:
                continue

            if entry_date not in target_dates:
                continue

            temp = entry.get('main', {}).get('temp')
            wind_speed = entry.get('wind', {}).get('speed')
            description = entry.get('weather', [{}])[0].get('description', 'N/A')

            if entry_date not in daily_summary:
                daily_summary[entry_date] = {'temps': [], 'winds': [], 'descriptions': set()}

            if temp is not None: daily_summary[entry_date]['temps'].append(temp)
            if wind_speed is not None: daily_summary[entry_date]['winds'].append(wind_speed)
            daily_summary[entry_date]['descriptions'].add(description.capitalize())

        if not daily_summary:
            return f"Could not process forecast data for {city} for the specified dates. API might have returned empty or unexpected results."

        output_lines = [f"Weather Forecast for {city} (next {days} day(s)):"]
        for date_obj in sorted(daily_summary.keys()):
            data = daily_summary[date_obj]
            min_temp_str = f"{min(data['temps']):.1f}" if data['temps'] else 'N/A'
            max_temp_str = f"{max(data['temps']):.1f}" if data['temps'] else 'N/A'
            avg_wind_str = f"{sum(data['winds']) / len(data['winds']):.1f} m/s" if data['winds'] else 'N/A'
            weather_desc_str = ", ".join(sorted(list(data['descriptions']))) if data['descriptions'] else 'N/A'

            output_lines.append(f"\n- {date_obj.strftime('%Y-%m-%d (%A')}:")
            output_lines.append(f"  Temp: {min_temp_str}°C - {max_temp_str}°C")
            output_lines.append(f"  Weather: {weather_desc_str}")
            output_lines.append(f"  Avg Wind: {avg_wind_str}")

        return "\n".join(output_lines)
    except requests.exceptions.RequestException as e:
        error_detail = e.response.text if e.response else str(e)
        return f"Error: Failed to fetch weather forecast for {city}: {e}. Detail: {error_detail[:200]}..."
    except Exception as e:
        if VERBOSE: traceback.print_exc(file=sys.stderr)
        return f"Error: An unexpected error occurred while processing forecast for {city}: {e}"


# 2. Routing Tool (UPDATED to use improved coordinate resolution)
class RouteInput(BaseModel):
    locations: List[str] = Field(description="A list of two or more locations (city names or coordinates like 'latitude,longitude' or 'longitude,latitude') defining the route segments.")

@tool("plan_route_ors", args_schema=RouteInput)
def plan_route_ors(locations: List[str]) -> str:
    """
    Calculates route information (distance, duration) between a sequence of locations
    using OpenRouteService (ORS). Takes a list of location strings. Each string can be
    a city name (which will be geocoded via OpenWeatherMap) or coordinates
    (parsed as 'lat,lon' or 'lon,lat').
    For each segment between consecutive valid locations, it requests route data for
    driving, cycling, and walking profiles from ORS.
    Returns a string summarizing the route segments, including distance (km),
    duration (min) for each mode, and indicates the recommended mode (shortest duration).
    Requires at least two valid locations to be resolved.
    """
    if not OPEN_ROUTE_SERVICE_API_KEY:
        return "Error: OpenRouteService API Key is not configured. Cannot plan route."
    if not OPEN_WEATHER_API_KEY:
        # Needed for geocoding city names if they are provided
        if VERBOSE: print("--- Planner Tools Info: OpenWeatherMap API Key not configured. Will only work if all locations are provided as coordinates. ---", file=sys.stderr)
        # Allow proceeding if coordinates are provided, but geocoding will fail

    if not isinstance(locations, list) or len(locations) < 2:
        return "Error: At least two locations (as a list of strings) are required to plan a route."

    coordinates_list_for_ors = [] # Stores [lon, lat] for ORS API call
    resolved_location_names_for_summary = [] # Keep original names for readability

    for i, loc_input_str in enumerate(locations):
        # Use the robust helper to get (latitude, longitude)
        lat_lon_tuple = _get_coordinates_owm(loc_input_str, OPEN_WEATHER_API_KEY)

        if lat_lon_tuple:
            # ORS API expects coordinates in [longitude, latitude] order
            ors_coord_pair = [lat_lon_tuple[1], lat_lon_tuple[0]]
            coordinates_list_for_ors.append(ors_coord_pair)
            # Use the original input string in the summary for clarity
            resolved_location_names_for_summary.append(f"{loc_input_str} ({lat_lon_tuple[0]:.4f},{lat_lon_tuple[1]:.4f})")
        else:
            # If any location fails to resolve, stop planning the route
            return f"Error: Could not resolve location '{loc_input_str}' (index {i}) to coordinates. Cannot plan the full route."

    # Should have at least two pairs of coordinates now if we reached here
    if len(coordinates_list_for_ors) < 2:
        return "Error: Less than two locations were successfully resolved to coordinates. Cannot plan route."

    profiles = {'driving-car': 'Car', 'cycling-regular': 'Cycling', 'foot-walking': 'Walking'}
    base_ors_url = "https://api.openrouteservice.org/v2/directions/"
    headers = {
        'Authorization': OPEN_ROUTE_SERVICE_API_KEY,
        'Content-Type': 'application/json',
        'Accept': 'application/json, application/geo+json, application/gpx+xml, img/png; charset=utf-8',
    }

    segment_summaries_text = []
    total_recommended_dist_km = 0.0
    total_recommended_dur_min = 0.0

    for i in range(len(coordinates_list_for_ors) - 1):
        start_coord = coordinates_list_for_ors[i]
        end_coord = coordinates_list_for_ors[i+1]
        # Use the resolved names (which include coords now) for the summary
        origin_name = resolved_location_names_for_summary[i]
        dest_name = resolved_location_names_for_summary[i+1]

        segment_text = [f"\n--- Segment {i+1}: {origin_name} -> {dest_name} ---"]
        segment_mode_details = {}

        for profile_key, profile_label in profiles.items():
            url = f"{base_ors_url}{profile_key}"
            body = {'coordinates': [start_coord, end_coord]}
            try:
                response = requests.post(url, headers=headers, json=body, timeout=20)
                response.raise_for_status()
                data = response.json()
                if data.get('routes') and data['routes'][0].get('summary'):
                    summary = data['routes'][0]['summary']
                    dist_km = summary.get('distance', 0) / 1000
                    dur_min = summary.get('duration', 0) / 60
                    # Check for valid results (sometimes API returns 0 distance/duration)
                    if dist_km > 0 or dur_min > 0:
                        segment_mode_details[profile_label] = {'distance': dist_km, 'duration': dur_min}
                        segment_text.append(f"  - {profile_label}: {dist_km:.2f} km, {dur_min:.1f} min")
                    else:
                        segment_text.append(f"  - {profile_label}: Route found but distance/duration is zero (check points/profile).")
                        segment_mode_details[profile_label] = {'distance': None, 'duration': None}
                else:
                    segment_text.append(f"  - {profile_label}: Route not found or data incomplete for this mode.")
                    segment_mode_details[profile_label] = {'distance': None, 'duration': None}
            except requests.exceptions.RequestException as e_req:
                err_detail = e_req.response.text if e_req.response else str(e_req)
                status_code = e_req.response.status_code if e_req.response else 'N/A'
                print(f"--- Planner Tools Error: ORS request failed for {profile_label} ({origin_name}->{dest_name}): Status {status_code}, Detail: {err_detail[:200]}... ---", file=sys.stderr)
                segment_text.append(f"  - {profile_label}: API Error (Status: {status_code})")
                segment_mode_details[profile_label] = {'distance': None, 'duration': None}
            except Exception as e_exc:
                print(f"--- Planner Tools Error: Unexpected ORS error for {profile_label} ({origin_name}->{dest_name}): {e_exc} ---", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                segment_text.append(f"  - {profile_label}: Calculation Error")
                segment_mode_details[profile_label] = {'distance': None, 'duration': None}

        valid_modes = {m: d for m, d in segment_mode_details.items() if d.get('duration') is not None and d.get('distance') is not None}
        recommended_mode = min(valid_modes, key=lambda m: valid_modes[m]['duration']) if valid_modes else None

        if recommended_mode:
            rec_info = segment_mode_details[recommended_mode]
            segment_text.append(f"  -> Recommended: {recommended_mode} ({rec_info['distance']:.2f} km, {rec_info['duration']:.1f} min)")
            total_recommended_dist_km += rec_info['distance']
            total_recommended_dur_min += rec_info['duration']
        else:
            segment_text.append("  -> Recommended: None (no valid modes available for this segment)")
        segment_summaries_text.extend(segment_text)

    final_summary = ["Route Plan Summary:"] + segment_summaries_text
    if total_recommended_dist_km > 0 or total_recommended_dur_min > 0 :
        final_summary.append("\n--- Total Estimated Route (sum of recommended modes for successful segments) ---")
        final_summary.append(f"  - Total Distance: {total_recommended_dist_km:.2f} km")
        final_summary.append(f"  - Total Duration: {total_recommended_dur_min:.1f} min ({total_recommended_dur_min/60:.1f} hours)")
    elif not segment_summaries_text: # Should not happen if initial checks pass, but as safety
        return "Error: Could not calculate any route segments. Please check locations and API services."

    return "\n".join(final_summary)


# 3. General Web Search Tool (using Brave) - No changes needed here
brave_search_client_instance = None
if BRAVE_API_KEY:
    try:
        brave_search_client_instance = BraveSearchManual(api_key=BRAVE_API_KEY, verbose=VERBOSE)
        if VERBOSE: print("--- Planner Tools: BraveSearchManual initialized successfully for general_web_search. ---", file=sys.stderr)
    except Exception as e:
        print(f"--- Planner Tools Error: Failed to initialize BraveSearchManual: {e}. General Web Search tool will be disabled. ---", file=sys.stderr)
else:
    if VERBOSE: print("--- Planner Tools Warning: BRAVE_API_KEY not found. General Web Search tool will be disabled. ---", file=sys.stderr)

class WebSearchInput(BaseModel):
    query: str = Field(description="The search query string.")
    count: int = Field(default=3, description="Number of search results desired (max 5 for this context).")

@tool("general_web_search", args_schema=WebSearchInput)
def general_web_search(query: str, count: int = 3) -> str:
    """
    Performs a general web search using the Brave Search API to find relevant web pages.
    Use this as a fallback when specific tools (like weather, routing) are not suitable
    or for finding information not covered by other tools (e.g., opening hours if not
    available via a specific 'Places' tool, finding specific event details, etc.).
    Returns a formatted string containing the top search results (title, URL, description).
    """
    if not brave_search_client_instance:
        return "Error: Web search tool is not available (Brave API key missing or client initialization failed)."
    try:
        results = brave_search_client_instance.search_web(query=query, count=min(count, 5))
        if not results: return f"No web search results found for '{query}'."
        output = [f"Web Search Results for '{query}':"]
        for i, r in enumerate(results):
            output.append(f"\n{i+1}. Title: {r.get('title', 'N/A')}\n   URL: {r.get('url', 'N/A')}\n   Snippet: {r.get('description', 'N/A')}")
        return "\n".join(output)
    except ToolException as e_tool:
        return f"Error: Web search API request failed: {e_tool}"
    except Exception as e_exc:
        if VERBOSE: traceback.print_exc(file=sys.stderr)
        return f"Error: An unexpected error occurred during web search: {e_exc}"


# 4. Placeholder/Simulated Tools (Corrected invoke call)
class OperationalDetailsInput(BaseModel):
    place_name: str = Field(description="The name of the place (e.g., museum, restaurant, shop).")
    location: str = Field(description="The city or general area where the place is located.")

@tool("get_operational_details", args_schema=OperationalDetailsInput)
def get_operational_details(place_name: str, location: str) -> str:
    """
    (Simulated) Attempts to find operational details like address and opening hours for a specific place.
    Ideally, this would use a dedicated 'Places' API, but currently relies on general web search
    or returns a simulated response. Ask the user to verify the information.
    """
    if VERBOSE: print(f"--- Planner Tools: Simulating 'get_operational_details' for {place_name} in {location} ---", file=sys.stderr)
    if brave_search_client_instance:
        search_query = f"opening hours and address for {place_name} in {location}"
        try:
            # Use .invoke() with a dictionary matching the WebSearchInput schema
            search_result = general_web_search.invoke({"query": search_query, "count": 1})

            if "Error:" not in search_result and "No web search results found" not in search_result:
                 # Return search results but remind user to verify
                 return f"Found potential details via web search for '{place_name} in {location}' (Please verify these details as they are from a general search and may not be precise):\n{search_result}\n[End of Search Result]"
            else:
                 if VERBOSE: print(f"--- Planner Tools: Web search fallback for operational details failed or yielded no results. Reason: {search_result} ---", file=sys.stderr)
                 # Fall through to placeholder if search failed
        except Exception as e_invoke:
             print(f"--- Planner Tools Error: Failed to invoke general_web_search within get_operational_details: {e_invoke} ---", file=sys.stderr)
             # Fall through to placeholder

    # Placeholder response if web search is unavailable or failed
    return f"Placeholder/Simulated response for '{place_name}' in '{location}'. Specific operational details (hours, address) could not be reliably fetched via available tools. Please search for this information online or assume standard business hours (e.g., 9 AM - 5 PM weekdays) and verify externally. [User verification required]"


# 5. Calendar Tool (start_datetime kept mandatory, improved validation)
class CalendarEventInput(BaseModel):
    summary: str = Field(description="The title or summary of the event.")
    # Keeping start_datetime mandatory as per preferred strategy (prompt LLM)
    start_datetime: str = Field(description="Start date and time in ISO format (e.g., 'YYYY-MM-DD HH:MM:SS' or 'YYYY-MM-DDTHH:MM:SS'). This is REQUIRED.")
    end_datetime: Optional[str] = Field(default=None, description="End date and time in ISO format. Optional.")
    location: Optional[str] = Field(default=None, description="Location of the event. Optional.")
    description: Optional[str] = Field(default=None, description="Description or notes for the event. Optional.")

@tool("add_calendar_event", args_schema=CalendarEventInput)
def add_calendar_event(summary: str, start_datetime: str, end_datetime: Optional[str] = None, location: Optional[str] = None, description: Optional[str] = None) -> str:
    """
    (Simulated) Adds an event to a user's calendar or task list based on provided details.
    Requires at least 'summary' and 'start_datetime'.
    Currently, it just confirms that the event *would* be added based on input validation.
    """
    if VERBOSE: print(f"--- Planner Tools: Simulating 'add_calendar_event': {summary} @ {start_datetime} ---", file=sys.stderr)
    # Validate start_datetime (which is mandatory due to schema)
    try:
        # Allow space as separator, replace before parsing
        dt_str_start = start_datetime.replace(" ", "T")
        datetime.fromisoformat(dt_str_start)
    except ValueError:
        return f"Error: Invalid start_datetime format '{start_datetime}'. Please use valid ISO format like 'YYYY-MM-DD HH:MM:SS' or 'YYYY-MM-DDTHH:MM:SS'."

    details = [f"Event: {summary}", f"Starts: {start_datetime}"]
    # Validate end_datetime if provided
    if end_datetime:
        try:
            dt_str_end = end_datetime.replace(" ", "T")
            # Optional: Check if end is after start
            if datetime.fromisoformat(dt_str_end) < datetime.fromisoformat(dt_str_start):
                 return f"Error: Optional end_datetime '{end_datetime}' cannot be before start_datetime '{start_datetime}'."
            details.append(f"Ends: {end_datetime}")
        except ValueError:
             return f"Error: Invalid end_datetime format '{end_datetime}'. Use ISO format."

    if location: details.append(f"Location: {location}")
    if description: details.append(f"Notes: {description}")

    return f"Success: Simulated adding calendar event:\n- " + "\n- ".join(details) + "\n[Note: This is a simulation. Please add this event to your actual calendar application.]"

# --- List of tools for the agent ---
# Define the potential list
planner_tools_list = [
    get_weather_forecast_daily,
    plan_route_ors,
    get_operational_details,
    add_calendar_event,
    general_web_search # Will only work if brave_search_client_instance is not None
]

# Filter out general_web_search if the client isn't ready
active_planner_tools = [
    get_weather_forecast_daily,
    plan_route_ors,
    get_operational_details, # Simulated, always "active"
    add_calendar_event,      # Simulated, always "active"
]
if brave_search_client_instance:
    active_planner_tools.append(general_web_search)
else:
    if VERBOSE: print("--- Planner Tools: `general_web_search` tool is NOT active due to client initialization failure or missing API key. ---", file=sys.stderr)


# --- Testing Block ---
if __name__ == '__main__':
    print("--- Testing Planner Tools (ensure .env has API keys) ---")

    # Test Coordinate Parsing and Geocoding Helper
    # print("\nTesting Coordinate Resolution:")
    # print(f"  'Paris': {_get_coordinates_owm('Paris', OPEN_WEATHER_API_KEY)}")
    # print(f"  'Barcelona, Spain': {_get_coordinates_owm('Barcelona, Spain', OPEN_WEATHER_API_KEY)}") # Should geocode 'Barcelona'
    # print(f"  '48.8566,2.3522': {_get_coordinates_owm('48.8566,2.3522', OPEN_WEATHER_API_KEY)}") # lat,lon
    # print(f"  '2.3522, 48.8566': {_get_coordinates_owm('2.3522, 48.8566', OPEN_WEATHER_API_KEY)}") # lon,lat
    # print(f"  'InvalidCity123': {_get_coordinates_owm('InvalidCity123', OPEN_WEATHER_API_KEY)}")
    # print(f"  '999,999': {_get_coordinates_owm('999,999', OPEN_WEATHER_API_KEY)}") # Out of range

    # Test Routing with different inputs
    print("\nTesting Routing:")
    print("  Route: London -> Paris")
    print(plan_route_ors.invoke({"locations": ["London", "Paris"]}))
    # print("\n  Route: Barcelona -> Girona (using names)")
    # print(plan_route_ors.invoke({"locations": ["Barcelona", "Girona"]}))
    # print("\n  Route: Barcelona -> Girona (using 'City, Country')")
    # print(plan_route_ors.invoke({"locations": ["Barcelona, Spain", "Girona, Spain"]})) # Should now work
    # print("\n  Route: NYC (lat,lon) -> LA (lat,lon)")
    # print(plan_route_ors.invoke({"locations": ["40.7128,-74.0060", "34.0522,-118.2437"]}))

    # Test Operational Details (Simulated with fixed invoke)
    # print("\nTesting Operational Details (Eiffel Tower, Paris):")
    # print(get_operational_details.invoke({"place_name": "Eiffel Tower", "location": "Paris"}))

    # Test Calendar Add (Simulated)
    # print("\nTesting Add Calendar Event (Valid):")
    # print(add_calendar_event.invoke({"summary": "Meeting", "start_datetime": "2024-12-01 10:00:00"}))
    # print("\nTesting Add Calendar Event (Invalid Date Format):")
    # print(add_calendar_event.invoke({"summary": "Meeting", "start_datetime": "01-12-2024 10:00"}))
    # print("\nTesting Add Calendar Event (End before Start):")
    # print(add_calendar_event.invoke({"summary": "Meeting", "start_datetime": "2024-12-01 10:00:00", "end_datetime": "2024-12-01 09:00:00"}))

    print(f"\n--- Active planner tools available for import ({len(active_planner_tools)}): {[t.name for t in active_planner_tools]} ---")
# --- END OF FILE planner_tools.py ---