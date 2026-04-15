# 24小时 AI 公交语音助手 MVP

这是一个面向移动端和桌面端浏览器的跨平台 Web MVP，聚焦 Phase 1 核心能力：

- 支持公交到站查询
- 支持语音采集、ASR 和 TTS
- 支持最近站点定位

## 启动方式

当前项目已经整理为适合部署到 **Azure Web App** 的单体 Web 应用：

- `main.py` 负责 FastAPI 后端 API 和首页路由
- `index.html` 作为前端入口
- `Dockerfile` 仍可保留作容器部署备用，但不是必须

### Azure Web App 直接部署（推荐）

如果你要直接使用 **Azure Web App（代码部署）**，推荐选择：

- 发布方式：`Code`
- 运行时：`Python 3.10` 或 `Python 3.11`
- 平台：`Linux`

启动命令可以填写：

```bash
gunicorn -k uvicorn.workers.UvicornWorker main:app --bind 0.0.0.0:${PORT} --timeout 600
```

在 Azure Web App 的应用设置中请确保配置：

- `WEBSITES_PORT=8000`
- `LTA_API_KEY=你的LTA_API_KEY`

Azure 会自动安装 `requirements.txt` 中的依赖并启动应用，所以不需要 Docker。

部署完成后直接访问 Azure Web App 的默认域名即可。

### 本地开发

如果你只想在本地调试，可以继续使用：

```bash
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

然后访问：

```text
http://127.0.0.1:8000
```

### Docker 本地运行

```bash
docker build -t kinetic-concierge .
docker run -p 8000:8000 -e LTA_API_KEY=你的LTA_API_KEY kinetic-concierge
```

## 功能说明

- **语音识别**：使用浏览器 Web Speech API
- **语音播报**：使用浏览器 SpeechSynthesis
- **定位**：使用浏览器 Geolocation API
- **公交数据**：支持从 LTA DataMall 拉取公交到站与线路信息
- **后端 Context Manager**：已通过 `/api/query`、`/api/context/location`、`/api/context/bus-routes` 与 `/api/context/bus-stop-routes` 接入
- **路线缓存**：后端会自动缓存 Bus Routes 并按间隔定时刷新，前端优先读取缓存数据

## 环境变量

启动前建议配置：

```bash
set LTA_API_KEY=你的LTA_API_KEY
set LTA_REFRESH_INTERVAL=900
```

- `LTA_API_KEY`：LTA DataMall API Key
- `LTA_REFRESH_INTERVAL`：Bus Routes 缓存刷新间隔，单位秒，默认 900

### Azure Web App 配置建议

如果使用 **Azure Web App（代码部署）**，建议在应用设置中配置：

- `LTA_API_KEY`：LTA DataMall API Key
- `LTA_REFRESH_INTERVAL`：Bus Routes 刷新间隔，默认 900
- `WEBSITES_PORT`：8000

Azure 启动命令可使用：

```bash
gunicorn -k uvicorn.workers.UvicornWorker main:app --bind 0.0.0.0:8000 --timeout 600
```

如果你以后想切回容器模式，再使用仓库中的 `Dockerfile` 即可。

### 部署步骤（推荐）

1. 在 Azure 创建 Web App，发布方式选择 `Code`
2. 运行时选择 `Python 3.10` 或 `Python 3.11`
3. 在配置中设置 `LTA_API_KEY`、`LTA_REFRESH_INTERVAL` 和 `WEBSITES_PORT=8000`
4. 在“启动命令”中填入 `gunicorn -k uvicorn.workers.UvicornWorker main:app --bind 0.0.0.0:8000 --timeout 600`
5. 部署后访问 Web App 默认域名

### GitHub 到 Azure 一键部署配置

如果你希望“代码推到 GitHub 就自动部署到 Azure”，可以使用仓库里的 GitHub Actions 工作流：

1. 先把代码推送到 GitHub 仓库，并确保默认分支是 `main`
2. 在 Azure Web App 页面中找到 **Get publish profile**（下载发布配置文件）
3. 打开 GitHub 仓库，进入 **Settings → Secrets and variables → Actions**
4. 新增两个 Secret：
   - `AZURE_WEBAPP_NAME`：你的 Azure Web App 名称
   - `AZURE_WEBAPP_PUBLISH_PROFILE`：把刚才下载的 publish profile 内容粘贴进去
5. 推送代码到 `main` 分支，或者在 GitHub Actions 页面手动触发 `Deploy Azure Web App`

工作流文件已经放在：

```text
.github/workflows/deploy-azure-webapp.yml
```

如果你改了分支名，不是 `main`，记得把 workflow 里的分支名一起改掉。

## 后续接入建议

1. 对接 Azure API Management 统一入口
2. 增加真实公交 API / 地图 API / 天气 API
3. 将更多前端查询能力接入后端 Context Manager
4. 将语音识别迁移至 Azure Speech Streaming