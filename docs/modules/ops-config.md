# 模块文档: 配置、部署与运维

## 1. 目标

定义系统运行所需的配置、环境变量、日志和部署边界，避免开发阶段把运行细节散落在代码中。

## 2. 建议目录

```text
config/
  stations.yaml
  settings.example.yaml
  logging.json

docker-compose.yaml
.env.example
```

## 3. `stations.yaml` 结构建议

每个站点至少包含：

- `city_code`
- `city_name`
- `icao_code`
- `timezone_name`
- `settlement_unit`
- `wunderground_station_code`
- `latitude`
- `longitude`
- `is_active`

## 4. 环境变量建议

### 基础

- `APP_ENV`
- `DATABASE_URL`
- `LOG_LEVEL`

### 第三方 API

- `POLYMARKET_API_BASE`
- `OPEN_METEO_API_BASE`
- `NOAA_AWC_API_BASE`

### 交易相关

- `TRADING_MODE`
- `POLYMARKET_PRIVATE_KEY`
- `POLYGON_RPC_URL`
- `MAX_SINGLE_TRADE_USDC`
- `MAX_DAILY_LOSS_USDC`
- `MAX_CONCURRENT_POSITIONS`

## 5. 日志规范

- 全部使用 JSON 日志
- 必带字段：
  - `timestamp`
  - `level`
  - `module`
  - `event`
  - `message`
  - `context`

## 6. 健康检查

至少提供：

- API 健康检查
- 最近 weather fetch 时间
- 最近 market fetch 时间
- 最近 signal run 时间
- 数据库是否可写

## 7. 部署建议

第一版使用 Docker Compose：

- `api`
- `worker`
- `db` 可选，若先用 SQLite 可不单独起服务

## 8. 安全要求

- 私钥绝不入库
- `.env` 不提交版本控制
- 控制类 API 必须带鉴权

## 9. 告警建议

第一版只保留日志和 risk_events。

第二版再加：

- Telegram
- Discord
- 邮件或桌面通知

## 10. 完成标准

- 新环境能够在 30 分钟内按文档启动
- 关键配置项都可通过环境变量覆盖
