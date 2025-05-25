import os
import requests
import json
import pandas as pd
from dotenv import load_dotenv
from urllib.parse import urlencode
from datetime import datetime

# Load environment variables from .env file
load_dotenv()

# Get API keys from environment variables
open_weather_api_key = os.getenv('OPEN_WEATHER_API_KEY')
open_route_service_api_key = os.getenv('OPEN_ROUTE_SERVICE_API_KEY')

def weather_api():
    # === Convert City to Coordinates ===
    city = input("Enter the city to check the weather: ")
    geo_url = f"http://api.openweathermap.org/geo/1.0/direct?q={city}&limit=1&appid={open_weather_api_key}"
    geo_response = requests.get(geo_url)

    if geo_response.status_code == 200 and geo_response.json():
        coordinates = geo_response.json()[0]
        lat, lon = coordinates['lat'], coordinates['lon']
        print(f"\nCoordinates for {city}: Latitude = {lat}, Longitude = {lon}")
    else:
        print("\nFailed to get coordinates for the city.")
        exit()

    # === Get 5-Day Weather Forecast (3-hour intervals) ===
    forecast_url = f"http://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={open_weather_api_key}"
    forecast_response = requests.get(forecast_url)

    # Time slots
    time_slots = {
        "Morning": (6, 12),
        "Afternoon": (12, 18),
        "Evening": (18, 24),
        "Night": (0, 6)
    }

    if forecast_response.status_code == 200:
        print(f"\n=== 5-Day Weather Forecast for {city} ===")
        forecast_data = forecast_response.json()
        
        # Organize forecast by date and time slot
        forecast_summary = {}

        for entry in forecast_data['list']:
            date = pd.to_datetime(entry['dt_txt']).date()
            hour = pd.to_datetime(entry['dt_txt']).hour
            temp = entry['main']['temp']
            wind_speed = entry['wind']['speed']
            description = entry['weather'][0]['description']

            # Determine the time slot
            for slot, (start, end) in time_slots.items():
                if start <= hour < end:
                    if date not in forecast_summary:
                        forecast_summary[date] = {slot: {
                            'temps': [temp],
                            'winds': [wind_speed],
                            'descriptions': [description]
                        }}
                    elif slot not in forecast_summary[date]:
                        forecast_summary[date][slot] = {
                            'temps': [temp],
                            'winds': [wind_speed],
                            'descriptions': [description]
                        }
                    else:
                        forecast_summary[date][slot]['temps'].append(temp)
                        forecast_summary[date][slot]['winds'].append(wind_speed)
                        forecast_summary[date][slot]['descriptions'].append(description)

        # Display the summary
        for date, slots in forecast_summary.items():
            print(f"\nDate: {date}")
            for slot, data in slots.items():
                avg_temp = sum(data['temps']) / len(data['temps'])
                min_temp = min(data['temps'])
                max_temp = max(data['temps'])
                avg_wind = sum(data['winds']) / len(data['winds'])
                
                # Get the most common description manually
                descriptions = data['descriptions']
                common_description = max(set(descriptions), key=descriptions.count)

                print(f"  {slot}:")
                print(f"    - Avg Temp: {avg_temp:.2f}K")
                print(f"    - Min Temp: {min_temp:.2f}K")
                print(f"    - Max Temp: {max_temp:.2f}K")
                print(f"    - Avg Wind Speed: {avg_wind:.2f} m/s")
                print(f"    - Most Common Weather: {common_description.capitalize()}")
    else:
        print("\nFailed to fetch 5-day forecast:", forecast_response.status_code, forecast_response.text)


def get_coordinates(location):
    """If the input is a city name, convert it to coordinates."""
    if ',' not in location:
        # Geocode the city name
        geo_url = f"http://api.openweathermap.org/geo/1.0/direct?q={location}&limit=1&appid={open_weather_api_key}"
        response = requests.get(geo_url)
        if response.status_code == 200 and response.json():
            data = response.json()[0]
            print(f"→ Found coordinates for {location}: {data['lat']}, {data['lon']}")
            print([data['lon'], data['lat']])
            return [data['lon'], data['lat']], location
        else:
            print(f"⚠️ Could not find coordinates for {location}. Skipping.")
    else:
        try:
            # Directly parse the coordinates
            lon, lat = map(float, location.split(','))
            print(f"→ Using direct coordinates: {lon}, {lat}")
            print([lat, lon])
            return [lat, lon], f"{lat},{lon}"
        except ValueError:
            print(f"⚠️ Invalid coordinate format: {location}")
    return None, None

def route_api():
    # === OpenRouteService API ===
    print("\nEnter coordinates (longitude,latitude) or city names for the route. Enter 'done' when finished:")
    coordinates = []
    locations = []
    while True:
        location = input("Location (city or 'lon,lat'): ")
        if location.lower() == 'done':
            break
        coord, name = get_coordinates(location)
        if coord:
            coordinates.append(coord)
            locations.append(name)

    if len(coordinates) < 2:
        print("\nAt least two points are required to calculate the route.")
        return

    # Profiles for different types of transport
    profiles = {
        'driving-car': 'Car',
        'cycling-regular': 'Cycling',
        'foot-walking': 'Walking'
    }

    segment_summaries = []
    for i in range(len(coordinates) - 1):
        origin_name = locations[i]
        dest_name = locations[i + 1]
        start = coordinates[i]
        end = coordinates[i + 1]
        leg = {}

        for profile, label in profiles.items():
            url = f"https://api.openrouteservice.org/v2/directions/{profile}"
            headers = {
                'Authorization': open_route_service_api_key,
                'Content-Type': 'application/json'
            }
            body = {
                'coordinates': [start, end],
                'instructions': False
            }
            resp = requests.post(url, headers=headers, data=json.dumps(body))
            if resp.status_code == 200:
                data = resp.json()
                dist = data['routes'][0]['summary']['distance'] / 1000
                dur = data['routes'][0]['summary']['duration'] / 60
                leg[label] = {'distance': dist, 'duration': dur}
            else:
                leg[label] = {'distance': None, 'duration': None}

        # Choose recommended by shortest duration
        valid_legs = {m: v for m, v in leg.items() if v['duration'] is not None}
        if valid_legs:
            rec = min(valid_legs.items(), key=lambda x: x[1]['duration'])[0]
        else:
            rec = None

        leg['recommended'] = rec
        segment_summaries.append((origin_name, dest_name, leg))

    # Display summary
    total_dist = 0.0
    total_dur = 0.0
    print("\n=== Route Summary by Segment ===")
    for idx, (orig, dest, leg) in enumerate(segment_summaries, 1):
        print(f"\nLeg {idx}: {orig} → {dest}")
        for mode in ['Car', 'Cycling', 'Walking']:
            info = leg.get(mode)
            if info and info['distance'] is not None:
                print(f"  {mode}: {info['distance']:.2f} km, {info['duration']:.2f} min")
            else:
                print(f"  {mode}: not available")
        rec = leg.get('recommended')
        if rec:
            rd = leg[rec]['distance']
            rt = leg[rec]['duration']
            print(f"  ⇒ Recommended: {rec} ({rd:.2f} km, {rt:.2f} min)")
            total_dist += rd
            total_dur += rt

    print(f"\nTotal Recommended Distance: {total_dist:.2f} km")
    print(f"Total Recommended Duration: {total_dur:.2f} min")

def format_datetime_for_google(dt: str) -> str:
    """
    Format datetime to YYYYMMDDTHHMMSS for Google Calendar links, in local time.
    
    Args:
        dt (str): Datetime string in format 'YYYY-MM-DD HH:MM:SS'

    Returns:
        str: Google Calendar-compatible datetime (local time, no 'Z')
    """
    dt_obj = datetime.strptime(dt, "%Y-%m-%d %H:%M:%S")
    return dt_obj.strftime("%Y%m%dT%H%M%S")

def generate_google_calendar_link(summary: str, start_datetime: str, end_datetime: str,
                                   location: str = "", description: str = "") -> str:
    """
    Generate a Google Calendar event creation URL with local time.

    Args:
        summary (str): Title of the event.
        start_datetime (str): Start datetime in 'YYYY-MM-DD HH:MM:SS' (local time).
        end_datetime (str): End datetime in 'YYYY-MM-DD HH:MM:SS' (local time).
        location (str): Location of the event (optional).
        description (str): Event description or notes (optional).

    Returns:
        str: A URL to pre-fill an event in Google Calendar.
    """
    start = format_datetime_for_google(start_datetime)
    end = format_datetime_for_google(end_datetime)

    params = {
        "action": "TEMPLATE",
        "text": summary,
        "dates": f"{start}/{end}",  # Local time — no 'Z'
        "details": description,
        "location": location,
    }

    return "https://calendar.google.com/calendar/render?" + urlencode(params)


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