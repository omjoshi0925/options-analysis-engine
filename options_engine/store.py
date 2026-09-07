"""Durable run ledger and deduplicated observations; raw snapshots remain immutable."""
from pathlib import Path
from contextlib import closing
import hashlib
import json
import sqlite3
import uuid
import numpy as np
import pandas as pd
from .analysis import analyze_options
from .data import FilterConfig, read_snapshot
from .live_utils import clean_json, session_window


def training_quality(row, config, open_cache=None):
    reasons = []
    if row.get("data_kind") != "market":
        reasons.append("not_real_market_data")
    if row.get("provider") != "tradier" or row.get("feed") != "production":
        reasons.append("unverified_feed")
    captured = pd.Timestamp(row["as_of"])
    if captured.tzinfo is None:
        return ["timezone_missing"]
    captured = captured.tz_convert("UTC")
    stamp_values = {}
    for field, maximum in (("bid_timestamp", config.max_quote_age_seconds),
                            ("ask_timestamp", config.max_quote_age_seconds),
                            ("spot_timestamp", config.max_spot_age_seconds)):
        try:
            stamp = pd.Timestamp(row.get(field))
            if pd.isna(stamp) or stamp.tzinfo is None:
                raise ValueError("missing timestamp")
            stamp = stamp.tz_convert("UTC")
            age = (captured-stamp).total_seconds()
            stamp_values[field] = stamp
            if age < -5:
                reasons.append("future_"+field)
            if age > maximum:
                reasons.append("stale_"+field)
        except (TypeError, ValueError):
            reasons.append("missing_"+field)
    if len(stamp_values) == 3:
        span = (max(stamp_values.values())-min(stamp_values.values())).total_seconds()
        if span > config.max_timestamp_skew_seconds:
            reasons.append("asynchronous_quotes_and_spot")
    cache = open_cache if open_cache is not None else {}
    key = captured.isoformat()
    if key not in cache:
        cache[key] = session_window(captured)["is_open"]
    if not cache[key]:
        reasons.append("outside_regular_session")
    size = row.get("contract_size")
    if size != 100:
        reasons.append("nonstandard_contract_size")
    if not row.get("iv_brent_converged") or row.get("iv_brent_poorly_identified"):
        reasons.append("iv_not_identified")
    iv = row.get("iv_brent_volatility", np.nan)
    if not np.isfinite(iv) or not .03 <= iv <= 3.0:
        reasons.append("iv_outside_training_range")
    if row.get("mid", 0) < .10:
        reasons.append("midpoint_below_training_floor")
    if not config.min_days <= row.get("days_to_expiry", -1) <= config.max_days:
        reasons.append("training_maturity_filter")
    if abs(row.get("log_moneyness", 1)) > .35:
        reasons.append("outside_training_moneyness")
    return reasons


def observation_fingerprint(row):
    # Capture time is intentionally absent: polling an unchanged observation is not new data.
    fields = ("provider", "feed", "symbol", "contractSymbol", "option_type", "expiration", "strike",
              "bid", "ask", "bid_timestamp", "ask_timestamp", "spot", "spot_timestamp",
              "lastTradeDate", "volume", "openInterest")
    values = clean_json({key: row.get(key) for key in fields})
    return hashlib.sha256(json.dumps(values, sort_keys=True, allow_nan=False).encode()).hexdigest()


class ObservationStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root/"observations.sqlite3"
        with closing(self.connect()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
                    provider TEXT NOT NULL, status TEXT NOT NULL, snapshot_path TEXT,
                    snapshot_hash TEXT UNIQUE, raw_rows INTEGER DEFAULT 0,
                    accepted_rows INTEGER DEFAULT 0, inserted_rows INTEGER DEFAULT 0,
                    training_rows INTEGER DEFAULT 0, details_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS observations (
                    observation_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id),
                    as_of TEXT NOT NULL, session_date TEXT NOT NULL, symbol TEXT NOT NULL,
                    training_eligible INTEGER NOT NULL, quality_reasons TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS observations_session ON observations(session_date);
                CREATE INDEX IF NOT EXISTS observations_training ON observations(training_eligible, session_date);
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def begin_run(self, provider, started_at=None):
        run_id = uuid.uuid4().hex
        started = started_at or pd.Timestamp.now(tz="UTC").isoformat()
        with closing(self.connect()) as db, db:
            db.execute("INSERT INTO runs(run_id, started_at, provider, status) VALUES (?,?,?,?)",
                       (run_id, started, provider, "running"))
        return run_id

    def fail_run(self, run_id, details, status="failed"):
        with closing(self.connect()) as db, db:
            db.execute("UPDATE runs SET status=?, finished_at=?, details_json=? WHERE run_id=?",
                       (status, pd.Timestamp.now(tz="UTC").isoformat(), json.dumps(clean_json(details)), run_id))

    def recover_interrupted(self):
        with closing(self.connect()) as db, db:
            db.execute("UPDATE runs SET status='interrupted', finished_at=? WHERE status='running'",
                       (pd.Timestamp.now(tz="UTC").isoformat(),))

    def ingest(self, snapshot_path, config, run_id=None):
        raw, metadata = read_snapshot(snapshot_path)
        sha = metadata["csv_sha256"]["raw_options.csv"]
        with closing(self.connect()) as db:
            previous = db.execute("SELECT run_id FROM runs WHERE snapshot_hash=?", (sha,)).fetchone()
        if previous:
            if run_id:
                self.fail_run(run_id, {"duplicate_of": previous["run_id"]}, "duplicate_snapshot")
            return dict(status="duplicate_snapshot", run_id=previous["run_id"], inserted_rows=0)
        run_id = run_id or self.begin_run(metadata.get("provider", "import"))
        filters = FilterConfig(min_open_interest=config.min_open_interest,
                                max_relative_spread=config.max_relative_spread,
                                min_days=config.min_days, max_days=config.max_days)
        analyzed, audit = analyze_options(raw, filters)
        # Write derived inspection artifacts separately; do not mutate raw snapshot files.
        derived = self.root/"audits"/run_id
        derived.mkdir(parents=True, exist_ok=True)
        audit.to_csv(derived/"filter_audit.csv", index=False)
        prepared, cache = [], {}
        for row in analyzed.to_dict("records"):
            if metadata.get("data_kind") != "market":
                row["data_kind"] = metadata.get("data_kind", "unknown")
            reasons = training_quality(row, config, cache)
            row["quality_reasons"] = ";".join(reasons)
            row["training_eligible"] = not reasons
            stamp = pd.Timestamp(row["as_of"]).tz_convert("UTC")
            session = str(stamp.tz_convert("America/New_York").date())
            row["session_date"] = session
            row["observation_id"] = observation_fingerprint(row)
            prepared.append(row)
        pd.DataFrame(prepared).to_csv(derived/"analyzed_options.csv", index=False)
        inserted = eligible_inserted = 0
        with closing(self.connect()) as db, db:
            for row in prepared:
                cur = db.execute("""INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?,?,?)""",
                                 (row["observation_id"], run_id, row["as_of"], row["session_date"], row["symbol"],
                                  int(row["training_eligible"]), row["quality_reasons"],
                                  json.dumps(clean_json(row), sort_keys=True, allow_nan=False)))
                inserted += cur.rowcount
                eligible_inserted += cur.rowcount*int(row["training_eligible"])
            status = "partial" if metadata.get("failures") else "ok"
            details = dict(failures=metadata.get("failures", []), config=config.public_dict(),
                           duplicate_observations=len(prepared)-inserted,
                           quality_counts=pd.Series([reason for row in prepared for reason in row["quality_reasons"].split(";") if reason]).value_counts().to_dict())
            db.execute("""UPDATE runs SET finished_at=?, status=?, snapshot_path=?, snapshot_hash=?,
                       raw_rows=?, accepted_rows=?, inserted_rows=?, training_rows=?, details_json=? WHERE run_id=?""",
                       (pd.Timestamp.now(tz="UTC").isoformat(), status, str(Path(snapshot_path).resolve()), sha,
                        len(raw), len(analyzed), inserted, eligible_inserted, json.dumps(clean_json(details)), run_id))
        return dict(status=status, run_id=run_id, raw_rows=len(raw), accepted_rows=len(analyzed),
                    inserted_rows=inserted, training_rows=eligible_inserted, details=details)

    def training_frame(self, before=None, lookback_sessions=60, max_rows_per_symbol_session=500):
        query = """WITH eligible AS (
                    SELECT * FROM observations WHERE training_eligible=1 AND session_date < ?
                  ), recent AS (
                    SELECT * FROM eligible WHERE session_date IN
                      (SELECT DISTINCT session_date FROM eligible ORDER BY session_date DESC LIMIT ?)
                  ), ranked AS (
                    SELECT *, ROW_NUMBER() OVER (PARTITION BY session_date,symbol ORDER BY observation_id) AS sample_rank FROM recent
                  ) SELECT payload_json FROM ranked WHERE sample_rank <= ? ORDER BY as_of,observation_id"""
        params = (str(before or "9999-12-31"), int(lookback_sessions), int(max_rows_per_symbol_session))
        with closing(self.connect()) as db:
            records = [json.loads(row[0]) for row in db.execute(query, params)]
        return pd.DataFrame(records)

    def status(self):
        with closing(self.connect()) as db:
            totals = dict(db.execute("""SELECT COUNT(*) AS observations, COALESCE(SUM(training_eligible),0) AS training_rows,
                        COUNT(DISTINCT CASE WHEN training_eligible=1 THEN session_date END) AS training_sessions,
                        MAX(as_of) AS latest_observation FROM observations""").fetchone())
            runs = [dict(row) for row in db.execute("SELECT run_id,started_at,status,raw_rows,inserted_rows,training_rows FROM runs ORDER BY started_at DESC LIMIT 10")]
            counts = [dict(row) for row in db.execute("SELECT quality_reasons,COUNT(*) AS n FROM observations WHERE training_eligible=0 GROUP BY quality_reasons ORDER BY n DESC LIMIT 10")]
        return {**totals, "recent_runs": runs, "quality_exclusions": counts}
