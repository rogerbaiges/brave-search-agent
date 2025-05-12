import os
import requests
import json
import pandas as pd
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get API keys from environment variables
open_weather_api_key = os.getenv('OPEN_WEATHER_API_KEY')
open_route_service_api_key = os.getenv('OPEN_ROUTE_SERVICE_API_KEY')

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
