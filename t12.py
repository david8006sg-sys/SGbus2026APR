import os
import json
import math
import requests
from datetime import datetime, timezone
from collections import defaultdict

# --- 全局配置 ---
LTA_API_KEY = os.getenv("LTA_API_KEY", "")
LTA_API_BASE = "https://datamall2.mytransport.sg/ltaodataservice"

class BusSmartEngine:
    def __init__(self, routes_path="bus_routes.json", stops_path="bus_stops.json"):
        print("📂 [System] 正在初始化生产级索引数据库 (V3 Live Ready)...")
        try:
            with open(routes_path, 'r', encoding='utf-8') as f:
                self.routes = json.load(f)
            with open(stops_path, 'r', encoding='utf-8') as f:
                self.stops = json.load(f)
        except FileNotFoundError:
            print("❌ 错误: 未找到本地数据文件。请确保 bus_routes.json 和 bus_stops.json 在当前目录。")
            exit(1)

        # 核心映射索引：建立站点到路线的快速倒排索引
        self.stop_map = {s['BusStopCode']: s for s in self.stops}
        self.stop_to_routes = defaultdict(list)
        for r in self.routes:
            self.stop_to_routes[r['BusStopCode']].append(r)
        print(f"✅ [System] 引擎就绪: 已建立 {len(self.stops)} 个站点和 {len(self.routes)} 条路线记录。")

    # --- 地理计算工具 (Haversine Formula) ---
    def haversine(self, lat1, lon1, lat2, lon2):
        R = 6371000  # 地球半径 (米)
        p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
        dphi, dlamb = math.radians(float(lat2-lat1)), math.radians(float(lon2-lon1))
        a = math.sin(dphi/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlamb/2)**2
        return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))

    # --- 增强型 V3 实时 API 接入 ---
    def get_realtime_v3(self, stop_code, service_no):
        """调用 LTA v3 接口获取精确的到站、拥挤度和车辆信息"""
        headers = {"AccountKey": LTA_API_KEY, "Accept": "application/json"}
        svc = service_no.strip().upper()
        url = f"{LTA_API_BASE}/v3/BusArrival"
        params = {"BusStopCode": stop_code, "ServiceNo": svc}
        
        try:
            r = requests.get(url, headers=headers, params=params, timeout=8)
            data = r.json()
            services = data.get("Services", [])
            if not services: return None
            
            next_bus = services[0].get("NextBus", {})
            est_time = next_bus.get("EstimatedArrival")
            
            if est_time and est_time.strip():
                # 计算到站分钟差 (ETA)
                eta_dt = datetime.fromisoformat(est_time.replace("Z", "+00:00"))
                diff = (eta_dt - datetime.now(timezone.utc)).total_seconds() / 60
                
                # 拥挤度映射
                load_map = {"SEA": "有座", "SDA": "较挤", "LSD": "拥挤"}
                
                return {
                    "minutes": max(0, int(diff)),
                    "load": load_map.get(next_bus.get("Load"), "未知"),
                    "is_wab": next_bus.get("Feature") == "WAB" # Wheelchair Accessible (适合大行李)
                }
            return None
        except Exception as e:
            # print(f"DEBUG: API Error - {e}")
            return None

    # --- 核心规划逻辑 (含集群搜索与去重) ---
    def plan_trip(self, s_lat, s_lon, e_lat, e_lon):
        dist = self.haversine(s_lat, s_lon, e_lat, e_lon)
        
        # 1. 步行评估 (直线距离 < 800m 建议步行)
        if dist < 800:
            return {"type": "walk", "minutes": round(dist/80), "dist_m": round(dist)}

        # 2. 空间搜索获取起点和终点站簇 (400米半径)
        start_cluster = [s['BusStopCode'] for s in self.stops if self.haversine(s_lat, s_lon, s['Latitude'], s['Longitude']) <= 400]
        end_cluster = [s['BusStopCode'] for s in self.stops if self.haversine(e_lat, e_lon, s['Latitude'], s['Longitude']) <= 400]
        
        if not start_cluster or not end_cluster:
            return {"type": "none"}

        raw_options = []
        for s_code in start_cluster:
            # 建立起点线路快速查找表 (ServiceNo, Direction)
            s_services = {(r['ServiceNo'], r['Direction']): r for r in self.stop_to_routes.get(s_code, [])}
            
            for e_code in end_cluster:
                if s_code == e_code: continue
                # 遍历终点站的所有线路
                for r_end in self.stop_to_routes.get(e_code, []):
                    key = (r_end['ServiceNo'], r_end['Direction'])
                    if key in s_services:
                        r_start = s_services[key]
                        # 核心逻辑：确认上车点在下车点之前
                        if int(r_end['StopSequence']) > int(r_start['StopSequence']):
                            raw_options.append({
                                "service": r_end['ServiceNo'],
                                "from_name": self.stop_map[s_code]['Description'],
                                "from_code": s_code,
                                "to_name": self.stop_map[e_code]['Description'],
                                "stops": int(r_end['StopSequence']) - int(r_start['StopSequence']),
                                "dist_km": round(float(r_end['Distance']) - float(r_start['Distance']), 2)
                            })

        # 3. 集群去重 (De-duplication)
        # 同一路巴士，只保留站点数最少的上车点，消除“同一路车出现多次”的冗余
        unique_results = {}
        for opt in raw_options:
            svc = opt['service']
            if svc not in unique_results or opt['stops'] < unique_results[svc]['stops']:
                unique_results[svc] = opt

        # 4. 接入实时 V3 数据并排序
        final_options = list(unique_results.values())
        print(f"📡 [Logic] 正在为 {len(final_options)} 条可选线路请求实时 V3 数据...")
        
        for opt in final_options:
            opt['live'] = self.get_realtime_v3(opt['from_code'], opt['service'])

        # 排序：优先展示有实时数据的线路，其次按 ETA 时间，最后按站点数
        final_options.sort(key=lambda x: (
            0 if x['live'] else 1, 
            x['live']['minutes'] if x['live'] else 999, 
            x['stops']
        ))

        return {"type": "bus", "options": final_options[:3]} if final_options else {"type": "none"}

# --- 执行与结果展示 ---
if __name__ == "__main__":
    engine = BusSmartEngine()
    
    # 测试场景：Suntec City (1.2935, 103.8576) -> Changi Airport T2 (1.3575, 103.9885)
    print("\n[AI Assistant] 正在为您计算前往机场 T2 的最优实时方案...")
    
    #trip = engine.plan_trip(1.2935, 103.8576, 1.3575, 103.9885)
    trip = engine.plan_trip(1.1533, 103.9452, 1.357500, 103.988500)

    if trip['type'] == "bus":
        print("🤖 AI: 为您找到以下最快线路：\n")
        for i, opt in enumerate(trip['options'], 1):
            live = opt['live']
            if live:
                eta_text = f"⏳ {live['minutes']} 分钟后到站 ({live['load']})"
                wab_text = " [♿ 适合行李]" if live['is_wab'] else ""
            else:
                eta_text = "⚠️ 暂无实时位置 (建议直接前往站台)"
                wab_text = ""

            print(f"   {i}. 乘坐 {opt['service']} 路 | {eta_text}{wab_text}")
            print(f"      📍 上车点: {opt['from_name']} (站码 {opt['from_code']})")
            print(f"      🏁 下车点: {opt['to_name']}")
            print(f"      📊 行程: 经过 {opt['stops']} 站 | 全程 {opt['dist_km']} km")
            print("-" * 45)
    elif trip['type'] == "walk":
        print(f"🚶 AI: 目的地很近（约 {trip['dist_m']} 米），建议步行约 {trip['minutes']} 分钟，比等车更快。")
    else:
        print("🤖 AI: 抱歉，目前没有找到直达巴士。建议考虑换乘或搭乘地铁。")