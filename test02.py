import math
import requests

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

def get_forecast_by_location(lat, lon):
    api_key = "v2:c301d3e632007d24480125f32e20315e53467c6bca4707f4cc08a8dbe9353a74:uR417bu2gr6LnnYc14EzFWgRT9iHKsgb"
    headers = {"api-key": api_key}

    # ✅ Fetch data FIRST
    r = requests.get("https://api-open.data.gov.sg/v2/real-time/api/two-hr-forecast", headers=headers, timeout=5)
    r.raise_for_status()
    data = r.json()

    # ✅ Access data AFTER fetching
    area_metadata = data['data']['area_metadata']
    forecasts     = data['data']['items'][0]['forecasts']  # ✅ correct path

    # Build lookup dict: area name → forecast
    forecast_lookup = {f['area']: f['forecast'] for f in forecasts}

    # Find closest area by distance
    closest_area = min(
        area_metadata,
        key=lambda a: haversine(lat, lon, a['label_location']['latitude'], a['label_location']['longitude'])
    )

    area_name = closest_area['name']
    area_name = 'Changi'
    forecast  = forecast_lookup.get(area_name, 'N/A')
    return area_name, forecast


lat, lon = 1.2966, 103.8520

area, forecast = get_forecast_by_location(lat, lon)
print(f"Closest area : {area}")
print(f"Forecast     : {forecast}")