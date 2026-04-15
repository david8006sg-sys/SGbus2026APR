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

        # 2. 立即加载并关联所有 JSON 数据
        # 这样 main.py 启动时，数据就已经准备好了
        self._initialize_data()
        
        # print(f"✅ [INIT] Engine Ready. Loaded {len(self.stop_map)} stops.", flush=True)

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
        # """
        # 分层路径规划引擎
        # Tier 1: 步行评估 (Walking)
        # Tier 2: 直达巴士搜索 (Direct)
        # Tier 3: 一次换乘搜索 (Transfer)
        # """
        
        # --- Tier 1: 步行评估 (Walking) ---
        dist = self.haversine(s_lat, s_lon, e_lat, e_lon)
        if dist < 800:
            return {
                "type": "walk",
                "dist_m": round(dist),
                "minutes": max(1, round(dist / 80)),
                "message": "目的地很近，建议步行。",
            }

        # --- 站簇识别 (Cluster Detection) ---
        # 预先筛选起点和终点 400 米内的站点，减少后续计算量
        start_cluster = self._candidate_stops(s_lat, s_lon, 400)
        end_cluster = self._candidate_stops(e_lat, e_lon, 400)
        
        if not start_cluster or not end_cluster:
            return {"type": "none", "message": "起点或终点周边暂无可用巴士站。"}

        # --- Tier 2: 直达搜索 (Direct Search) ---
        direct_options = self._find_direct_routes(start_cluster, end_cluster)
        
        if direct_options:
            # 对直达方案进行排序并获取实时数据
            processed_direct = self._process_options(direct_options)
            return {
                "type": "bus",
                "mode": "direct",
                "best": processed_direct[0] if processed_direct else None,
                "options": processed_direct[:3],
                "message": "为您找到直达巴士方案。"
            }

        # --- Tier 3: 转乘搜索 (One-Transfer Search) ---
        # 如果没有直达，启动基于路径相交的换乘算法
        transfer_options = self._find_transfer_routes(start_cluster, end_cluster)
        
        if transfer_options:
            return {
                "type": "bus",
                "mode": "transfer",
                "options": transfer_options[:2], # 换乘方案通常返回前 2 个最优解
                "message": "直达不可行，已为您计算转乘方案。"
            }

        return {"type": "none", "message": "暂无直达或一次转乘的巴士方案。"}

    def _find_direct_routes(self, start_cluster, end_cluster):
        """逻辑层：直达线路搜索"""
        raw_options = []
        for s_code in start_cluster:
            # 获取起点站所有线路字典: {(Svc, Dir): RouteInfo}
            s_routes = {self._route_key(r): r for r in self.stop_to_routes.get(s_code, [])}
            
            for e_code in end_cluster:
                if s_code == e_code: continue
                
                for r_end in self.stop_to_routes.get(e_code, []):
                    key = self._route_key(r_end)
                    if key in s_routes:
                        r_start = s_routes[key]
                        # 方向校验：StopSequence 必须递增
                        if int(r_end['StopSequence']) > int(r_start['StopSequence']):
                            # 💡 在这里调用！将搜索到的原始数据“格式化”为前端需要的 Polyline 数据
                            leg_data = self._format_leg(s_code, e_code, r_start, r_end)
                            raw_options.append(self._format_leg(s_code, e_code, r_start, r_end))
        return raw_options

    def _find_transfer_routes(self, start_cluster, end_cluster):
        """逻辑层：基于交点搜索的转乘算法"""
        transfer_results = []
        
        # 建立终点簇线路索引，加速匹配
        target_routes = {}
        for e_code in end_cluster:
            for r in self.stop_to_routes.get(e_code, []):
                target_routes[self._route_key(r)] = (e_code, r)

        for s_code in start_cluster:
            for r_start_a in self.stop_to_routes.get(s_code, []):
                route_key_a = self._route_key(r_start_a)
                # 获取线路 A 所有的后续路径
                full_route_a = self.service_to_route.get(route_key_a, [])
                
                for hub in full_route_a:
                    # 必须是上车点之后的站点
                    if int(hub['StopSequence']) <= int(r_start_a['StopSequence']):
                        continue
                    
                    hub_code = hub['BusStopCode']
                    # 枢纽匹配：检查中转站是否有线路 B 能到终点
                    for r_start_b in self.stop_to_routes.get(hub_code, []):
                        route_key_b = self._route_key(r_start_b)
                        if route_key_b == route_key_a: continue # 避免同线转乘
                        
                        if route_key_b in target_routes:
                            e_code, r_end_b = target_routes[route_key_b]
                            # 方向校验
                            if int(r_end_b['StopSequence']) > int(r_start_b['StopSequence']):
                                # 📍 【在此处加入 _format_leg 调用】
                                # 分别格式化第一程和第二程，自动生成各自的 polyline 坐标数组
                                leg1_data = self._format_leg(s_code, hub_code, r_start_a, hub)
                                leg2_data = self._format_leg(hub_code, e_code, r_start_b, r_end_b)

                                transfer_results.append({
                                    "leg1": self._format_leg(s_code, hub_code, r_start_a, hub),
                                    "leg2": self._format_leg(hub_code, e_code, r_start_b, r_end_b),
                                    "total_stops": (int(hub['StopSequence']) - int(r_start_a['StopSequence'])) + 
                                                (int(r_end_b['StopSequence']) - int(r_start_b['StopSequence']))
                                })
        
        transfer_results.sort(key=lambda x: x['total_stops'])
        return transfer_results

    def _format_leg(self, s_code, e_code, r_start, r_end):
        """辅助：构建单一行程段"""
        return {
            "service": r_end['ServiceNo'],
            "direction": str(r_end.get('Direction', '1')),
            "from_code": s_code,
            "from_name": self.stop_map[s_code]['Description'],
            "to_code": e_code,
            "to_name": self.stop_map[e_code]['Description'],
            "stops": int(r_end['StopSequence']) - int(r_start['StopSequence']),
            "dist_km": round(float(r_end['Distance']) - float(r_start['Distance']), 2),
            "live": self.get_realtime_v3(s_code, r_end['ServiceNo'])
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
        
    def _initialize_data(self):
        # 1. 加载原始数据（它目前是个列表）
        raw_stops = self._load_json("bus_stops.json")
        
        # 💡 关键修复：将列表转换为字典 { "站点代码": {站点信息} }
        if isinstance(raw_stops, list):
            self.stop_map = {stop['BusStopCode']: stop for stop in raw_stops if 'BusStopCode' in stop}
        else:
            self.stop_map = raw_stops # 如果已经是字典则保持不变

        # 2. 加载线路数据
        raw_routes = self._load_json("bus_routes.json")
        
        self.service_to_route = {}
        for r in raw_routes:
            key = (r['ServiceNo'], r['Direction'])
            if key not in self.service_to_route:
                self.service_to_route[key] = []
            
            # 💡 现在 self.stop_map 是字典了，.get() 就不会报错了
            stop_code = r['BusStopCode']
            stop_info = self.stop_map.get(stop_code, {})
            
            self.service_to_route[key].append({
                "BusStopCode": stop_code,
                "StopSequence": int(r['StopSequence']),
                "Latitude": float(stop_info.get('Latitude', 0)),
                "Longitude": float(stop_info.get('Longitude', 0))
            })
        
   
    def _format_leg(self, s_code, e_code, r_start, r_end):
        svc = r_start['ServiceNo']
        direction = r_start['Direction']
        
        # 提取该段行程经过的所有坐标点
        full_path = self.service_to_route.get((svc, direction), [])
        polyline = []
        
        start_seq = int(r_start['StopSequence'])
        end_seq = int(r_end['StopSequence'])
        
        for stop in full_path:
            if start_seq <= stop['StopSequence'] <= end_seq:
                # 存入 Leaflet 需要的 [lat, lon] 格式
                polyline.append([stop['Latitude'], stop['Longitude']])

        # 获取实时到站信息
        live = self.get_realtime_arrivals(s_code).get(svc)

        return {
            "service": svc,
            "from_code": s_code,
            "from_name": self.stop_map[s_code]['Description'],
            "to_code": e_code,
            "to_name": self.stop_map[e_code]['Description'],
            "stops": end_seq - start_seq,
            "dist_km": round(float(r_end['Distance']) - float(r_start['Distance']), 2),
            "polyline": polyline,  # 👈 关键：传给前端绘制线段
            "live_minutes": live['minutes'] if live else None
        }
    
    def _load_json(self, filename):
        """通用 JSON 加载辅助函数"""
        # 获取当前文件所在的绝对路径，确保在 Azure 环境下也能找到文件
        base_path = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(base_path, filename)
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"❌ 错误: 找不到文件 {file_path}")
            return {}
        except Exception as e:
            print(f"❌ 加载 {filename} 出错: {e}")
            return {}
    
    def _process_options(self, raw_options):
    # """
    # 对直达线路进行去重、排序并注入实时数据
    # """
        if not raw_options:
            return []

        # 1. 线路去重：如果同一路车有多个站点可选，保留站数最少的
        unique_results = {}
        for opt in raw_options:
            svc = opt['service']
            if svc not in unique_results or opt['stops'] < unique_results[svc]['stops']:
                unique_results[svc] = opt

        final_options = list(unique_results.values())

        # 2. 注入实时到站数据并计算置信度 (Confidence)
        for opt in final_options:
            # 获取实时数据
            opt['live'] = self.get_realtime_v3(opt['from_code'], opt['service'])
            
            # 计算置信度：基准 100分，每多一站扣 8分，每等一分钟扣 1分
            wait_mins = opt['live']['minutes'] if opt.get('live') and opt['live']['minutes'] is not None else 18
            opt['confidence'] = max(0, 100 - (opt['stops'] * 8) - wait_mins)

        # 3. 最终排序：有实时数据的排前面，然后按到站时间，最后按站数
        final_options.sort(key=lambda x: (
            0 if x.get('live') and x['live']['minutes'] is not None else 1,
            x['live']['minutes'] if x.get('live') and x['live']['minutes'] is not None else 999,
            x['stops']
        ))

        return final_options