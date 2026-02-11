# 编队识别系统 (Formation Recognition System)

基于规则的空中作战编队识别系统，集成 Redis 缓存、增量同步和 7 天滚动存储。

## 核心特性

### 🚀 高性能识别
- **智能增量识别**：只处理变化的目标，减少 90% 重复计算
- **Redis 缓存加速**：TargetState 实时缓存，毫秒级响应
- **多级存储**：内存 + Redis + SQLite，平衡性能与持久化

### 📡 实时同步
- **WebSocket 推送**：目标状态变化实时推送
- **增量同步 API**：支持断点续传，按需拉取差异
- **版本控制**：毫秒级版本号，精确追踪变化历史

### 🗄️ 数据管理
- **7 天滚动存储**：编队结果自动过期清理
- **时间序列索引**：高效查询任意时段数据
- **缓存预热**：服务重启自动恢复活跃目标

## 快速开始

### 1. 环境准备

```bash
# 安装依赖
pip install -r requirements.txt

# 启动 Redis（Docker）
docker run -d --name redis-formation -p 6379:6379 redis:7-alpine

# 或本地安装 Redis
# Ubuntu: sudo apt-get install redis-server
# macOS: brew install redis

1. 本地启动
```angular2html
# 安装依赖
pip install -r requirements.txt

# 启动服务
python main.py

# 或使用uvicorn直接启动
uvicorn main:app --reload --host 0.0.0.0 --port 8000

2.Docker启动
# 构建镜像
docker build -t formation-api .

# 运行容器
docker run -p 8000:8000 formation-api

# 或使用docker-compose
docker-compose up -d
```

2. 配置
编辑 cache/redis_client.py 中的 RedisConfig：
```
class RedisConfig:
    HOST = "localhost"      # Redis 地址
    PORT = 6379             # Redis 端口
    DB = 0                  # 数据库编号
    PASSWORD = None         # 密码（如有）
    
    # TTL 配置（秒）
    TARGET_TTL = 86400          # 目标状态 24 小时
    FORMATION_TTL = 604800      # 编队结果 7 天
    DELTA_STREAM_TTL = 604800   # 增量流 7 天
`````

3. 访问Swagger文档
```angular2html
Web界面: http://localhost:8000/
API文档: http://localhost:8000/docs
Swagger UI: http://localhost:8000/docs
ReDoc: http://localhost:8000/redoc
OpenAPI JSON: http://localhost:8000/openapi.json
```

4. API调用示例
```angular2html
# 健康检查
curl http://localhost:8000/health

# 编队识别
curl -X POST "http://localhost:8000/recognize" \
  -H "Content-Type: application/json" \
  -d '{
    "targets": [
      {
        "id": "F16-001",
        "type": "Fighter",
        "time": "2024-01-15T10:00:00",
        "position": {"longitude": 116.5, "latitude": 39.9, "altitude": 5000},
        "heading": 90,
        "speed": 250,
        "nation": "BLUE",
        "alliance": "NATO"
      },
      {
        "id": "F16-002",
        "type": "Fighter",
        "time": "2024-01-15T10:00:00",
        "position": {"longitude": 116.51, "latitude": 39.91, "altitude": 5100},
        "heading": 92,
        "speed": 255,
        "nation": "BLUE",
        "alliance": "NATO"
      }
    ],
    "preset": "tight_fighter"
  }'

# 获取规则预设
curl http://localhost:8000/rules/presets

# 场景自适应
curl -X POST "http://localhost:8000/rules/adapt?scene_type=strike"

# 编队识别（自动缓存）
POST /recognize
Content-Type: application/json

{
    "targets": [
        {
            "id": "T1",
            "名称": "F-16A",
            "类型": "Fighter",
            "时间": "2024-01-15T10:00:00",
            "位置": [116.5, 39.9, 5000],
            "航向": 90.0,
            "速度": 250.0,
            "国家": "BLUE",
            "联盟": "NATO"
        }
    ],
    "preset": "tight_fighter"
}

# 纯缓存更新（不识别）
POST /cache/targets/batch_update
Content-Type: application/json

{
    "targets": [...],  # 同上
    "emit_events": true  # 是否发送 WebSocket 事件
}

# 增量同步
POST /cache/sync/session
{
    "client_id": "client_001",
    "target_ids": ["T1", "T2"]  # 不传表示订阅全部
}

# 拉取增量
POST /cache/sync/pull
{
    "session_id": "sync_client_001_abc123",
    "since_versions": {
        "T1": 1705312200000,
        "T2": 1705312201000
    }
}

# WebSocket 实时订阅
const ws = new WebSocket('ws://localhost:8000/cache/ws/client_001');

ws.onopen = () => {
    // 订阅目标更新
    ws.send(JSON.stringify({
        type: 'SUBSCRIBE',
        target_ids: ['T1', 'T2', 'T3']
    }));
};

ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    
    if (msg.type === 'TARGET_UPDATE') {
        console.log('目标更新:', msg.target_id, msg.delta);
        // delta 包含位置、航向、速度的变化量
    }
    
    if (msg.type === 'FORMATION_DETECTED') {
        console.log('新编队识别:', msg.formation);
    }
    
    if (msg.type === 'INITIAL_STATE') {
        console.log('初始全量状态:', msg.data);
    }
};

# 编队结果查询
# 最近 10 个编队
GET /cache/formations/recent?count=10

# 时间范围查询
GET /cache/formations/range?start=2024-01-01T00:00:00&end=2024-01-02T00:00:00

# 按日期查询
GET /cache/formations/date/20240115

# 编队统计
GET /cache/formations/statistics/overview?days=7
```
5.主要API端点

| 方法     | 路径                            | 说明      |
| :----- | :---------------------------- | :------ |
| GET    | `/health`                     | 健康检查    |
| POST   | `/recognize`                  | 编队识别    |
| POST   | `/recognize/batch`            | 批量识别    |
| GET    | `/rules/presets`              | 获取规则预设  |
| POST   | `/rules/presets/{name}/apply` | 应用预设    |
| GET    | `/rules/current`              | 当前规则配置  |
| POST   | `/rules/add`                  | 添加自定义规则 |
| PUT    | `/rules/{id}`                 | 更新规则    |
| DELETE | `/rules/{id}`                 | 删除规则    |
| GET    | `/formations`                 | 获取所有编队  |
| GET    | `/formations/{id}`            | 编队详情    |
| GET    | `/stats/summary`              | 统计摘要    |

