import requests
import json         

collection_id = 1456          
url = "https://api-production.data.gov.sg/v2/public/api/collections/{}/metadata".format(collection_id)
        
response = requests.get(url)
#print(response.json())

#api_key = os.getenv("DATAGOVSG") or os.getenv("LTA_API_KEY")
    #if not api_key:
    #    return None
    # Use correct header name for Data.gov.sg API
api_key = "v2:c301d3e632007d24480125f32e20315e53467c6bca4707f4cc08a8dbe9353a74:uR417bu2gr6LnnYc14EzFWgRT9iHKsgb"
headers = {"api-key": api_key}


r = requests.get(f"https://api-open.data.gov.sg/v2/real-time/api/air-temperature", headers=headers, timeout=5)
r.raise_for_status()
data = r.json()
#return data.get("value", [])
#data = r.json().get("items", [])[0]
#readings = data.get("readings", [])

# Navigate to the readings list
readings = data['data']['readings'][0]['data']
value = next((rec['value'] for rec in readings if rec.get('stationId') == 'S24'), None)
#print(value)  # 30.5

#print(f"DEBUG: 站点temerature {data} ")

r = requests.get("https://api-open.data.gov.sg/v2/real-time/api/two-hr-forecast", headers=headers, timeout=5)
r.raise_for_status()  
data = r.json() 
print(data) 