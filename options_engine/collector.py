"""Restartable polling service with backoff, hard worker deadlines and durable status."""
from pathlib import Path
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import random
import signal
import shutil
import subprocess
import sys
import threading
import time
import pandas as pd
from .live_config import LiveConfig
from .live_utils import atomic_json, process_lock, session_window
from .store import ObservationStore
from .learning import train, monitor_latest


def worker_process(config_path, destination, timeout, stop):
    process = subprocess.Popen([sys.executable, "-m", "options_engine.collector_worker", str(config_path), str(destination)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic()+timeout
    try:
        while process.poll() is None:
            if stop.is_set() or time.monotonic() >= deadline:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                if stop.is_set():
                    raise InterruptedError("Collection stopped")
                raise TimeoutError(f"Acquisition exceeded {timeout} seconds")
            stop.wait(.2)
        return process.returncode
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def collect_cycle(config_path, config, root, store, stop, executor=worker_process):
    run_id = store.begin_run(config.provider)
    day = pd.Timestamp.now(tz="America/New_York").date().isoformat()
    pending = root/"pending"/run_id
    pending.parent.mkdir(parents=True, exist_ok=True)
    try:
        if shutil.disk_usage(root).free < config.min_free_disk_mb*1024**2:
            raise OSError(f"Less than {config.min_free_disk_mb} MB free; collection paused without deleting historical data")
        code = executor(config_path, pending, config.cycle_timeout_seconds, stop)
        if code != 0:
            error_path = pending.with_suffix(".failure.json")
            details = json.loads(error_path.read_text()) if error_path.exists() else {"error": "Acquisition worker failed", "returncode": code}
            store.fail_run(run_id, details)
            atomic_json(root/"failures"/(run_id+".json"), details)
            return dict(status="failed", run_id=run_id, retry_after_seconds=details.get("retry_after_seconds", 0), details=details)
        # Only complete worker snapshots move into the permanent archive.
        destination = root/"snapshots"/day/run_id
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(pending, destination)
        result = store.ingest(destination, config, run_id)
        try:
            monitor_latest(root, run_id)
        except (ValueError, KeyError, OSError) as exc:
            result["monitor_error"] = str(exc)
        meta = json.loads((destination/"metadata.json").read_text())
        result["retry_after_seconds"] = meta.get("retry_after_seconds", 0)
        return result
    except InterruptedError:
        store.fail_run(run_id, {"error": "Collector interrupted"}, "interrupted")
        raise
    except Exception as exc:  # Service boundary; retain data errors and continue subsequent scheduled cycles.
        details = {"error": f"{type(exc).__name__}: {exc}"}
        store.fail_run(run_id, details)
        atomic_json(root/"failures"/(run_id+".json"), details)
        return dict(status="failed", run_id=run_id, retry_after_seconds=0, details=details)


def retry_delay(config, consecutive_failures, provider_retry=0, rng=None):
    rng = rng or random
    cap = min(config.max_backoff_seconds, config.interval_seconds*2**min(consecutive_failures, 16))
    # Jitter only adds delay. Provider Retry-After is a lower bound, including across restarts.
    return max(cap+rng.uniform(0, .1*cap), float(provider_retry or 0))


def recover_snapshots(root, config, store):
    """Recover complete snapshots left between file publication and DB commit."""
    from contextlib import closing
    with closing(store.connect()) as db:
        indexed = {row[0] for row in db.execute("SELECT snapshot_path FROM runs WHERE snapshot_hash IS NOT NULL")}
    def quarantine(folder, exc):
        # Preserve bad files for inspection without letting one poison every restart.
        run_id = store.begin_run(config.provider)
        target = root/"quarantine"/(folder.name+"_"+run_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(folder, target)
        details = dict(error=f"Recovery failed: {type(exc).__name__}: {exc}", quarantine=str(target))
        store.fail_run(run_id, details, "quarantined")
        atomic_json(root/"failures"/(run_id+".json"), details)
    for manifest in (root/"pending").glob("*/metadata.json"):
        folder = manifest.parent
        try:
            meta = json.loads(manifest.read_text())
            stamp = pd.Timestamp(meta.get("acquisition_finished", pd.Timestamp.now(tz="UTC")))
            day = str(stamp.tz_convert("America/New_York").date())
            target = root/"snapshots"/day/folder.name
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                os.replace(folder, target)
        except (ValueError, TypeError, KeyError) as exc:
            quarantine(folder, exc)
    recovered = []
    for manifest in sorted((root/"snapshots").glob("*/*/metadata.json")):
        if str(manifest.parent.resolve()) not in indexed:
            try:
                recovered.append(store.ingest(manifest.parent, config))
            except (ValueError, TypeError, KeyError, OSError) as exc:
                quarantine(manifest.parent, exc)
    store.recover_interrupted()
    return recovered


def run_collector(config_path, once=False, probe=False):
    config_path = Path(config_path).resolve()
    config, root = LiveConfig.load(config_path)
    _ = (config.constant_rate, config.constant_dividend_yields)   # live collection stamps constants; series are evaluation-only
    if config.provider == "dolt_eod":
        raise ValueError("dolt_eod is an import-only historical provider; use the import-eod command instead of the collector")
    if config.provider == "tradier" and not os.environ.get("TRADIER_TOKEN"):
        raise ValueError("Set TRADIER_TOKEN locally before starting the Tradier collector. It is never saved in config or logs.")
    root.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("options_collector")
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(root/"collector.log", maxBytes=5_000_000, backupCount=4)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    stop = threading.Event()
    previous_handlers = {}
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[sig] = signal.signal(sig, lambda *_: stop.set())
    status_path = root/"collector_status.json"
    try:
        with process_lock(root/"collector.lock"):
            store = ObservationStore(root)
            store.recover_interrupted()
            recovered = recover_snapshots(root, config, store)
            if recovered:
                logger.info("recovered_snapshots=%s", len(recovered))
            previous = json.loads(status_path.read_text()) if status_path.exists() else {}
            next_due = pd.Timestamp(previous["next_due"]) if previous.get("next_due") else pd.Timestamp.now(tz="UTC")
            failures = int(previous.get("consecutive_failures", 0))
            last_training_check = None
            while not stop.is_set():
                now = pd.Timestamp.now(tz="UTC")
                window = session_window(now)
                # Check once per local day; train() independently enforces complete dates and fresh holdout.
                day = str(now.tz_convert("America/New_York").date())
                if config.auto_train and last_training_check != day:
                    try:
                        training = train(root, config, now)
                        logger.info("training_state=%s", training["state"])
                    except Exception as exc:
                        logger.error("training_failed=%s", type(exc).__name__)
                        atomic_json(root/"training_status.json", dict(state="error", message=str(exc), checked_at=now.isoformat()))
                    last_training_check = day
                status = dict(pid=os.getpid(), provider=config.provider, heartbeat=now.isoformat(),
                              next_due=next_due.isoformat(), consecutive_failures=failures,
                              session=window, state="waiting_for_market" if not window["is_open"] else "waiting_for_schedule")
                due = now >= next_due
                # A manual probe bypasses market hours, but never a persisted throttle/cadence deadline.
                if (window["is_open"] or probe) and due:
                    status["state"] = "collecting"
                    atomic_json(status_path, status)
                    result = collect_cycle(config_path, config, root, store, stop)
                    unsuccessful = result["status"] == "failed" or result.get("retry_after_seconds", 0) > 0
                    failures = failures+1 if unsuccessful else 0
                    delay = retry_delay(config, failures, result.get("retry_after_seconds", 0)) if unsuccessful else config.interval_seconds
                    next_due = pd.Timestamp.now(tz="UTC")+pd.Timedelta(seconds=delay)
                    status.update(state=result["status"], last_result=result, next_due=next_due.isoformat(),
                                  consecutive_failures=failures, heartbeat=pd.Timestamp.now(tz="UTC").isoformat())
                    logger.info("cycle_status=%s run=%s inserted=%s", result["status"], result.get("run_id"), result.get("inserted_rows", 0))
                    atomic_json(status_path, status)
                    if once or probe:
                        print(json.dumps(status, indent=2))
                        return 2 if unsuccessful else 0
                else:
                    atomic_json(status_path, status)
                    if once or probe:
                        print(json.dumps(status, indent=2))
                        return 0
                stop.wait(30)
            return 0
    except InterruptedError:
        return 0
    finally:
        if stop.is_set() and status_path.exists():
            status = json.loads(status_path.read_text())
            status.update(state="stopped", heartbeat=pd.Timestamp.now(tz="UTC").isoformat())
            atomic_json(status_path, status)
        for sig, previous in previous_handlers.items():
            signal.signal(sig, previous)
        logger.removeHandler(handler)
        handler.close()


def live_status(config_path):
    config, root = LiveConfig.load(config_path)
    result = {"provider": config.provider, "data_root": str(root)}
    if not (root/"observations.sqlite3").exists():
        result["state"] = "not_started"
        return result
    result["database"] = ObservationStore(root).status()
    for key, filename in (("collector", "collector_status.json"), ("training", "training_status.json"),
                           ("monitoring", "latest_monitor.json"), ("registry", "models/registry.json")):
        path = root/filename
        if path.exists():
            result[key] = json.loads(path.read_text())
    if result.get("collector", {}).get("heartbeat"):
        age = (pd.Timestamp.now(tz="UTC")-pd.Timestamp(result["collector"]["heartbeat"])).total_seconds()
        result["heartbeat_age_seconds"] = age
        result["heartbeat_stale"] = age > config.cycle_timeout_seconds+90
    return result
