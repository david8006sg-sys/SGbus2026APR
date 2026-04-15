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

- **语音识别**：默认使用浏览器 Web Speech API，也可切换到 Azure Speech
- **语音播报**：使用浏览器 SpeechSynthesis
- **定位**：使用浏览器 Geolocation API
- **公交数据**：支持从 LTA DataMall 拉取公交到站与线路信息
- **后端 Context Manager**：已通过 `/api/query`、`/api/context/location`、`/api/context/bus-routes` 与 `/api/context/bus-stop-routes` 接入
- **路线缓存**：后端会自动缓存 Bus Routes 并按间隔定时刷新，前端优先读取缓存数据

## Azure Speech 语音识别

如果你希望启用 **Azure Speech Services**，前端左侧已经新增了一个语音设置卡片，可以在 **Web Speech / Azure Speech / Auto** 之间切换。

### 支持能力

- **en-SG**：可使用新加坡英语识别模式
- **Code-switching**：支持中英夹杂场景，适合新加坡本地口语
- **自定义词库**：后端会把全岛巴士站、路名、站号、线路号整理成 phrase hints，并下发给前端做识别强化

### 需要配置的环境变量

```bash
set AZURE_SPEECH_KEY=你的AzureSpeechKey
set AZURE_SPEECH_REGION=你的AzureSpeechRegion
```

### Azure 后台自定义词库建议

建议你在 Azure Speech Studio / Custom Speech 里上传一份包含全岛巴士站的 Excel，字段可包括：

- BusStopCode
- Description
- RoadName
- ServiceNo

这样可以进一步提高对站点名、道路名和巴士线路号的识别率，尤其是新加坡本地发音和中英混说场景。

如果 Azure 没有配置，系统会自动回退到浏览器 Web Speech API。

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

### 前端 index.html 怎么和 Azure Web App 后端连接？

目前这个项目的最简单方式是：**前端和后端部署到同一个 Azure Web App**。

- `main.py` 会直接返回 `index.html`
- 浏览器访问 `/` 时，前端和后端天然同域
- 这样 `index.html` 里的接口请求可以直接用相对路径，例如 `/api/v1/search-stops`

所以在当前结构下，**你不需要单独把 `index.html` 再部署一次**。

如果你以后想把前端拆出来，单独放到别的地方（比如 Azure Static Web Apps、Blob Static Website、Netlify），那就把 `index.html` 里的：

```html
<script>window.__API_BASE__='https://你的后端站点.azurewebsites.net';</script>
```

放在主脚本前面，然后前端会自动把接口请求打到这个后端地址。

这种前后端分离模式下，还需要在后端保留 CORS 允许前端域名访问。现在 `main.py` 已经是 `allow_origins=["*"]`，开发阶段够用；如果正式上线，建议改成只允许你的前端域名。

### 怎样测试前端？

你可以分成 **本地测试** 和 **Azure 上测试** 两种方式：

#### 1. 本地测试

1. 启动后端：

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

2. 浏览器打开：

```text
http://127.0.0.1:8000
```

3. 重点验证这些前端能力：
   - 页面是否正常加载
   - 地图是否正常显示
   - 语音按钮是否可点
   - 邮编输入后是否会更新当前位置
   - 点击“Start Journey”后是否能生成路线卡片
   - 点击附近站点卡片是否能刷新路线和到站信息

4. 如果接口有问题，可以直接访问这些地址查看返回值：
   - `http://127.0.0.1:8000/health`
   - `http://127.0.0.1:8000/api/v1/search-stops?q=Jurong`
   - `http://127.0.0.1:8000/api/v1/nearby-stops?lat=1.2966&lon=103.8520`

#### 2. Azure 上测试

1. 部署到 Azure Web App 后，打开你的站点域名
2. 按下面顺序测：
   - 首页能否打开
   - 浏览器控制台是否有报错
   - `/health` 是否返回 `{"status":"ok"}`
   - 输入邮编是否能更新位置
   - 语音识别是否可用（不同浏览器支持不同）

#### 3. 推荐的浏览器测试项

- Chrome / Edge 优先测试，因为 Web Speech API 支持更好
- 允许麦克风权限
- 如果在 Azure 上测试，确认页面是通过 HTTPS 访问

#### 4. 快速排查

- 如果页面空白：先看浏览器 F12 控制台有没有 JS 报错
- 如果站点加载慢：检查 `index.html` 里的外部 CDN（Leaflet、Tailwind、Google Fonts）是否能访问
- 如果后端接口报 500：检查 Azure Web App 的日志和 `LTA_API_KEY` 是否已配置

## 后续接入建议

1. 对接 Azure API Management 统一入口
2. 增加真实公交 API / 地图 API / 天气 API
3. 将更多前端查询能力接入后端 Context Manager
4. 将语音识别迁移至 Azure Speech Streaming#   S G b u s 2 0 2 6 A P R  
 