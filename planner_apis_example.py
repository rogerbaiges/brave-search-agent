import os
import requests
import json
import pandas as pd # Keep for weather_api if it was using it
from dotenv import load_dotenv
from urllib.parse import urlencode, quote_plus # Added quote_plus
from datetime import datetime, timedelta
import math
from typing import Optional # Added for type hinting

# Load environment variables from .env file
load_dotenv()

# Get API keys from environment variables
open_weather_api_key = os.getenv('OPEN_WEATHER_API_KEY')
open_route_service_api_key = os.getenv('OPEN_ROUTE_SERVICE_API_KEY')

# --- Helper for Haversine Distance (Unchanged) ---
def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    lat1_rad, lon1_rad, lat2_rad, lon2_rad = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad
    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# --- weather_api (Identical to your last provided version) ---
def weather_api():
    city = input("Enter the city to check the weather: ")
    days_input_str = input("Enter number of days for forecast (e.g., 5 for next 5 days, 30 for a month out): ")
    try:
        days_to_forecast = int(days_input_str)
        if days_to_forecast <= 0:
            print("Number of days must be positive.")
            return
    except ValueError:
        print("Invalid number of days.")
        return

    geo_url = f"http://api.openweathermap.org/geo/1.0/direct?q={city}&limit=1&appid={open_weather_api_key}"
    geo_response = requests.get(geo_url)
    lat, lon = None, None

    if geo_response.status_code == 200 and geo_response.json():
        coordinates_data = geo_response.json()[0]
        lat, lon = coordinates_data['lat'], coordinates_data['lon']
        print(f"\nCoordinates for {city}: Latitude = {lat}, Longitude = {lon}")
    else:
        print(f"\nFailed to get coordinates for the city: {city}")
        if ',' in city:
            city_part = city.split(',')[0].strip()
            print(f"Attempting geocoding for '{city_part}'...")
            geo_url = f"http://api.openweathermap.org/geo/1.0/direct?q={city_part}&limit=1&appid={open_weather_api_key}"
            geo_response = requests.get(geo_url)
            if geo_response.status_code == 200 and geo_response.json():
                coordinates_data = geo_response.json()[0]
                lat, lon = coordinates_data['lat'], coordinates_data['lon']
                print(f"Coordinates for {city_part}: Latitude = {lat}, Longitude = {lon}")
            else:
                print(f"Still failed to get coordinates for {city_part}.")
                return
        else:
            return
            
    today = datetime.now().date()
    
    if days_to_forecast > 5:
        print(f"\nPrecise forecast for {city} beyond 5 days is not available via this API.")
        target_date_for_typical = today + timedelta(days=days_to_forecast // 2) 
        target_month_year = target_date_for_typical.strftime("%B %Y")
        print(f"Searching for typical weather in {city} during {target_month_year} using a simulated web search...")
        print(f"Simulated Web Search: Typical weather in {city} during {target_month_year} is often mild with occasional showers. Average temperature around 15-20°C. (User should verify this from actual climate data sources).")
        show_5_day = input("Do you also want to see the available 5-day forecast? (yes/no): ").lower()
        if show_5_day != 'yes':
            return
        days_to_forecast = 5 

    if lat is None or lon is None: 
        print("Coordinates not resolved. Cannot fetch weather.")
        return

    forecast_url = f"http://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={open_weather_api_key}&units=metric"
    forecast_response = requests.get(forecast_url)

    if forecast_response.status_code == 200:
        print(f"\n=== {days_to_forecast}-Day Weather Forecast for {city} ===")
        forecast_data = forecast_response.json()
        daily_summary = {}
        target_dates = [today + timedelta(days=i) for i in range(days_to_forecast)]

        for entry in forecast_data.get('list', []):
            entry_datetime = datetime.strptime(entry['dt_txt'], '%Y-%m-%d %H:%M:%S')
            entry_date = entry_datetime.date()
            if entry_date not in target_dates:
                continue

            if entry_date not in daily_summary:
                daily_summary[entry_date] = {'temps': [], 'feels_like': [], 'winds': [], 'precip_prob': [], 'descriptions': set()}
            
            daily_summary[entry_date]['temps'].append(entry['main']['temp'])
            daily_summary[entry_date]['feels_like'].append(entry['main']['feels_like'])
            daily_summary[entry_date]['winds'].append(entry['wind']['speed'])
            daily_summary[entry_date]['precip_prob'].append(entry.get('pop', 0) * 100) 
            daily_summary[entry_date]['descriptions'].add(entry['weather'][0]['description'].capitalize())

        for date_obj in sorted(daily_summary.keys()):
            data = daily_summary[date_obj]
            min_temp_str = f"{min(data['temps']):.1f}" if data['temps'] else 'N/A'
            max_temp_str = f"{max(data['temps']):.1f}" if data['temps'] else 'N/A'
            avg_feels_like_str = f"{sum(data['feels_like'])/len(data['feels_like']):.1f}" if data['feels_like'] else 'N/A'
            avg_wind_str = f"{sum(data['winds'])/len(data['winds']):.1f} m/s" if data['winds'] else 'N/A'
            max_precip_prob_str = f"{max(data['precip_prob']):.0f}%" if data['precip_prob'] else '0%'
            weather_desc_str = ", ".join(sorted(list(data['descriptions']))) if data['descriptions'] else 'N/A'

            print(f"\nDate: {date_obj.strftime('%Y-%m-%d (%A')}")
            print(f"  Temp: {min_temp_str}°C - {max_temp_str}°C (Feels like avg: {avg_feels_like_str}°C)")
            print(f"  Weather: {weather_desc_str}")
            print(f"  Precipitation Chance: ~{max_precip_prob_str}")
            print(f"  Avg Wind: {avg_wind_str}")
    else:
        print("\nFailed to fetch forecast:", forecast_response.status_code, forecast_response.text)

# --- get_coordinates (Identical to your last provided version) ---
def get_coordinates(location_str: str, api_key: str) -> tuple[Optional[tuple[float, float]], str]:
    if not location_str or not location_str.strip():
        print(f"⚠️ Invalid empty location string provided.")
        return None, location_str

    if ',' in location_str:
        parts = location_str.split(',')
        if len(parts) == 2:
            try:
                val1, val2 = float(parts[0].strip()), float(parts[1].strip())
                is_val1_lat, is_val1_lon = -90 <= val1 <= 90, -180 <= val1 <= 180
                is_val2_lat, is_val2_lon = -90 <= val2 <= 90, -180 <= val2 <= 180
                if is_val1_lat and is_val2_lon: 
                    print(f"→ Parsed direct coordinates for '{location_str}': ({val1}, {val2})")
                    return (val1, val2), location_str
                if is_val1_lon and is_val2_lat: 
                    print(f"→ Parsed direct coordinates for '{location_str}' as lon,lat: ({val2}, {val1})")
                    return (val2, val1), location_str 
            except ValueError:
                pass

    def _owm_geocode(query_str, original_input_str):
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
                print(f"→ Geocoded '{query_str}' to: {full_display_name} ({lat:.4f}, {lon:.4f})")
                return (lat, lon), full_display_name
        except requests.exceptions.RequestException as e:
            print(f"⚠️ OWM Geocoding request failed for '{query_str}': {e}")
        except Exception as e:
            print(f"⚠️ Unexpected error during OWM geocoding for '{query_str}': {e}")
        return None, original_input_str 

    coords, display_name = _owm_geocode(location_str.strip(), location_str)
    if coords:
        return coords, display_name

    if ',' in location_str:
        city_part = location_str.split(',')[0].strip()
        if city_part and city_part.lower() != location_str.strip().lower(): 
            print(f"ℹ️ Geocoding for '{location_str}' failed, trying fallback with '{city_part}'...")
            coords, display_name = _owm_geocode(city_part, city_part) 
            if coords:
                return coords, display_name 

    print(f"⚠️ Could not find coordinates for '{location_str}' after all attempts.")
    return None, location_str 

# --- MODIFIED Route API with Multiple Viable Options & Total Summary ---
def route_api():
    print("\nEnter locations (city name or 'lat,lon'). Enter 'done' when finished:")
    locations_input_str = []
    while True:
        location_str = input("Location: ").strip()
        if location_str.lower() == 'done':
            break
        if location_str: 
            locations_input_str.append(location_str)

    if len(locations_input_str) < 2:
        print("\nAt least two locations are required to calculate a route.")
        return

    resolved_locations_data = [] 
    for loc_str in locations_input_str:
        coords_latlon, display_name = get_coordinates(loc_str, open_weather_api_key)
        if coords_latlon:
            ors_coords_lonlat = [coords_latlon[1], coords_latlon[0]]
            resolved_locations_data.append({'latlon': coords_latlon, 'gmaps_name': display_name, 'ors_coords': ors_coords_lonlat, 'name_for_summary': display_name})
        else:
            print(f"Skipping route calculation as '{loc_str}' could not be resolved to coordinates.")
            return 

    if len(resolved_locations_data) < 2:
        print("\nLess than two locations were successfully resolved. Cannot plan route.")
        return

    # Thresholds for heuristics
    MAX_DRIVING_KM_BEFORE_FLIGHT_PRIMARY = 800 # If car route is longer, flight is strongly suggested
    MIN_KM_FOR_FLIGHT_CONSIDERATION = 300      # Min distance to even think about a flight
    MAX_CYCLING_KM = 200
    MAX_WALKING_KM = 40
    
    FLIGHT_SPEED_KMH = 800
    FLIGHT_FIXED_TIME_HOURS = 3.0 

    print("\n=== Route Segment Analysis ===")
    
    trip_segments_details = [] 
    overall_trip_is_primarily_flight = False

    for i in range(len(resolved_locations_data) - 1):
        start_data = resolved_locations_data[i]
        end_data = resolved_locations_data[i+1]

        start_coords_latlon, origin_display_name, start_ors_coords = start_data['latlon'], start_data['name_for_summary'], start_data['ors_coords']
        end_coords_latlon, dest_display_name, end_ors_coords = end_data['latlon'], end_data['name_for_summary'], end_data['ors_coords']
        
        print(f"\n--- Segment {i+1}: {origin_display_name} → {dest_display_name} ---")

        straight_line_dist_km = haversine(start_coords_latlon[0], start_coords_latlon[1], end_coords_latlon[0], end_coords_latlon[1])
        print(f"  (Approximate straight-line distance: {straight_line_dist_km:.0f} km)")

        segment_data = {'origin': origin_display_name, 'destination': dest_display_name, 'viable_modes': {}, 'primary_mode_for_total': None}
        ors_car_route_found_this_segment = False
        car_route_details = None

        # 1. Attempt Car
        if straight_line_dist_km < MAX_DRIVING_KM_BEFORE_FLIGHT_PRIMARY * 1.8: # Allow detour factor
            try:
                url = "https://api.openrouteservice.org/v2/directions/driving-car"
                headers = {'Authorization': open_route_service_api_key, 'Content-Type': 'application/json'}
                body = {'coordinates': [start_ors_coords, end_ors_coords], 'instructions': False}
                resp = requests.post(url, headers=headers, data=json.dumps(body), timeout=10)
                if resp.status_code == 200 and resp.json().get('routes') and resp.json()['routes'][0].get('summary'):
                    data = resp.json()['routes'][0]['summary']
                    dist = data['distance'] / 1000
                    dur = data['duration'] / 60
                    print(f"  Viable Mode: Car - {dist:.1f} km, {dur:.0f} min (~{dur/60:.1f} hours)")
                    segment_data['viable_modes']['Car'] = {'distance_km': dist, 'duration_min': dur}
                    ors_car_route_found_this_segment = True
                    car_route_details = segment_data['viable_modes']['Car']
                elif resp.status_code != 200 :
                    print(f"  Car: ORS API Error ({resp.status_code}). {resp.text[:100]}")
                else:
                    print(f"  Car: No ORS route found by API.")
            except Exception as e:
                print(f"  Car: Error during ORS request - {e}")
        else:
            print(f"  Car: Not considered primary due to very long distance ({straight_line_dist_km:.0f} km).")

        # 2. Consider Flight
        if straight_line_dist_km > MIN_KM_FOR_FLIGHT_CONSIDERATION:
            flight_total_time_hours = (straight_line_dist_km / FLIGHT_SPEED_KMH) + FLIGHT_FIXED_TIME_HOURS
            flight_total_time_min = flight_total_time_hours * 60
            print(f"  Viable Mode: Flight - Approx. {straight_line_dist_km:.0f} km (direct), Estimated ~{flight_total_time_hours:.1f} hours ({flight_total_time_min:.0f} min) total travel time. Please check airline websites for actual schedules and prices.")
            segment_data['viable_modes']['Flight'] = {'distance_km': straight_line_dist_km, 'duration_min': flight_total_time_min, 'is_estimated': True}
            if not ors_car_route_found_this_segment or (car_route_details and flight_total_time_min < car_route_details['duration_min']) or straight_line_dist_km > MAX_DRIVING_KM_BEFORE_FLIGHT_PRIMARY :
                overall_trip_is_primarily_flight = True # If any segment is primarily flight

        # 3. Cycling (if land route seems possible and distance is okay)
        if ors_car_route_found_this_segment and straight_line_dist_km <= MAX_CYCLING_KM:
            try:
                url = "https://api.openrouteservice.org/v2/directions/cycling-regular"
                headers = {'Authorization': open_route_service_api_key, 'Content-Type': 'application/json'}
                body = {'coordinates': [start_ors_coords, end_ors_coords], 'instructions': False}
                resp = requests.post(url, headers=headers, data=json.dumps(body), timeout=10)
                if resp.status_code == 200 and resp.json().get('routes'):
                    data = resp.json()['routes'][0]['summary']
                    dist = data['distance'] / 1000; dur = data['duration'] / 60
                    print(f"  Viable Mode: Cycling - {dist:.1f} km, {dur:.0f} min (~{dur/60:.1f} hours)")
                    segment_data['viable_modes']['Cycling'] = {'distance_km': dist, 'duration_min': dur}
                else: print(f"  Cycling: No ORS route or API error.")
            except: print(f"  Cycling: Error during ORS request.")
        elif ors_car_route_found_this_segment : # Implies land route, but too far
             print(f"  Cycling: Not calculated (distance {straight_line_dist_km:.0f} km > cycling threshold).")

        # 4. Walking (if land route seems possible and distance is okay)
        if ors_car_route_found_this_segment and straight_line_dist_km <= MAX_WALKING_KM:
            try:
                url = "https://api.openrouteservice.org/v2/directions/foot-walking"
                headers = {'Authorization': open_route_service_api_key, 'Content-Type': 'application/json'}
                body = {'coordinates': [start_ors_coords, end_ors_coords], 'instructions': False}
                resp = requests.post(url, headers=headers, data=json.dumps(body), timeout=10)
                if resp.status_code == 200 and resp.json().get('routes'):
                    data = resp.json()['routes'][0]['summary']
                    dist = data['distance'] / 1000; dur = data['duration'] / 60
                    print(f"  Viable Mode: Walking - {dist:.1f} km, {dur:.0f} min (~{dur/60:.1f} hours)")
                    segment_data['viable_modes']['Walking'] = {'distance_km': dist, 'duration_min': dur}
                else: print(f"  Walking: No ORS route or API error.")
            except: print(f"  Walking: Error during ORS request.")
        elif ors_car_route_found_this_segment:
            print(f"  Walking: Not calculated (distance {straight_line_dist_km:.0f} km > walking threshold).")
            
        if not segment_data['viable_modes']:
            print("  No suitable transportation modes found or calculated for this segment.")
        
        # Determine primary mode for this segment for total calculation (Flight > Car > Cycling > Walking)
        if 'Flight' in segment_data['viable_modes']: segment_data['primary_mode_for_total'] = 'Flight'
        elif 'Car' in segment_data['viable_modes']: segment_data['primary_mode_for_total'] = 'Car'
        elif 'Cycling' in segment_data['viable_modes']: segment_data['primary_mode_for_total'] = 'Cycling'
        elif 'Walking' in segment_data['viable_modes']: segment_data['primary_mode_for_total'] = 'Walking'
        
        trip_segments_details.append(segment_data)
    
    # --- Overall Trip Summary & Google Maps Link ---
    if trip_segments_details:
        print("\n\n=== Overall Trip Summary ===")
        total_trip_distance_km = 0
        total_trip_duration_min = 0
        # Consolidate primary modes used across the entire trip
        final_trip_primary_modes = set()

        for i, seg_detail in enumerate(trip_segments_details):
            print(f"\nSegment {i+1}: {seg_detail['origin']} → {seg_detail['destination']}")
            if seg_detail['viable_modes']:
                print("  Options:")
                for mode, data in seg_detail['viable_modes'].items():
                    estimate_tag = "(estimated)" if data.get('is_estimated') else ""
                    print(f"    - {mode}{estimate_tag}: {data['distance_km']:.1f} km, {data['duration_min']:.0f} min (~{data['duration_min']/60:.1f} hours)")
                
                # Add to total based on the segment's primary mode
                primary_seg_mode = seg_detail.get('primary_mode_for_total')
                if primary_seg_mode and primary_seg_mode in seg_detail['viable_modes']:
                    mode_data = seg_detail['viable_modes'][primary_seg_mode]
                    total_trip_distance_km += mode_data['distance_km']
                    total_trip_duration_min += mode_data['duration_min']
                    final_trip_primary_modes.add(primary_seg_mode)
            else:
                print(f"  No transportation modes determined for this segment.")
        
        print("\n------------------------------------")
        modes_str = ", ".join(sorted(list(final_trip_primary_modes))) if final_trip_primary_modes else "N/A"
        print(f"Total Estimated Trip Distance (using primary modes: {modes_str}): {total_trip_distance_km:.1f} km")
        print(f"Total Estimated Trip Duration (using primary modes: {modes_str}): {total_trip_duration_min:.0f} min (~{total_trip_duration_min/60:.1f} hours)")
        print("------------------------------------")

        # Google Maps Link Generation
        gmaps_base_url = "https://www.google.com/maps/dir/?api=1"
        origin_gmaps = quote_plus(resolved_locations_data[0]['gmaps_name'])
        destination_gmaps = quote_plus(resolved_locations_data[-1]['gmaps_name'])
        gmaps_params = {"origin": origin_gmaps, "destination": destination_gmaps}
        
        if len(resolved_locations_data) > 2:
            waypoints_gmaps = "|".join([data['gmaps_name'] for data in resolved_locations_data[1:-1]])
            gmaps_params["waypoints"] = quote_plus(waypoints_gmaps) # Waypoints string itself needs to be quoted if it contains special chars like '|' if not handled by urlencode
            
        gmaps_travel_mode = "driving" # Default
        if overall_trip_is_primarily_flight or "Flight" in final_trip_primary_modes :
            pass 
        elif "Car" in final_trip_primary_modes:
            gmaps_travel_mode = "driving"
        elif "Cycling" in final_trip_primary_modes:
            gmaps_travel_mode = "bicycling"
        elif "Walking" in final_trip_primary_modes:
            gmaps_travel_mode = "walking"
        
        if not (overall_trip_is_primarily_flight or "Flight" in final_trip_primary_modes) :
            gmaps_params["travelmode"] = gmaps_travel_mode

        full_gmaps_url = f"{gmaps_base_url}&{urlencode(gmaps_params)}"
        print("\n--- Google Maps Link for Route Visualization ---")
        print("Note: This link provides a general route. For flights, check airline websites.")
        print(full_gmaps_url)

    elif not trip_segments_details and len(locations_input_str) >=2 :
         print("\nNo route segments could be planned with the provided locations.")


# --- Calendar Link Generation (Identical to your last provided version) ---
def format_datetime_for_google(dt: str) -> str:
    dt_obj = datetime.strptime(dt, "%Y-%m-%d %H:%M:%S")
    return dt_obj.strftime("%Y%m%dT%H%M%S")

def generate_google_calendar_link(summary: str, start_datetime: str, end_datetime: str,
                                   location: str = "", description: str = "") -> str:
    start = format_datetime_for_google(start_datetime)
    end = format_datetime_for_google(end_datetime)
    params = {
        "action": "TEMPLATE",
        "text": summary,
        "dates": f"{start}/{end}",
        "details": description,
        "location": location,
    }
    return "https://calendar.google.com/calendar/render?" + urlencode(params)

# --- Main Loop (Identical to your last provided version) ---
if __name__ == "__main__":
    print("Welcome to the Weather and Route Planner API Example!")
    while True:
        print("\nChoose an option:")
        print("1. Check Weather")
        print("2. Calculate Route")
        print("3. Add Event to Google Calendar")
        print("4. Exit")
        choice = input("Enter your choice (1/2/3/4): ")

        if choice == '1':
            weather_api()
        elif choice == '2':
            route_api()
        elif choice == '3':
            summary = input("Enter event title: ")
            start_datetime = input("Enter start datetime (YYYY-MM-DD HH:MM:SS): ")
            end_datetime = input("Enter end datetime (YYYY-MM-DD HH:MM:SS): ")
            location = input("Enter event location (optional): ")
            description = input("Enter event description (optional): ")
            link = generate_google_calendar_link(summary, start_datetime, end_datetime, location, description)
            print("\nOpen this link to create the event in Google Calendar:")
            print(link)
        elif choice == '4':
            print("Exiting the program.")
            break
        else:
            print("Invalid choice. Please try again.")