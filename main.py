from pathlib import Path
from typing import Iterable
import time
import os
import logging

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import requests
from bus_engine import BusSmartEngine

# 确保日志输出到 stdout，以便 Azure Log Stream 捕获
logger = logging.getLogger("uvicorn.error")

app = FastAPI()

# 允许跨域，方便本地 index.html 调用
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = BusSmartEngine()
BASE_DIR = Path(__file__).resolve().parent
AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY", "").strip()
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "").strip()
_AZURE_SPEECH_TOKEN_CACHE: dict[str, object] = {"token": "", "expires_at": 0.0}


def _azure_speech_ready() -> bool:

    return bool(AZURE_SPEECH_KEY and AZURE_SPEECH_REGION)

def verify_azure_at_startup():
    """在程序启动时验证 Azure 参数并测试 Token 交换"""
    logger.info("="*50)
    logger.info("🔍 [Azure Speech 启动校验]")
    
    # 1. 检查环境变量提取
    if not AZURE_SPEECH_KEY:
        logger.error("❌ 错误: AZURE_SPEECH_KEY 为空，请检查 Azure App Service 'Configuration' 设置。")
    else:
        # 脱敏打印：显示前4位和总长度
        logger.info(f"✅ KEY 已加载: {AZURE_SPEECH_KEY[:4]}**** (长度: {len(AZURE_SPEECH_KEY)})")
        
    if not AZURE_SPEECH_REGION:
        logger.error("❌ 错误: AZURE_SPEECH_REGION 为空。")
    else:
        logger.info(f"✅ REGION 已加载: {AZURE_SPEECH_REGION}")

    # 2. 尝试实际换取一次 Token (真正的可用性测试)
    if _azure_speech_ready():
        token_url = f"https://{AZURE_SPEECH_REGION}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
        try:
            start_time = time.time()
            response = requests.post(
                token_url, 
                headers={'Ocp-Apim-Subscription-Key': AZURE_SPEECH_KEY}, 
                timeout=5
            )
            elapsed = (time.time() - start_time) * 1000
            
            if response.status_code == 200:
                logger.info(f"🚀 [成功] Azure 握手正常! Token 交换耗时: {elapsed:.0f}ms")
            else:
                logger.error(f"❌ [失败] Azure 返回状态码: {response.status_code}")
                logger.error(f"📝 错误详情: {response.text}")
        except Exception as e:
            logger.error(f"⚠️ [异常] 无法连接到 Azure 认证服务器: {str(e)}")
    
    logger.info("="*50)
# 执行预检
verify_azure_at_startup()

def _azure_speech_missing_fields() -> list[str]:
    missing: list[str] = []
    if not AZURE_SPEECH_KEY:
        missing.append("AZURE_SPEECH_KEY")
    if not AZURE_SPEECH_REGION:
        missing.append("AZURE_SPEECH_REGION")
    return missing


def _speech_phrase_hints(limit: int = 500) -> list[str]:
    phrases: list[str] = []
    seen: set[str] = set()

    def add_many(values: Iterable[str | None]) -> None:
        for value in values:
            if not value:
                continue
            phrase = " ".join(str(value).replace("/", " ").split()).strip()
            if not phrase:
                continue
            key = phrase.lower()
            if key in seen:
                continue
            seen.add(key)
            phrases.append(phrase)
            if len(phrases) >= limit:
                return

    add_many(stop.get("Description") for stop in engine.stops)
    add_many(stop.get("RoadName") for stop in engine.stops)
    add_many(stop.get("BusStopCode") for stop in engine.stops)
    add_many(route.get("ServiceNo") for route in engine.routes)

    return phrases[:limit]

class TripRequest(BaseModel):
    s_lat: float
    s_lon: float
    e_lat: float
    e_lon: float


@app.get("/")
async def index():
    return FileResponse(BASE_DIR / "index.html")


@app.get("/api/v1/nearby-stops")
async def nearby_stops(
    lat: float = Query(...),
    lon: float = Query(...),
    radius_m: int = Query(600, ge=50, le=3000),
    limit: int = Query(8, ge=1, le=20),
):
    return {
        "type": "nearby_stops",
        "location": {"lat": lat, "lon": lon},
        "radius_m": radius_m,
        "stops": engine.nearby_stops(lat, lon, radius_m=radius_m, limit=limit),
    }


@app.get("/api/v1/routes/{service_no}")
async def route_summary(service_no: str):
    summary = engine.route_summary(service_no)
    if not summary:
        raise HTTPException(status_code=404, detail="Service not found")
    return summary


@app.get("/api/v1/search-stops")
async def search_stops(q: str = Query(..., min_length=1), limit: int = Query(10, ge=1, le=20)):
    keyword = q.strip().lower()
    matches = []
    for stop in engine.stops:
        haystack = f"{stop.get('BusStopCode','')} {stop.get('Description','')} {stop.get('RoadName','')}".lower()
        if keyword in haystack:
            matches.append({
                "code": stop.get("BusStopCode"),
                "name": stop.get("Description", ""),
                "road": stop.get("RoadName", ""),
                "latitude": stop.get("Latitude"),
                "longitude": stop.get("Longitude"),
            })
    return {"query": q, "results": matches[:limit]}


@app.get("/api/v1/speech/config")
async def speech_config():
    ready = _azure_speech_ready()
    return {
        "enabled": ready,
        "ready": ready,
        "region": AZURE_SPEECH_REGION if ready else None,
        "default_language": "en-SG",
        "supports_code_switching": True,
        "phrase_hint_count": len(_speech_phrase_hints(500)),
        "missing_fields": _azure_speech_missing_fields(),
        "message": "Azure Speech ready" if ready else "Azure Speech is not configured on the backend",
    }


@app.get("/api/v1/speech/hints")
async def speech_hints(limit: int = Query(500, ge=10, le=1000)):
    phrases = _speech_phrase_hints(limit)
    return {
        "count": len(phrases),
        "phrases": phrases,
    }


@app.get("/api/v1/speech/token")
async def speech_token():
    if not _azure_speech_ready():
        raise HTTPException(status_code=503, detail="Azure Speech is not configured")

    now = time.time()
    cached_token = str(_AZURE_SPEECH_TOKEN_CACHE.get("token") or "")
    cached_expires_at = float(_AZURE_SPEECH_TOKEN_CACHE.get("expires_at") or 0.0)
    if cached_token and now < cached_expires_at:
        return {
            "token": cached_token,
            "region": AZURE_SPEECH_REGION,
            "expires_in": int(max(1, cached_expires_at - now)),
            "source": "cache",
        }

    url = f"https://{AZURE_SPEECH_REGION}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
    try:
        response = requests.post(
            url,
            headers={"Ocp-Apim-Subscription-Key": AZURE_SPEECH_KEY},
            timeout=10,
        )
        response.raise_for_status()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to obtain Azure Speech token: {exc}") from exc

    token = response.text.strip()
    if not token:
        raise HTTPException(status_code=502, detail="Azure Speech token response was empty")

    # Azure Speech tokens usually expire after about 10 minutes.
    # Cache briefly so the frontend keeps calling our backend proxy instead of Azure directly.
    _AZURE_SPEECH_TOKEN_CACHE["token"] = token
    _AZURE_SPEECH_TOKEN_CACHE["expires_at"] = now + 540

    return {
        "token": token,
        "region": AZURE_SPEECH_REGION,
        "expires_in": 600,
        "source": "azure-proxy",
    }



@app.get("/api/v1/stops/{stop_code}/arrivals")
async def stop_arrivals(stop_code: str, service_no: str | None = None):
    stop = engine.stop_map.get(stop_code)
    if not stop:
        raise HTTPException(status_code=404, detail="Stop not found")

    services = []
    stop_routes = engine.stop_to_routes.get(stop_code, [])
    if service_no:
        stop_routes = [r for r in stop_routes if r["ServiceNo"] == service_no]

    seen = set()
    for route in stop_routes:
        svc = route["ServiceNo"]
        if svc in seen:
            continue
        seen.add(svc)
        services.append({
            "service": svc,
            "operator": route.get("Operator"),
            "arrival": engine.get_realtime_v3(stop_code, svc),
        })

    services.sort(key=lambda item: (0 if item["arrival"] else 1, item["arrival"]["minutes"] if item["arrival"] else 999))
    return {
        "stop": {
            "code": stop["BusStopCode"],
            "name": stop.get("Description", ""),
            "road": stop.get("RoadName", ""),
            "latitude": stop.get("Latitude"),
            "longitude": stop.get("Longitude"),
        },
        "services": services[:6],
    }

@app.post("/api/v1/plan")
async def plan(request: TripRequest):
    return engine.plan_trip(request.s_lat, request.s_lon, request.e_lat, request.e_lon)

@app.get("/health")
async def health():
    return {"status": "ok"}