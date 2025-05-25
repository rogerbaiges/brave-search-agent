# --- START OF FILE planner_tools.py ---
import os
import sys
import json
import requests
import traceback
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from urllib.parse import urlencode, quote_plus # quote_plus for Google Maps link

import math # For Haversine distance

from langchain_core.tools import tool, ToolException
from pydantic.v1 import BaseModel, Field

from brave_search_api import BraveSearchManual
from config import VERBOSE

from dotenv import load_dotenv
load_dotenv()

OPEN_WEATHER_API_KEY = os.getenv("OPEN_WEATHER_API_KEY")
OPEN_ROUTE_SERVICE_API_KEY = os.getenv("OPEN_ROUTE_SERVICE_API_KEY")
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")

# --- Helper for Haversine Distance (from planner_apis_example.py) ---
def _haversine(lat1, lon1, lat2, lon2):
    R = 6371
    lat1_rad, lon1_rad, lat2_rad, lon2_rad = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad
    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# --- Corrected Geocoding Helper (from planner_apis_example.py) ---
def _get_coordinates_owm_robust(location_str: str, api_key: Optional[str]) -> tuple[Optional[tuple[float, float]], str]:
    """
    Gets (latitude, longitude) for a location string.
    Tries direct parsing, then OWM geocoding, with a fallback for "City, Country" formats.
    Returns ((lat, lon), display_name_for_location) or (None, original_location_str) on failure.
    """
    if not api_key: # Added check for api_key for OWM geocoding
        if VERBOSE: print(f"--- Planner Tools Error (_get_coordinates_owm_robust): OpenWeatherMap API Key not available. Cannot geocode '{location_str}' by name. ---", file=sys.stderr)
        # Try direct parsing only if API key is missing
        if ',' in location_str:
            parts = location_str.split(',')
            if len(parts) == 2:
                try:
                    val1, val2 = float(parts[0].strip()), float(parts[1].strip())
                    is_val1_lat, is_val1_lon = -90 <= val1 <= 90, -180 <= val1 <= 180
                    is_val2_lat, is_val2_lon = -90 <= val2 <= 90, -180 <= val2 <= 180
                    if is_val1_lat and is_val2_lon: return (val1, val2), location_str
                    if is_val1_lon and is_val2_lat: return (val2, val1), location_str
                except ValueError: pass
        return None, location_str


    if not location_str or not location_str.strip():
        if VERBOSE: print(f"--- Planner Tools Info (_get_coordinates_owm_robust): Invalid empty location string provided for '{location_str}'. ---", file=sys.stderr)
        return None, location_str

    if ',' in location_str:
        parts = location_str.split(',')
        if len(parts) == 2:
            try:
                val1, val2 = float(parts[0].strip()), float(parts[1].strip())
                is_val1_lat, is_val1_lon = -90 <= val1 <= 90, -180 <= val1 <= 180
                is_val2_lat, is_val2_lon = -90 <= val2 <= 90, -180 <= val2 <= 180
                if is_val1_lat and is_val2_lon:
                    if VERBOSE: print(f"--- Planner Tools Info (_get_coordinates_owm_robust): Parsed direct lat,lon for '{location_str}': ({val1}, {val2}) ---", file=sys.stderr)
                    return (val1, val2), location_str
                if is_val1_lon and is_val2_lat:
                    if VERBOSE: print(f"--- Planner Tools Info (_get_coordinates_owm_robust): Parsed direct lon,lat for '{location_str}': ({val2}, {val1}) ---", file=sys.stderr)
                    return (val2, val1), location_str
            except ValueError:
                pass

    def _owm_geocode_attempt(query_str, original_input_for_error_msg):
        geo_url = f"http://api.openweathermap.org/geo/1.0/direct?q={query_str}&limit=1&appid={api_key}"
        try:
            response = requests.get(geo_url, timeout=5)
            response.raise_for_status()
            data = response.json()
            if data and isinstance(data, list) and len(data) > 0 and 'lat' in data[0] and 'lon' in data[0]:
                lat, lon = data[0]['lat'], data[0]['lon']
                display_name = data[0].get('name', query_str)
                country = data[0].get('country', '')
                full_display_name = f"{display_name}, {country}" if country and country.strip() else display_name
                if VERBOSE: print(f"--- Planner Tools Info (_get_coordinates_owm_robust): Geocoded '{query_str}' to: {full_display_name} ({lat:.4f}, {lon:.4f}) ---", file=sys.stderr)
                return (lat, lon), full_display_name
        except requests.exceptions.RequestException as e:
            if VERBOSE: print(f"--- Planner Tools Warning (_get_coordinates_owm_robust): OWM Geocoding request failed for '{query_str}': {e} ---", file=sys.stderr)
        except Exception as e:
            if VERBOSE: print(f"--- Planner Tools Warning (_get_coordinates_owm_robust): Unexpected error during OWM geocoding for '{query_str}': {e} ---", file=sys.stderr)
        return None, original_input_for_error_msg

    coords, display_name = _owm_geocode_attempt(location_str.strip(), location_str)
    if coords:
        return coords, display_name

    if ',' in location_str:
        city_part = location_str.split(',')[0].strip()
        if city_part and city_part.lower() != location_str.strip().lower():
            if VERBOSE: print(f"--- Planner Tools Info (_get_coordinates_owm_robust): Geocoding for '{location_str}' failed, trying fallback with '{city_part}'... ---", file=sys.stderr)
            coords, display_name = _owm_geocode_attempt(city_part, city_part)
            if coords:
                return coords, display_name

    if VERBOSE: print(f"--- Planner Tools Warning (_get_coordinates_owm_robust): Could not find coordinates for '{location_str}' after all attempts. ---", file=sys.stderr)
    return None, location_str


# --- Tool Definitions ---

# 1. Weather Tool - MODIFIED
class WeatherInput(BaseModel):
    city: str = Field(description="The city name for which to get the weather forecast. Can also be 'lat,lon' or 'lon,lat'.")
    days: int = Field(default=5, description="Number of days for the forecast. If > 5, will provide typical weather info for the approximate future date using web search if available, alongside any available 5-day forecast.")

@tool("get_weather_forecast_daily", args_schema=WeatherInput)
def get_weather_forecast_daily(city: str, days: int = 5) -> str:
    """
    Retrieves daily weather forecast. For up to 5 days, uses OpenWeatherMap API for detailed forecast
    (temp range, feels like, precipitation chance, wind, description).
    If 'days' is greater than 5, it provides the 5-day forecast AND attempts a general web search
    for typical weather conditions for that city around the target future month/season.
    The LLM should synthesize this information if typical weather is returned.
    """
    if not OPEN_WEATHER_API_KEY:
        return "Error: OpenWeatherMap API Key not configured. Cannot provide weather forecast."

    coordinates_tuple, display_city_name = _get_coordinates_owm_robust(city, OPEN_WEATHER_API_KEY)
    if not coordinates_tuple:
        return f"Error: Could not retrieve valid coordinates for the location '{city}'. Please ensure it's a valid city name or coordinate format."

    lat, lon = coordinates_tuple
    
    today = datetime.now().date()
    output_parts = []
    
    # Precise 5-day forecast part
    days_for_api = min(days, 5) # OWM API limit
    if days_for_api > 0 :
        forecast_url = f"http://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={OPEN_WEATHER_API_KEY}&units=metric"
        try:
            forecast_response = requests.get(forecast_url, timeout=15)
            forecast_response.raise_for_status()
            forecast_data = forecast_response.json()
            daily_summary = {}
            target_dates = [today + timedelta(days=i) for i in range(days_for_api)]

            for entry in forecast_data.get('list', []):
                entry_datetime = datetime.strptime(entry['dt_txt'], '%Y-%m-%d %H:%M:%S')
                entry_date = entry_datetime.date()
                if entry_date not in target_dates: continue

                if entry_date not in daily_summary:
                    daily_summary[entry_date] = {'temps': [], 'feels_like': [], 'winds': [], 'precip_prob': [], 'descriptions': set()}
                
                daily_summary[entry_date]['temps'].append(entry['main']['temp'])
                daily_summary[entry_date]['feels_like'].append(entry['main']['feels_like'])
                daily_summary[entry_date]['winds'].append(entry['wind']['speed'])
                daily_summary[entry_date]['precip_prob'].append(entry.get('pop', 0) * 100)
                daily_summary[entry_date]['descriptions'].add(entry['weather'][0]['description'].capitalize())

            if daily_summary:
                output_parts.append(f"Detailed Weather Forecast for {display_city_name} (next {len(daily_summary)} day(s)):")
                for date_obj in sorted(daily_summary.keys()):
                    data = daily_summary[date_obj]
                    min_t, max_t = (f"{min(data['temps']):.1f}", f"{max(data['temps']):.1f}") if data['temps'] else ('N/A','N/A')
                    avg_fl = f"{sum(data['feels_like'])/len(data['feels_like']):.1f}" if data['feels_like'] else 'N/A'
                    avg_w = f"{sum(data['winds'])/len(data['winds']):.1f} m/s" if data['winds'] else 'N/A'
                    max_pp = f"{max(data['precip_prob']):.0f}%" if data['precip_prob'] else '0%'
                    desc = ", ".join(sorted(list(data['descriptions']))) or 'N/A'
                    output_parts.append(f"\n- {date_obj.strftime('%Y-%m-%d (%A')}:")
                    output_parts.append(f"  Temp: {min_t}°C - {max_t}°C (Feels like avg: {avg_fl}°C)")
                    output_parts.append(f"  Weather: {desc}")
                    output_parts.append(f"  Precipitation Chance: ~{max_pp}")
                    output_parts.append(f"  Avg Wind: {avg_w}")
            else:
                output_parts.append(f"No detailed forecast data processed for {display_city_name} for the next {days_for_api} days.")

        except requests.exceptions.RequestException as e:
            output_parts.append(f"Error fetching detailed forecast: {e}")
        except Exception as e:
            if VERBOSE: traceback.print_exc(file=sys.stderr)
            output_parts.append(f"Unexpected error processing detailed forecast: {e}")

    # Long-range typical weather part
    if days > 5:
        output_parts.append(f"\nNote: Precise forecast for {display_city_name} beyond 5 days is not available via direct API.")
        # Determine a representative future month for typical weather search
        # For simplicity, take the midpoint of the requested period if it's far out, or just target month.
        future_target_date = today + timedelta(days=days if days > 5 else 30) # Default to ~a month out if 'days' isn't super large
        if days > 15 : # if asking for many days out, pick a date in the middle
             future_target_date = today + timedelta(days=days//2)

        target_month_year = future_target_date.strftime("%B %Y")
        search_query = f"typical weather in {display_city_name} during {target_month_year}"
        output_parts.append(f"Attempting to find typical weather for {display_city_name} around {target_month_year} using web search...")
        
        if brave_search_client_instance:
            try:
                # Call general_web_search tool directly (as this is Python code, not an LLM call)
                # This assumes general_web_search is imported or accessible
                web_search_result_str = general_web_search.invoke({"query": search_query, "count": 1})
                # Parse the JSON string result from general_web_search
                web_search_result_json = json.loads(web_search_result_str)
                if web_search_result_json.get("results"):
                    top_result = web_search_result_json["results"][0]
                    typical_info = f"Typical weather (from web search - [Source: {top_result.get('url','N/A')}]): {top_result.get('title','N/A')} - {top_result.get('description','N/A')}. Please verify this general information."
                    output_parts.append(typical_info)
                else:
                    output_parts.append(f"Web search for typical weather yielded no specific results. Please consult climate websites for {display_city_name} in {target_month_year}.")
            except Exception as e_ws:
                output_parts.append(f"Error during web search for typical weather: {e_ws}")
        else:
            output_parts.append("Web search tool for typical weather is not available.")
            
    if not output_parts: # Should not happen if coords were resolved.
        return f"Error: No weather information could be generated for {city}."
    return "\n".join(output_parts)


# 2. Routing Tool - MODIFIED
class RouteInput(BaseModel):
    locations: List[str] = Field(description="A list of two or more locations (city names or coordinates like 'latitude,longitude' or 'longitude,latitude') defining the route segments.")
    # TODO_LLM_GUIDANCE: Add optional preferred_modes: List[str] = Field(default=None, description="Optional list of preferred modes (e.g., ['Car', 'Flight']). If provided, tool will focus on these.")

@tool("plan_route_ors", args_schema=RouteInput)
def plan_route_ors(locations: List[str]) -> str:
    """
    Calculates route information between a sequence of locations using OpenRouteService (ORS) for land travel
    and estimates for flights. Takes a list of location strings.
    It provides viable transport modes (Car, Flight, Cycling, Walking) for each segment based on distance heuristics.
    Cycling/Walking are only considered for shorter, land-based segments. Flights are estimated for long distances or
    if car routes fail over significant distances (e.g., ocean crossings).
    Returns a string summarizing each segment's viable modes with distance/duration, an overall trip summary
    (total distance/time for primary modes), and a Google Maps link for visualization.
    The LLM should synthesize this information, presenting all viable options per segment.
    """
    if not OPEN_ROUTE_SERVICE_API_KEY: return "Error: OpenRouteService API Key is not configured."
    if not OPEN_WEATHER_API_KEY: # For geocoding
        if VERBOSE: print("--- Planner Tools Info (plan_route_ors): OWM API Key missing, geocoding by name will fail if coords not direct. ---", file=sys.stderr)
        # Allow to proceed if all locations are given as coords

    if not isinstance(locations, list) or len(locations) < 2:
        return "Error: At least two locations (as a list of strings) are required."

    resolved_loc_data = []
    for loc_str in locations:
        coords_tuple, display_name = _get_coordinates_owm_robust(loc_str, OPEN_WEATHER_API_KEY)
        if coords_tuple:
            ors_coords = [coords_tuple[1], coords_tuple[0]] # lon, lat for ORS
            resolved_loc_data.append({'latlon': coords_tuple, 'gmaps_name': display_name, 'ors_coords': ors_coords, 'name_for_summary': display_name})
        else:
            return f"Error: Could not resolve location '{loc_str}' to coordinates. Cannot plan full route."

    if len(resolved_loc_data) < 2: return "Error: Less than two locations successfully resolved."

    # Heuristics
    MAX_DRIVING_KM_PRIMARY = 800
    MIN_KM_FOR_FLIGHT = 300
    MAX_CYCLING_KM_LAND = 200
    MAX_WALKING_KM_LAND = 40
    FLIGHT_SPEED_KMH = 800
    FLIGHT_FIXED_HOURS = 3.0

    output_segments_text = ["Route Segment Analysis:"]
    trip_segments_details_for_summary = []
    overall_trip_primarily_flight = False

    for i in range(len(resolved_loc_data) - 1):
        start, end = resolved_loc_data[i], resolved_loc_data[i+1]
        origin_name, dest_name = start['name_for_summary'], end['name_for_summary']
        start_ors, end_ors = start['ors_coords'], end['ors_coords']
        start_ll, end_ll = start['latlon'], end['latlon']

        segment_text = [f"\n--- Segment {i+1}: {origin_name} -> {dest_name} ---"]
        straight_dist_km = _haversine(start_ll[0], start_ll[1], end_ll[0], end_ll[1])
        segment_text.append(f"  (Approx. straight-line distance: {straight_dist_km:.0f} km)")

        current_segment_modes = {}
        ors_car_ok = False
        car_details = None

        # Car
        if straight_dist_km < MAX_DRIVING_KM_PRIMARY * 1.8:
            try:
                r = requests.post(f"https://api.openrouteservice.org/v2/directions/driving-car",
                                  headers={'Authorization': OPEN_ROUTE_SERVICE_API_KEY, 'Content-Type': 'application/json'},
                                  json={'coordinates': [start_ors, end_ors]}, timeout=15)
                r.raise_for_status()
                data = r.json()
                if data.get('routes') and data['routes'][0].get('summary'):
                    s = data['routes'][0]['summary']
                    dist, dur = s['distance']/1000, s['duration']/60
                    segment_text.append(f"  Viable Mode: Car - {dist:.1f} km, {dur:.0f} min (~{dur/60:.1f} hrs)")
                    current_segment_modes['Car'] = {'distance_km': dist, 'duration_min': dur}
                    ors_car_ok = True
                    car_details = current_segment_modes['Car']
                else: segment_text.append("  Car: No ORS route found.")
            except Exception as e: segment_text.append(f"  Car: ORS API error - {str(e)[:100]}")
        else: segment_text.append(f"  Car: Not considered (distance {straight_dist_km:.0f} km > driving threshold).")

        # Flight
        if straight_dist_km > MIN_KM_FOR_FLIGHT:
            flight_h = (straight_dist_km / FLIGHT_SPEED_KMH) + FLIGHT_FIXED_HOURS
            flight_m = flight_h * 60
            segment_text.append(f"  Viable Mode: Flight (estimated) - Approx. {straight_dist_km:.0f} km, ~{flight_h:.1f} hrs ({flight_m:.0f} min) total. Check airlines.")
            current_segment_modes['Flight'] = {'distance_km': straight_dist_km, 'duration_min': flight_m, 'is_estimated': True}
            if not ors_car_ok or straight_dist_km > MAX_DRIVING_KM_PRIMARY or (car_details and flight_m < car_details['duration_min']):
                overall_trip_primarily_flight = True
        
        # Cycling / Walking (only if car route was feasible for land check)
        if ors_car_ok:
            if straight_dist_km <= MAX_CYCLING_KM_LAND:
                try: # Simplified cycling call
                    r_cyc = requests.post(f"https://api.openrouteservice.org/v2/directions/cycling-regular", headers={'Authorization': OPEN_ROUTE_SERVICE_API_KEY}, json={'coordinates': [start_ors, end_ors]}, timeout=10)
                    if r_cyc.status_code == 200 and r_cyc.json().get('routes'):
                        s_cyc = r_cyc.json()['routes'][0]['summary']; d_c, dr_c = s_cyc['distance']/1000, s_cyc['duration']/60
                        segment_text.append(f"  Viable Mode: Cycling - {d_c:.1f} km, {dr_c:.0f} min (~{dr_c/60:.1f} hrs)")
                        current_segment_modes['Cycling'] = {'distance_km': d_c, 'duration_min': dr_c}
                    else: segment_text.append("  Cycling: No ORS route.")
                except: segment_text.append("  Cycling: ORS API error.")
            elif straight_dist_km > MAX_CYCLING_KM_LAND:
                segment_text.append(f"  Cycling: Not calculated (distance {straight_dist_km:.0f} km > threshold).")

            if straight_dist_km <= MAX_WALKING_KM_LAND:
                try: # Simplified walking call
                    r_walk = requests.post(f"https://api.openrouteservice.org/v2/directions/foot-walking", headers={'Authorization': OPEN_ROUTE_SERVICE_API_KEY}, json={'coordinates': [start_ors, end_ors]}, timeout=10)
                    if r_walk.status_code == 200 and r_walk.json().get('routes'):
                        s_walk = r_walk.json()['routes'][0]['summary']; d_w, dr_w = s_walk['distance']/1000, s_walk['duration']/60
                        segment_text.append(f"  Viable Mode: Walking - {d_w:.1f} km, {dr_w:.0f} min (~{dr_w/60:.1f} hrs)")
                        current_segment_modes['Walking'] = {'distance_km': d_w, 'duration_min': dr_w}
                    else: segment_text.append("  Walking: No ORS route.")
                except: segment_text.append("  Walking: ORS API error.")
            elif straight_dist_km > MAX_WALKING_KM_LAND:
                 segment_text.append(f"  Walking: Not calculated (distance {straight_dist_km:.0f} km > threshold).")

        if not current_segment_modes: segment_text.append("  No suitable transportation modes determined for this segment.")
        
        # Determine primary mode for summary totals
        primary_mode_for_segment_total = None
        if 'Flight' in current_segment_modes and (not ors_car_ok or straight_dist_km > MAX_DRIVING_KM_PRIMARY or (car_details and current_segment_modes['Flight']['duration_min'] < car_details['duration_min'])):
            primary_mode_for_segment_total = 'Flight'
        elif 'Car' in current_segment_modes: primary_mode_for_segment_total = 'Car'
        elif 'Cycling' in current_segment_modes: primary_mode_for_segment_total = 'Cycling'
        elif 'Walking' in current_segment_modes: primary_mode_for_segment_total = 'Walking'

        trip_segments_details_for_summary.append({
            'origin': origin_name, 'destination': dest_name,
            'viable_modes_data': current_segment_modes,
            'primary_mode_for_total': primary_mode_for_segment_total
        })
        output_segments_text.extend(segment_text)

    # Overall Summary
    if trip_segments_details_for_summary:
        output_segments_text.append("\n\n=== Overall Trip Summary ===")
        total_dist, total_dur = 0,0
        final_modes_set = set()
        for seg in trip_segments_details_for_summary:
            pm = seg['primary_mode_for_total']
            if pm and pm in seg['viable_modes_data']:
                total_dist += seg['viable_modes_data'][pm]['distance_km']
                total_dur += seg['viable_modes_data'][pm]['duration_min']
                final_modes_set.add(pm)
        
        modes_str = ", ".join(sorted(list(final_modes_set))) or "N/A"
        output_segments_text.append(f"Total Estimated Trip Distance (primary modes: {modes_str}): {total_dist:.1f} km")
        output_segments_text.append(f"Total Estimated Trip Duration (primary modes: {modes_str}): {total_dur:.0f} min (~{total_dur/60:.1f} hrs)")
        
        # Google Maps Link
        gmaps_origin = quote_plus(resolved_loc_data[0]['gmaps_name'])
        gmaps_dest = quote_plus(resolved_loc_data[-1]['gmaps_name'])
        gmaps_params_dict = {"origin": gmaps_origin, "destination": gmaps_dest}
        if len(resolved_loc_data) > 2:
            gmaps_waypoints = "|".join([quote_plus(data['gmaps_name']) for data in resolved_loc_data[1:-1]])
            gmaps_params_dict["waypoints"] = gmaps_waypoints
        
        gmaps_mode = "driving" # Default
        if overall_trip_primarily_flight or "Flight" in final_modes_set: pass # No specific mode for Gmaps if flight involved
        elif "Car" in final_modes_set: gmaps_mode = "driving"
        elif "Cycling" in final_modes_set: gmaps_mode = "bicycling"
        elif "Walking" in final_modes_set: gmaps_mode = "walking"
        
        if not (overall_trip_primarily_flight or "Flight" in final_modes_set):
            gmaps_params_dict["travelmode"] = gmaps_mode
            
        gmaps_url = f"https://www.google.com/maps/dir/?api=1&{urlencode(gmaps_params_dict)}"
        output_segments_text.append("\n--- Google Maps Link for Visualization ---")
        output_segments_text.append("Note: This link provides a general route. For flights, check airline websites.")
        output_segments_text.append(gmaps_url)

    elif not trip_segments_details_for_summary and len(locations) >=2:
         output_segments_text.append("\nNo route segments could be planned with the provided locations.")
    
    return "\n".join(output_segments_text)


# 3. General Web Search Tool (using Brave) - Kept identical
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

# 4. Operational Details Tool - Kept identical
class OperationalDetailsInput(BaseModel):
    place_name: str = Field(description="The name of the place (e.g., museum, restaurant, shop).")
    location: str = Field(description="The city or general area where the place is located.")

@tool("get_operational_details", args_schema=OperationalDetailsInput)
def get_operational_details(place_name: str, location: str) -> str:
    """
    (Simulated) Attempts to find operational details like address and opening hours for a specific place.
    Currently relies on `general_web_search`. Results require user verification.
    The LLM should clearly state that details found this way need to be confirmed by the user from official sources.
    """
    if VERBOSE: print(f"--- Planner Tools: 'get_operational_details' for {place_name} in {location} using web search ---", file=sys.stderr)
    if brave_search_client_instance:
        search_query = f"official opening hours and address for {place_name} in {location}"
        try:
            search_result_str = general_web_search.invoke({"query": search_query, "count": 1})
            search_result_json = json.loads(search_result_str) # general_web_search returns JSON string
            
            if search_result_json.get("results"):
                 top_result = search_result_json["results"][0]
                 return (f"Potential details for '{place_name} in {location}' (from web search - VERIFY EXTERNALLY):\n"
                         f"Title: {top_result.get('title', 'N/A')}\n"
                         f"URL: {top_result.get('url', 'N/A')}\n"
                         f"Snippet: {top_result.get('description', 'N/A')}\n"
                         f"[IMPORTANT: User must verify this information from official sources as it's from a general web search.]")
            elif search_result_json.get("error"):
                return f"Could not get operational details: Web search error: {search_result_json.get('error')}"
            else:
                 return f"Could not find specific operational details for '{place_name} in {location}' via web search. Please try a more specific search or check official websites. [User verification required]"
        except Exception as e_invoke:
             return f"Error invoking web search for operational details: {e_invoke}. [User verification required]"
    return f"Web search tool unavailable. Cannot fetch operational details for '{place_name} in {location}'. Please search manually. [User verification required]"

# 5. Calendar Tool - Kept identical
class CalendarEventInput(BaseModel):
    summary: str = Field(description="The title or summary of the event.")
    start_datetime: str = Field(description="Start date and time in 'YYYY-MM-DD HH:MM:SS' format (local time). This is REQUIRED.")
    end_datetime: Optional[str] = Field(default=None, description="End date and time in 'YYYY-MM-DD HH:MM:SS' format (local time). Optional; if not provided, a 1-hour duration from start_datetime will be assumed.")
    location: Optional[str] = Field(default="", description="Location of the event. Optional.")
    description: Optional[str] = Field(default="", description="Description or notes for the event. Optional.")

def _format_datetime_for_google(dt_str: str) -> str:
    try:
        dt_obj = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        return dt_obj.strftime("%Y%m%dT%H%M%S")
    except ValueError:
        raise ValueError(f"Invalid datetime format: '{dt_str}'. Expected 'YYYY-MM-DD HH:MM:SS'.")

@tool("add_calendar_event", args_schema=CalendarEventInput)
def add_calendar_event(summary: str, start_datetime: str, end_datetime: Optional[str] = None, location: Optional[str] = "", description: Optional[str] = "") -> str:
    """
    Generates a Google Calendar event creation link that the user can click.
    Requires 'summary' and 'start_datetime'. 'end_datetime' is optional; if not provided or empty, a 1-hour duration from the start_datetime is automatically assumed by this tool.
    Both 'start_datetime' and 'end_datetime' (if provided) MUST be in 'YYYY-MM-DD HH:MM:SS' format (local time).

    IMPORTANT FOR LLM: When this tool is successfully called, it will return a success message containing a full Google Calendar URL.
    In your final synthesized plan for the user, you MUST extract this exact URL from the tool's output message
    and present it as a clickable markdown link using the format:
    '[Add Event to Google Calendar](THE_EXACT_URL_RETURNED_BY_THIS_TOOL)'.
    Example tool output: 'Success: Generated Google Calendar link... click link: https://calendar.google.com/...'
    Your output in the plan should then contain: '[Add Event to Google Calendar](https://calendar.google.com/...)'

    Returns a success message with the Google Calendar URL or an error message if inputs are invalid.
    """
    if VERBOSE: print(f"--- Planner Tools: Generating Google Calendar link for: {summary} from {start_datetime} to {end_datetime if end_datetime else ' (1hr default)'} ---", file=sys.stderr)
    
    final_end_datetime = end_datetime
    if end_datetime is None or not end_datetime.strip():
        if VERBOSE: print("--- Planner Tools Info: 'end_datetime' not provided or empty. Assuming a default duration of 1 hour. ---", file=sys.stderr)
        try:
            start_dt_obj_for_default = datetime.strptime(start_datetime, "%Y-%m-%d %H:%M:%S")
            final_end_datetime = (start_dt_obj_for_default + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
            if VERBOSE: print(f"--- Planner Tools Info: Calculated end_datetime: {final_end_datetime} ---", file=sys.stderr)
        except ValueError:
            return "Error: Invalid 'start_datetime' format. Cannot calculate default end_datetime. Please provide 'start_datetime' in 'YYYY-MM-DD HH:MM:SS' format."
    
    try:
        start_dt_obj = datetime.strptime(start_datetime, "%Y-%m-%d %H:%M:%S")
        end_dt_obj = datetime.strptime(final_end_datetime, "%Y-%m-%d %H:%M:%S")

        if end_dt_obj <= start_dt_obj:
            return f"Error: end_datetime ({final_end_datetime}) must be after start_datetime ({start_datetime})."

        google_start = _format_datetime_for_google(start_datetime)
        google_end = _format_datetime_for_google(final_end_datetime)

        params = {
            "action": "TEMPLATE",
            "text": summary,
            "dates": f"{google_start}/{google_end}",
            "details": description if description else "",
            "location": location if location else "",
        }
        calendar_url = "https://calendar.google.com/calendar/render?" + urlencode(params)

        return (f"Success: Generated Google Calendar link for event '{summary}'. "
                f"To add this to your calendar, please click the following link: {calendar_url} "
                f"[Note: This link will open Google Calendar to create the event. You may need to sign in.]")

    except ValueError as ve:
        return f"Error: Invalid datetime format provided. {ve}"
    except Exception as e:
        if VERBOSE:
            print(f"--- Planner Tools Error (add_calendar_event): {e} ---", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
        return f"Error: Could not generate calendar link. Details: {e}"

# --- List of tools for the agent ---
active_planner_tools = [
    get_weather_forecast_daily,
    plan_route_ors,
    get_operational_details,
    add_calendar_event,
]
if brave_search_client_instance:
    active_planner_tools.append(general_web_search)
else:
    if VERBOSE: print("--- Planner Tools: `general_web_search` tool is NOT active due to client initialization failure or missing API key. ---", file=sys.stderr)


# --- Testing Block (Optional) ---
if __name__ == '__main__':
    print("--- Testing Planner Tools (ensure .env has API keys) ---")
    
    # Test Weather
    # print("\nTesting Weather (Paris, 2 days):")
    # print(get_weather_forecast_daily.invoke({"city": "Paris", "days": 2}))
    # print("\nTesting Weather (London, 7 days - should trigger typical weather search):")
    # print(get_weather_forecast_daily.invoke({"city": "London", "days": 7}))

    # Test Routing
    print("\nTesting Routing (London to Paris):")
    print(plan_route_ors.invoke({"locations": ["London", "Paris"]}))
    print("\nTesting Routing (Barcelona to Madrid to Lisbon):")
    print(plan_route_ors.invoke({"locations": ["Barcelona", "Madrid", "Lisbon"]}))
    print("\nTesting Routing (Madrid to Gran Canaria - should suggest flight):")
    print(plan_route_ors.invoke({"locations": ["Madrid", "Gran Canaria"]}))


    # Test Operational Details
    # print("\nTesting Operational Details (Eiffel Tower, Paris):")
    # print(get_operational_details.invoke({"place_name": "Eiffel Tower", "location": "Paris"}))

    # Test Calendar
    # print("\nTesting Calendar Event (Meeting):")
    # print(add_calendar_event.invoke({"summary": "Team Meeting", "start_datetime": "2025-06-10 14:00:00", "end_datetime": "2025-06-10 15:30:00", "location": "Office"}))
    # print("\nTesting Calendar Event (Lunch - default duration):")
    # print(add_calendar_event.invoke({"summary": "Lunch with Client", "start_datetime": "2025-06-11 12:30:00"}))


    print(f"\n--- Active planner tools available for import ({len(active_planner_tools)}): {[t.name for t in active_planner_tools]} ---")

# --- END OF FILE planner_tools.py ---