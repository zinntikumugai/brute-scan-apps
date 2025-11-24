# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Smart meter B-route data logger that retrieves power consumption data from Japanese smart meters using RL7023 Stick-D/IPS Wi-SUN module and stores it in InfluxDB v2. The system uses the `keilog` library (Git submodule) for Wi-SUN communication.

## Critical Architecture Concepts

### Data Flow Architecture

```
RL7023 Stick-D/IPS (Wi-SUN hardware)
  ↓ Serial (ECHONET Lite protocol)
BrouteReader (keilog thread - keilib/broute.py)
  ↓ Python Queue (thread-safe communication)
SmartMeterLogger (src/smartmeter_logger.py)
  ↓ CSV files (long format: 1 row per property)
Telegraf (CSV tail input plugin)
  ↓ InfluxDB Line Protocol
InfluxDB v2 (external server)
```

### Threading Model

**Critical**: The application uses a **Worker thread pattern** from keilog:

1. `BrouteReader` extends `Worker` (threading.Thread) from `keilib/worker.py`
2. Communication between threads uses Python `Queue` (thread-safe)
3. `BrouteReader` puts data to queue as: `['BR', epc, value, status]`
4. Main thread reads from queue with timeout to allow signal handling
5. Graceful shutdown uses `stopEvent` (threading.Event) - calling `reader.stop()` triggers `stopEvent.set()` and `join()`

**Never** try to call methods like `reader.read()` - BrouteReader doesn't have read methods. It's a background thread that pushes data to the queue.

### CSV Format - Long Format

**Critical**: The CSV format is **long format** (1 row per property), not wide format:

```csv
timestamp,unitid,epc,dataid,value
2025-11-24T12:00:00.123456,smartmeter01,E7,,1234
2025-11-24T12:00:00.234567,smartmeter01,E0,,5678.9
```

This design prevents sparse data issues. Each ECHONET Lite property arrives at different times through the queue and gets written immediately as a separate CSV row. Telegraf uses `csv_tag_columns = ["unitid", "epc", "dataid"]` to convert these into InfluxDB tags.

### keilog Integration

**Critical paths and imports**:
- keilog is a **Git submodule** at `./keilog/` - always use `git submodule update --init --recursive`
- Import from `keilib.broute` not `keilog`: `from keilib.broute import WiSunRL7023, BrouteReader`
- Dockerfile sets `ENV PYTHONPATH="/app/keilog"` to enable `keilib` imports
- Wrapper module `keiconf_broute.py` creates properly configured BrouteReader instances

### Signal Handling (keilog-compatible)

The application implements graceful shutdown compatible with keilog's signal handling:

1. **SIGTERM/SIGINT**: Graceful shutdown (sets `shutdown_requested` flag)
2. **SIGUSR1**: Toggle log level DEBUG ⇔ INFO (runtime debugging)
3. **DEBUG environment variable**: If set to "1", enables debug mode with console logging
4. Docker `stop_grace_period: 30s` gives enough time for BrouteReader thread to stop cleanly

### ECHONET Lite Property Codes

Properties are identified by EPC codes (config/settings.yml):
- **D3**: Coefficient (係数)
- **D7**: Unit (積算電力量単位)
- **E1**: Effective digits (積算電力量有効桁数)
- **E7**: Instantaneous power [W] (瞬時電力)
- **E0**: Total energy (forward) [kWh] (積算電力量・正方向)
- **E3**: Reverse energy [kWh] (積算電力量・逆方向)

## Development Commands

### Local Development with UV

```bash
# Install dependencies
uv pip install -e .
uv pip install -e ".[dev]"

# Lock dependencies
uv lock

# Run locally (requires hardware)
export BROUTE_ID=your_id BROUTE_PASSWORD=your_password SERIAL_PORT=/dev/ttyUSB0
python src/smartmeter_logger.py
```

### Docker Development

```bash
# Build image
docker build -t smartmeter-logger:dev .

# Run with docker-compose
docker compose up -d
docker compose logs -f smartmeter_logger

# Debug mode
docker compose run --rm -e DEBUG=1 smartmeter_logger

# Restart safely (graceful shutdown)
docker compose restart smartmeter_logger

# Access container
docker compose exec smartmeter_logger /bin/bash
```

### Code Quality

```bash
# Format code
uv run black src/

# Lint code
uv run ruff check src/

# Format check
uv run black --check src/
```

### Git Submodules

```bash
# Initialize keilog submodule (required after clone)
git submodule update --init --recursive

# Update keilog to latest
cd keilog && git pull origin master && cd ..
git add keilog && git commit -m "Update keilog submodule"
```

### Debugging Running Containers

```bash
# View logs
docker compose exec smartmeter_logger tail -f /app/logs/smartmeter_logger.log

# Toggle debug level (SIGUSR1)
docker compose exec smartmeter_logger kill -USR1 1

# Check CSV output
docker compose exec smartmeter_logger tail /app/logs/*.csv

# Test Telegraf configuration
docker compose exec telegraf telegraf --config /etc/telegraf/telegraf.conf --test
```

## Configuration Hierarchy

Configuration is loaded with environment variable override priority:

1. **config/settings.yml**: Base configuration
2. **.env file**: Environment variables (not committed)
3. **Environment variables in docker-compose.yml**: Runtime overrides

Example override chain for Bルート ID:
```
config/settings.yml: broute.id = ""
↓ overridden by
.env: BROUTE_ID=actual_id
↓ overridden by
docker-compose.yml: environment.BROUTE_ID=${BROUTE_ID}
```

## Common Patterns

### Adding New ECHONET Lite Properties

1. Add EPC code to `config/settings.yml`:
   ```yaml
   acquisition:
     properties:
       - E7  # existing
       - E8  # new property
   ```

2. Update `_parse_queue_data()` in `src/smartmeter_logger.py` if special type handling needed:
   ```python
   elif epc in ['E8']:  # Add type conversion
       value = float(value)
   ```

CSV format automatically handles new properties without schema changes.

### Modifying Data Output

**To add InfluxDB direct write** (skip CSV/Telegraf):
```yaml
# config/settings.yml
csv:
  enabled: false
influxdb:
  enabled: true
```

Then remove telegraf service from docker-compose.yml.

**To change CSV format**: Edit `_write_to_csv()` in `src/smartmeter_logger.py` and update `telegraf.conf` accordingly.

### Handling BrouteReader State Machine

BrouteReader (keilog) uses internal state machine:
```
INIT → OPEN → SETUP → SCAN → JOIN (connected)
```

If connection fails, it automatically retries from earlier state. Don't manually manage states - let keilog handle reconnection logic.

## Deployment

### GitHub Actions

Multi-platform Docker builds (amd64/arm64) automatically triggered on:
- Push to master/main
- Version tags (v*)
- Manual workflow dispatch

Images pushed to: `ghcr.io/zinntikumugai/brute-scan-apps:latest`

### Production Deployment

1. Pull latest image: `docker compose pull`
2. Restart with new image: `docker compose up -d`
3. Verify logs: `docker compose logs -f smartmeter_logger`
4. Check data flow: CSV → Telegraf → InfluxDB

### Rollback

```bash
# Use specific version tag
docker compose down
docker run -d --env-file .env ghcr.io/zinntikumugai/brute-scan-apps:v1.0.0
```

## Troubleshooting Patterns

### BrouteReader Not Receiving Data

1. Check state machine reached JOIN state (logs show state transitions)
2. Verify B-route credentials in .env
3. Ensure Wi-SUN module is close to smart meter
4. Check serial port permissions: `ls -l /dev/ttyUSB0`

### CSV/Telegraf Pipeline Issues

1. Verify CSV files being created: `docker compose exec smartmeter_logger ls -la /app/logs/`
2. Check CSV format matches telegraf.conf column definitions
3. Test Telegraf parsing: `docker compose exec telegraf telegraf --test`
4. Check Telegraf logs for type conversion errors

### Thread/Signal Issues

If graceful shutdown fails:
1. Check `stop_grace_period` in docker-compose.yml (default: 30s)
2. Verify signal handlers registered before BrouteReader.start()
3. Ensure main loop checks `shutdown_requested` frequently (timeout <= 1s)
4. BrouteReader.stop() must complete within grace period

## Python Version

**Python 3.13** is required (specified in pyproject.toml and Dockerfile). Do not downgrade - the project explicitly targets 3.13 for modern features and performance.

## Important Files

- **src/smartmeter_logger.py**: Main application (signal handling, CSV writing, queue reading)
- **keiconf_broute.py**: keilog wrapper (creates BrouteReader with correct parameters)
- **config/settings.yml**: Application configuration (loaded with env overrides)
- **telegraf.conf**: CSV → InfluxDB pipeline configuration
- **docker-compose.yml**: Multi-container orchestration (logger + telegraf)
- **.github/workflows/docker-build.yml**: CI/CD for multi-arch builds

## Do Not

- Do not call `reader.read()` or similar synchronous methods - BrouteReader is asynchronous
- Do not use wide CSV format with multiple columns per row - causes sparse data issues
- Do not forget `git submodule update` after clone - keilog is required
- Do not modify keilog source code - it's an external dependency (submodule)
- Do not use Python < 3.13 - project explicitly requires 3.13
- Do not skip graceful shutdown - can corrupt serial port state or data files
