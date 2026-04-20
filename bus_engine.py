import json
import math
import requests
import os
from datetime import datetime, timezone
from collections import defaultdict

LTA_API_BASE = "https://datamall2.mytransport.sg/ltaodataservice"

class BusSmartEngine:
    def __init__(self):
        # 路径确保在当前目录下     
        base_path = os.path.dirname(__file__)
        with open(os.path.join(base_path, "bus_routes.json"), 'r', encoding='utf-8') as f:
            self.routes = json.load(f)
        with open(os.path.join(base_path, "bus_stops.json"), 'r', encoding='utf-8') as f:
            self.stops = json.load(f)
        
        self.stop_map = {s['BusStopCode']: s for s in self.stops}
        self.stop_to_routes = defaultdict(list)
        for r in self.routes:
            self.stop_to_routes[r['BusStopCode']].append(r)
        self._arrival_cache = {}

    def _route_key(self, route):
        return (route.get("ServiceNo"), route.get("Direction"))

    def _stop_payload(self, stop, user_lat=None, user_lon=None):
        payload = {
            "code": stop["BusStopCode"],
            "name": stop.get("Description", ""),
            "latitude": float(stop["Latitude"]),
            "longitude": float(stop["Longitude"]),
        }
        if user_lat is not None and user_lon is not None:
            payload["distance_m"] = int(round(self.haversine(user_lat, user_lon, stop["Latitude"], stop["Longitude"])))
        return payload

    def haversine(self, lat1, lon1, lat2, lon2):
        R = 6371000
        p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
        dphi, dlamb = math.radians(float(lat2-lat1)), math.radians(float(lon2-lon1))
        a = math.sin(dphi/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlamb/2)**2
        return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))

    def _parse_arrival_payload(self, payload):
        services = payload.get("Services", []) if isinstance(payload, dict) else []
        arrival_map = {}
        for svc in services:
            service_no = svc.get("ServiceNo")
            next_bus = svc.get("NextBus", {}) or {}
            est_time = next_bus.get("EstimatedArrival")
            if not service_no or not est_time:
                continue
            try:
                eta_dt = datetime.fromisoformat(est_time.replace("Z", "+00:00"))
                diff = (eta_dt - datetime.now(timezone.utc)).total_seconds() / 60
            except Exception:
                continue

            load_map = {"SEA": "有座", "SDA": "较挤", "LSD": "拥挤"}
            arrival_map[str(service_no)] = {
                "minutes": max(0, int(diff)),
                "load": load_map.get(next_bus.get("Load"), "未知"),
                "is_wab": next_bus.get("Feature") == "WAB",
                "raw_eta": est_time,
            }
        return arrival_map

    def get_realtime_arrivals(self, stop_code):
        api_key = os.getenv("LTA_API_KEY")
        if not api_key:
            return {}

        cached = self._arrival_cache.get(stop_code)
        if cached and (datetime.now(timezone.utc) - cached[0]).total_seconds() < 20:
            return cached[1]

        headers = {"AccountKey": api_key, "Accept": "application/json"}
        url = f"https://datamall2.mytransport.sg/ltaodataservice/v3/BusArrival"
        params = {"BusStopCode": stop_code}
        try:
            r = requests.get(url, headers=headers, params=params, timeout=5)
            r.raise_for_status()
            arrivals = self._parse_arrival_payload(r.json())
            self._arrival_cache[stop_code] = (datetime.now(timezone.utc), arrivals)
            return arrivals
        except Exception:
            return {}

    def get_realtime_v3(self, stop_code, service_no):
        arrivals = self.get_realtime_arrivals(stop_code)
        return arrivals.get(str(service_no))

    def _candidate_stops(self, lat, lon, radius_m=400):
        return [
            s["BusStopCode"]
            for s in self.stops
            if self.haversine(lat, lon, s["Latitude"], s["Longitude"]) <= radius_m
        ]

    def nearby_stops(self, lat, lon, radius_m=600, limit=8):
        nearby = []
        for stop in self.stops:
            distance = self.haversine(lat, lon, stop["Latitude"], stop["Longitude"])
            if distance <= radius_m:
                nearby.append(self._stop_payload(stop, lat, lon))

        nearby.sort(key=lambda item: item["distance_m"])

        for stop in nearby[:limit]:
            services = sorted({route["ServiceNo"] for route in self.stop_to_routes.get(stop["code"], [])}, key=lambda x: (len(x), x))
            stop["services"] = services

            arrivals_by_service = self.get_realtime_arrivals(stop["code"])
            arrivals = []
            seen = set()
            for svc in services:
                if svc in seen:
                    continue
                seen.add(svc)
                live = arrivals_by_service.get(svc)
                arrivals.append({
                    "service": svc,
                    "minutes": live["minutes"] if live else None,
                    "load": live["load"] if live else None,
                    "is_wab": live["is_wab"] if live else False,
                })

            arrivals.sort(key=lambda item: (item["minutes"] is None, item["minutes"] if item["minutes"] is not None else 9999, item["service"]))
            stop["nearest_arrival"] = arrivals[0] if arrivals else None
            stop["arrivals"] = arrivals[:3]
        return nearby[:limit]

    def best_route_candidates(self, s_lat, s_lon, e_lat, e_lon):
        dist = self.haversine(s_lat, s_lon, e_lat, e_lon)
        if dist < 800:
            return {"type": "walk", "dist_m": round(dist), "minutes": max(1, round(dist / 80))}

        start_cluster = self._candidate_stops(s_lat, s_lon, 400)
        end_cluster = self._candidate_stops(e_lat, e_lon, 400)
        if not start_cluster or not end_cluster:
            return {"type": "none", "message": "范围内无可用站点。"}

        # --- 1. 直达搜索 (Direct Search) ---
        direct_options = []
        for s_code in start_cluster:
            s_map = {self._route_key(r): r for r in self.stop_to_routes[s_code]}
            for e_code in end_cluster:
                for r_e in self.stop_to_routes[e_code]:
                    key = self._route_key(r_e)
                    if key in s_map:
                        r_s = s_map[key]
                        if int(r_e['StopSequence']) > int(r_s['StopSequence']):
                            direct_options.append({
                                "service": r_e['ServiceNo'],
                                "from_name": self.stop_map[s_code]['Description'],
                                "from_code": s_code,
                                "to_name": self.stop_map[e_code]['Description'],
                                "stops": int(r_e['StopSequence']) - int(r_s['StopSequence']),
                                "dist_km": round(float(r_e['Distance']) - float(r_s['Distance']), 2)
                            })
        
        if direct_options:
            unique = {}
            for opt in direct_options:
                if opt['service'] not in unique or opt['stops'] < unique[opt['service']]['stops']:
                    unique[opt['service']] = opt

            final_list = list(unique.values())

            # --- 核心修改：打散并注入数据 ---
            flattened_options = []
            for opt in final_list:
                stop_code = str(opt['from_code']).strip()
                svc_no = str(opt['service']).strip().upper()
                
                # 获取该站点的实时数据池
                arrivals = self.get_realtime_arrivals(stop_code)
                
                # 弹性匹配 (36 vs 036)
                #live = arrivals.get(svc_no) or arrivals.get(svc_no.zfill(2))
                live = arrivals.get('36')
                print(f"DEBUG: 站点bbbbb {svc_no} bus:{arrivals} ")
                # 构造扁平化对象，不再使用嵌套的 'live' 字典
                flat_opt = {
                    "service": opt['service'],
                    "from_name": opt['from_name'],
                    "from_code": opt['from_code'],
                    "to_name": opt['to_name'],
                    "stops": opt['stops'],
                    "dist_km": opt['dist_km'],
                    
                    # 💡 直接提取实时字段，确保序列化 100% 成功
                    "live_minutes": live.get('minutes') if live else None,
                    #"live_minutes": 100,
                    "live_load": live.get('load') if live else "N/A",
                    "live_is_wab": live.get('is_wab') if live else False,
                    "live_next_minutes": live.get('next_minutes') if live else None
                }
                flattened_options.append(flat_opt)

            # --- 基于实时分钟数排序 ---
            # flattened_options.sort(key=lambda x: (
            #     0 if x['live_minutes'] is not None else 1, 
            #     x['live_minutes'] if x['live_minutes'] is not None else 999
            # ))

            return {
                "status": "success",
                "type": "bus",
                "options": flattened_options[:3], # 取前 3 个最快的
                "message": "找到直达方案。"
            }
        # --- 2. 转乘搜索 (Intersection Search) ---
        # 逻辑：Leg1 线路经过的站点 ∩ Leg2 线路经过的站点
        for s_code in start_cluster:
            for r_s in self.stop_to_routes[s_code]:
                svc_a = r_s['ServiceNo']
                dir_a = r_s.get('Direction', '1')
                full_route_a = self.service_to_route[(svc_a, dir_a)]
                
                # 遍历线路 A 的后续站点作为“潜在转乘点”
                for node_a in full_route_a:
                    if int(node_a['StopSequence']) <= int(r_s['StopSequence']): continue
                    
                    t_code = node_a['BusStopCode'] # 潜在转乘站
                    # 检查转乘站是否有线路直达终点簇
                    for r_t in self.stop_to_routes[t_code]:
                        svc_b = r_t['ServiceNo']
                        dir_b = r_t.get('Direction', '1')
                        full_route_b = self.service_to_route[(svc_b, dir_b)]
                        
                        for node_b_end in full_route_b:
                            if node_b_end['BusStopCode'] in end_cluster and int(node_b_end['StopSequence']) > int(r_t['StopSequence']):
                                # 命中转乘点！
                                return {
                                    "type": "transfer",
                                    "message": "未找到直达，建议转乘方案。",
                                    "options": [{
                                        "leg1": {"service": svc_a, "from_name": self.stop_map[s_code]['Description'], "transfer_at": self.stop_map[t_code]['Description']},
                                        "leg2": {"service": svc_b, "to_name": self.stop_map[node_b_end['BusStopCode']]['Description']}
                                    }]
                                }
        return {"type": "none", "message": "未找到可行方案。"}
    

    def route_summary(self, service_no):
        entries = [r for r in self.routes if r["ServiceNo"] == service_no]
        if not entries:
            return None

        # 保留较简洁的线路信息，按顺序排列
        entries.sort(key=lambda item: (int(item.get("Direction", 0)), int(item.get("StopSequence", 0))))
        grouped = {}
        for r in entries:
            key = str(r.get("Direction", "1"))
            grouped.setdefault(key, []).append({
                "stop_code": r["BusStopCode"],
                "stop_name": self.stop_map.get(r["BusStopCode"], {}).get("Description", ""),
                "sequence": int(r.get("StopSequence", 0)),
                "distance_km": float(r.get("Distance", 0)),
            })

        return {
            "service": service_no,
            "directions": grouped,
        }

    def plan_trip(self, s_lat, s_lon, e_lat, e_lon):
        return self.best_route_candidates(s_lat, s_lon, e_lat, e_lon)

    def get_traffic_incidents(self):
        api_key = os.getenv("LTA_API_KEY")
        if not api_key:
            return []
        headers = {"AccountKey": api_key, "Accept": "application/json"}
        try:
            r = requests.get(f"{LTA_API_BASE}/TrafficIncidents", headers=headers, timeout=5)
            r.raise_for_status()
            data = r.json()
            return data.get("value", [])
        except Exception:
            return []

    def get_train_service_alerts(self):
        api_key = os.getenv("LTA_API_KEY")
        if not api_key:
            return []
        headers = {"AccountKey": api_key, "Accept": "application/json"}
        try:
            r = requests.get(f"{LTA_API_BASE}/TrainServiceAlerts", headers=headers, timeout=5)
            r.raise_for_status()
            data = r.json()
            return data.get("value", [])
        except Exception:
            return []

    def get_facilities_maintenance(self):
        api_key = os.getenv("LTA_API_KEY")
        if not api_key:
            return []
        headers = {"AccountKey": api_key, "Accept": "application/json"}
        try:
            r = requests.get(f"{LTA_API_BASE}/v2/FacilitiesMaintenance", headers=headers, timeout=5)
            r.raise_for_status()
            data = r.json()
            return data.get("value", [])
        except Exception:
            return []

    def get_air_temperature(self, lat=None, lon=None):
        """
        Fetch real-time air temperature data and return the temperature at the nearest station to the given lat/lon.
        Returns None if unavailable.
        """
        # Use DATAGOVSG key or fallback to LTA_API_KEY for compatibility
        api_key = os.getenv("DATAGOVSG") or os.getenv("LTA_API_KEY")
        if not api_key:
            return None
        # Use correct header name for Data.gov.sg API
        headers = {"api-key": api_key}
        try:
            r = requests.get(f"https://api-open.data.gov.sg/v2/real-time/api/air-temperature", headers=headers, timeout=5)
            r.raise_for_status()
            data = r.json().get("items", [])[0]
            readings = data.get("readings", [])
            print(f"DEBUG: 站点temerature {readings} ")
            if not readings:
                return None
            # Prefer reading from station S24 if available
            for rec in readings:
                if rec.get('stationId') == 'S24':
                    return rec.get('value')
            # If lat/lon provided, find nearest; else, average
            if lat is not None and lon is not None:
                def dist(r):
                    return self.haversine(lat, lon, r.get('latitude'), r.get('longitude'))
                nearest = min(readings, key=dist)
                return nearest.get('value')
            # fallback to average
            vals = [r.get('value') for r in readings if 'value' in r]
            return sum(vals)/len(vals) if vals else None
        except Exception:
            return None

    def get_two_hr_forecast(self):
        """
        Fetch 2-hour weather forecast for Singapore regions.
        Returns list of {'area': ..., 'forecast': ...}.
        """
        # Use DATAGOVSG key or fallback to LTA_API_KEY for compatibility
        api_key = os.getenv("DATAGOVSG") or os.getenv("LTA_API_KEY")
        if not api_key:
            return []
        # Use correct header name for Data.gov.sg API
        headers = {"api-key": api_key}
        try:
            r = requests.get("https://api-open.data.gov.sg/v2/real-time/api/two-hr-forecast", headers=headers, timeout=5)
            r.raise_for_status()
            data = r.json().get("items", [{}])[0]
            print(f"DEBUG: get_two_hr_forecast {data} ")
            return data.get("forecasts", [])
        except Exception:
            return []