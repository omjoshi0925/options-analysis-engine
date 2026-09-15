"""Design D: the locked fresh evaluation (Research Plan section 7, Amendment 7; docs/LOCK.md).

For a session t that is not yet in the store, `predict_session` forms the
prediction set (contracts present at the prior available session that have
not expired at t's close) and prices each under the RV baseline, B1, M(RV),
and M(B1) using S_t, r_t, q_t and prior-session information only. It refuses
to run if the chain for t is already in the store. `score_session` runs only
after the prediction file is committed and the chain for t is imported; it
matches on the contract key, ignores contracts absent from the prediction
set, and appends one line to the fresh-evaluation log. `fresh_eval_report`
refuses to draw inference until the sample rule is met.

The locked code is enforced physically: both commands hash the modules and
configuration listed in docs/lock.json and refuse to run if any differs.
"""
from __future__ import annotations

import bisect
import csv
import datetime as dt
import json
import subprocess
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__
from .baselines import b1_baseline
from .carry_inputs import IV_TRAINING_RANGE, CarryInputs, apply_carry, as_date, file_digest
from .compare import BLOCK_LENGTH, REPLICATES, SEED, SENSITIVITY_BLOCKS, block_indices, pair_statistics
from .data import time_to_expiry
from .eod_import import load_underlying_csv, session_closes
from .iv import implied_volatility
from .learning import predict_volatility, price_with_volatility
from .live_config import LiveConfig
from .live_utils import atomic_json, clean_json
from .store import ObservationStore
from .volatility import realized_volatility
from .walkforward import WalkForwardSpec, fit_fold

LOCK_DATE = "2026-09-15"
LOCKED_CONFIG = "config/v2/C3.json"
LOCKED_SPEC = WalkForwardSpec(min_train_sessions=120, gap=1, validation_sessions=2, window="rolling", max_train_sessions=250)
SAMPLE_SESSIONS = 60
SAMPLE_DEADLINE = "2027-03-31"
METHODS = ("rv", "b1", "m_rv", "m_b1")
METHOD_LABELS = dict(rv="RV baseline", b1="B1", m_rv="M(RV)", m_b1="M(B1)")
# (model, reference, label, primary): the pre-registered pairs of Amendment 7, in the order the expectations are stated.
PAIRS = (("m_rv", "b1", "M(RV) vs B1", True), ("m_b1", "b1", "M(B1) vs B1", False), ("m_rv", "rv", "M(RV) vs RV", False))
PRIMARY_WIN_RATE_BOUND = .15
# Design C VIX terciles over set A's evaluation sessions (docs/results/v2/design-c/breakdowns.json, cut_points.vix_terciles).
VIX_CUTS = (16.446666666666665, 20.156666666666666)
MATURITY_SPLIT_DAYS = 30.0
# Files whose hashes the lock enforces: the locked configuration and every module the model, features, baselines, carry,
# pricing, quality gates, import, and inference depend on. cli.py is glue and is not enforced.
LOCKED_FILES = ("config/v2/C3.json", "config/eod-full.json", "options_engine/locked.py", "options_engine/learning.py",
                "options_engine/walkforward.py", "options_engine/baselines.py", "options_engine/carry_inputs.py", "options_engine/compare.py",
                "options_engine/core.py", "options_engine/iv.py", "options_engine/volatility.py", "options_engine/store.py",
                "options_engine/analysis.py", "options_engine/data.py", "options_engine/eod_import.py", "options_engine/live_config.py")
PREDICTION_COLUMNS = ["session", "prior_session", "gap_days", "predicted_at_utc", "symbol", "contractSymbol", "option_type", "expiration", "strike",
                      "spot", "r", "q", "T", "days_to_expiry", "rv_sigma", "b1_sigma", "m_rv_sigma", "m_rv_supported", "m_b1_sigma", "m_b1_supported",
                      "rv_price", "b1_price", "m_rv_price", "m_b1_price", "prior_observation_id"]
LOG_HEADER = ("# Fresh evaluation log (Design D, locked)\n\n"
              "One line per scored session, appended by `score-locked`; nothing here is edited by hand. Losses are session means of the\n"
              "squared spot-normalized pricing error against the session's mids over the scored contracts (the plan's RV baseline plus the\n"
              "three methods of Amendment 7). No inference is drawn until the sample rule in docs/LOCK.md is met: the first 60 available\n"
              "sessions after the lock, or all sessions available by 2027-03-31, whichever comes first, with no interim stopping on results.\n\n"
              "| Session | Prior session | Contracts predicted | Contracts scored | L_RV | L_B1 | L_M(RV) | L_M(B1) |\n"
              "|---|---|---:|---:|---:|---:|---:|---:|\n")


def repo_root():
    return Path(__file__).resolve().parents[1]


# ----------------------------------------------------------------------------- lock record
def write_lock_record(out_path, root=None, commit=None, version=__version__, lock_date=LOCK_DATE, config=LOCKED_CONFIG, files=LOCKED_FILES):
    """docs/lock.json: the hashes the locked commands verify before running, plus the locked settings."""
    root = Path(root or repo_root())
    record = dict(version=version, commit=commit, lock_date=str(lock_date), config=config, spec=asdict(LOCKED_SPEC),
                  sample_rule=dict(sessions=SAMPLE_SESSIONS, deadline=SAMPLE_DEADLINE, interim_stopping="none"),
                  files={path: file_digest(root/path) for path in files})
    atomic_json(out_path, record)
    return record


def verify_lock(lock_path, root=None):
    """Refuse unless every locked file still hashes as recorded; returns the record."""
    record = json.loads(Path(lock_path).read_text())
    root = Path(root or repo_root())
    changed = []
    for path, recorded in record["files"].items():
        current = file_digest(root/path) if (root/path).exists() else None
        if current != recorded:
            changed.append(path)
    if changed:
        raise ValueError(f"Locked files differ from {lock_path}: {', '.join(changed)}. The fresh evaluation runs only on the locked code and configuration")
    return record


# ----------------------------------------------------------------------------- store queries
def stored_sessions(store):
    with closing(store.connect()) as db:
        return [row[0] for row in db.execute("SELECT DISTINCT session_date FROM observations ORDER BY session_date")]


def chain_present(store, session):
    """True if any observation or snapshot for the session exists in the data root, eligible or not."""
    with closing(store.connect()) as db:
        count = db.execute("SELECT COUNT(*) FROM observations WHERE session_date=?", (session,)).fetchone()[0]
    return count > 0 or (store.root/"snapshots"/session).exists()


def session_rows(store, session, eligible_only=True):
    query = "SELECT payload_json, training_eligible, quality_reasons FROM observations WHERE session_date=?"+(" AND training_eligible=1" if eligible_only else "")
    with closing(store.connect()) as db:
        records = [dict(json.loads(row[0]), training_eligible=bool(row[1]), quality_reasons=row[2]) for row in db.execute(query, (session,))]
    return pd.DataFrame(records)


def import_started_at(store, session):
    """When the snapshot for the session was ingested (UTC ISO), or None."""
    with closing(store.connect()) as db:
        rows = db.execute("SELECT started_at FROM runs WHERE snapshot_path LIKE ? ORDER BY started_at", (f"%/snapshots/{session}/%",)).fetchall()
    return rows[0][0] if rows else None


# ----------------------------------------------------------------------------- inputs
def locked_carry(config, rate_csv=None, dividends_csv=None, bars_csv=None, dividend_history_end=None):
    """The locked configuration's carry with this session's refreshed input files; the configuration file itself is never edited."""
    rate_spec, dividend_spec = dict(config.rate_spec), dict(config.dividend_spec)
    if rate_csv is not None:
        if rate_spec["mode"] != "series":
            raise ValueError("The locked configuration's rate is constant; --rate-csv does not apply")
        rate_spec["path"] = str(Path(rate_csv).resolve())
    if dividend_spec["mode"] == "series":
        if dividends_csv is not None:
            dividend_spec["path"] = str(Path(dividends_csv).resolve())
        if bars_csv is not None:
            dividend_spec["bars"] = str(Path(bars_csv).resolve())
        if dividend_history_end is not None:
            dividend_spec["history_end"] = str(as_date(dividend_history_end))
    elif dividends_csv is not None or dividend_history_end is not None:
        raise ValueError("The locked configuration's dividend yield is constant; the dividend overrides do not apply")
    return CarryInputs(rate_spec, dividend_spec, getattr(config, "base_dir", None))


def underlying_inputs(bars, symbols, session, config):
    """S_t per symbol and the RV baseline from bars strictly before the session; both from the stocks database export only."""
    closes, baselines, history = {}, {}, {}
    for symbol in symbols:
        group = bars.loc[bars.symbol == symbol].sort_values("date").reset_index(drop=True)
        at_t = group.loc[group.date == session]
        if at_t.empty or not np.isfinite(float(at_t.close.iloc[0])) or float(at_t.close.iloc[0]) <= 0:
            raise ValueError(f"No underlying close for {symbol} on {session} in the bars file; import S_t from the stocks database first")
        prior = group.loc[group.date < session]
        estimate = realized_volatility(prior, config.baseline_estimator, config.history_window)
        closes[symbol] = float(at_t.close.iloc[0])
        baselines[symbol] = float(estimate.sigma)
        history[symbol] = dict(bars_before_session=int(len(prior)), last_bar_before_session=str(prior.date.max()),
                               baseline_source=f"dolt_prior_{config.history_window}_session_{config.baseline_estimator}")
    return closes, baselines, history


# ----------------------------------------------------------------------------- models
def training_windows(sessions, spec):
    """The fold the walk-forward would build for a session appended after `sessions`: train = sessions[:-gap][-max:]."""
    train = sessions[:len(sessions)-spec.gap] if spec.gap else list(sessions)
    if spec.window == "rolling":
        train = train[-spec.max_train_sessions:]
    if len(train) < spec.min_train_sessions:
        raise ValueError(f"Need {spec.min_train_sessions} training sessions before the prior session; have {len(train)}")
    return list(train)


def fit_locked_models(frame, spec):
    """M(RV) and M(B1) as the walk-forward fits them for the next session: alpha reselected on the training tail, refit on the window."""
    sessions = sorted(frame.session_date.unique())
    train = training_windows(sessions, spec)
    rv_frame = frame.loc[frame.session_date.isin(train)].reset_index(drop=True)
    model_rv, alpha_rv = fit_fold(rv_frame, spec)
    b1 = b1_baseline(frame)
    with_b1 = b1.loc[b1.b1_sigma.notna(), ["observation_id", "b1_sigma", "b1_source"]]
    b1_frame = rv_frame.merge(with_b1, on="observation_id", how="inner").reset_index(drop=True)
    if b1_frame.session_date.nunique() < spec.min_train_sessions:
        raise ValueError(f"M(B1) needs {spec.min_train_sessions} training sessions with a prior-session implied volatility; have {b1_frame.session_date.nunique()}")
    b1_frame["baseline_sigma"] = b1_frame.pop("b1_sigma").astype(float)
    b1_frame["baseline_source"] = "design_b:b1_sigma"
    model_b1, alpha_b1 = fit_fold(b1_frame, spec)

    def describe(model, alpha, table):
        return dict(alpha=alpha, training_sessions=int(table.session_date.nunique()), training_rows=int(len(table)),
                    first_training_session=str(table.session_date.min()), last_training_session=str(table.session_date.max()),
                    feature_names=model["feature_names"], excluded_groups=model["excluded_groups"], symbols=model["symbols"], support=model["support"])
    info = dict(m_rv=describe(model_rv, alpha_rv, rv_frame),
                m_b1=dict(describe(model_b1, alpha_b1, b1_frame), b1_rows_by_source={k: int(v) for k, v in b1_frame.b1_source.value_counts().sort_index().items()}),
                prior_session=sessions[-1], sessions_loaded=len(sessions))
    return model_rv, model_b1, info


# ----------------------------------------------------------------------------- predict
def prediction_set(prior_rows, session, close_time, spot, rate, yields, rv_sigma, model_rv, model_b1):
    """Contracts present at the prior session that have not expired at the session's close, priced four ways at t."""
    keep = ["symbol", "contractSymbol", "option_type", "expiration", "strike", "iv_brent_volatility", "observation_id"]
    rows = prior_rows[keep].rename(columns={"iv_brent_volatility": "b1_sigma", "observation_id": "prior_observation_id"}).copy()
    hour = int(prior_rows.expiry_hour.iloc[0]) if "expiry_hour" in prior_rows and prior_rows.expiry_hour.notna().all() else 16
    as_of = close_time.isoformat()
    rows["T"] = [time_to_expiry(expiration, as_of, hour) for expiration in rows.expiration]
    expired = int((rows["T"] <= 0).sum())
    rows = rows.loc[rows["T"] > 0].reset_index(drop=True)
    if rows.empty:
        raise ValueError("Every prior-session contract has expired; nothing to predict")
    rows["days_to_expiry"] = rows["T"]*365
    rows["spot"] = rows.symbol.map(spot).astype(float)
    rows["r"] = float(rate)
    rows["q"] = rows.symbol.map(yields).astype(float)
    rows["rv_sigma"] = rows.symbol.map(rv_sigma).astype(float)
    rows["b1_sigma"] = rows.b1_sigma.astype(float)
    sigmas = {}
    rows["baseline_sigma"] = rows.rv_sigma
    sigmas["m_rv"], rows["m_rv_supported"] = predict_volatility(model_rv, rows)
    rows["baseline_sigma"] = rows.b1_sigma
    sigmas["m_b1"], rows["m_b1_supported"] = predict_volatility(model_b1, rows)
    rows["m_rv_sigma"], rows["m_b1_sigma"] = sigmas["m_rv"], sigmas["m_b1"]
    for method in METHODS:
        rows[f"{method}_price"] = price_with_volatility(rows, rows[f"{method}_sigma"].to_numpy(float))
    rows = rows.drop(columns=["baseline_sigma"]).sort_values(["symbol", "contractSymbol"]).reset_index(drop=True)
    return rows, expired


def predict_session(config_path, session, underlying_csv, out_dir, rate_csv=None, dividends_csv=None, dividend_history_end=None,
                    lock_path=None, spec=None, lookback_sessions=None, now=None):
    """Write predictions-{session}.csv and its sidecar; refuse if the chain for the session is already in the store."""
    spec = spec or LOCKED_SPEC
    lock_path = Path(lock_path or repo_root()/"docs"/"lock.json")
    lock = verify_lock(lock_path)
    config, root = LiveConfig.load(config_path)
    store = ObservationStore(root)
    session = str(as_date(session))
    close_time = session_closes([session])[session]
    if close_time is None:
        raise ValueError(f"{session} is not an XNYS session")
    if session <= lock["lock_date"]:
        raise ValueError(f"{session} is not after the lock date {lock['lock_date']}; fresh sessions are dated strictly after it")
    if chain_present(store, session):
        raise ValueError(f"The option chain for {session} is already in the store; the prediction set must be formed before the chain is imported")
    later = [s for s in stored_sessions(store) if s > session]
    if later:
        raise ValueError(f"The store holds {len(later)} session(s) after {session} (first {later[0]}); fresh sessions are predicted in order")
    out_dir = Path(out_dir)
    csv_path, json_path = out_dir/f"predictions-{session}.csv", out_dir/f"predictions-{session}.json"
    if csv_path.exists() or json_path.exists():
        raise ValueError(f"Prediction files for {session} exist in {out_dir}; they are never overwritten")
    bars = load_underlying_csv(underlying_csv)
    carry = locked_carry(config, rate_csv, dividends_csv, underlying_csv, dividend_history_end)
    lookback = lookback_sessions or spec.max_train_sessions+spec.gap+2
    frame = store.training_frame(before=session, lookback_sessions=lookback, max_rows_per_symbol_session=config.max_rows_per_symbol_session)
    if frame.empty:
        raise ValueError("The store holds no training-eligible rows before the session")
    last_stored = str(frame.session_date.max())
    frame, failures = apply_carry(frame, carry)
    if frame.empty:
        raise ValueError("No stored row prices under the locked carry")
    model_rv, model_b1, models = fit_locked_models(frame, spec)
    prior = models["prior_session"]
    prior_rows = frame.loc[frame.session_date == prior]
    symbols = sorted(prior_rows.symbol.unique())
    spot, rv_sigma, history = underlying_inputs(bars, symbols, session, config)
    rate = carry.rate_for(session)
    yields = {symbol: carry.yield_for(symbol, session) for symbol in symbols}
    rows, expired = prediction_set(prior_rows, session, close_time, spot, rate, yields, rv_sigma, model_rv, model_b1)
    stamp = (pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now).tz_convert("UTC")).isoformat()
    gap = (dt.date.fromisoformat(session)-dt.date.fromisoformat(prior)).days
    rows.insert(0, "session", session)
    rows.insert(1, "prior_session", prior)
    rows.insert(2, "gap_days", gap)
    rows.insert(3, "predicted_at_utc", stamp)
    rows = rows[PREDICTION_COLUMNS]
    out_dir.mkdir(parents=True, exist_ok=True)
    rows.to_csv(csv_path, index=False)
    sidecar = dict(session=session, prior_session=prior, gap_days=gap, predicted_at_utc=stamp,
                   predictions=dict(path=str(csv_path), rows=int(len(rows)), sha256=file_digest(csv_path), columns=PREDICTION_COLUMNS),
                   lock=dict(path=str(lock_path), version=lock.get("version"), commit=lock.get("commit"), lock_date=lock.get("lock_date")),
                   code_version=__version__, config=dict(path=str(config_path), sha256=file_digest(config_path)), spec=asdict(spec),
                   carry=carry.describe(), rate=float(rate), yields=yields,
                   underlying=dict(path=str(underlying_csv), sha256=file_digest(underlying_csv), closes=spot, history=history),
                   rv=dict(estimator=config.baseline_estimator, window=config.history_window, sigma=rv_sigma),
                   models={k: models[k] for k in ("m_rv", "m_b1")},
                   store=dict(root=str(root), last_stored_session=last_stored, sessions_loaded=models["sessions_loaded"], lookback_sessions=lookback,
                              prior_session_rows=int(len(prior_rows)), carry_failures_by_reason={k: int(v) for k, v in failures.reason.value_counts().items()}),
                   counts=dict(prior_contracts=int(len(prior_rows)), expired_at_session=expired, predicted=int(len(rows)),
                               by_symbol={k: int(v) for k, v in rows.symbol.value_counts().sort_index().items()},
                               m_rv_supported=int(rows.m_rv_supported.sum()), m_b1_supported=int(rows.m_b1_supported.sum())),
                   protocol="Research Plan section 7: the chain for this session is not read until this prediction file is committed")
    atomic_json(json_path, clean_json(sidecar))
    return dict(sidecar, sidecar=str(json_path))


# ----------------------------------------------------------------------------- score
def committed_state(path):
    """Whether the file is tracked and identical to HEAD, and the commit that last touched it."""
    path = Path(path).resolve()

    def git(*args):
        return subprocess.run(["git", *args], cwd=path.parent, capture_output=True, text=True, check=False)
    tracked = git("ls-files", "--error-unmatch", path.name).returncode == 0
    clean = tracked and git("diff", "--quiet", "HEAD", "--", path.name).returncode == 0
    commit = committed_at = None
    if tracked:
        log = git("log", "-1", "--format=%H%n%cI", "--", path.name)
        if log.returncode == 0 and log.stdout.strip():
            commit, committed_at = log.stdout.strip().split("\n")[:2]
    return dict(tracked=tracked, clean=clean, commit=commit, committed_at=committed_at)


def ensure_log(log_path):
    log_path = Path(log_path)
    if not log_path.exists():
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(LOG_HEADER)
    return log_path


def append_log_line(log_path, result):
    log_path = ensure_log(log_path)
    text = log_path.read_text()
    if f"| {result['session']} |" in text:
        raise ValueError(f"{log_path} already has a line for {result['session']}")
    losses = result["losses"]["overall"]
    line = (f"| {result['session']} | {result['prior_session']} | {result['counts']['predicted']} | {result['counts']['scored']} | "
            f"{losses['rv']:.3e} | {losses['b1']:.3e} | {losses['m_rv']:.3e} | {losses['m_b1']:.3e} |\n")
    log_path.write_text(text+("" if text.endswith("\n") else "\n")+line)
    return line


def session_losses(scored):
    """Session mean of the squared spot-normalized pricing error per method, plus the pre-registered pairs."""
    losses = {}
    for method in METHODS:
        error = (scored[f"{method}_price"].to_numpy(float)-scored.mid.to_numpy(float))/scored.spot.to_numpy(float)
        losses[method] = float(np.mean(error**2))
    pairs = {}
    for model, reference, label, primary in PAIRS:
        base, learned = losses[reference], losses[model]
        pairs[label] = dict(model=model, reference=reference, primary=primary, d=base-learned,
                            rho=(float(1-np.sqrt(learned)/np.sqrt(base)) if base > 0 else None), model_wins=bool(learned < base))
    return losses, pairs


def score_session(config_path, session, predictions_dir, log_path, lock_path=None, out_dir=None, now=None):
    """Score the predicted contracts that appear in the imported chain; refuse unless the prediction file is committed."""
    lock_path = Path(lock_path or repo_root()/"docs"/"lock.json")
    lock = verify_lock(lock_path)
    config, root = LiveConfig.load(config_path)
    store = ObservationStore(root)
    session = str(as_date(session))
    predictions_dir = Path(predictions_dir)
    csv_path, json_path = predictions_dir/f"predictions-{session}.csv", predictions_dir/f"predictions-{session}.json"
    if not csv_path.exists() or not json_path.exists():
        raise ValueError(f"No prediction file for {session} in {predictions_dir}; predict-locked must run before the chain is imported")
    meta = json.loads(json_path.read_text())
    if file_digest(csv_path) != meta["predictions"]["sha256"]:
        raise ValueError(f"{csv_path} differs from the hash recorded when it was written")
    state = committed_state(csv_path)
    if not (state["tracked"] and state["clean"]):
        raise ValueError(f"{csv_path.name} is not committed (tracked={state['tracked']}, matches HEAD={state['clean']}); "
                         "commit the prediction file before importing the chain and scoring")
    if not chain_present(store, session):
        raise ValueError(f"The chain for {session} is not in the store; import it now that the prediction file is committed, then score")
    imported_at = import_started_at(store, session)
    committed_at = pd.Timestamp(state["committed_at"]).tz_convert("UTC")
    if imported_at is not None and pd.Timestamp(imported_at).tz_convert("UTC") < committed_at:
        raise ValueError(f"The chain for {session} was imported at {imported_at}, before the prediction file was committed at {committed_at.isoformat()}; "
                         "the protocol's separation of inputs and targets was violated and the session cannot be scored")
    out_dir = Path(out_dir or predictions_dir)
    scores_path = out_dir/f"scores-{session}.json"
    if scores_path.exists():
        raise ValueError(f"{scores_path} exists; a session is scored once")
    predictions = pd.read_csv(csv_path)
    present = session_rows(store, session, eligible_only=False)
    if present.empty:
        raise ValueError(f"The store has no rows for {session}")
    keys = ["symbol", "contractSymbol"]
    at_t = present[keys+["observation_id", "mid", "bid", "ask", "spot", "T", "training_eligible", "quality_reasons"]].rename(
        columns={"spot": "spot_at_session", "T": "T_at_session"})
    matched = predictions.merge(at_t, on=keys, how="left", indicator=True)
    absent = matched["_merge"] == "left_only"
    ineligible = ~absent & ~matched.training_eligible.eq(True).to_numpy()
    candidates = matched.loc[~absent & ~ineligible].copy()
    identified = []
    for row in candidates.itertuples(index=False):
        result = implied_volatility(row.mid, row.spot, row.strike, row.T_at_session, row.r, row.q, row.option_type)
        identified.append(bool(result.converged and not result.poorly_identified and IV_TRAINING_RANGE[0] <= result.volatility <= IV_TRAINING_RANGE[1]))
    scored = candidates.loc[np.asarray(identified, bool)].reset_index(drop=True) if len(candidates) else candidates
    if scored.empty:
        raise ValueError(f"No predicted contract is scoreable at {session}")
    losses, pairs = session_losses(scored)
    by_symbol = {symbol: session_losses(group)[0] for symbol, group in scored.groupby("symbol")}
    by_maturity = {}
    for label, mask in (("<=30d", scored.days_to_expiry <= MATURITY_SPLIT_DAYS), (">30d", scored.days_to_expiry > MATURITY_SPLIT_DAYS)):
        by_maturity[label] = dict(rows=int(mask.sum()), losses=(session_losses(scored.loc[mask])[0] if mask.any() else None))
    reasons = pd.Series([r for text in matched.loc[ineligible, "quality_reasons"].fillna("") for r in text.split(";") if r]).value_counts()
    new_at_t = present.merge(predictions[keys], on=keys, how="left", indicator=True)
    new_at_t = new_at_t.loc[new_at_t["_merge"] == "left_only"]
    stamp = (pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now).tz_convert("UTC")).isoformat()
    result = dict(session=session, prior_session=meta["prior_session"], gap_days=meta["gap_days"], scored_at_utc=stamp,
                  prediction=dict(path=str(csv_path), sha256=meta["predictions"]["sha256"], predicted_at_utc=meta["predicted_at_utc"],
                                  commit=state["commit"], committed_at=state["committed_at"]),
                  chain_imported_at=imported_at, lock=dict(path=str(lock_path), version=lock.get("version"), commit=lock.get("commit")),
                  code_version=__version__, config=dict(path=str(config_path), sha256=file_digest(config_path)),
                  counts=dict(predicted=int(len(predictions)), present_at_session=int((~absent).sum()), absent_at_session=int(absent.sum()),
                              quality_excluded_at_session=int(ineligible.sum()), quality_reasons={k: int(v) for k, v in reasons.items()},
                              not_identified_under_locked_carry=int(len(candidates)-len(scored)), scored=int(len(scored)),
                              scored_by_symbol={k: int(v) for k, v in scored.symbol.value_counts().sort_index().items()},
                              contracts_at_session_not_predicted=int(len(new_at_t)),
                              eligible_contracts_at_session_not_predicted=int(new_at_t.training_eligible.astype(bool).sum())),
                  consistency=dict(spot_mismatches=int((np.abs(scored.spot_at_session-scored.spot) > 1e-6*scored.spot).sum()),
                                   max_relative_spot_difference=float((np.abs(scored.spot_at_session-scored.spot)/scored.spot).max()),
                                   T_mismatches=int((np.abs(scored.T_at_session-scored["T"]) > 1e-9).sum()),
                                   note="predicted contracts are priced with the S_t and T of the prediction file; the store's values are compared, not used"),
                  losses=dict(overall=losses, by_symbol=by_symbol, by_maturity=by_maturity), pairs=pairs,
                  scored_contracts=[dict(symbol=r.symbol, contractSymbol=r.contractSymbol, mid=float(r.mid)) for r in scored.itertuples(index=False)])
    atomic_json(scores_path, clean_json(result))
    line = append_log_line(log_path, result)
    return dict(result, scores=str(scores_path), log=str(log_path), log_line=line.strip())


# ----------------------------------------------------------------------------- report (gated by the sample rule)
def vix_prior_levels(vix_path, sessions):
    """VIXCLS at the most recent observation strictly before each session (blank and "." rows skipped)."""
    dates, values = [], []
    with open(vix_path, newline="") as stream:
        for row in csv.DictReader(stream):
            cells = list(row.values())
            text = (cells[1] or "").strip()
            if text in ("", "."):
                continue
            dates.append(as_date(cells[0]))
            values.append(float(text))
    order = np.argsort(dates)
    dates, values = [dates[i] for i in order], [values[i] for i in order]
    levels = {}
    for session in sessions:
        index = bisect.bisect_left(dates, as_date(session))
        if index == 0:
            raise ValueError(f"no VIX observation dated before {session}")
        levels[session] = values[index-1]
    return levels


def sample_rule_met(n, as_of):
    return n >= SAMPLE_SESSIONS or str(as_date(as_of)) > SAMPLE_DEADLINE


def fresh_eval_report(scores_dir, out_dir, as_of=None, vix_path=None, block_length=BLOCK_LENGTH, replicates=REPLICATES, seed=SEED,
                      sensitivity=SENSITIVITY_BLOCKS):
    """Section 6 inference over the scored sessions against the Amendment 7 expectations; refuses before the sample rule is met."""
    files = sorted(Path(scores_dir).glob("scores-*.json"))
    records = sorted((json.loads(f.read_text()) for f in files), key=lambda r: r["session"])
    n = len(records)
    as_of = str(as_date(as_of or dt.date.today()))
    if not sample_rule_met(n, as_of):
        raise ValueError(f"Sample rule not met: {n} of {SAMPLE_SESSIONS} sessions scored and the deadline {SAMPLE_DEADLINE} has not passed as of {as_of}; "
                         "no inference before then (Research Plan section 7)")
    if n < 8:
        raise ValueError(f"{n} sessions scored; the tests need at least 8")
    sessions = [r["session"] for r in records]
    series = {m: np.array([r["losses"]["overall"][m] for r in records], float) for m in METHODS}
    block = min(block_length, n)
    indices = {block: block_indices(n, block, replicates, seed)}
    for other in sensitivity:
        if other != block and other <= n:
            indices[other] = block_indices(n, other, replicates, seed)
    comparisons = {label: pair_statistics(series[reference], series[model], indices, block, primary=primary) for model, reference, label, primary in PAIRS}
    primary, incremental, structure = (comparisons[label] for _, _, label, _ in PAIRS)

    def cell_median_rho(bucket):
        values = []
        for r in records:
            cell = r["losses"]["by_maturity"].get(bucket) or {}
            losses = cell.get("losses")
            if losses and losses["rv"] > 0:
                values.append(1-np.sqrt(losses["m_rv"])/np.sqrt(losses["rv"]))
        return (float(np.median(values)), len(values)) if values else (None, 0)
    short_rho, short_n = cell_median_rho("<=30d")
    long_rho, long_n = cell_median_rho(">30d")
    rho_structure = 1-np.sqrt(series["m_rv"])/np.sqrt(series["rv"])
    vix = None
    if vix_path is not None:
        levels = vix_prior_levels(vix_path, sessions)
        regime = np.array(["high" if levels[s] > VIX_CUTS[1] else ("middle" if levels[s] > VIX_CUTS[0] else "low") for s in sessions])
        vix = dict(path=str(vix_path), sha256=file_digest(vix_path), cuts=list(VIX_CUTS), sessions_by_regime={k: int((regime == k).sum()) for k in ("low", "middle", "high")},
                   median_rho_by_regime={k: (float(np.median(rho_structure[regime == k])) if (regime == k).any() else None) for k in ("low", "middle", "high")})
        vix["high_exceeds_rest"] = (vix["median_rho_by_regime"]["high"] is not None and (regime != "high").any()
                                    and vix["median_rho_by_regime"]["high"] > float(np.median(rho_structure[regime != "high"])))
    expectations = dict(
        primary_b1_beats_m_rv=dict(expected="interval for mean(L_B1 - L_M(RV)) below zero and M(RV) win rate under 0.15",
                                   interval=primary["interval"], win_rate=primary["win_rate"],
                                   met=bool(primary["interval"][1] < 0 and primary["win_rate"] < PRIMARY_WIN_RATE_BOUND)),
        incremental_null=dict(expected="interval for mean(L_B1 - L_M(B1)) includes zero at every block length; a confirmed null is the result, not a failure",
                              intervals=incremental["sensitivity"], met=bool(all(lo <= 0 <= hi for lo, hi in incremental["sensitivity"].values()))),
        structure_positive=dict(expected="median rho of M(RV) versus the RV baseline above zero, larger in high-VIX sessions and at maturities of 31 days or longer",
                                median_rho=structure["median_relative_improvement"], met=bool(structure["median_relative_improvement"] > 0),
                                maturity=dict(median_rho_le_30d=short_rho, sessions_le_30d=short_n, median_rho_over_30d=long_rho, sessions_over_30d=long_n,
                                              longer_exceeds_shorter=(None if short_rho is None or long_rho is None else bool(long_rho > short_rho))),
                                vix=vix))
    result = dict(exploratory=False, sample=dict(sessions=n, first=sessions[0], last=sessions[-1], as_of=as_of, rule=dict(sessions=SAMPLE_SESSIONS, deadline=SAMPLE_DEADLINE)),
                  bootstrap=dict(block_length=block, requested_block_length=block_length, replicates=replicates, seed=seed, sensitivity_blocks=sorted(indices)),
                  comparisons=comparisons, expectations=expectations, code_version=__version__,
                  note="Research Plan section 7 with Amendment 7: the expectations were fixed before any fresh session was scored; the interval is reported at whatever width the sample supports.")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(out_dir/"fresh-eval.json", clean_json(result))
    lines = ["# Fresh evaluation (Design D, locked)", "",
             f"{n} sessions from {sessions[0]} to {sessions[-1]}; paired circular block bootstrap, block {block}, {replicates:,} replicates, seed {seed}; "
             f"sensitivity at blocks {', '.join(str(b) for b in sorted(indices) if b != block) or 'none'}.", "",
             "| Comparison | Mean L_reference - L_model | 95% interval | Median rho | Win rate | Label |", "|---|---:|---:|---:|---:|---|"]
    for _, _, label, _ in PAIRS:
        c = comparisons[label]
        lines.append(f"| {label} | {c['mean_differential']:.3e} | [{c['interval'][0]:.2e}, {c['interval'][1]:.2e}] | {c['median_relative_improvement']:.4f} | "
                     f"{c['win_rate']:.3f} | {c['label']} |")
    lines += ["", "## Pre-registered expectations (Amendment 7)", ""]
    for name, item in expectations.items():
        lines.append(f"- {name}: expected {item['expected']}; met: {item['met']}.")
    (out_dir/"REPORT.md").write_text("\n".join(lines)+"\n")
    return dict(result, output=str(out_dir))
