"""Design D, the locked fresh evaluation (options_engine.locked): lock verification, blind prediction and its refusals,
scoring only after the prediction file is committed, and the sample-rule gate on inference."""
import json
import shutil
import subprocess

import numpy as np
import pandas as pd
import pytest

from options_engine import BlackScholesEngine
from options_engine import locked
from options_engine.carry_inputs import apply_carry, CarryInputs
from options_engine.cli import parser, run
from options_engine.eod_import import import_eod
from options_engine.live_config import LiveConfig
from options_engine.locked import (LOCKED_FILES, METHODS, PAIRS, PREDICTION_COLUMNS, SAMPLE_SESSIONS, committed_state, fresh_eval_report,
                                   locked_carry, predict_session, score_session, training_windows, verify_lock, write_lock_record)
from options_engine.store import ObservationStore
from options_engine.walkforward import WalkForwardSpec
from test_eod_import import eod_config

SMALL_SPEC = WalkForwardSpec(min_train_sessions=8, gap=1, validation_sessions=2, window="rolling", max_train_sessions=10)


def quote_rows(day, spot, expiration, strikes, sigma=.2, tiny=()):
    rows = []
    T = (pd.Timestamp(expiration)-pd.Timestamp(day)).days/365
    for strike in strikes:
        m = np.log(spot/strike)
        iv = sigma*np.exp(.1+.3*m+.5*m*m)
        for kind in ("Call", "Put"):
            mid = BlackScholesEngine(spot, strike, T, .04, iv, .01).price(kind.lower())
            bid, ask = (round(mid*.99, 4), round(mid*1.01, 4)) if (strike, kind) not in tiny else (.045, .055)
            rows.append(dict(date=day, act_symbol="TEST", expiration=expiration, strike=strike, call_put=kind, bid=bid, ask=ask, vol=round(iv, 4)))
    return rows


def locked_fixture(base, sessions=14, sigma=.2):
    """Contracts persist across sessions (five staggered expiries, the nearest expiring exactly at the fresh session t), so B1 exists
    for every stored session after the first, one expiry drops out of the prediction set at t, and t's chain adds a new expiry,
    drops one predicted strike, and quotes one predicted contract below the training floor. The chain for t is written to a
    separate file so the store can be built without it."""
    import exchange_calendars as xc
    days = [str(d.date()) for d in xc.get_calendar("XNYS").sessions_in_range("2023-01-01", "2023-12-31")]
    first = 70
    chain_days = days[first:first+sessions]
    t = days[first+sessions+2]
    history = days[:first+sessions+3]
    rng = np.random.default_rng(11)
    closes = 100*np.exp(np.cumsum(rng.normal(0, sigma/np.sqrt(252), len(history))))
    underlying = pd.DataFrame(dict(date=history, act_symbol="TEST", open=closes*.999, high=closes*1.01, low=closes*.99, close=closes))
    expiries = [days[first+sessions+2+21*k] for k in range(5)]          # expiries[0] == t
    strikes = [88.0, 92.0, 96.0, 100.0, 104.0, 108.0, 112.0]              # a fixed grid, so the same contracts recur session after session
    rows = []
    for i, day in enumerate(chain_days):
        spot = closes[first+i]
        for expiration in expiries:
            rows.append(quote_rows(day, spot, expiration, strikes, sigma))
    spot_t = closes[first+sessions+2]
    at_t = [quote_rows(t, spot_t, expiries[1], strikes[1:], sigma),                                       # one strike absent at t
            quote_rows(t, spot_t, expiries[2], strikes, sigma, tiny=((112.0, "Call"),)),                  # one quote below the floor
            quote_rows(t, spot_t, expiries[3], strikes, sigma), quote_rows(t, spot_t, expiries[4], strikes, sigma),
            quote_rows(t, spot_t, days[first+sessions+2+21*5], strikes, sigma)]                            # new expiry, not predicted
    chain_path, chain_t_path, underlying_path = base/"chain.csv", base/"chain_t.csv", base/"underlying.csv"
    pd.DataFrame([r for group in rows for r in group]).to_csv(chain_path, index=False)
    pd.DataFrame([r for group in at_t for r in group]).to_csv(chain_t_path, index=False)
    underlying.to_csv(underlying_path, index=False)
    return dict(chain=chain_path, chain_t=chain_t_path, underlying=underlying_path, sessions=chain_days, t=t, between=days[first+sessions],
                expiries=expiries, new_rows=14, strikes=strikes)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    base = tmp_path_factory.mktemp("locked")
    files = locked_fixture(base)
    root = base/"data"/"root"
    import_eod(files["chain"], files["underlying"], eod_config(), root)
    settings = dict(eod_config().public_dict(), data_root="data/root")
    config = base/"locked.json"
    config.write_text(json.dumps(settings, indent=2, sort_keys=True))
    lock = base/"lock.json"
    write_lock_record(lock, commit="0123abcd", lock_date="2000-01-01")
    return dict(files, base=base, root=root, config=config, lock=lock)


def copied_env(env, tmp_path):
    """A private copy of the store so a test can import the fresh session without touching the shared fixture."""
    root = tmp_path/"root"
    shutil.copytree(env["root"], root)
    config = tmp_path/"locked.json"
    config.write_text(json.dumps(dict(json.loads(env["config"].read_text()), data_root="root"), indent=2, sort_keys=True))
    return dict(env, root=root, config=config)


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *args], cwd=cwd, capture_output=True, text=True, check=True)


def test_lock_record_verifies_and_refuses_changed_files(tmp_path):
    record = write_lock_record(tmp_path/"lock.json", commit="abc123", lock_date="2000-01-01")
    assert set(record["files"]) == set(LOCKED_FILES) and record["commit"] == "abc123" and record["spec"]["max_train_sessions"] == 250
    assert verify_lock(tmp_path/"lock.json")["lock_date"] == "2000-01-01"
    tampered = dict(record, files=dict(record["files"], **{"options_engine/learning.py": "0"*64}))
    (tmp_path/"tampered.json").write_text(json.dumps(tampered))
    with pytest.raises(ValueError, match="learning.py"):
        verify_lock(tmp_path/"tampered.json")
    assert training_windows([f"s{i}" for i in range(15)], SMALL_SPEC) == [f"s{i}" for i in range(4, 14)]   # gap 1, rolling 10
    with pytest.raises(ValueError, match="training sessions"):
        training_windows([f"s{i}" for i in range(5)], SMALL_SPEC)
    config, _ = LiveConfig.load(locked.repo_root()/"config"/"eod-full.json")
    with pytest.raises(ValueError, match="constant"):
        locked_carry(config, rate_csv="x.csv")
    with pytest.raises(ValueError, match="constant"):
        locked_carry(config, dividend_history_end="2030-01-01")
    c3, _ = LiveConfig.load(locked.repo_root()/"config"/"v2"/"C3.json")
    carry = locked_carry(c3, dividend_history_end="2030-06-30")
    assert carry.describe()["dividend"]["history_end"] == "2030-06-30" and carry.describe()["rate"]["mode"] == "series"


def test_predict_refuses_stored_sessions_and_predicts_blind(env, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(locked, "LOCKED_SPEC", SMALL_SPEC)
    out = tmp_path/"fresh"
    with pytest.raises(ValueError, match="already in the store"):
        predict_session(env["config"], env["sessions"][-1], env["underlying"], out, lock_path=env["lock"])
    (tmp_path/"future-lock.json").write_text(json.dumps(dict(json.loads(env["lock"].read_text()), lock_date="2030-01-01")))
    with pytest.raises(ValueError, match="lock date"):
        predict_session(env["config"], env["t"], env["underlying"], out, lock_path=tmp_path/"future-lock.json")
    with pytest.raises(ValueError, match="not an XNYS session"):
        predict_session(env["config"], "2023-07-04", env["underlying"], out, lock_path=env["lock"])
    code = run(parser().parse_args(["predict-locked", "--session", env["t"], "--config", str(env["config"]), "--underlying-csv", str(env["underlying"]),
                                    "--out-dir", str(out), "--lock", str(env["lock"])]))
    summary = json.loads(capsys.readouterr().out)
    # the prediction set is exactly the prior session's eligible contracts that outlive t; the fixture's far-from-the-money
    # short-dated quotes fail the training floor at t-1, so the counts come from the store rather than the grid
    config, root = LiveConfig.load(env["config"])
    prior = ObservationStore(root).training_frame(before=env["t"], lookback_sessions=1)
    prior, _ = apply_carry(prior, CarryInputs.from_config(config))
    expiring, live = int((prior.expiration == env["t"]).sum()), int((prior.expiration > env["t"]).sum())
    assert code == 0 and summary["prior_session"] == env["sessions"][-1] and summary["counts"]["expired_at_session"] == expiring == 8
    predictions = pd.read_csv(out/f"predictions-{env['t']}.csv")
    assert list(predictions.columns) == PREDICTION_COLUMNS and len(predictions) == live == summary["counts"]["predicted"] == 55
    assert (predictions.session == env["t"]).all() and (predictions.expiration > env["t"]).all() and env["expiries"][0] not in set(predictions.expiration)
    assert predictions.predicted_at_utc.nunique() == 1 and predictions.predicted_at_utc.iloc[0].endswith("+00:00")
    for method in METHODS:
        assert np.isfinite(predictions[f"{method}_price"]).all() and (predictions[f"{method}_price"] > 0).all()
    # B1 is the prior session's own implied volatility of the same contract, solved under the locked carry
    merged = predictions.merge(prior[["contractSymbol", "iv_brent_volatility", "baseline_sigma"]], on="contractSymbol")
    assert len(merged) == len(predictions) and np.allclose(merged.b1_sigma, merged.iv_brent_volatility)
    assert not np.allclose(merged.rv_sigma, merged.baseline_sigma)        # the RV baseline at t uses bars through t-1, not t-2
    assert predictions.m_rv_supported.mean() > .5 and (predictions.m_rv_sigma[~predictions.m_rv_supported] == predictions.rv_sigma[~predictions.m_rv_supported]).all()
    sidecar = json.loads((out/f"predictions-{env['t']}.json").read_text())
    assert sidecar["predictions"]["sha256"] == locked.file_digest(out/f"predictions-{env['t']}.csv") and sidecar["lock"]["commit"] == "0123abcd"
    assert sidecar["models"]["m_rv"]["training_sessions"] == 10 and sidecar["models"]["m_b1"]["b1_rows_by_source"] == {"same_contract": sidecar["models"]["m_b1"]["training_rows"]}
    assert sidecar["underlying"]["closes"]["TEST"] == pytest.approx(predictions.spot.iloc[0]) and sidecar["counts"]["prior_contracts"] == len(prior) == live+expiring
    with pytest.raises(ValueError, match="never overwritten"):
        predict_session(env["config"], env["t"], env["underlying"], out, lock_path=env["lock"])
    record = json.loads(env["lock"].read_text())
    record["files"]["options_engine/walkforward.py"] = "0"*64
    (tmp_path/"tampered-lock.json").write_text(json.dumps(record))
    with pytest.raises(ValueError, match="differ from"):
        run(parser().parse_args(["predict-locked", "--session", env["t"], "--config", str(env["config"]), "--underlying-csv", str(env["underlying"]),
                                 "--out-dir", str(tmp_path/"other"), "--lock", str(tmp_path/"tampered-lock.json")]))


def test_score_requires_a_committed_prediction_and_an_imported_chain(env, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(locked, "LOCKED_SPEC", SMALL_SPEC)
    env = copied_env(env, tmp_path)
    repo = tmp_path/"repo"
    repo.mkdir()
    git(repo, "init", "-q")
    fresh, log = repo/"fresh", repo/"FRESH_EVAL.md"
    result = predict_session(env["config"], env["t"], env["underlying"], fresh, lock_path=env["lock"])
    csv_path = fresh/f"predictions-{env['t']}.csv"
    assert not committed_state(csv_path)["tracked"]
    with pytest.raises(ValueError, match="not committed"):
        score_session(env["config"], env["t"], fresh, log, lock_path=env["lock"])
    git(repo, "add", "fresh")
    git(repo, "commit", "-q", "-m", "fresh: predictions")
    state = committed_state(csv_path)
    assert state["tracked"] and state["clean"] and len(state["commit"]) == 40
    with pytest.raises(ValueError, match="not in the store"):
        score_session(env["config"], env["t"], fresh, log, lock_path=env["lock"])
    import_eod(env["chain_t"], env["underlying"], eod_config(), env["root"])            # the chain, only after the prediction commit
    with pytest.raises(ValueError, match="already in the store"):
        predict_session(env["config"], env["t"], env["underlying"], tmp_path/"again", lock_path=env["lock"])
    monkeypatch.setattr(locked, "import_started_at", lambda store, session: "2000-01-01T00:00:00+00:00")
    with pytest.raises(ValueError, match="before the prediction file was committed"):
        score_session(env["config"], env["t"], fresh, log, lock_path=env["lock"])
    monkeypatch.undo()
    monkeypatch.setattr(locked, "LOCKED_SPEC", SMALL_SPEC)
    csv_path.write_text(csv_path.read_text()+"\n")
    with pytest.raises(ValueError, match="differs from the hash"):
        score_session(env["config"], env["t"], fresh, log, lock_path=env["lock"])
    git(repo, "checkout", "--", "fresh")
    code = run(parser().parse_args(["score-locked", "--session", env["t"], "--config", str(env["config"]), "--predictions-dir", str(fresh), "--log", str(log),
                                    "--lock", str(env["lock"])]))
    summary = json.loads(capsys.readouterr().out)
    counts = summary["counts"]
    predictions = pd.read_csv(csv_path)
    present = locked.session_rows(ObservationStore(env["root"]), env["t"], eligible_only=False)
    absent_expected = int(((predictions.expiration == env["expiries"][1]) & (predictions.strike == 88.0)).sum())          # the strike missing at t
    tiny_expected = int(((predictions.expiration == env["expiries"][2]) & (predictions.strike == 112.0) & (predictions.option_type == "call")).sum())
    not_predicted_expected = int((~present.contractSymbol.isin(predictions.contractSymbol)).sum())
    assert code == 0 and counts["predicted"] == result["counts"]["predicted"] == len(predictions) == 55
    assert counts["absent_at_session"] == absent_expected == 1 and counts["quality_excluded_at_session"] == tiny_expected == 1
    assert counts["quality_reasons"] == {"midpoint_below_training_floor": 1}
    assert counts["scored"] == 55-1-1-counts["not_identified_under_locked_carry"] and counts["contracts_at_session_not_predicted"] == not_predicted_expected == env["new_rows"]
    assert summary["consistency"]["spot_mismatches"] == 0 and summary["consistency"]["T_mismatches"] == 0
    losses = summary["losses"]["overall"]
    assert all(np.isfinite(losses[m]) and losses[m] > 0 for m in METHODS) and set(summary["pairs"]) == {label for _, _, label, _ in PAIRS}
    assert summary["pairs"]["M(RV) vs B1"]["d"] == pytest.approx(losses["b1"]-losses["m_rv"]) and summary["pairs"]["M(RV) vs B1"]["primary"]
    scores = json.loads((fresh/f"scores-{env['t']}.json").read_text())
    assert scores["prediction"]["commit"] == state["commit"] and scores["losses"]["by_maturity"]["<=30d"]["rows"] > 0 and scores["losses"]["by_maturity"][">30d"]["rows"] > 0
    text = log.read_text()
    assert text.startswith("# Fresh evaluation log") and text.rstrip().endswith("|") and text.count(f"| {env['t']} |") == 1
    assert summary["log_line"].split(" | ")[2:4] == ["55", str(counts["scored"])]
    with pytest.raises(ValueError, match="scored once"):
        score_session(env["config"], env["t"], fresh, log, lock_path=env["lock"])


def synthetic_scores(directory, n, seed=0):
    import exchange_calendars as xc
    sessions = [str(d.date()) for d in xc.get_calendar("XNYS").sessions_in_range("2026-09-16", "2027-03-31")][:n]
    rng = np.random.default_rng(seed)
    for session in sessions:
        b1 = rng.uniform(1e-5, 3e-5)
        overall = dict(rv=b1*rng.uniform(2, 4), b1=b1, m_rv=b1*rng.uniform(2, 3), m_b1=b1*rng.uniform(.9, 1.1))
        short = dict(rows=10, losses=dict(overall, m_rv=overall["rv"]*1.1))                    # the model loses at short maturities
        long = dict(rows=10, losses=dict(overall, m_rv=overall["rv"]*.5))                      # and wins at longer ones
        payload = dict(session=session, losses=dict(overall=overall, by_maturity={"<=30d": short, ">30d": long}))
        (directory/f"scores-{session}.json").write_text(json.dumps(payload))
    return sessions


def test_fresh_eval_report_waits_for_the_sample_rule(tmp_path):
    scores = tmp_path/"scores"
    scores.mkdir()
    synthetic_scores(scores, 5)
    with pytest.raises(ValueError, match="Sample rule not met"):
        fresh_eval_report(scores, tmp_path/"report", as_of="2026-12-01", replicates=200)
    with pytest.raises(ValueError, match="at least 8"):
        fresh_eval_report(scores, tmp_path/"report", as_of="2027-04-01", replicates=200)
    sessions = synthetic_scores(scores, SAMPLE_SESSIONS)
    vix = tmp_path/"vix.csv"
    vix.write_text("observation_date,VIXCLS\n2026-09-15,15.0\n"+"".join(f"{s},{12+(i % 3)*5:.1f}\n" for i, s in enumerate(sessions)))
    result = fresh_eval_report(scores, tmp_path/"report", as_of="2026-12-01", vix_path=vix, replicates=200)
    assert result["sample"]["sessions"] == SAMPLE_SESSIONS and result["bootstrap"]["block_length"] == 21 and set(result["comparisons"]) == {label for _, _, label, _ in PAIRS}
    expectations = result["expectations"]
    assert expectations["primary_b1_beats_m_rv"]["met"] and expectations["incremental_null"]["met"] and expectations["structure_positive"]["met"]
    assert expectations["structure_positive"]["maturity"]["longer_exceeds_shorter"] is True
    assert sum(expectations["structure_positive"]["vix"]["sessions_by_regime"].values()) == SAMPLE_SESSIONS
    assert (tmp_path/"report"/"fresh-eval.json").exists() and "Pre-registered expectations" in (tmp_path/"report"/"REPORT.md").read_text()
    code = run(parser().parse_args(["fresh-eval-report", "--scores-dir", str(scores), "--out", str(tmp_path/"cli"), "--as-of", "2027-04-01", "--replicates", "100"]))
    assert code == 0 and (tmp_path/"cli"/"REPORT.md").exists()
