# SRS Callback Gateway

一个用于接收 SRS `http_hooks`、按规则转发到下游 HTTP 服务、并在本地持久化事件与投递状态的网关。

## Overview

这个项目当前采用比较常见的仓库结构：

- `gateway/`：应用源码与镜像构建上下文
- `deploy/`：Docker Compose 与运行时配置
- `deploy/data/`：运行时持久化数据目录

项目本身维护一个自建镜像：

- `gateway` -> `gateway/Dockerfile`

运行时依赖一个外部容器：

- `ossrs/srs:6`

## Architecture

请求流转如下：

1. SRS 将事件发送到 `POST /api/srs/hook`
2. 网关将原始事件写入 SQLite
3. 网关根据路由规则生成待投递任务
4. 后台 worker 异步投递到目标 HTTP 服务
5. 管理端通过 `/admin` 和管理 API 查看路由、事件、投递结果

## Directory Layout

```text
SRScallback/
├─ README.md
├─ gateway/
│  ├─ Dockerfile
│  ├─ requirements.txt
│  ├─ app/
│  └─ tests/
└─ deploy/
   ├─ docker-compose.yml
   ├─ srs.conf
   └─ data/
      └─ gateway.db
```

## Requirements

- Docker
- Docker Compose

如果你只想本地直接跑 Python 进程，还需要：

- Python 3.12

## Quick Start

### 1. 启动服务

在项目根目录执行：

```powershell
docker compose -f deploy/docker-compose.yml up -d --build
```

启动后会有两个服务：

- Gateway 管理界面：`http://localhost:13010/admin`
- Gateway 健康检查：`http://localhost:13010/healthz`
- SRS HTTP API：`http://localhost:1985`
- SRS HTTP-FLV：`http://localhost:8080`
- SRS RTMP：`rtmp://localhost/live`

### 2. 数据库如何创建

不需要手工创建数据库。

Gateway 启动时会自动：

- 创建 `deploy/data/gateway.db`
- 创建所需的 SQLite 表和索引
- 在目录不存在时自动创建 `deploy/data/`

只要容器能正常启动，数据库就会自动初始化完成。

### 3. 停止服务

```powershell
docker compose -f deploy/docker-compose.yml down
```

如果你希望连容器一起清掉但保留数据库文件，这个命令已经足够。

## Daily Operations

### 查看日志

```powershell
docker compose -f deploy/docker-compose.yml logs -f srs-callback-gateway
```

```powershell
docker compose -f deploy/docker-compose.yml logs -f srs
```

### 重新构建并启动

```powershell
docker compose -f deploy/docker-compose.yml up -d --build
```

### 删除运行容器但保留数据

```powershell
docker compose -f deploy/docker-compose.yml down
```

### 清空本地数据库重新开始

先停服务，再删除数据库文件：

```powershell
docker compose -f deploy/docker-compose.yml down
Remove-Item deploy/data/gateway.db
docker compose -f deploy/docker-compose.yml up -d --build
```

下次启动时会自动重新建库。

## Configuration

`deploy/docker-compose.yml` 中当前使用的主要环境变量：

- `DB_PATH=/data/gateway.db`
- `ADMIN_TOKEN`
- `ALLOW_PRIVATE_TARGETS=true`
- `DELIVERY_POLL_INTERVAL_MS=1500`
- `DOWNSTREAM_PAYLOAD_MODE=raw`

可选环境变量说明：

- `ALLOWED_TARGET_HOSTS`：限制允许投递的目标域名，逗号分隔
- `SEED_DEMO_ROUTE`：是否自动插入一条 demo 路由，默认 `false`
- `DEFAULT_TARGET_TIMEOUT_MS`：默认下游超时，默认 `5000`

## Admin Access

如果 `ADMIN_TOKEN` 为空：

- `/api/routes`
- `/api/events`
- `/api/deliveries`

这些管理接口不做鉴权。

如果设置了 `ADMIN_TOKEN`，调用这些接口时需要带：

```http
Authorization: Bearer <your-token>
```

## First-Time Usage

推荐第一次启动后按这个顺序操作：

1. 打开 `http://localhost:13010/admin`
2. 创建一条路由规则，指定要接收的事件类型和下游目标 URL
3. 在 SRS 中把回调地址指向 `http://host.docker.internal:13010/api/srs/hook` 或你的宿主机可达地址
4. 推一次流，触发 `on_publish`
5. 回到管理页检查事件和投递结果

## SRS Hook Configuration

SRS 需要把 `http_hooks` 指到 Gateway。

如果 SRS 与 Gateway 一起通过当前 Compose 运行，SRS 容器内访问 Gateway 可使用：

- `http://srs-callback-gateway:13000/api/srs/hook`

如果是宿主机或其他环境中的 SRS，请改成对应可达地址。

## API Summary

公开接口：

- `POST /api/srs/hook`
- `GET /healthz`
- `GET /readyz`
- `GET /metrics`
- `GET /`
- `GET /admin`

管理接口：

- `GET /api/routes`
- `POST /api/routes`
- `PUT /api/routes/{route_id}`
- `DELETE /api/routes/{route_id}`
- `GET /api/events`
- `GET /api/deliveries`
- `POST /api/deliveries/{delivery_id}/retry`

## Local Development

如果不想用 Docker，也可以直接运行网关：

```powershell
cd gateway
py -3.12 -m pip install -r requirements.txt
$env:DB_PATH = (Resolve-Path ..\\deploy\\data\\gateway.db).Path
uvicorn app.main:app --host 0.0.0.0 --port 13000
```

这种方式只启动 Gateway，不会自动启动 SRS。

## Data Persistence

当前默认数据文件位置：

- `deploy/data/gateway.db`

这是运行数据，不建议提交到版本库，也不建议手动编辑。

## Suggested Convention

以后维护这个项目，建议遵守下面这套约定：

- 根目录 `README.md` 作为唯一主文档入口
- `gateway/` 只放应用与镜像构建内容
- `deploy/` 只放部署与运行配置
- `deploy/data/` 只放本地持久化数据
- 测试或临时工具尽量放在独立目录，并明确标注是否为开发辅助文件
