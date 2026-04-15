import os
from urllib import response
from bus_engine import BusSmartEngine  # 假设你的文件名是 bus_engine.py

def test_realtime_arrival():
    # 1. 确保环境变量已设置 (LTA API KEY)
    # 如果没在系统设置，可以临时在代码里取消下面一行的注释
    # os.environ["LTA_API_KEY"] = "你的_LTA_API_KEY"

    engine = BusSmartEngine()
    
    # 2. 定义测试数据 (例如: 站点 02151 是新达城附近)
    test_stop = "02151"
    test_service = "36"
    # test_service = None  # 测试不传 ServiceNo 的情况

    print(f"🔍 正在查询站点 [{test_stop}] 的线路 [{test_service}]...")
    
    # 3. 调用你类中的 get_realtime_v3 方法
    arrival_data = engine.get_realtime_v3_v2(test_stop, test_service)

    

    # 4. 输出结果
    if arrival_data:
        print("\n✅ 查询成功!")
        print(f"🚌 路线: {test_service}")
        print(f"⏳ 预计到达: {arrival_data['minutes']} 分钟")
        print(f"👨‍👩‍👧‍👦 拥挤程度: {arrival_data['load']}")
        print(f"♿ 轮椅通道: {'支持' if arrival_data['is_wab'] else '不支持'}")
        print(f"📅 原始时间戳: {arrival_data['raw_eta']}")
    else:
        print("\n❌ 未找到数据。可能原因: 1. 密钥无效 2. 该时段该路线无车 3. 站点代码错误")


   # engine.nearby_stops(1.3000, 103.8500, radius_m=600, limit=8)

if __name__ == "__main__":
    # test_realtime_arrival()
    engine = BusSmartEngine()
    
    # 模拟一个较远或无直达的场景
    print("\n[AI Assistant] 正在规划您的行程...")
    #trip = engine.plan_trip(1.3000, 103.8500, 1.3575, 103.9885)
    trip = engine.best_route_candidates(1.3000, 103.8500, 1.3575, 103.9885)

    #trip = engine.plan_trip(1.1533, 103.9452, 1.357500, 103.988500)
    #print(f"📡 [API TEST] Status: {trip} | Body Len: {trip.}", flush=True)
    
    if trip['type'] == "bus":
        print("🤖 AI: 为您找到以下直达线路：\n")
      #  for i, opt in enumerate(trip['options'], 1):
            # live = opt['live']
            # eta = f"⏳ {live['minutes']}分" if live else "⚠️ 暂无实时"
        print(f" all: ({trip}")

        #rint(f"   {i}. {opt['service']}路 | {opt['live_minutes']}分 | {opt['from_name']} -> {opt['to_name']}")
    elif trip['type'] == "transfer":
        t = trip
        print("🤖 AI: 没找到直达，建议转乘方案：\n")
        print(f"   🚩 第一阶段: 乘坐 {t['leg1']['service']} 路")
        print(f"      上车点: {t['leg1']['from']} (站码 {t['leg1']['from_code']})")
        print(f"      📍 并在 {t['transfer_at']} 准备换乘")
        print(f"   🚌 第二阶段: 换乘 {t['leg2']['service']} 路")
        print(f"      🏁 最终到达: {t['leg2']['to']}")
    elif trip['type'] == "walk":
        print(f"🚶 AI: 目的地很近，建议步行 {trip['minutes']} 分钟。")
    else:
        print("🤖 AI: 抱歉，目前没有找到可行的巴士方案。")