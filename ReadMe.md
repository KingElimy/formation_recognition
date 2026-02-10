1. 本地启动
```angular2html
# 安装依赖
pip install -r requirements.txt

# 启动服务
python main.py

# 或使用uvicorn直接启动
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

2. Docker启动
```angular2html
# 构建镜像
docker build -t formation-api .

# 运行容器
docker run -p 8000:8000 formation-api

# 或使用docker-compose
docker-compose up -d
```

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
