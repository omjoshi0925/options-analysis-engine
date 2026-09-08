"""Chronological volatility learning with explicit features and a gated model registry.

Learns log(IV / independently estimated volatility). No current option price,
provider IV, solved IV, or target-derived Greek is included in the feature matrix.
"""
from pathlib import Path
import hashlib
import json
import uuid
import numpy as np
import pandas as pd
from .core import BlackScholesEngine
from .live_utils import atomic_json, process_lock
from .store import ObservationStore

MODEL_SCHEMA = 1
INPUT_COLUMNS = ("spot", "strike", "T", "r", "q", "baseline_sigma", "option_type", "symbol")


def basis(frame, symbols):
    m = np.log(frame.spot.to_numpy(float)/frame.strike.to_numpy(float))
    T = frame["T"].to_numpy(float)
    r, q = frame.r.to_numpy(float), frame.q.to_numpy(float)
    h = frame.baseline_sigma.to_numpy(float)
    arrays = [m, m*m, m*m*m, np.sqrt(T), np.log(T), m*np.sqrt(T), m*m*np.sqrt(T),
              np.log(h), r*T, q*T, (frame.option_type == "put").to_numpy(float)]
    names = ["log_moneyness", "moneyness_squared", "moneyness_cubed", "sqrt_time", "log_time",
             "moneyness_sqrt_time", "moneyness_squared_sqrt_time", "log_baseline_volatility",
             "rate_time", "yield_time", "is_put"]
    for symbol in symbols:
        arrays.append((frame.symbol == symbol).to_numpy(float))
        names.append("symbol_"+symbol)
    matrix = np.column_stack(arrays)
    if not np.isfinite(matrix).all():
        raise ValueError("Nonfinite prediction features")
    return matrix, names


def fit_ridge(frame, alpha):
    symbols = sorted(frame.symbol.unique())
    X, names = basis(frame, symbols)
    # Equal total weight for each session/symbol/expiry group.
    sizes = frame.groupby(["session_date", "symbol", "expiration"])["symbol"].transform("size").to_numpy()
    weights = 1/sizes
    weights /= weights.mean()
    center = np.average(X, axis=0, weights=weights)
    scale = np.sqrt(np.average((X-center)**2, axis=0, weights=weights))
    scale[scale < 1e-10] = 1.0
    Z = np.column_stack([np.ones(len(X)), (X-center)/scale])
    target = np.log(frame.iv_brent_volatility.to_numpy(float)/frame.baseline_sigma.to_numpy(float))
    regularizer = np.eye(Z.shape[1])*float(alpha)
    regularizer[0, 0] = 0.0
    coefficients = np.linalg.solve(Z.T@(weights[:, None]*Z)+regularizer, Z.T@(weights*target))
    support = {key: [float(frame[key].min()), float(frame[key].max())] for key in ("T", "baseline_sigma", "r", "q")}
    m = np.log(frame.spot/frame.strike)
    support["log_moneyness"] = [float(m.min()), float(m.max())]
    return dict(schema=MODEL_SCHEMA, kind="ridge_log_iv_ratio", alpha=float(alpha), symbols=symbols,
                feature_names=names, center=center.tolist(), scale=scale.tolist(), coefficients=coefficients.tolist(),
                support=support, trained_through=max(frame.session_date), training_rows=len(frame),
                training_sessions=sorted(frame.session_date.unique()),
                baseline_sources=sorted(frame.baseline_source.dropna().unique()) if "baseline_source" in frame else [])


def predict_volatility(model, frame):
    if model.get("schema") != MODEL_SCHEMA or model.get("kind") != "ridge_log_iv_ratio":
        raise ValueError("Unsupported model schema")
    X, names = basis(frame, model["symbols"])
    if names != model["feature_names"]:
        raise ValueError("Feature schema does not match model")
    center, scale = np.asarray(model["center"]), np.asarray(model["scale"])
    coefficient = np.asarray(model["coefficients"])
    if not np.isfinite(center).all() or not np.isfinite(scale).all() or (scale <= 0).any() or not np.isfinite(coefficient).all():
        raise ValueError("Invalid model parameters")
    design = np.column_stack([np.ones(len(X)), (X-center)/scale])
    learned = frame.baseline_sigma.to_numpy(float)*np.exp(np.clip(design@coefficient, -1.5, 1.5))
    learned = np.clip(learned, .03, 3.0)
    supported = frame.symbol.isin(model["symbols"]).to_numpy()
    for key, (lo, hi) in model["support"].items():
        value = np.log(frame.spot/frame.strike).to_numpy() if key == "log_moneyness" else frame[key].to_numpy(float)
        margin = max(1e-10, .1*(hi-lo))
        supported &= (value >= lo-margin) & (value <= hi+margin)
    # Unsupported symbols/regimes use the independent baseline, without extrapolating the learned adjustment.
    return np.where(supported, learned, frame.baseline_sigma.to_numpy(float)), supported


def price_with_volatility(frame, volatilities):
    return np.array([BlackScholesEngine(row.spot, row.strike, row.T, row.r, sigma, row.q).price(row.option_type)
                     for row, sigma in zip(frame.itertuples(index=False), volatilities, strict=True)])


def score_predictions(frame, prices):
    error = prices-frame.mid.to_numpy(float)
    normalized = error/frame.spot.to_numpy(float)
    return dict(n=len(frame), mae=float(np.mean(abs(error))), rmse=float(np.sqrt(np.mean(error**2))),
                spot_normalized_rmse=float(np.sqrt(np.mean(normalized**2))),
                within_spread=float(np.mean((prices >= frame.bid.to_numpy()) & (prices <= frame.ask.to_numpy()))))


def evaluate(model, frame):
    if model is None:
        sigmas, supported = frame.baseline_sigma.to_numpy(float), np.zeros(len(frame), dtype=bool)
    else:
        sigmas, supported = predict_volatility(model, frame)
    prices = price_with_volatility(frame, sigmas)
    return {**score_predictions(frame, prices), "learned_coverage": float(supported.mean())}, prices, sigmas


def strike_shape_diagnostics(frame, prices):
    """Discrete European strike monotonicity/convexity diagnostics at observed nodes."""
    data = frame.copy()
    data["prediction"] = prices
    monotonic = convex = comparisons = 0
    for _, group in data.groupby(["as_of", "symbol", "expiration", "option_type", "spot", "r", "q", "T"]):
        group = group.sort_values("strike").drop_duplicates("strike")
        if len(group) < 2:
            continue
        slopes = np.diff(group.prediction)/np.diff(group.strike)
        discount = np.exp(-float(group.r.iloc[0])*float(group["T"].iloc[0]))
        lo, hi = (-discount, 0.0) if group.option_type.iloc[0] == "call" else (0.0, discount)
        monotonic += int(np.sum((slopes < lo-1e-7) | (slopes > hi+1e-7)))
        convex += int(np.sum(np.diff(slopes) < -1e-7))
        comparisons += len(slopes)
    return dict(strike_comparisons=comparisons, slope_bound_violations=monotonic, convexity_violations=convex)


def chronological_splits(frame, minimum_sessions=12, minimum_rows=50):
    sessions = sorted(frame.session_date.unique())
    if len(sessions) < minimum_sessions:
        raise ValueError(f"Need at least {minimum_sessions} complete trading sessions; have {len(sessions)}")
    # Two untouched test sessions, two validation sessions, and a one-session gap at each boundary.
    selected = dict(train=sessions[:-6], gap_before_validation=sessions[-6:-5],
                    validation=sessions[-5:-3], gap_before_test=sessions[-3:-2], test=sessions[-2:])
    result = {name: frame.loc[frame.session_date.isin(selected[name])].copy() for name in ("train", "validation", "test")}
    for name, subset in result.items():
        if len(subset) < minimum_rows:
            raise ValueError(f"Need {minimum_rows} rows in {name}; have {len(subset)}")
    return result, selected


def load_active_model(root):
    models = Path(root)/"models"
    registry = models/"registry.json"
    if not registry.exists():
        return None
    state = json.loads(registry.read_text())
    active = state.get("active")
    if not active:
        return None
    name = active["file"]
    if Path(name).name != name or not name.endswith(".json"):
        raise ValueError("Unsafe registry model filename")
    content = (models/name).read_bytes()
    if hashlib.sha256(content).hexdigest() != active["sha256"]:
        raise ValueError("Active model checksum mismatch; restore the known model before using it")
    return json.loads(content)


def train(root, config, now=None):
    root = Path(root)
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    if now.tzinfo is None:
        raise ValueError("Training cutoff must include a timezone")
    today = str(now.tz_convert("America/New_York").date())
    with process_lock(root/"training.lock"):
        frame = ObservationStore(root).training_frame(before=today, lookback_sessions=config.training_lookback_sessions,
                                                       max_rows_per_symbol_session=config.max_rows_per_symbol_session)
        status_path = root/"training_status.json"
        status = dict(checked_at=now.isoformat(), training_rows=len(frame),
                      complete_sessions=frame.session_date.nunique() if len(frame) else 0)
        if len(frame) < config.min_training_rows or status["complete_sessions"] < config.min_training_sessions:
            status.update(state="collecting_data", message=f"Need {config.min_training_rows} strict-quality rows across {config.min_training_sessions} complete sessions.")
            atomic_json(status_path, status)
            return status
        splits, dates = chronological_splits(frame, config.min_training_sessions, config.min_split_rows)
        model_dir = root/"models"
        model_dir.mkdir(exist_ok=True)
        registry_path = model_dir/"registry.json"
        state = json.loads(registry_path.read_text()) if registry_path.exists() else {"active": None, "history": []}
        # Persist test consumption even after a rejection; later attempts need a genuinely new holdout.
        last_test = state.get("last_evaluated_session")
        fresh_count = sum(day > (last_test or "") for day in sorted(frame.session_date.unique()))
        if last_test and (min(dates["test"]) <= last_test or fresh_count < config.retrain_every_sessions):
            status.update(state="awaiting_fresh_holdout", message="The next evaluation needs two new complete test sessions.")
            atomic_json(status_path, status)
            return status
        validation_base, _, _ = evaluate(None, splits["validation"])
        candidates = []
        for alpha in (.01, 1.0, 100.0):
            model = fit_ridge(splits["train"], alpha)
            validation, _, _ = evaluate(model, splits["validation"])
            candidates.append((validation["spot_normalized_rmse"], model, validation))
        _, model, validation = min(candidates, key=lambda item: item[0])
        test_base, baseline_prices, _ = evaluate(None, splits["test"])
        test_metrics, learned_prices, learned_sigmas = evaluate(model, splits["test"])
        incumbent = load_active_model(root)
        incumbent_metrics, _, _ = evaluate(incumbent, splits["test"])
        threshold = config.promotion_min_improvement
        reasons = []
        for name, result, comparator in (("validation_vs_baseline", validation, validation_base),
                                          ("test_vs_baseline", test_metrics, test_base),
                                          ("test_vs_incumbent", test_metrics, incumbent_metrics)):
            if result["spot_normalized_rmse"] >= comparator["spot_normalized_rmse"]*(1-threshold):
                reasons.append(name+"_improvement_below_gate")
        if test_metrics["within_spread"]+0.01 < test_base["within_spread"]:
            reasons.append("test_within_spread_rate_deteriorated")
        shape = strike_shape_diagnostics(splits["test"], learned_prices)
        if shape["slope_bound_violations"] or shape["convexity_violations"]:
            reasons.append("observed_strike_shape_violations")
        group_metrics = []
        for symbol, group in splits["test"].groupby("symbol"):
            base_result, _, _ = evaluate(None, group)
            learned_result, _, _ = evaluate(model, group)
            group_metrics.append(dict(symbol=symbol, baseline=base_result, candidate=learned_result))
            if learned_result["spot_normalized_rmse"] > base_result["spot_normalized_rmse"]*1.05+1e-12:
                reasons.append("symbol_regression_"+symbol)
        model_id = now.strftime("%Y%m%dT%H%M%SZ")+"_"+uuid.uuid4().hex[:8]
        dataset_hash = hashlib.sha256("\n".join(sorted(frame.observation_id)).encode()).hexdigest()
        model.update(model_id=model_id, evaluated_through=max(dates["test"]), dataset_sha256=dataset_hash)
        report = dict(model_id=model_id, created_at=now.isoformat(), splits=dates, dataset_sha256=dataset_hash,
                      feature_columns=list(INPUT_COLUMNS), target="log(calculated_IV / baseline_sigma)",
                      selected_alpha=model["alpha"], validation_candidates=[dict(alpha=item[1]["alpha"], metrics=item[2]) for item in candidates],
                      validation_baseline=validation_base, validation_candidate=validation,
                      test_baseline=test_base, test_candidate=test_metrics, test_incumbent=incumbent_metrics,
                      test_by_symbol=group_metrics, promoted=not reasons, gate_failures=reasons,
                      test_strike_shape=shape,
                      interpretation="Out-of-time contemporary-price estimation, not a future option-return forecast. Two test sessions are a limited promotion check, not statistical proof.")
        model_path = model_dir/(model_id+".json")
        atomic_json(model_path, model)
        evaluation_dir = root/"evaluations"/model_id
        atomic_json(evaluation_dir/"report.json", report)
        scored = splits["test"][["observation_id", "as_of", "session_date", "symbol", "option_type", "strike", "expiration", "mid", "spot"]].copy()
        scored["baseline_price"], scored["learned_price"], scored["learned_sigma"] = baseline_prices, learned_prices, learned_sigmas
        scored.to_csv(evaluation_dir/"test_predictions.csv", index=False)
        (evaluation_dir/"REPORT.md").write_text(
            "# Chronological model evaluation\n\n"+f"Model: {model_id}\n\n"+
            f"Status: {'promoted' if not reasons else 'rejected'}\n\n"+
            f"Training ends {max(dates['train'])}; validation {dates['validation']}; untouched test {dates['test']}. One-session gaps separate the periods.\n\n"+
            "| Test metric | Baseline | Candidate |\n|---|---:|---:|\n"+
            "\n".join(f"| {metric} | {test_base[metric]:.8g} | {test_metrics[metric]:.8g} |" for metric in ("n","mae","rmse","spot_normalized_rmse","within_spread"))+
            "\n\nGate failures: "+(", ".join(reasons) or "none")+
            "\n\nNo refit uses validation/test rows in this saved model. Hyperparameters are selected on validation; consumed test dates are recorded even when the candidate is rejected.\n\n"+
            report["interpretation"]+"\n")
        active_entry = dict(model_id=model_id, file=model_path.name,
                            sha256=hashlib.sha256(model_path.read_bytes()).hexdigest())
        state["last_evaluated_session"] = max(dates["test"])
        state["latest_evaluation"] = model_id
        if not reasons:
            state["active"] = active_entry
            state["history"].append(active_entry)
        atomic_json(registry_path, state)
        status.update(state="promoted" if not reasons else "candidate_rejected", model_id=model_id,
                      gate_failures=reasons, evaluation=str(evaluation_dir))
        atomic_json(status_path, status)
        return status


def monitor_latest(root, run_id):
    root = Path(root)
    source = root/"audits"/run_id/"analyzed_options.csv"
    if not source.exists() or source.stat().st_size < 3:
        return None
    frame = pd.read_csv(source)
    if frame.empty:
        return None
    frame = frame.loc[frame.training_eligible.astype(bool)].copy()
    if frame.empty:
        return None
    model = load_active_model(root)
    baseline, _, _ = evaluate(None, frame)
    current, _, _ = evaluate(model, frame)
    status = dict(run_id=run_id, as_of=frame.as_of.max(), model_id=model.get("model_id") if model else None,
                  baseline=baseline, current=current,
                  batch_degradation_warning=bool(model and current["spot_normalized_rmse"] > baseline["spot_normalized_rmse"]*1.10),
                  note="A single-batch warning is not a statistical drift test.")
    atomic_json(root/"monitoring"/(run_id+".json"), status)
    atomic_json(root/"latest_monitor.json", status)
    return status


def score_snapshot(root, snapshot, output, config):
    from .data import read_snapshot, FilterConfig
    from .analysis import analyze_options
    raw, metadata = read_snapshot(snapshot)
    output = Path(output)
    if output.exists():
        raise ValueError("Score output exists; choose a new directory")
    frame, audit = analyze_options(raw, FilterConfig(min_open_interest=config.min_open_interest,
                                   max_relative_spread=config.max_relative_spread, min_days=config.min_days, max_days=config.max_days))
    if frame.empty:
        raise ValueError("No usable quotes in the snapshot")
    model = load_active_model(root)
    if model:
        earliest = min(pd.Timestamp(stamp).tz_convert("America/New_York").date().isoformat() for stamp in frame.as_of)
        if earliest <= model.get("evaluated_through", model["trained_through"]):
            raise ValueError("Snapshot overlaps the active model's training or evaluation period; choose a later snapshot")
    baseline, base_prices, _ = evaluate(None, frame)
    current, prices, sigmas = evaluate(model, frame)
    frame["learned_price"] = prices
    frame["learned_sigma"] = sigmas
    frame["learned_error"] = frame.mid-prices
    frame["model_used"] = predict_volatility(model, frame)[1] if model else False
    from .store import training_quality
    cache = {}
    if metadata.get("data_kind") != "market":
        frame["data_kind"] = metadata.get("data_kind", "unknown")
    frame["data_quality_reasons"] = [";".join(training_quality(row, config, cache)) for row in frame.to_dict("records")]
    report = dict(model_id=model.get("model_id") if model else None, baseline=baseline, current=current,
                  data_kind=metadata.get("data_kind", "unknown"),
                  rows_with_quality_issues=int(frame.data_quality_reasons.ne("").sum()),
                  note="Contemporary quote comparison on a later snapshot; this is not a future-return forecast.")
    atomic_json(output/"report.json", report)
    frame.to_csv(output/"scored_options.csv", index=False)
    audit.to_csv(output/"filter_audit.csv", index=False)
    return report


def select_model(root, model_id=None):
    root = Path(root)
    with process_lock(root/"training.lock"):
        path = root/"models/registry.json"
        state = json.loads(path.read_text()) if path.exists() else {"active": None, "history": []}
        if model_id is None:
            state["active"] = None
        else:
            matches = [entry for entry in state["history"] if entry["model_id"] == model_id]
            if not matches:
                raise ValueError("Rollback is limited to a previously promoted model ID")
            entry = matches[-1]
            if hashlib.sha256((root/"models"/entry["file"]).read_bytes()).hexdigest() != entry["sha256"]:
                raise ValueError("Rollback model checksum mismatch")
            state["active"] = entry
        atomic_json(path, state)
        return state["active"]
