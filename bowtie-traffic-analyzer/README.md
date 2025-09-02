# Bowtie Traffic Analyzer

Spin up a local Prometheus instance pre-configured to federate client traffic metrics from multiple Bowtie controllers, display the aggregated results, and optionally provide user and device attribution.

## How It Works
[Each Bowtie Controller aggregates it's device metrics in Prometheus](https://docs.bowtie.works/operating/controller.html#observability). A custom exporter can be defined via an OpenTelemetry configuration file, which will expose those aggregated metrics at the configured endpoint. This tool then spins up a local Prometheus instance to scrape the metrics from that endpoint over the Bowtie tunnel, and then optionally, via a session cookie, pull down device and user information to map traffic accordingly.

## Prerequisites

- Python 3.7+
- Docker & Docker Compose
- Running Bowtie client
- Access to Bowtie Controller web UI

## Quick Start

### 1. Setup

```bash
# Ensure Docker is running
docker info

# Clone and install
git clone https://github.com/bowtieworks/bowtie-helpers/bowtie-traffic-analyzer.git
cd bowtie-traffic-analyzer
pip3 install -r requirements.txt
```

### 2. Configure Controllers

Create and upload OTEL configuration to all controllers in the cluster:

```bash
# Upload via Controller web UI > Settings > otel.yaml
# Be sure to change <CONTROLLER_NAME> to a unique identifier for that peer
cat > /etc/otel.yaml << 'EOF'
exporters:
  prometheus:
    endpoint: '0.0.0.0:9092'
processors:
  transform/add_appliance_id:
    metric_statements:
      - context: datapoint
        statements:
          - set(attributes["appliance_id"], "<CONTROLLER_NAME>")
service:
  pipelines:
    metrics:
      receivers: [prometheus/federated]
      processors: [transform/add_appliance_id]
      exporters: [prometheus]
EOF
```

### 3. Start Local Prometheus

Edit [prometheus.yaml](config/prometheus.yaml) with your controller's WireGuard IPs:

```yaml
scrape_configs:
  - job_name: 'bowtie-controllers'
    static_configs:
      - targets: 
        - '10.100.0.188:9092' # Replace with your Controller's WG IPs
        - '10.100.0.13:9092'
        # Add more as needed
```

<details>
<summary>Options for finding a Controller's Wireguard IPs</summary>

```bash
# Option 1: From controller shell
ssh root@controller
ip addr show bowtie | grep "inet "

# Option 2: From local machine
sudo wg

# Option 3: From Bowtie app
Bowtie > Help > Routes

# Option 4: From web UI
Controller > Devices > Bowtie Controllers
```
</details>

Start services:

```bash
docker-compose up -d

# Verify Prometheus is running and controllers are UP
curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[].health'
# Or view in browser: http://localhost:9090/targets
```

### 4. Run Analysis

```bash
# First run - will prompt for device/user mappings
./bowtie_traffic_analyzer.py --time-range 24h

# To run on windows
python bowtie_traffic_analyzer.py --time-range 24h

# Generate CSV reports
./bowtie_traffic_analyzer.py --time-range 7d --output-prefix reports/weekly
```

## Usage

### Understanding Parameters

**Important:** 
- `--time-range` determines the data period included in the report (e.g., `7d` = past 7 days of traffic)
- `--output-prefix` is only for file naming and doesn't affect the data content

Example:
```bash
# This creates a file named "daily_*.csv" but contains 7 days of data
./bowtie_traffic_analyzer.py --time-range 7d --output-prefix reports/daily
```

### Time Ranges

- `1h`, `6h`, `24h` (default), `7d`, `30d`

### Examples

```bash
# 24-hour traffic report (data: past 24h, filename: includes date)
./bowtie_traffic_analyzer.py --time-range 24h --output-prefix daily_$(date +%Y%m%d)

# Weekly report (data: past 7 days, filename: "weekly_*.csv")
./bowtie_traffic_analyzer.py --time-range 7d --output-prefix weekly

# Monthly report (data: past 30 days, filename: "monthly_*.csv")
./bowtie_traffic_analyzer.py --time-range 30d --output-prefix monthly

# User-only summary for the past week
./bowtie_traffic_analyzer.py --time-range 7d --users-only

# Real-time monitoring (shows past hour, updates every 60s)
watch -n 60 './bowtie_traffic_analyzer.py --time-range 1h --skip-update'
```

### Output Files

`--output-prefix`, generates three CSVs with cumulative totals for the specified time range:
- `*_detailed_*.csv` - Per-device traffic data over the time period
- `*_aggregated_*.csv` - Summary by controller over the time period
- `*_users_*.csv` - Per-user statistics over the time period

Each row shows total bytes sent/received during the entire `--time-range` period.

### Device/User Mapping

The analyzer maps public keys to device names and user emails. On first run, it will:

1. Prompt for a session cookie from your Controller web UI
2. Fetch and cache mappings for 24 hours
3. Auto-refresh when stale

To manually update mappings:
```bash
./bowtie_traffic_analyzer.py --update-mappings
```

To get the session cookie:
1. Login to Controller web UI
2. Open DevTools (F12) → Application → Cookies
3. Copy the session cookie value

## Troubleshooting

### No metrics appearing
```bash
# Check Prometheus targets via API
curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[].health'

# Verify controller metrics
curl http://CONTROLLER_IP:9092/metrics | grep wireguard

# Check collector logs on controller
journalctl -u opentelemetry-collector -f
```

### Authentication errors
- Session cookie may have expired - re-login to controller
- Cookie format: `name=value` or `name1=value1; name2=value2`
- Test: `curl -H "Cookie: YOUR_COOKIE" "https://controller/-net/api/v0/device"`

### Port conflicts
```bash
lsof -i :9090  # Prometheus
docker-compose logs prometheus
```

## Cleanup

### Stop Services
```bash
# Stop Prometheus container (keeps data)
docker-compose stop

# Stop and remove container (keeps data volume)
docker-compose down

# Complete cleanup (removes container AND data)
docker-compose down -v
```

### Remove Cached Data
```bash
# Remove device/user mapping cache
rm -rf mappings/*

# Remove generated reports
rm -rf reports/*
```

## Support

For issues or questions, visit the [Bowtie Helpers repository](https://github.com/bowtieworks/bowtie-helpers) or contact `support@bowtie.security`.