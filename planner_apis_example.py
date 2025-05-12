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


def route_api():
    # === OpenRouteService API ===
    print("\nEnter coordinates (longitude,latitude) or city names for the route. Enter 'done' when finished:")

    def get_coordinates(location):
        """If the input is a city name, convert it to coordinates."""
        if ',' not in location:
            geo_url = f"http://api.openweathermap.org/geo/1.0/direct?q={location}&limit=1&appid={open_weather_api_key}"
            response = requests.get(geo_url)
            if response.status_code == 200 and response.json():
                data = response.json()[0]
                return [data['lon'], data['lat']]
        else:
            try:
                lon, lat = map(float, location.split(','))
                return [lon, lat]
            except ValueError:
                print(f"Invalid coordinate format: {location}")
        return None

    coordinates = []
    while True:
        location = input("Location (city or 'lon,lat'): ")
        if location.lower() == 'done':
            break
        coord = get_coordinates(location)
        if coord:
            coordinates.append(coord)

    if len(coordinates) < 2:
        print("\nAt least two points are required to calculate the route.")
    else:
        print("\nCalculating the optimal route...")

        # OpenRouteService request
        route_url = "https://api.openrouteservice.org/v2/directions/driving-car"
        headers = {
            'Authorization': open_route_service_api_key,
            'Content-Type': 'application/json'
        }

        # Prepare the request body (without roundtrip)
        body = {
            'coordinates': coordinates,
            'instructions': True   # Instrucciones activadas
        }

        # Make the API request
        route_response = requests.post(route_url, headers=headers, data=json.dumps(body))

        if route_response.status_code == 200:
            print("\nOpenRouteService API Test Successful:")
            route_data = route_response.json()
            
            # === Resumen General ===
            distance = route_data['routes'][0]['summary']['distance'] / 1000
            duration = route_data['routes'][0]['summary']['duration'] / 60
            steps = len(route_data['routes'][0]['segments'][0]['steps'])
            
            print(f"\n=== Route Summary ===")
            print(f"Total Distance: {distance:.2f} km")
            print(f"Estimated Travel Time: {duration:.2f} minutes")
            print(f"Number of Steps: {steps}")
            
            # === Detalle Paso a Paso ===
            print(f"\n=== Step-by-Step Directions ===")
            for idx, step in enumerate(route_data['routes'][0]['segments'][0]['steps'], start=1):
                instruction = step['instruction']
                step_distance = step['distance'] / 1000
                step_duration = step['duration'] / 60
                way_point = step['way_points']
                print(f"\nStep {idx}:")
                print(f"  - Instruction: {instruction}")
                print(f"  - Distance: {step_distance:.2f} km")
                print(f"  - Estimated Time: {step_duration:.2f} minutes")
                print(f"  - Way Points: {way_point}")

        else:
            print("\nOpenRouteService API Test Failed:", route_response.status_code, route_response.text)

if __name__ == "__main__":
    print("Welcome to the Weather and Route Planner API Example!")
    while True:
        print("\nChoose an option:")
        print("1. Check Weather")
        print("2. Calculate Route")
        print("3. Exit")
        choice = input("Enter your choice (1/2/3): ")

        if choice == '1':
            weather_api()
        elif choice == '2':
            route_api()
        elif choice == '3':
            print("Exiting the program.")
            break
        else:
            print("Invalid choice. Please try again.")