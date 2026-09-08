#!/usr/bin/env python
"""Build or check docs/results/manifest.json for the frozen study (tag study-v1).

The manifest lists, for every numeric claim in docs/RESULTS.md, the saved file
and the field or derivation that produces it, plus SHA-256 hashes of every
artifact the report depends on. Build mode needs the local data roots, import
CSVs, and results directories that are not committed; check mode verifies
whatever is available, starting with the committed artifacts, and skips
local-only sources that are absent.

    python docs/results/build_manifest.py            # rebuild the manifest
    python docs/results/build_manifest.py --check    # verify against it

Nothing here reruns the import or the walk-forward. The only computation is
hashing, counting, and the deterministic (seed 0) block bootstrap re-derived
from the committed fold table with the package's own function.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
MANIFEST = Path("docs/results/manifest.json")
BOOTSTRAP_FILE = Path("docs/results/full-history-v2/bootstrap-block-lengths.json")
BOOTSTRAP_BLOCKS = (10, 21, 63, 126)
STUDY = dict(tag="study-v1", frozen_on="2026-09-08", report="docs/RESULTS.md", code_version="3.2.1",
             repository="https://github.com/omjoshi0925/options-analysis-engine")

RUNS = {
    "full-history-v2": dict(
        results="results/full-history-v2", committed="docs/results/full-history-v2",
        config="config/eod-full.json", data_root="data/eod-live-full",
        role="Full-history walk-forward cited throughout docs/RESULTS.md (3.2.1 code: Newey-West variant, per-symbol fold losses)",
        command="python -m options_engine walk-forward --config config/eod-full.json --output results/full-history-v2 "
                "--min-train-sessions 120 --gap 1 --window rolling --max-train-sessions 250"),
    "spy-2023-v2": dict(
        results="results/spy-2023-v2", committed="docs/results/spy-2023-v2",
        config="config/eod.json", data_root="data/live",
        role="Single-year SPY 2023 walk-forward cited in docs/RESULTS.md",
        command="python -m options_engine walk-forward --config config/eod.json --output results/spy-2023-v2 "
                "--min-train-sessions 60 --gap 1 --window expanding"),
    "full-history-v1": dict(
        results="results/full-history", committed="docs/results/full-history-v1",
        config="config/eod-full.json", data_root="data/eod-live-full",
        role="Same specification run before the Newey-West variant existed; identical DM and bootstrap values; already committed",
        command=None),
    "spy-2023-v1": dict(
        results="results/spy-2023", committed=None, config="config/eod.json", data_root="data/live",
        role="SPY 2023 run before the Newey-West variant; identical DM and bootstrap values; local only, superseded by spy-2023-v2",
        command=None),
}
RUN_FILES = ("folds.csv", "significance.json", "REPORT.md")
EXPORTS = {
    "full-history": dict(
        local="results/full-history-observations.csv",
        committed="docs/results/full-history-v2/observations-with-exclusions.csv.gz",
        config="config/eod-full.json", data_root="data/eod-live-full",
        command="python -m options_engine export --config config/eod-full.json "
                "--output results/full-history-observations.csv --include-excluded",
        generated="2026-09-08 during the freeze; the study itself had not saved one. "
                  "The store hash was identical before and after the export."),
    "spy-2023": dict(
        local="results/spy-2023-observations.csv",
        committed="docs/results/spy-2023-v2/observations-with-exclusions.csv.gz",
        config="config/eod.json", data_root="data/live",
        command="python -m options_engine export --config config/eod.json "
                "--output results/spy-2023-observations.csv --include-excluded",
        generated="2026-09-08 12:40 local time by the study; a fresh export during the freeze was byte-identical."),
}
IMPORT_CSVS = [
    dict(path="full_chain.csv", role="DoltHub post-no-preference/options option_chain export used by the full-history import-eod"),
    dict(path="full_underlying.csv", role="DoltHub post-no-preference/stocks ohlcv export (SPY, QQQ, AAPL bars) used by the full-history import-eod"),
    dict(path="spy_chain_2023.csv", role="option_chain export used by the SPY 2023 import-eod"),
    dict(path="spy_underlying.csv", role="ohlcv export used by the SPY 2023 import-eod"),
]
CONFIGS = [
    dict(path="config/eod-full.json", role="full-history import-eod, walk-forward, and export"),
    dict(path="config/eod.json", role="SPY 2023 import-eod, walk-forward, and export"),
]
DOLT_CLONES = {"options": "post-no-preference/options", "stocks": "post-no-preference/stocks"}
EXPORT_COLUMNS = ["symbol", "session_date", "training_eligible", "quality_reasons"]


# ----------------------------------------------------------------------------- helpers
def sha256_file(path, gz_member=False):
    digest = hashlib.sha256()
    opener = gzip.open if gz_member else open
    with opener(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_entry(relpath, **extra):
    path = ROOT/relpath
    return dict(path=str(relpath), sha256=sha256_file(path), bytes=path.stat().st_size, **extra)


def exists(relpath):
    return (ROOT/relpath).exists()


def git(*args):
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def jsonable(value):
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if hasattr(value, "item"):
        return value.item()
    return value


def calendar():
    import exchange_calendars as xc
    return xc.get_calendar("XNYS")


def is_session(cal, day):
    try:
        cal.date_to_session(day)
        return True
    except Exception:  # noqa: BLE001 - the calendar raises several types for non-sessions
        return False


def package_versions():
    out = {"python": sys.version.split()[0]}
    for name in ("numpy", "pandas", "scipy", "exchange_calendars"):
        try:
            out[name] = __import__(name).__version__
        except Exception:  # noqa: BLE001
            out[name] = None
    return out


# ----------------------------------------------------------------------------- loaders
def load_run(name):
    """Prefer the committed copy; fall back to results/ for a local-only run."""
    run = RUNS[name]
    for base in (run["committed"], run["results"]):
        if base and exists(f"{base}/folds.csv") and exists(f"{base}/significance.json"):
            folds = pd.read_csv(ROOT/base/"folds.csv")
            significance = json.loads((ROOT/base/"significance.json").read_text())
            return dict(base=base, folds=folds, significance=significance)
    return None


def load_export(name):
    spec = EXPORTS[name]
    for candidate in (spec["local"], spec["committed"]):
        if exists(candidate):
            frame = pd.read_csv(ROOT/candidate, usecols=EXPORT_COLUMNS, dtype={"quality_reasons": "string"})
            frame["quality_reasons"] = frame.quality_reasons.fillna("")
            frame["training_eligible"] = frame.training_eligible.astype(bool)
            return frame, candidate
    return None, None


# ----------------------------------------------------------------------------- statistics
def fold_stats(folds):
    improvement = 1-folds.model_rmse/folds.baseline_rmse
    years = pd.to_datetime(folds.evaluated_session).dt.year
    by_year = {}
    for year, group in folds.groupby(years):
        by_year[int(year)] = dict(folds=int(len(group)),
                                  win_rate=float((group.model_loss < group.baseline_loss).mean()),
                                  rmse_improvement=float(1-group.model_rmse.mean()/group.baseline_rmse.mean()))
    symbols = {}
    for column in folds.columns:
        if column.startswith("baseline_loss_"):
            symbols[column.removeprefix("baseline_loss_")] = int(folds[column].notna().sum())
    return dict(folds=int(len(folds)), first=str(folds.evaluated_session.iloc[0]), last=str(folds.evaluated_session.iloc[-1]),
                evaluation_rows=int(folds.evaluation_rows.sum()), win_rate=float((folds.model_loss < folds.baseline_loss).mean()),
                mean_baseline_rmse=float(folds.baseline_rmse.mean()), mean_model_rmse=float(folds.model_rmse.mean()),
                mean_rmse_improvement=float(1-folds.model_rmse.mean()/folds.baseline_rmse.mean()),
                median_improvement=float(improvement.median()), iqr_low=float(improvement.quantile(.25)),
                iqr_high=float(improvement.quantile(.75)), mean_differential=float((folds.baseline_loss-folds.model_loss).mean()),
                by_year=by_year, folds_with_symbol=symbols, calendar_years=len(by_year),
                all_years_positive=bool(all(v["rmse_improvement"] > 0 for v in by_year.values())))


def bootstrap_intervals(folds):
    from options_engine.walkforward import circular_block_bootstrap_ci
    differential = (folds.baseline_loss-folds.model_loss).to_numpy(float)
    return {str(b): circular_block_bootstrap_ci(differential, n_boot=2000, block_length=b, seed=0) for b in BOOTSTRAP_BLOCKS}


def export_stats(frame, first_evaluated=None):
    excluded = frame.loc[~frame.training_eligible]
    out = dict(rows=int(len(frame)), training_eligible=int(frame.training_eligible.sum()),
               sessions=int(frame.session_date.nunique()), first_session=str(frame.session_date.min()),
               last_session=str(frame.session_date.max()), excluded_rows=int(len(excluded)),
               exclusions_by_reason={k: int(v) for k, v in excluded.quality_reasons.value_counts().items()},
               per_symbol={s: dict(rows=int(len(g)), training_eligible=int(g.training_eligible.sum()), sessions=int(g.session_date.nunique()))
                           for s, g in frame.groupby("symbol")},
               sessions_by_year={int(k): int(v) for k, v in pd.Series(sorted(frame.session_date.unique())).str[:4].value_counts().sort_index().items()})
    sessions = set(frame.session_date.unique())
    for symbol in out["per_symbol"]:
        present = set(frame.loc[frame.symbol == symbol, "session_date"])
        out["per_symbol"][symbol]["absent_sessions"] = sorted(sessions-present)
    if first_evaluated:
        window = frame.loc[frame.session_date >= first_evaluated]
        out["evaluated_window"] = dict(first=first_evaluated, sessions=int(window.session_date.nunique()), rows=int(len(window)),
                                       training_eligible=int(window.training_eligible.sum()),
                                       per_symbol={s: dict(rows=int(len(g)), training_eligible=int(g.training_eligible.sum()))
                                                   for s, g in window.groupby("symbol")},
                                       training_only_sessions_before=int(frame.loc[frame.session_date < first_evaluated].session_date.nunique()))
    return out


def calendar_stats(session_dates):
    cal = calendar()
    first, last = min(session_dates), max(session_dates)
    all_sessions = [str(s.date()) for s in cal.sessions_in_range(first, last)]
    missing = sorted(set(all_sessions)-set(session_dates))
    by_year = {}
    for day in all_sessions:
        by_year.setdefault(int(day[:4]), dict(xnys_sessions=0, in_store=0))["xnys_sessions"] += 1
    for day in session_dates:
        by_year.setdefault(int(day[:4]), dict(xnys_sessions=0, in_store=0))["in_store"] += 1
    return dict(first=first, last=last, xnys_sessions=len(all_sessions), in_store=len(set(session_dates)),
                missing=len(missing), missing_by_year={int(k): int(v) for k, v in pd.Series([m[:4] for m in missing]).value_counts().sort_index().items()} if missing else {},
                by_year=by_year)


def chain_stats(relpath):
    if not exists(relpath):
        return None
    cal = calendar()
    chain = pd.read_csv(ROOT/relpath, usecols=["date", "act_symbol"])
    chain["date"] = pd.to_datetime(chain.date).dt.date
    dates = sorted(chain.date.unique())
    non_sessions = [d for d in dates if not is_session(cal, d)]
    in_2019 = [d for d in non_sessions if d.year == 2019]
    other = [d for d in non_sessions if d.year != 2019]
    other_weekend = [d for d in other if d.weekday() >= 5]
    other_weekday = [d for d in other if d.weekday() < 5]
    per_symbol = {s: dict(rows=int(len(g)), first=str(g.date.min()), last=str(g.date.max()), distinct_dates=int(g.date.nunique()))
                  for s, g in chain.groupby("act_symbol")}
    return dict(rows=int(len(chain)), symbols=sorted(per_symbol), per_symbol=per_symbol, distinct_dates=len(dates),
                first=str(dates[0]), last=str(dates[-1]), session_dates=len(dates)-len(non_sessions),
                non_session_dates=len(non_sessions), rows_on_non_session_dates=int(chain.date.isin(non_sessions).sum()),
                non_session_dates_2019=len(in_2019), non_session_2019_first=str(in_2019[0]) if in_2019 else None,
                non_session_2019_last=str(in_2019[-1]) if in_2019 else None,
                non_session_2019_by_weekday={k: int(v) for k, v in pd.Series([d.strftime("%A") for d in in_2019]).value_counts().items()} if in_2019 else {},
                rows_on_2019_non_session_dates=int(chain.date.isin(in_2019).sum()),
                dates_2019=int(sum(1 for d in dates if d.year == 2019)),
                session_dates_2019=[str(d) for d in dates if d.year == 2019 and d not in in_2019],
                non_session_dates_other_years=len(other), other_years_weekend_dates=[str(d) for d in other_weekend],
                other_years_weekday_holidays=len(other_weekday), other_years_weekday_holiday_dates=[str(d) for d in other_weekday],
                rows_on_other_year_non_session_dates=int(chain.date.isin(other).sum()),
                rows_on_session_dates_by_symbol={s: int(n) for s, n in chain.loc[~chain.date.isin(non_sessions)].groupby("act_symbol").size().items()})


def underlying_stats(relpath):
    if not exists(relpath):
        return None
    bars = pd.read_csv(ROOT/relpath, usecols=["date", "act_symbol", "close"])
    bars["date"] = pd.to_datetime(bars.date).dt.date
    per_symbol = {s: dict(rows=int(len(g)), first=str(g.date.min()), last=str(g.date.max())) for s, g in bars.groupby("act_symbol")}
    missing_spy = [str(d) for d in ("2022-08-01", "2022-09-19")
                   if not len(bars.loc[(bars.act_symbol == "SPY") & (bars.date == pd.Timestamp(d).date())])]
    return dict(rows=int(len(bars)), symbols=sorted(per_symbol), per_symbol=per_symbol, spy_close_missing_on=missing_spy)


def store_stats(data_root):
    path = ROOT/data_root/"observations.sqlite3"
    if not path.exists():
        return None
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    totals = dict(db.execute("""SELECT COUNT(*) AS observations, SUM(training_eligible) AS training_rows,
                                COUNT(DISTINCT session_date) AS sessions, MIN(session_date) AS first_session,
                                MAX(session_date) AS last_session FROM observations""").fetchone())
    per_symbol = {r["symbol"]: dict(rows=r["n"], training_eligible=r["e"], sessions=r["s"]) for r in db.execute(
        "SELECT symbol, COUNT(*) n, SUM(training_eligible) e, COUNT(DISTINCT session_date) s FROM observations GROUP BY symbol")}
    reasons = {r["quality_reasons"]: r["n"] for r in db.execute(
        "SELECT quality_reasons, COUNT(*) n FROM observations WHERE training_eligible=0 GROUP BY quality_reasons ORDER BY n DESC")}
    runs = dict(db.execute("SELECT COUNT(*) AS runs, MIN(started_at) AS first_started, MAX(started_at) AS last_started FROM runs").fetchone())
    tier = db.execute("SELECT value FROM store_meta WHERE key='training_tier'").fetchone()
    db.close()
    return dict(path=str(Path(data_root)/"observations.sqlite3"), sha256=sha256_file(path), bytes=path.stat().st_size, **totals,
                per_symbol=per_symbol, exclusions_by_reason=reasons, ingest_runs=runs, pinned_tier=tier["value"] if tier else None,
                query_for_totals="SELECT COUNT(*), SUM(training_eligible), COUNT(DISTINCT session_date) FROM observations",
                query_for_exclusions="SELECT quality_reasons, COUNT(*) FROM observations WHERE training_eligible=0 GROUP BY quality_reasons")


def snapshot_entries(data_root):
    base = ROOT/data_root/"snapshots"
    if not base.exists():
        return None
    entries = []
    for folder in sorted(base.glob("*/*/")):
        meta = json.loads((folder/"metadata.json").read_text())
        raw = sha256_file(folder/"raw_options.csv")
        item = dict(session=meta["session"], path=str(folder.relative_to(ROOT)),
                    metadata_json_sha256=sha256_file(folder/"metadata.json"), raw_options_csv_sha256=raw,
                    recorded_csv_sha256_matches=meta.get("csv_sha256", {}).get("raw_options.csv") == raw)
        if meta.get("failures"):
            item["failures"] = meta["failures"]
        entries.append(item)
    with_source = sum("source_files" in json.loads((ROOT/e["path"]/"metadata.json").read_text()) for e in entries)
    return dict(data_root=data_root, count=len(entries), first_session=entries[0]["session"], last_session=entries[-1]["session"],
                files_per_snapshot=["metadata.json", "raw_options.csv"],
                all_recorded_csv_sha256_match=all(e["recorded_csv_sha256_matches"] for e in entries),
                snapshots_with_source_files_recorded=int(with_source),
                note="Folder names carry no content hash and metadata.json has no source_files entry: this import ran before the "
                     "3.2.1 commits that added both. The import CSV hashes are recorded in this manifest instead.",
                directories=entries)


def dolt_info():
    out = {}
    for folder, name in DOLT_CLONES.items():
        clone = ROOT/folder
        if not (clone/".dolt").exists():
            out[name] = None
            continue
        stat = (clone/".dolt").stat()
        created = getattr(stat, "st_birthtime", stat.st_mtime)
        info = dict(clone_dir=folder, dolt_dir_created=pd.Timestamp(created, unit="s", tz="UTC").tz_convert("America/Los_Angeles").isoformat())
        try:
            log = subprocess.run(["dolt", "log", "-n", "1"], cwd=clone, capture_output=True, text=True, check=True).stdout
            commit = re.search(r"commit\s+(\w+)", log)
            when = re.search(r"Date:\s+(.+)", log)
            message = [line.strip() for line in log.splitlines() if line.startswith("\t")]
            info.update(head_commit=commit.group(1) if commit else None, head_date=when.group(1).strip() if when else None,
                        head_message=message[0] if message else None)
            remote = subprocess.run(["dolt", "remote", "-v"], cwd=clone, capture_output=True, text=True, check=True).stdout.split()
            info["remote"] = remote[1] if len(remote) > 1 else None
            if folder == "options":
                query = "SELECT COUNT(*) AS n FROM option_chain WHERE act_symbol='QQQ'"
                count = subprocess.run(["dolt", "sql", "-r", "csv", "-q", query], cwd=clone, capture_output=True, text=True, check=True).stdout
                info["qqq_option_chain_rows"] = dict(query=query, result=int(count.strip().splitlines()[-1]))
        except (OSError, subprocess.CalledProcessError) as exc:
            info["error"] = str(exc)
        out[name] = info
    return out


def code_constants():
    source = ROOT/"options_engine/store.py"
    lines = source.read_text().splitlines()

    def locate(pattern):
        for number, line in enumerate(lines, 1):
            if re.search(pattern, line):
                return dict(line=number, text=line.strip())
        return None
    return dict(file="options_engine/store.py", sha256=sha256_file(source), function="eod_training_quality",
                iv_range=locate(r"\.03 <= iv <= 3\.0"), midpoint_floor=locate(r'row\.get\("mid", 0\) < \.10'),
                moneyness_band=locate(r"log_moneyness.*> \.35"))


def audit_stats(data_root):
    base = ROOT/data_root/"audits"
    if not base.exists():
        return None
    total = accepted = 0
    reasons, per_symbol = {}, {}
    for path in sorted(base.glob("*/filter_audit.csv")):
        frame = pd.read_csv(path, usecols=["symbol", "accepted", "filter_reasons"], dtype={"filter_reasons": "string"})
        flags = frame.accepted.astype(bool)
        total += len(frame)
        accepted += int(flags.sum())
        for symbol, group in frame.groupby("symbol"):
            item = per_symbol.setdefault(symbol, dict(raw_rows=0, accepted=0))
            item["raw_rows"] += int(len(group))
            item["accepted"] += int(group.accepted.astype(bool).sum())
        for reason, n in frame.loc[~flags, "filter_reasons"].fillna("").value_counts().items():
            reasons[reason] = reasons.get(reason, 0)+int(n)
    return dict(audit_files=len(list(base.glob("*/filter_audit.csv"))), raw_rows=total, accepted=accepted, rejected=total-accepted,
                per_symbol=per_symbol, rejection_reasons=dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
                note="Acquisition filters (quote validity, relative spread) run at ingest before storage; the per-run audits live under "
                     "data/<root>/audits/<run_id>/filter_audit.csv and are not committed.")


# ----------------------------------------------------------------------------- claims
def make_claims(ctx):
    full, spy = ctx["runs"]["full-history-v2"], ctx["runs"]["spy-2023-v2"]
    fs, ss = full["stats"], spy["stats"]
    fsig, ssig = full["significance"], spy["significance"]
    fx = ctx["exports"]["full-history"]["stats"]
    sx = ctx["exports"]["spy-2023"]["stats"]
    chain = ctx.get("import_csv_stats", {}).get("full_chain.csv")
    boot = ctx["derived"]["bootstrap"]
    cov = ctx["coverage"]
    consts = ctx["code_constants"]
    cfg = ctx["config_values"]["config/eod-full.json"]
    claims = []
    FULL_SIG = "docs/results/full-history-v2/significance.json"
    FULL_FOLDS = "docs/results/full-history-v2/folds.csv"
    FULL_EXPORT = EXPORTS["full-history"]["committed"]
    SPY_SIG = "docs/results/spy-2023-v2/significance.json"
    SPY_FOLDS = "docs/results/spy-2023-v2/folds.csv"
    SPY_EXPORT = EXPORTS["spy-2023"]["committed"]

    def add(cid, section, text, reported, value, fmt=None, source=None, field=None, status="traced", note=None):
        rendered = None
        if value is not None and fmt:
            rendered = fmt.format(value)
        elif value is not None:
            rendered = str(value)
        item = dict(id=cid, section=section, text=text, reported=reported, value=jsonable(value), rendered=rendered,
                    matches_reported=(rendered == reported) if rendered is not None and reported is not None else None,
                    source=source, field=field, status=status)
        if note:
            item["note"] = note
        claims.append(item)

    # --- Summary and Data
    add("data.quotes_stored", "Summary; Data", "292,018 end-of-day US option quotes / 292,018 quotes stored", "292,018", fx["rows"], "{:,}",
        FULL_EXPORT, "row count (every stored observation, eligible or excluded); also SELECT COUNT(*) FROM observations in data/eod-live-full/observations.sqlite3")
    add("data.symbols", "Summary; Data", "SPY, QQQ, AAPL", "SPY, QQQ, AAPL", ", ".join(sorted(fx["per_symbol"])), None, FULL_EXPORT,
        "distinct values of the symbol column", status="untraceable",
        note="QQQ is in the configuration's ticker list but the chain export, the store, the folds, and the export contain no QQQ rows; the study covers SPY and AAPL.")
    add("data.span", "Summary", "February 2019 through September 2026", "2019-02-09 to 2026-09-07",
        f"{chain['first']} to {chain['last']}" if chain else None, None, "full_chain.csv (local only; sha256 in import_csvs)", "min and max of the date column")
    add("data.sessions_accepted", "Data", "1,177 sessions accepted", "1,177", fx["sessions"], "{:,}", FULL_EXPORT,
        "distinct session_date; also the number of directories under data/eod-live-full/snapshots")
    add("data.training_rows", "Data", "260,296 passed training-quality gates", "260,296", fx["training_eligible"], "{:,}", FULL_EXPORT,
        "sum of training_eligible")
    add("data.training_share", "Data", "(89.1%)", "89.1%", fx["training_eligible"]/fx["rows"], "{:.1%}", FULL_EXPORT,
        "training_eligible sum divided by row count", status="derived")
    add("data.candidate_sessions_refused", "Data", "103 candidate sessions were refused", "103", chain["non_session_dates"] if chain else None, "{:,}",
        "full_chain.csv (local only)", "distinct dates that are not XNYS sessions (exchange_calendars); equals distinct dates (1,280) minus stored sessions (1,177)",
        status="derived", note="The import summary that printed this number was not saved; the count is recomputed from the import CSV with the same calendar rule.")
    add("data.refused_2019_non_trading", "Data", "47 dates in 2019 that fall on non-trading days", "47", chain["non_session_dates_2019"] if chain else None, "{:,}",
        "full_chain.csv (local only)", "distinct 2019 dates that are not XNYS sessions (46 Saturdays, 1 Sunday)", status="derived")
    add("data.refused_holidays", "Data", "54 exchange holidays carrying stale rows", "54", chain["other_years_weekday_holidays"] if chain else None, "{:,}",
        "full_chain.csv (local only)", "distinct non-2019 weekday dates that are not XNYS sessions", status="untraceable",
        note="Does not reproduce: the export has 55 weekday holidays plus one Saturday (2020-01-04) outside 2019, so 47 + 55 + 1 = 103 non-session dates were refused.")
    add("data.missing_spy_close_sessions", "Data", "2 sessions where the SPY underlying close was missing (2022-08-01, 2022-09-19)", "2",
        len(cov.get("missing_spy_close_sessions", [])) or None, "{:,}", "data/eod-live-full/snapshots/<date>/*/metadata.json (local only)",
        "failures[].reason == missing_underlying_close for symbol SPY", status="traced",
        note="The two events are recorded, but those sessions were accepted with AAPL rows only; they are not among the 103 refused sessions. "
             "full_underlying.csv has no SPY bar on either date.")
    add("data.exclusions_total", "Data", "Quote-level exclusions (31,722 rows)", "31,722", fx["excluded_rows"], "{:,}", FULL_EXPORT,
        "rows with training_eligible false")
    labels = [("data.exclusions.iv", "Implied volatility not identifiable / outside [3%, 300%]", "13,050", "iv_not_identified;iv_outside_training_range"),
              ("data.exclusions.midpoint", "Midpoint below $0.10 training floor", "11,171", "midpoint_below_training_floor"),
              ("data.exclusions.moneyness", "Outside +-35% log-moneyness band", "4,997", "outside_training_moneyness"),
              ("data.exclusions.iv_and_moneyness", "IV unidentifiable and outside moneyness band", "1,957", "iv_not_identified;iv_outside_training_range;outside_training_moneyness"),
              ("data.exclusions.midpoint_and_moneyness", "Midpoint floor and moneyness band", "523", "midpoint_below_training_floor;outside_training_moneyness"),
              ("data.exclusions.iv_range_and_moneyness", "IV range and moneyness band", "24", "iv_outside_training_range;outside_training_moneyness")]
    for cid, label, reported, key in labels:
        add(cid, "Data (exclusion table)", label, reported, fx["exclusions_by_reason"].get(key, 0), "{:,}", FULL_EXPORT,
            f"count of rows whose quality_reasons == '{key}'")
    add("params.rate", "Data; Method", "r = 4%", "4%", cfg["rate"], "{:.0%}", "config/eod-full.json", "rate")
    for symbol, reported in (("SPY", "1.4%"), ("QQQ", "0.6%"), ("AAPL", "0.5%")):
        add(f"params.dividend_yield.{symbol}", "Data", f"q = {reported} for {symbol}", reported, cfg["dividend_yields"][symbol], "{:.1%}",
            "config/eod-full.json", f"dividend_yields.{symbol}")
    add("params.history_window", "Method", "60-session close-to-close realized volatility", "60", cfg["history_window"], "{}", "config/eod-full.json",
        "history_window (baseline_estimator = close_to_close; snapshot metadata assumptions.<symbol>.baseline_source = dolt_prior_60_session_close_to_close)")
    def numbers(key):
        located = consts.get(key)
        return [float(x) for x in re.findall(r"\d*\.\d+|\d+", located["text"])] if located else None

    def code_field(key):
        located = consts.get(key)
        return f"line {located['line']} of eod_training_quality: {located['text']}" if located else None
    iv = numbers("iv_range")
    add("params.iv_range", "Data (exclusion table)", "IV outside [3%, 300%]", "[3%, 300%]",
        f"[{iv[0]:.0%}, {iv[1]:.0%}]" if iv else None, None, consts["file"], code_field("iv_range"), status="traced_to_code")
    mid = numbers("midpoint_floor")
    add("params.midpoint_floor", "Data (exclusion table)", "Midpoint below $0.10", "$0.10",
        f"${mid[-1]:.2f}" if mid else None, None, consts["file"], code_field("midpoint_floor"), status="traced_to_code")
    band = numbers("moneyness_band")
    add("params.moneyness_band", "Data (exclusion table)", "+-35% log-moneyness band", "0.35",
        f"{band[-1]:.2f}" if band else None, None, consts["file"], code_field("moneyness_band"), status="traced_to_code")
    # --- Method
    spec = fsig["spec"]
    add("method.max_train_sessions", "Method", "rolling 250-session training window", "250", spec["max_train_sessions"], "{}", FULL_SIG, "spec.max_train_sessions")
    add("method.min_train_sessions", "Method; Data-quality findings", "minimum 120 sessions / after 120 daily training sessions accumulate", "120",
        spec["min_train_sessions"], "{}", FULL_SIG, "spec.min_train_sessions")
    add("method.gap", "Method", "one-session embargo gap", "1", spec["gap"], "{}", FULL_SIG, "spec.gap")
    add("method.validation_sessions", "Method", "re-selected inside every fold on the last two sessions", "2", spec["validation_sessions"], "{}", FULL_SIG,
        "spec.validation_sessions")
    add("method.window", "Method", "rolling window", "rolling", spec["window"], None, FULL_SIG, "spec.window")
    add("method.nw_lags", "Method; Results", "Newey-West (Bartlett) HAC variance at 15 lags", "15", fsig["diebold_mariano_newey_west"]["hac_lags"], "{}", FULL_SIG,
        "diebold_mariano_newey_west.hac_lags")
    add("method.shared_training_sessions", "Serial dependence", "Adjacent folds share roughly 249 of 250 training sessions", "249 of 250",
        f"{spec['max_train_sessions']-1} of {spec['max_train_sessions']}", None, FULL_SIG, "spec.max_train_sessions minus one (rolling window shifts by one session per fold)",
        status="derived")
    # --- Results, full history
    add("full.folds", "Summary; Results", "1,056 folds", "1,056", fsig["sessions_evaluated"], "{:,}", FULL_SIG, "sessions_evaluated; also row count of folds.csv")
    add("full.first_session", "Results", "2020-10-23", "2020-10-23", fs["first"], None, FULL_FOLDS, "first evaluated_session")
    add("full.last_session", "Results", "2026-09-04", "2026-09-04", fs["last"], None, FULL_FOLDS, "last evaluated_session")
    add("full.win_rate", "Summary; Results", "Model win rate (session loss) 0.664 / 66.4% of folds", "0.664", fsig["model_win_rate"], "{:.3f}", FULL_SIG, "model_win_rate")
    add("full.mean_baseline_rmse", "Results", "Mean session RMSE, baseline 0.00704", "0.00704", fs["mean_baseline_rmse"], "{:.5f}", FULL_FOLDS, "mean of baseline_rmse", status="derived")
    add("full.mean_model_rmse", "Results", "Mean session RMSE, model 0.00407", "0.00407", fs["mean_model_rmse"], "{:.5f}", FULL_FOLDS, "mean of model_rmse", status="derived")
    add("full.mean_rmse_improvement", "Results", "Mean RMSE improvement 42.2%", "42.2%", fs["mean_rmse_improvement"], "{:.1%}", FULL_FOLDS,
        "1 - mean(model_rmse) / mean(baseline_rmse)", status="derived")
    add("full.median_improvement", "Summary; Results; Conclusion", "median per-fold RMSE improvement of 10.4%", "10.4%", fs["median_improvement"], "{:.1%}", FULL_FOLDS,
        "median over folds of 1 - model_rmse / baseline_rmse", status="derived")
    add("full.iqr_low", "Summary; Results", "IQR lower bound -7.6%", "-7.6%", fs["iqr_low"], "{:.1%}", FULL_FOLDS, "25th percentile of 1 - model_rmse / baseline_rmse", status="derived")
    add("full.iqr_high", "Summary; Results", "IQR upper bound 28.8%", "28.8%", fs["iqr_high"], "{:.1%}", FULL_FOLDS, "75th percentile of 1 - model_rmse / baseline_rmse", status="derived")
    add("full.mean_differential", "Results", "Mean loss differential 4.50e-04", "4.50e-04", fsig["diebold_mariano"]["mean_differential"], "{:.2e}", FULL_SIG, "diebold_mariano.mean_differential")
    add("full.dm_statistic", "Results", "DM (HLN, lag 0) 3.67", "3.67", fsig["diebold_mariano"]["statistic"], "{:.2f}", FULL_SIG, "diebold_mariano.statistic")
    add("full.dm_p", "Summary; Results", "p = 2.5e-04", "2.5e-04", fsig["diebold_mariano"]["p_value"], "{:.1e}", FULL_SIG, "diebold_mariano.p_value")
    add("full.nw_statistic", "Results; Serial dependence", "DM (Newey-West, 15 lags) 1.23", "1.23", fsig["diebold_mariano_newey_west"]["statistic"], "{:.2f}", FULL_SIG,
        "diebold_mariano_newey_west.statistic")
    add("full.nw_p", "Summary; Results; Serial dependence", "p = 0.22", "0.22", fsig["diebold_mariano_newey_west"]["p_value"], "{:.2f}", FULL_SIG, "diebold_mariano_newey_west.p_value")
    add("full.lag1_autocorrelation", "Results; Serial dependence", "Lag-1 autocorrelation of the differential 0.87", "0.87", fsig["diebold_mariano"]["lag1_autocorrelation"], "{:.2f}",
        FULL_SIG, "diebold_mariano.lag1_autocorrelation")
    ci = fsig["bootstrap_mean_differential"]
    add("full.ci10.block_length", "Results", "Block bootstrap 95% CI (block 10)", "10", ci["block_length"], "{}", FULL_SIG, "bootstrap_mean_differential.block_length")
    add("full.ci10.low", "Results; Serial dependence", "[1.00e-05, ...]", "1.00e-05", ci["low"], "{:.2e}", FULL_SIG, "bootstrap_mean_differential.low")
    add("full.ci10.high", "Results; Serial dependence", "[..., 1.19e-03]", "1.19e-03", ci["high"], "{:.2e}", FULL_SIG, "bootstrap_mean_differential.high")
    reported_years = {2020: ("28", "0.71", "88.5%"), 2021: ("148", "0.55", "6.3%"), 2022: ("144", "0.68", "13.8%"), 2023: ("146", "0.57", "4.2%"),
                      2024: ("174", "0.66", "9.1%"), 2025: ("249", "0.71", "29.3%"), 2026: ("167", "0.76", "20.5%")}
    for year, (n, win, imp) in reported_years.items():
        row = fs["by_year"].get(year, {})
        add(f"full.year.{year}.folds", "Results (by calendar year)", f"{year} folds", n, row.get("folds"), "{}", FULL_FOLDS,
            f"count of rows with evaluated_session in {year}", status="derived")
        add(f"full.year.{year}.win_rate", "Results (by calendar year)", f"{year} win rate", win, row.get("win_rate"), "{:.2f}", FULL_FOLDS,
            f"share of {year} rows with model_loss < baseline_loss", status="derived")
        add(f"full.year.{year}.rmse_improvement", "Results (by calendar year)", f"{year} RMSE improvement", imp, row.get("rmse_improvement"), "{:.1%}", FULL_FOLDS,
            f"1 - mean(model_rmse) / mean(baseline_rmse) over {year} rows", status="derived")
    add("full.calendar_years", "Summary; Conclusion", "all seven calendar years", "7", fs["calendar_years"], "{}", FULL_FOLDS, "distinct years of evaluated_session", status="derived")
    add("full.all_years_positive", "Summary; Results; Conclusion", "positive average improvement in all seven calendar years", "True", fs["all_years_positive"], None, FULL_FOLDS,
        "every per-year 1 - mean(model_rmse)/mean(baseline_rmse) > 0", status="derived",
        note="Holds for the ratio-of-means definition used in the table; the mean of per-fold improvements is negative in 2021 and 2023.")
    reported_blocks = {21: ("7.18e-06", "1.38e-03"), 63: ("5.05e-06", "1.33e-03"), 126: ("4.93e-06", "1.32e-03")}
    for block, (low, high) in reported_blocks.items():
        interval = boot.get(str(block), {})
        note = ("Not in any output saved by the study; re-derived deterministically (seed 0, 2,000 replications) from folds.csv with "
                "options_engine.walkforward.circular_block_bootstrap_ci and saved to bootstrap-block-lengths.json.")
        add(f"full.ci{block}.low", "Serial dependence (block-length table)", f"block {block} lower bound", low, interval.get("low"), "{:.2e}", str(BOOTSTRAP_FILE),
            f"intervals.{block}.low", status="derived", note=note+(" Reported 5.05e-06 is a rounding slip: the value renders as 5.04e-06 at three significant figures." if block == 63 else ""))
        add(f"full.ci{block}.high", "Serial dependence (block-length table)", f"block {block} upper bound", high, interval.get("high"), "{:.2e}", str(BOOTSTRAP_FILE),
            f"intervals.{block}.high", status="derived", note=note)
    # --- SPY 2023
    sspec = ssig["spec"]
    add("spy2023.folds", "Summary; Results", "Single-year SPY 2023 (83 folds)", "83", ssig["sessions_evaluated"], "{}", SPY_SIG, "sessions_evaluated; also row count of folds.csv")
    add("spy2023.window", "Results", "expanding window", "expanding", sspec["window"], None, SPY_SIG, "spec.window")
    add("spy2023.min_train_sessions", "Results", "60-session minimum", "60", sspec["min_train_sessions"], "{}", SPY_SIG, "spec.min_train_sessions")
    add("spy2023.first_session", "Data coverage vs evaluation window", "first evaluated session 2023-06-12", "2023-06-12", ss["first"], None, SPY_FOLDS, "first evaluated_session")
    add("spy2023.last_session", "Data coverage vs evaluation window", "last evaluated session 2023-12-29", "2023-12-29", ss["last"], None, SPY_FOLDS, "last evaluated_session")
    add("spy2023.win_rate", "Results", "win rate 0.687", "0.687", ssig["model_win_rate"], "{:.3f}", SPY_SIG, "model_win_rate")
    add("spy2023.mean_rmse_improvement", "Results", "mean RMSE improvement 16.8%", "16.8%", ss["mean_rmse_improvement"], "{:.1%}", SPY_FOLDS,
        "1 - mean(model_rmse) / mean(baseline_rmse)", status="derived")
    add("spy2023.dm_statistic", "Results", "DM (HLN) 4.86", "4.86", ssig["diebold_mariano"]["statistic"], "{:.2f}", SPY_SIG, "diebold_mariano.statistic")
    add("spy2023.dm_p", "Results", "p = 5.5e-06", "5.5e-06", ssig["diebold_mariano"]["p_value"], "{:.1e}", SPY_SIG, "diebold_mariano.p_value")
    add("spy2023.nw_lags", "Results", "Newey-West (6 lags)", "6", ssig["diebold_mariano_newey_west"]["hac_lags"], "{}", SPY_SIG, "diebold_mariano_newey_west.hac_lags")
    add("spy2023.nw_statistic", "Results", "Newey-West 2.09", "2.09", ssig["diebold_mariano_newey_west"]["statistic"], "{:.2f}", SPY_SIG, "diebold_mariano_newey_west.statistic")
    add("spy2023.nw_p", "Summary; Results", "p = 0.040", "0.040", ssig["diebold_mariano_newey_west"]["p_value"], "{:.3f}", SPY_SIG, "diebold_mariano_newey_west.p_value")
    sci = ssig["bootstrap_mean_differential"]
    add("spy2023.ci.block_length", "Results", "block bootstrap (default block length)", "4", sci["block_length"], "{}", SPY_SIG, "bootstrap_mean_differential.block_length")
    add("spy2023.ci.low", "Results", "[8.4e-07, ...]", "8.4e-07", sci["low"], "{:.1e}", SPY_SIG, "bootstrap_mean_differential.low")
    add("spy2023.ci.high", "Results", "[..., 6.0e-06]", "6.0e-06", sci["high"], "{:.1e}", SPY_SIG, "bootstrap_mean_differential.high")
    # --- Reproducibility
    add("repro.version", "Header; Reproducibility", "options_engine 3.2.1", "3.2.1", ctx["code"]["version"], None, "pyproject.toml; options_engine/__init__.py", "version / __version__")
    add("repro.tests", "Reproducibility", "181 offline tests", "181", ctx["verification"].get("tests_passed"), "{}", ctx["verification"]["path"],
        "'N passed' in the pytest -q summary recorded at the freeze", status="verified_by_run")
    add("repro.lint", "Reproducibility", "lint clean", "clean", ctx["verification"].get("lint"), None, ctx["verification"]["path"], "ruff check output", status="verified_by_run")
    add("repro.dolt_cloned", "Data; Reproducibility", "cloned 2026-09-08", "2026-09-08",
        (ctx["source_databases"].get("post-no-preference/options") or {}).get("dolt_dir_created", "")[:10] or None, None,
        "options/.dolt and stocks/.dolt (local only)", "directory creation date (local time); head commits recorded under source_databases")
    # --- Data coverage vs evaluation window (section added at the freeze)
    cal = cov["full"]["calendar"]
    add("coverage.chain_rows", "Data coverage vs evaluation window", "chain export rows", "356,936", chain["rows"] if chain else None, "{:,}", "full_chain.csv (local only)", "row count")
    add("coverage.chain_distinct_dates", "Data coverage vs evaluation window", "distinct dates in the chain export", "1,280", chain["distinct_dates"] if chain else None, "{:,}",
        "full_chain.csv (local only)", "distinct date values")
    add("coverage.rows_on_2019_non_sessions", "Data coverage vs evaluation window", "rows on the 47 weekend-stamped 2019 dates", "6,156",
        chain["rows_on_2019_non_session_dates"] if chain else None, "{:,}", "full_chain.csv (local only)", "rows whose date is a 2019 non-session")
    add("coverage.rows_on_non_sessions", "Data coverage vs evaluation window", "rows on all 103 non-session dates", "22,282",
        chain["rows_on_non_session_dates"] if chain else None, "{:,}", "full_chain.csv (local only)", "rows whose date is not an XNYS session")
    add("coverage.other_year_holidays", "Data coverage vs evaluation window", "weekday exchange holidays outside 2019", "55",
        chain["other_years_weekday_holidays"] if chain else None, "{}", "full_chain.csv (local only)", "non-2019 weekday dates that are not XNYS sessions")
    add("coverage.raw_rows_after_calendar", "Data coverage vs evaluation window", "rows passed to the acquisition filters", "334,370",
        (ctx.get("audits") or {}).get("raw_rows"), "{:,}", "data/eod-live-full/audits/*/filter_audit.csv (local only)", "total rows across all filter audits")
    add("coverage.acquisition_rejected", "Data coverage vs evaluation window", "rows rejected by the acquisition filters", "42,352",
        (ctx.get("audits") or {}).get("rejected"), "{:,}", "data/eod-live-full/audits/*/filter_audit.csv (local only)", "rows with accepted false")
    audits = ctx.get("audits") or {}
    spy_dropped = None
    if chain and audits.get("per_symbol"):
        spy_dropped = chain["rows_on_session_dates_by_symbol"].get("SPY", 0)-audits["per_symbol"].get("SPY", {}).get("raw_rows", 0)
    add("coverage.spy_rows_dropped_missing_close", "Data coverage vs evaluation window", "SPY rows dropped on 2022-08-01 and 2022-09-19 for a missing underlying close", "284",
        spy_dropped, "{:,}", "full_chain.csv and data/eod-live-full/audits (local only)", "SPY chain rows on session dates minus SPY rows reaching the acquisition filters",
        status="derived")
    add("coverage.qqq_rows_in_source", "Data coverage vs evaluation window", "QQQ rows in the cloned option_chain table", "0",
        ((ctx["source_databases"].get("post-no-preference/options") or {}).get("qqq_option_chain_rows") or {}).get("result"), "{}",
        "options/.dolt clone at the recorded head commit (local only)", "SELECT COUNT(*) FROM option_chain WHERE act_symbol='QQQ'")
    add("coverage.xnys_sessions_in_span", "Data coverage vs evaluation window", "XNYS sessions between the first and last stored session", "1,841", cal["xnys_sessions"], "{:,}",
        FULL_EXPORT, "exchange_calendars XNYS sessions_in_range(min session_date, max session_date)", status="derived")
    add("coverage.sessions_missing", "Data coverage vs evaluation window", "sessions absent from the source", "664", cal["missing"], "{:,}", FULL_EXPORT,
        "XNYS sessions in span minus distinct session_date", status="derived")
    coverage_table = {2019: ("163", "1", "0"), 2020: ("253", "148", "28"), 2021: ("252", "148", "148"), 2022: ("251", "144", "144"),
                      2023: ("250", "146", "146"), 2024: ("252", "174", "174"), 2025: ("250", "249", "249"), 2026: ("170", "167", "167")}
    for year, row in cal["by_year"].items():
        xnys, stored, folds = coverage_table.get(year, (None, None, None))
        add(f"coverage.year.{year}.xnys_sessions", "Data coverage vs evaluation window (table)", f"{year} XNYS sessions", xnys, row["xnys_sessions"], "{}", FULL_EXPORT,
            "exchange_calendars XNYS sessions in that year within the span", status="derived")
        add(f"coverage.year.{year}.in_store", "Data coverage vs evaluation window (table)", f"{year} sessions in store", stored, row["in_store"], "{}", FULL_EXPORT,
            "distinct session_date in that year", status="derived")
        add(f"coverage.year.{year}.folds", "Data coverage vs evaluation window (table)", f"{year} evaluated folds", folds, fs["by_year"].get(year, {}).get("folds", 0), "{}",
            FULL_FOLDS, "rows with evaluated_session in that year", status="derived")
    add("coverage.evaluated_sessions", "Data coverage vs evaluation window", "evaluated sessions", "1,056", fs["folds"], "{:,}", FULL_FOLDS, "row count")
    add("coverage.evaluated_observations", "Data coverage vs evaluation window", "evaluated quotes", "236,516", fs["evaluation_rows"], "{:,}", FULL_FOLDS, "sum of evaluation_rows",
        status="derived", note="Equals the training-eligible rows in the export with session_date >= 2020-10-23.")
    window = fx.get("evaluated_window", {})
    for symbol, reported, reported_folds in (("SPY", "119,219", "1,042"), ("AAPL", "117,297", "1,053")):
        add(f"coverage.evaluated.{symbol}", "Data coverage vs evaluation window", f"evaluated quotes {symbol}", reported,
            window.get("per_symbol", {}).get(symbol, {}).get("training_eligible"), "{:,}", FULL_EXPORT,
            f"training_eligible rows with symbol {symbol} and session_date >= 2020-10-23", status="derived")
        add(f"coverage.folds_with.{symbol}", "Data coverage vs evaluation window", f"folds containing {symbol}", reported_folds, fs["folds_with_symbol"].get(symbol), "{:,}",
            FULL_FOLDS, f"rows where baseline_loss_{symbol} is not null", status="derived")
    add("coverage.training_only_sessions", "Data coverage vs evaluation window", "stored sessions before the first evaluated session", "121",
        window.get("training_only_sessions_before"), "{}", FULL_EXPORT, "distinct session_date < 2020-10-23", status="derived")
    for symbol, (rows, eligible, sessions, absent) in {"SPY": ("150,436", "130,801", "1,161", "16"), "AAPL": ("141,582", "129,495", "1,174", "3")}.items():
        sym = fx["per_symbol"].get(symbol, {})
        add(f"coverage.store.{symbol}.rows", "Data coverage vs evaluation window", f"{symbol} quotes stored", rows, sym.get("rows"), "{:,}", FULL_EXPORT, f"rows with symbol {symbol}")
        add(f"coverage.store.{symbol}.training_eligible", "Data coverage vs evaluation window", f"{symbol} training-eligible", eligible, sym.get("training_eligible"), "{:,}", FULL_EXPORT,
            f"training_eligible rows with symbol {symbol}")
        add(f"coverage.store.{symbol}.sessions", "Data coverage vs evaluation window", f"{symbol} sessions", sessions, sym.get("sessions"), "{:,}", FULL_EXPORT,
            f"distinct session_date with symbol {symbol}")
        add(f"coverage.store.{symbol}.absent_sessions", "Data coverage vs evaluation window", f"stored sessions without {symbol}", absent,
            len(sym.get("absent_sessions", [])) if sym else None, "{}", FULL_EXPORT, f"distinct session_date lacking any {symbol} row", status="derived")
    add("coverage.store.QQQ.rows", "Data coverage vs evaluation window", "QQQ quotes stored", "0", fx["per_symbol"].get("QQQ", {}).get("rows", 0), "{}", FULL_EXPORT, "rows with symbol QQQ")
    spy_cal = cov["spy-2023"]["calendar"]
    add("coverage.spy2023.xnys_sessions", "Data coverage vs evaluation window", "XNYS sessions 2023-01-04 to 2023-12-29", "249", spy_cal["xnys_sessions"], "{}", SPY_EXPORT,
        "exchange_calendars XNYS sessions_in_range over the store span", status="derived")
    add("coverage.spy2023.sessions", "Data coverage vs evaluation window", "SPY 2023 sessions stored", "144", sx["sessions"], "{}", SPY_EXPORT, "distinct session_date")
    add("coverage.spy2023.rows", "Data coverage vs evaluation window", "SPY 2023 quotes stored", "16,987", sx["rows"], "{:,}", SPY_EXPORT, "row count")
    add("coverage.spy2023.training_eligible", "Data coverage vs evaluation window", "SPY 2023 training-eligible", "14,869", sx["training_eligible"], "{:,}", SPY_EXPORT, "sum of training_eligible")
    add("coverage.spy2023.evaluated_observations", "Data coverage vs evaluation window", "SPY 2023 evaluated quotes", "8,305", ss["evaluation_rows"], "{:,}", SPY_FOLDS, "sum of evaluation_rows",
        status="derived")
    add("coverage.snapshots_full", "Data coverage vs evaluation window", "snapshot directories, full-history root", "1,177",
        (ctx["snapshots"].get("data/eod-live-full") or {}).get("count"), "{:,}", "data/eod-live-full/snapshots (local only)", "directory count")
    add("coverage.snapshots_spy2023", "Data coverage vs evaluation window", "snapshot directories, SPY 2023 root", "144",
        (ctx["snapshots"].get("data/live") or {}).get("count"), "{}", "data/live/snapshots (local only)", "directory count")
    return claims


# ----------------------------------------------------------------------------- build / check
def gather(check_mode):
    ctx = dict(code=dict(version=None, commit=git("rev-parse", "HEAD"), commit_short=git("rev-parse", "--short", "HEAD")),
               runs={}, exports={}, derived={}, coverage={}, snapshots={}, config_values={})
    version = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT/"options_engine/__init__.py").read_text())
    ctx["code"]["version"] = version.group(1) if version else None
    for name in RUNS:
        run = load_run(name)
        if run:
            run["stats"] = fold_stats(run["folds"])
            ctx["runs"][name] = run
    ctx["derived"]["bootstrap"] = bootstrap_intervals(ctx["runs"]["full-history-v2"]["folds"])
    first_full = ctx["runs"]["full-history-v2"]["stats"]["first"]
    for name in EXPORTS:
        frame, path = load_export(name)
        if frame is None:
            raise SystemExit(f"Export for {name} not found: {EXPORTS[name]['local']} or {EXPORTS[name]['committed']}")
        stats = export_stats(frame, first_full if name == "full-history" else None)
        ctx["exports"][name] = dict(loaded_from=path, stats=stats, frame=frame)
    ctx["coverage"]["full"] = dict(calendar=calendar_stats(sorted(ctx["exports"]["full-history"]["frame"].session_date.unique())))
    ctx["coverage"]["spy-2023"] = dict(calendar=calendar_stats(sorted(ctx["exports"]["spy-2023"]["frame"].session_date.unique())))
    for item in CONFIGS:
        ctx["config_values"][item["path"]] = json.loads((ROOT/item["path"]).read_text())
    ctx["code_constants"] = code_constants()
    ctx["import_csv_stats"] = {}
    for item in IMPORT_CSVS:
        if "chain" in item["path"]:
            stats = chain_stats(item["path"])
        else:
            stats = underlying_stats(item["path"])
        if stats:
            ctx["import_csv_stats"][item["path"]] = stats
    ctx["stores"] = {root: store_stats(root) for root in ("data/eod-live-full", "data/live")}
    ctx["snapshots"] = {root: snapshot_entries(root) for root in ("data/eod-live-full", "data/live")}
    missing_close = []
    if ctx["snapshots"].get("data/eod-live-full"):
        for entry in ctx["snapshots"]["data/eod-live-full"]["directories"]:
            for failure in entry.get("failures", []):
                if failure.get("reason") == "missing_underlying_close" and failure.get("symbol") == "SPY":
                    missing_close.append(entry["session"])
    ctx["coverage"]["missing_spy_close_sessions"] = missing_close
    ctx["source_databases"] = dolt_info()
    ctx["audits"] = audit_stats("data/eod-live-full")
    verification = Path("docs/results/verification-3.2.1.txt")
    ctx["verification"] = dict(path=str(verification))
    if exists(verification):
        text = (ROOT/verification).read_text()
        passed = re.search(r"(\d+) passed", text)
        ctx["verification"]["tests_passed"] = int(passed.group(1)) if passed else None
        ctx["verification"]["lint"] = "clean" if "All checks passed" in text else None
    return ctx


def build_manifest(ctx):
    runs = {}
    for name, run in RUNS.items():
        loaded = ctx["runs"].get(name)
        files = {}
        for base_key in ("committed", "results"):
            base = run[base_key]
            if base and exists(base):
                files[base_key] = {f: file_entry(f"{base}/{f}") for f in RUN_FILES if exists(f"{base}/{f}")}
        if "committed" in files and "results" in files:
            files["committed_matches_results"] = all(files["committed"][f]["sha256"] == files["results"][f]["sha256"]
                                                     for f in files["committed"] if f in files["results"])
        runs[name] = dict(role=run["role"], config=run["config"], data_root=run["data_root"], command=run["command"],
                          command_note=None if run["command"] is None else
                          "Command as given in docs/RESULTS.md (full history) or implied by significance.json spec (SPY 2023); the shell history does not contain it.",
                          spec=loaded["significance"]["spec"] if loaded else None, files=files,
                          summary=({k: v for k, v in loaded["stats"].items() if k not in ("by_year",)} if loaded else None))
    exports = {}
    for name, spec in EXPORTS.items():
        item = dict(role="Every stored observation with its training_eligible flag and quality_reasons (the exclusion export)",
                    config=spec["config"], data_root=spec["data_root"], command=spec["command"], generated=spec["generated"],
                    columns_used_by_claims=EXPORT_COLUMNS)
        if exists(spec["committed"]):
            path = ROOT/spec["committed"]
            item["committed"] = dict(path=spec["committed"], sha256=sha256_file(path), bytes=path.stat().st_size, compression="gzip -n -9",
                                     uncompressed_sha256=sha256_file(path, gz_member=True))
        if exists(spec["local"]):
            item["uncompressed"] = file_entry(spec["local"])
        stats = dict(ctx["exports"][name]["stats"])
        item["summary"] = stats
        exports[name] = item
    manifest = dict(
        schema="options_engine study manifest, version 1",
        study=dict(**STUDY, code_commit=ctx["code"]["commit"], code_commit_short=ctx["code"]["commit_short"],
                   report_sha256=sha256_file(ROOT/STUDY["report"]),
                   description="1,056-fold rolling-origin walk-forward over DoltHub end-of-day chains (SPY and AAPL; QQQ configured but absent from the export) "
                               "plus a single-year SPY 2023 run, constant rate and dividend yields.",
                   built_with=package_versions(),
                   how_to_check="python docs/results/build_manifest.py --check"),
        source_databases=ctx["source_databases"],
        configs=[file_entry(item["path"], role=item["role"], values=ctx["config_values"][item["path"]]) for item in CONFIGS],
        import_csvs=[dict(file_entry(item["path"], role=item["role"]), committed=False,
                          summary=ctx["import_csv_stats"].get(item["path"])) if exists(item["path"]) else dict(item, missing=True)
                     for item in IMPORT_CSVS],
        observation_stores=ctx["stores"],
        acquisition_audits=ctx["audits"],
        snapshots=ctx["snapshots"],
        runs=runs,
        exports=exports,
        derived=[dict(path=str(BOOTSTRAP_FILE), role="Circular block bootstrap CIs at the block lengths tabulated in docs/RESULTS.md",
                      inputs=["docs/results/full-history-v2/folds.csv"], function="options_engine.walkforward.circular_block_bootstrap_ci",
                      parameters=dict(n_boot=2000, seed=0, confidence=0.95, block_lengths=list(BOOTSTRAP_BLOCKS)))],
        code_constants=ctx["code_constants"],
        verification=ctx["verification"],
        claims=make_claims(ctx),
    )
    return jsonable(manifest)


def write_bootstrap_file(ctx):
    payload = dict(source="docs/results/full-history-v2/folds.csv", series="baseline_loss - model_loss, one value per fold",
                   function="options_engine.walkforward.circular_block_bootstrap_ci", replications=2000, seed=0, confidence=0.95,
                   note="Re-derived at the freeze on 2026-09-08 because the study saved only the default block length (10) in significance.json. "
                        "Deterministic given the seed; the block-10 interval matches significance.json exactly.",
                   intervals=jsonable(ctx["derived"]["bootstrap"]))
    (ROOT/BOOTSTRAP_FILE).write_text(json.dumps(payload, indent=2, sort_keys=True)+"\n")


def print_claims(claims):
    width = max(len(c["id"]) for c in claims)
    counts = {}
    for claim in claims:
        counts[claim["status"]] = counts.get(claim["status"], 0)+1
        flag = {True: "ok", False: "MISMATCH", None: "-"}[claim["matches_reported"]]
        print(f"{claim['id']:<{width}}  {claim['status']:<16} {flag:<9} reported={claim['reported']!s:<22} rendered={claim['rendered']}")
    print("status counts:", counts)
    print("reported-vs-rendered mismatches:", [c["id"] for c in claims if c["matches_reported"] is False])


def close_enough(a, b):
    if isinstance(a, float) or isinstance(b, float):
        try:
            return abs(float(a)-float(b)) <= 1e-9*max(1.0, abs(float(a)), abs(float(b)))
        except (TypeError, ValueError):
            return False
    return a == b


def check(manifest):
    problems = []
    for entry in manifest["derived"]:
        problems += [] if exists(entry["path"]) else [f"missing derived file {entry['path']}"]
    committed = []
    for run in manifest["runs"].values():
        committed += list(run["files"].get("committed", {}).values())
    for export in manifest["exports"].values():
        if "committed" in export:
            committed.append(export["committed"])
    for item in manifest["configs"]:
        committed.append(item)
    for item in committed:
        path = ROOT/item["path"]
        if not path.exists():
            problems.append(f"missing committed artifact {item['path']}")
        elif sha256_file(path) != item["sha256"]:
            problems.append(f"sha256 mismatch for {item['path']}")
    report = ROOT/manifest["study"]["report"]
    if sha256_file(report) != manifest["study"]["report_sha256"]:
        problems.append(f"{manifest['study']['report']} differs from the frozen report hash")
    for item in manifest["import_csvs"]:
        if exists(item["path"]) and sha256_file(ROOT/item["path"]) != item["sha256"]:
            problems.append(f"sha256 mismatch for local {item['path']}")
    for store in (manifest.get("observation_stores") or {}).values():
        if store and exists(store["path"]) and sha256_file(ROOT/store["path"]) != store["sha256"]:
            problems.append(f"sha256 mismatch for local {store['path']}")
    for root, snaps in (manifest.get("snapshots") or {}).items():
        if snaps and exists(root+"/snapshots"):
            for entry in snaps["directories"]:
                folder = ROOT/entry["path"]
                if not folder.exists():
                    problems.append(f"missing snapshot {entry['path']}")
                elif sha256_file(folder/"raw_options.csv") != entry["raw_options_csv_sha256"] or \
                        sha256_file(folder/"metadata.json") != entry["metadata_json_sha256"]:
                    problems.append(f"sha256 mismatch inside snapshot {entry['path']}")
    ctx = gather(check_mode=True)
    saved = json.loads((ROOT/BOOTSTRAP_FILE).read_text())["intervals"] if exists(BOOTSTRAP_FILE) else {}
    for block, interval in ctx["derived"]["bootstrap"].items():
        for key in ("low", "high"):
            if block not in saved or not close_enough(saved[block][key], interval[key]):
                problems.append(f"bootstrap block {block} {key} does not reproduce")
    fresh = {c["id"]: c for c in make_claims(ctx)}
    skipped = 0
    for claim in manifest["claims"]:
        new = fresh.get(claim["id"])
        if new is None:
            problems.append(f"claim {claim['id']} missing from rebuilt claim set")
        elif new["value"] is None:
            skipped += 1
        elif not close_enough(new["value"], claim["value"]):
            problems.append(f"claim {claim['id']} changed: manifest {claim['value']!r}, recomputed {new['value']!r}")
    print(f"checked {len(manifest['claims'])} claims ({skipped} skipped: their local-only source is absent here)")
    print(f"checked {len(committed)} committed artifacts plus the report hash")
    if problems:
        print("PROBLEMS:")
        for problem in problems:
            print("  -", problem)
        return 1
    print("manifest verified: every checkable value and hash matches")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="verify against the committed manifest instead of rebuilding it")
    args = parser.parse_args()
    if args.check:
        return check(json.loads((ROOT/MANIFEST).read_text()))
    ctx = gather(check_mode=False)
    write_bootstrap_file(ctx)
    manifest = build_manifest(ctx)
    (ROOT/MANIFEST).write_text(json.dumps(manifest, indent=1, sort_keys=False)+"\n")
    print_claims(manifest["claims"])
    print(f"wrote {MANIFEST} ({(ROOT/MANIFEST).stat().st_size:,} bytes) and {BOOTSTRAP_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
