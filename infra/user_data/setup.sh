#!/bin/bash
set -euo pipefail

# ── system packages ────────────────────────────────────────────────────────────
yum update -y
yum install -y git python3.11 python3.11-pip

# ── CloudWatch agent ───────────────────────────────────────────────────────────
yum install -y amazon-cloudwatch-agent
cat > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json <<'CWAGENT'
{
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/var/log/poly-weather/api.log",
            "log_group_name": "/poly-weather/api",
            "log_stream_name": "{instance_id}",
            "timezone": "UTC"
          },
          {
            "file_path": "/var/log/poly-weather/worker.log",
            "log_group_name": "/poly-weather/worker",
            "log_stream_name": "{instance_id}",
            "timezone": "UTC"
          }
        ]
      }
    }
  }
}
CWAGENT
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config -m ec2 \
  -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json -s

# ── app directory & data volume ────────────────────────────────────────────────
mkdir -p /opt/poly-weather /var/lib/poly-weather /var/log/poly-weather

# Mount the extra EBS data volume if it is not already formatted/mounted
DATA_DEVICE=/dev/xvdf
if ! blkid "$DATA_DEVICE" > /dev/null 2>&1; then
  mkfs -t xfs "$DATA_DEVICE"
fi
if ! grep -q "$DATA_DEVICE" /etc/fstab; then
  echo "$DATA_DEVICE /var/lib/poly-weather xfs defaults,nofail 0 2" >> /etc/fstab
fi
mount -a

# ── clone repo ─────────────────────────────────────────────────────────────────
REPO_DIR=/opt/poly-weather/app
if [ ! -d "$REPO_DIR/.git" ]; then
  git clone https://github.com/JadeSure/poly_weather.git "$REPO_DIR"
fi

cd "$REPO_DIR"
python3.11 -m pip install -e .

# ── env file – point database at the persistent EBS volume ────────────────────
mkdir -p /etc/poly-weather
cat > /etc/poly-weather/.env <<'ENVFILE'
APP_ENV=production
DATABASE_URL=sqlite:////var/lib/poly-weather/weatheredge.db
LOG_LEVEL=INFO
SQL_ECHO=false
TRADING_MODE=paper
NOAA_AWC_API_BASE=https://aviationweather.gov/api/data
OPEN_METEO_API_BASE=https://api.open-meteo.com/v1
OPEN_METEO_ENSEMBLE_API_BASE=https://ensemble-api.open-meteo.com/v1
POLYMARKET_API_BASE=https://clob.polymarket.com
POLYMARKET_GAMMA_API_BASE=https://gamma-api.polymarket.com
POLYGON_RPC_URL=
POLYMARKET_PRIVATE_KEY=
MAX_SINGLE_TRADE_USDC=25
MAX_DAILY_LOSS_USDC=100
MAX_CONCURRENT_POSITIONS=20
MAX_CITY_EXPOSURE_USDC=50
MAX_MARKET_EXPOSURE_USDC=25
EXECUTION_SIGNAL_MAX_AGE_MINUTES=15
STATIONS_CONFIG_PATH=/opt/poly-weather/app/config/stations.yaml
LOGGING_CONFIG_PATH=/opt/poly-weather/app/config/logging.json
ENVFILE
chmod 600 /etc/poly-weather/.env

# ── systemd: API service ───────────────────────────────────────────────────────
cat > /etc/systemd/system/poly-weather-api.service <<'UNIT'
[Unit]
Description=Poly Weather API (uvicorn)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=nobody
Group=nobody
WorkingDirectory=/opt/poly-weather/app
EnvironmentFile=/etc/poly-weather/.env
ExecStart=/usr/local/bin/uvicorn src.api.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=30
StandardOutput=append:/var/log/poly-weather/api.log
StandardError=append:/var/log/poly-weather/api.log
ReadWritePaths=/var/lib/poly-weather /var/log/poly-weather

[Install]
WantedBy=multi-user.target
UNIT

# ── systemd: worker service ────────────────────────────────────────────────────
cat > /etc/systemd/system/poly-weather-worker.service <<'UNIT'
[Unit]
Description=Poly Weather worker (APScheduler)
After=network-online.target poly-weather-api.service
Wants=network-online.target

[Service]
Type=simple
User=nobody
Group=nobody
WorkingDirectory=/opt/poly-weather/app
EnvironmentFile=/etc/poly-weather/.env
ExecStart=/usr/bin/python3.11 -m src.worker.main
Restart=on-failure
RestartSec=30
StandardOutput=append:/var/log/poly-weather/worker.log
StandardError=append:/var/log/poly-weather/worker.log
ReadWritePaths=/var/lib/poly-weather /var/log/poly-weather

[Install]
WantedBy=multi-user.target
UNIT

# fix ownership so nobody can write to data/log dirs
chown -R nobody:nobody /var/lib/poly-weather /var/log/poly-weather

systemctl daemon-reload
systemctl enable poly-weather-api poly-weather-worker
systemctl start poly-weather-api poly-weather-worker
