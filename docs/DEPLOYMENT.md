# Deployment on an always-on host

The collector only acquires data while it is running, and quote downtime cannot
be reconstructed later. The macOS LaunchAgent in `scripts/collector_service.sh`
depends on a laptop staying awake and logged in. This page covers two
alternatives for a machine that stays on: a Docker image and a Linux systemd
unit. Neither was executed in the 3.1 validation environment; see
[validation](VALIDATION.md).

## Docker

The image installs the package with the dashboard extra and runs as an
unprivileged user. One image serves both roles: `dashboard` starts Streamlit
and any other arguments go to the `options_engine` command line.

```bash
docker build -t options-analysis-engine .
```

```bash
docker run --rm -p 8501:8501 options-analysis-engine dashboard
```

Create the collector configuration on the host first, then mount the config
directory read-only and a named volume for the data root. The default
`data_root` of `../data/live` relative to the config file resolves to
`/app/data/live` inside the container.

```bash
python3 -m options_engine init-live --provider tradier --config config/collector.json
```

```bash
docker run --rm -e TRADIER_TOKEN -v "$PWD/config:/app/config:ro" -v engine-data:/app/data options-analysis-engine collect --config config/collector.json
```

`-e TRADIER_TOKEN` forwards the variable from your shell without writing it
into the image or the config. The container's process lock, WAL ledger, and
backoff state live in the volume, so restarts resume where collection stopped.

`docker compose up --build` starts the dashboard and the collector together
on one shared volume. The dashboard's Collection & training tab reads the
same data root.

Back up the volume while the collector is stopped:

```bash
docker compose stop collector && docker run --rm -v engine-data:/data -v "$PWD:/backup" python:3.12-slim tar -czf "/backup/live-$(date +%Y%m%d-%H%M%S).tar.gz" -C /data . && docker compose start collector
```

## Linux systemd

Install the project under `/opt/options-analysis-engine` with its own
virtual environment and a dedicated user, then install the unit:

```bash
sudo useradd --system --create-home --home-dir /opt/options-analysis-engine options
```

```bash
sudo -u options bash -c 'cd /opt/options-analysis-engine && git clone https://github.com/omjoshi0925/options-analysis-engine.git . && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python -m options_engine init-live --provider tradier --config config/collector.json && mkdir -p data'
```

Put the token in an environment file readable only by the service user, and
edit the config's tickers, rate, and yields before enabling the service:

```bash
sudo install -d -m 700 -o options /etc/options-analysis-engine && printf 'TRADIER_TOKEN=%s\n' "$(read -rsp 'Tradier token: ' t; echo "$t")" | sudo -u options tee /etc/options-analysis-engine/environment >/dev/null && sudo chmod 600 /etc/options-analysis-engine/environment
```

```bash
sudo cp deploy/options-collector.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now options-collector
```

`ProtectSystem=strict` makes the filesystem read-only for the service except
the data directory, which is all the collector writes to. Check on it with:

```bash
systemctl status options-collector && sudo -u options /opt/options-analysis-engine/.venv/bin/python -m options_engine status --config /opt/options-analysis-engine/config/collector.json
```

## Operating notes

- Run one collector per data root; the process lock refuses a second.
- The collector waits outside XNYS regular sessions and honours persisted
  provider backoff across restarts, so a restart loop does not amplify a
  rate limit.
- The dashboard is read-mostly, but its training button runs the same gated
  evaluation as the collector's daily check; both use the training lock.
- Keep the provider token out of images, configs, logs, and compose files.
  The examples above pass it through the environment only.
