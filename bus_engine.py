import json
import math
import requests
import os
from datetime import datetime, timezone
from collections import defaultdict

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
            return {
                "type": "walk",
                "dist_m": round(dist),
                "minutes": max(1, round(dist / 80)),
                "message": "目的地很近，建议步行。",
            }

        start_cluster = self._candidate_stops(s_lat, s_lon, 400)
        end_cluster = self._candidate_stops(e_lat, e_lon, 400)
        if not start_cluster or not end_cluster:
            return {"type": "none", "message": "暂无可用巴士方案。"}

        raw_options = []
        for s_code in start_cluster:
            s_routes = {(r['ServiceNo'], r['Direction']): r for r in self.stop_to_routes.get(s_code, [])}
            for e_code in end_cluster:
                if s_code == e_code:
                    continue
                for r_end in self.stop_to_routes.get(e_code, []):
                    key = self._route_key(r_end)
                    if key not in s_routes:
                        continue
                    r_start = s_routes[key]
                    if int(r_end['StopSequence']) > int(r_start['StopSequence']):
                        raw_options.append({
                            "service": r_end['ServiceNo'],
                            "direction": str(r_end.get('Direction', '1')),
                            "from_name": self.stop_map[s_code]['Description'],
                            "from_code": s_code,
                            "to_name": self.stop_map[e_code]['Description'],
                            "stops": int(r_end['StopSequence']) - int(r_start['StopSequence']),
                            "dist_km": round(float(r_end['Distance']) - float(r_start['Distance']), 2),
                            "start_seq": int(r_start['StopSequence']),
                            "end_seq": int(r_end['StopSequence']),
                        })

        unique_results = {}
        for opt in raw_options:
            svc = opt['service']
            if svc not in unique_results or opt['stops'] < unique_results[svc]['stops']:
                unique_results[svc] = opt

        final_options = list(unique_results.values())
        for opt in final_options:
            opt['live'] = self.get_realtime_v3(opt['from_code'], opt['service'])
            opt['confidence'] = max(0, 100 - opt['stops'] * 8 - (opt['live']['minutes'] if opt.get('live') else 18))

        final_options.sort(key=lambda x: (
            0 if x.get('live') else 1,
            x['live']['minutes'] if x.get('live') else 999,
            x['stops'],
            x['confidence'],
        ))
        return {
            "type": "bus",
            "best": final_options[0] if final_options else None,
            "options": final_options[:3],
            "message": "已计算最佳巴士方案。" if final_options else "暂无直达巴士。",
        }

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