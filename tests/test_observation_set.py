"""Observation sets and the carry-aware commands, end to end on a temporary EOD store."""
import gzip
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from options_engine import BlackScholesEngine
from options_engine.carry_inputs import CarryInputs, apply_carry
from options_engine.cli import parser, run
from options_engine.eod_import import import_eod
from options_engine.live_config import LiveConfig
from options_engine.observation_set import (build_observation_set, read_observation_set, restrict_to_observation_set,
                                            write_observation_set)
from options_engine.store import ObservationStore
from options_engine.walkforward import WalkForwardSpec, walk_forward, walk_forward_report
from test_eod_import import eod_config


def invoke(capsys, *argv):
    code = run(parser().parse_args([str(a) for a in argv]))
    return code, json.loads(capsys.readouterr().out)


def rolling_fixture(base, sessions=20, sigma=.2):
    """Like test_eod_import.fixture_csvs but with two rolling expiries per session, so evaluation maturities stay inside the
    training range and the learned model is actually used (the single fixed expiry there makes every fold fall back)."""
    import exchange_calendars as xc
    days = [str(d.date()) for d in xc.get_calendar("XNYS").sessions_in_range("2023-01-01", "2023-12-31")]
    chain_days = days[70:70+sessions]
    rng = np.random.default_rng(11)
    closes = 100*np.exp(np.cumsum(rng.normal(0, sigma/np.sqrt(252), len(days))))
    underlying = pd.DataFrame(dict(date=days[:70+sessions], act_symbol="TEST", open=closes[:70+sessions]*.999,
                                   high=closes[:70+sessions]*1.01, low=closes[:70+sessions]*.99, close=closes[:70+sessions]))
    rows = []
    for i, day in enumerate(chain_days):
        spot = closes[70+i]
        for ahead in (21, 63):
            expiration = days[70+i+ahead]
            T = (pd.Timestamp(expiration)-pd.Timestamp(day)).days/365
            for strike in np.round(np.linspace(spot*.92, spot*1.08, 7), 1):
                iv = sigma*np.exp(.1+.3*np.log(spot/strike)+.5*np.log(spot/strike)**2)
                for kind in ("Call", "Put"):
                    mid = BlackScholesEngine(spot, strike, T, .04, iv, .01).price(kind.lower())
                    rows.append(dict(date=day, act_symbol="TEST", expiration=expiration, strike=strike, call_put=kind,
                                     bid=round(mid*.99, 4), ask=round(mid*1.01, 4), vol=round(iv, 4)))
    chain_path, underlying_path = base/"chain.csv", base/"underlying.csv"
    pd.DataFrame(rows).to_csv(chain_path, index=False)
    underlying.to_csv(underlying_path, index=False)
    return chain_path, underlying_path, chain_days


@pytest.fixture(scope="module")
def eod_root(tmp_path_factory):
    """Twenty imported sessions plus rate, dividend, split, and config files that reference them."""
    base = tmp_path_factory.mktemp("v2")
    chain_path, underlying_path, chain_days = rolling_fixture(base)
    root = base/"data"/"root"
    import_eod(chain_path, underlying_path, eod_config(), root)
    bars = pd.read_csv(underlying_path)
    inputs = base/"inputs"
    inputs.mkdir()
    # A quote on every session: the first session has no strictly-prior quote, every later one uses the previous session's.
    # The quotes oscillate instead of trending so evaluation rates stay inside each training window's range; a trending
    # series would trip the v1 support guard on every fold (the effect reported at CHECKPOINT 2).
    (inputs/"rates.csv").write_text("observation_date,DGS3MO\n"+"".join(f"{d},{2.0+.1*math.sin(i):.4f}\n" for i, d in enumerate(chain_days)))
    (inputs/"dividends.csv").write_text(f"symbol,ex_date,amount\nTEST,{bars.date.min()},0.5\nTEST,{chain_days[2]},0.5\n")
    (inputs/"splits.csv").write_text("symbol,ex_date,to_factor,for_factor\n")
    bars.to_csv(inputs/"bars.csv", index=False)
    series_dividend = {"mode": "series", "path": "inputs/dividends.csv", "bars": "inputs/bars.csv", "splits": "inputs/splits.csv",
                       "history_start": "2022-01-01", "history_end": chain_days[-1]}
    stale_dividend = dict(series_dividend, history_end=chain_days[-3])       # the last two sessions' windows end past coverage
    configs = {}
    for name, rate, dividend in (
            ("K0", {"mode": "constant", "value": .04}, {"mode": "constant", "yields": {"TEST": .01}}),
            ("K1", {"mode": "series", "path": "inputs/rates.csv"}, {"mode": "constant", "yields": {"TEST": .01}}),
            ("K3", {"mode": "series", "path": "inputs/rates.csv"}, series_dividend),
            ("K4", {"mode": "constant", "value": .04}, stale_dividend)):
        settings = dict(eod_config().public_dict(), data_root="data/root", rate=rate, dividend=dividend)
        settings.pop("dividend_yields", None)
        path = base/f"{name}.json"
        path.write_text(json.dumps(settings, indent=2, sort_keys=True))
        configs[name] = path
    other_root = dict(json.loads(configs["K0"].read_text()), data_root="data/elsewhere")
    (base/"K5.json").write_text(json.dumps(other_root, indent=2, sort_keys=True))
    configs["K5"] = base/"K5.json"
    return dict(base=base, root=root, configs=configs, sessions=chain_days)


def store_frame(eod_root):
    return ObservationStore(eod_root["root"]).training_frame(before="9999-12-31", lookback_sessions=1000)


def test_build_and_reuse_observation_set(eod_root, tmp_path):
    frame = store_frame(eod_root)
    names = ("K0", "K1", "K3", "K4")
    carries = {name: CarryInputs.from_config(LiveConfig.load(eod_root["configs"][name])[0]) for name in names}
    keys, summary = build_observation_set(frame, carries)
    first = eod_root["sessions"][0]
    history_end = pd.Timestamp(eod_root["sessions"][-3])
    stale_sessions = {s for s in eod_root["sessions"] if pd.Timestamp(s)-pd.Timedelta(days=1) > history_end}   # window ends past coverage
    first_rows, stale_rows = int((frame.session_date == first).sum()), int(frame.session_date.isin(stale_sessions).sum())
    assert summary["by_config"]["K0"]["dropped"] == 0
    assert summary["by_config"]["K1"]["by_reason"] == {"rate_unavailable": first_rows}
    assert summary["by_config"]["K3"]["by_reason"] == {"rate_unavailable": first_rows}
    assert summary["by_config"]["K4"]["by_reason"] == {"dividend_history_stale": stale_rows}
    assert summary["dropped_under_any_config"] == first_rows+stale_rows and summary["kept"] == len(frame)-first_rows-stale_rows
    assert summary["sessions_lost"] == sorted({first}|stale_sessions)      # the union over configs, not any single config
    assert not ({first}|stale_sessions) & set(keys.session_date)
    assert summary["by_config"]["K4"]["composition"]["by_year"] == {"2023": stale_rows}
    written = write_observation_set(keys, summary, tmp_path/"set.csv")
    ids, description = read_observation_set(tmp_path/"set.csv")
    assert ids == set(keys.observation_id) and description["sha256"] == written["sha256"] == description["recorded_sha256"]
    sidecar = json.loads((tmp_path/"set.drops.json").read_text())
    assert sidecar["observation_set"]["rows"] == len(keys) and sidecar["by_config"]["K1"]["carry"]["rate"]["mode"] == "series"
    restricted, counts = restrict_to_observation_set(frame, ids)
    assert counts == dict(candidate_rows=len(frame), matched_rows=len(keys), set_size=len(keys))
    with pytest.raises(ValueError, match="exists"):
        write_observation_set(keys, summary, tmp_path/"set.csv")
    # Compressed sets round-trip with the same sidecar and the uncompressed hash; tampering is caught.
    with gzip.open(tmp_path/"copy.csv.gz", "wb") as stream:
        stream.write((tmp_path/"set.csv").read_bytes())
    (tmp_path/"copy.drops.json").write_text((tmp_path/"set.drops.json").read_text())
    ids_gz, description_gz = read_observation_set(tmp_path/"copy.csv.gz")
    assert ids_gz == ids and description_gz["uncompressed_sha256"] == written["sha256"] and description_gz["sha256"] != written["sha256"]
    text = (tmp_path/"set.csv").read_text().splitlines()
    text[1] = text[1].replace(text[1].split(",")[0], "0"*64, 1)
    (tmp_path/"set.csv").write_text("\n".join(text)+"\n")
    with pytest.raises(ValueError, match="hash"):
        read_observation_set(tmp_path/"set.csv")
    with pytest.raises(ValueError, match="Duplicate"):
        build_observation_set(pd.concat([frame, frame.iloc[:1]], ignore_index=True), carries)


def test_constant_v1_carry_reproduces_the_stored_frame(eod_root):
    frame = store_frame(eod_root)
    kept, failures = apply_carry(frame, CarryInputs.from_config(LiveConfig.load(eod_root["configs"]["K0"])[0]))
    assert failures.empty and len(kept) == len(frame)
    aligned = frame.set_index("observation_id").loc[kept.observation_id]
    for column in ("iv_brent_volatility", "r", "q", "iv_brent_residual"):
        assert np.array_equal(aligned[column].to_numpy(), kept[column].to_numpy())


def test_cli_walk_forward_uses_the_model_and_honors_the_set(eod_root, capsys, tmp_path):
    configs = eod_root["configs"]
    out = tmp_path/"docs"/"set-A.csv"
    code, built = invoke(capsys, "observation-set", "build", "--configs", configs["K0"], configs["K1"], configs["K3"], "--out", out)
    assert code == 0 and built["rows"] == built["kept"] > 0 and Path(built["drops"]).exists()
    assert built["by_config"]["K1"] == {"rate_unavailable": built["dropped_under_any_config"]}
    keys = pd.read_csv(out)
    code, full = invoke(capsys, "walk-forward", "--config", configs["K0"], "--output", tmp_path/"full", "--min-train-sessions", "6",
                        "--gap", "1", "--bootstrap", "200")
    code, restricted = invoke(capsys, "walk-forward", "--config", configs["K3"], "--output", tmp_path/"restricted", "--min-train-sessions", "6",
                              "--gap", "1", "--bootstrap", "200", "--observation-set", out)
    assert code == 0
    folds_full, folds = pd.read_csv(tmp_path/"full"/"folds.csv"), pd.read_csv(tmp_path/"restricted"/"folds.csv")
    # The learned model is exercised: once the training window spans a few sessions the v1 support guard passes and the
    # model beats the baseline, so the new columns and statistics are not validated by 0 == 0.
    covered = folds.learned_coverage == 1
    assert covered.mean() > .5 and (folds.model_mse < folds.baseline_mse)[covered].all() and not full["diebold_mariano"]["degenerate"]
    assert full["learned_coverage"]["zero_coverage_folds"] == list(folds_full.evaluated_session[folds_full.learned_coverage == 0])
    assert restricted["learned_coverage"]["mean"] == pytest.approx(float(folds.learned_coverage.mean()))
    # The first session is outside the set, so the restricted run has one fewer session in every training window.
    assert len(folds) == len(folds_full)-1 and set(folds.evaluated_session) <= set(keys.session_date)
    assert folds.train_start.iloc[0] == sorted(set(keys.session_date))[0] and folds_full.train_start.iloc[0] == eod_root["sessions"][0]
    for column in ("baseline_mse", "model_mse", "baseline_rmse", "model_rmse", "rho", "d", "r_effective", "q_effective_TEST"):
        assert column in folds
    assert np.allclose(folds.rho, 1-np.sqrt(folds.model_mse)/np.sqrt(folds.baseline_mse)) and (folds.rho[covered] > 0).all()
    assert np.allclose(folds.d, folds.baseline_mse-folds.model_mse) and np.allclose(folds.baseline_mse, folds.baseline_rmse**2)
    rates = pd.read_csv(eod_root["base"]/"inputs"/"rates.csv")
    expected = [math.log1p(rates.loc[rates.observation_date < day, "DGS3MO"].iloc[-1]/100) for day in folds.evaluated_session]
    assert np.allclose(folds.r_effective, expected)                      # the strictly-prior rate reached the evaluation rows
    assert (folds.q_effective_TEST > 0).all() and not np.allclose(folds.q_effective_TEST, .01)
    assert restricted["observation_set"]["matched_rows"] == len(keys) and restricted["observation_set"]["problems"] == []
    assert restricted["carry"]["rate"]["mode"] == "series" and restricted["dropped_by_carry"]["rows"] == 0
    assert restricted["median_rho"] == pytest.approx(float(folds.rho.median())) and restricted["mean_d"] == pytest.approx(float(folds.d.mean()))
    # K0's folds equal a direct walk_forward on the raw store frame: constant carry changes nothing.
    direct = walk_forward(store_frame(eod_root), WalkForwardSpec(min_train_sessions=6, gap=1, validation_sessions=2))["folds"]
    assert np.allclose(direct.baseline_loss, folds_full.baseline_loss) and np.allclose(direct.model_loss, folds_full.model_loss)


def test_hand_written_set_restricts_training_and_evaluation(eod_root, capsys, tmp_path):
    frame = store_frame(eod_root)
    sessions = eod_root["sessions"]
    dropped_session, halved_session = sessions[10], sessions[14]
    keep = frame.loc[frame.session_date != dropped_session]
    half = keep.loc[keep.session_date == halved_session].observation_id.iloc[::2]
    keep = keep.loc[~keep.observation_id.isin(half)]
    keys = keep[["observation_id", "session_date", "symbol"]].sort_values(["session_date", "symbol", "observation_id"])
    written = write_observation_set(keys, dict(note="hand-written"), tmp_path/"hand.csv")
    assert written["rows"] == len(keys)
    code, result = invoke(capsys, "walk-forward", "--config", eod_root["configs"]["K0"], "--output", tmp_path/"hand", "--min-train-sessions", "6",
                          "--gap", "1", "--bootstrap", "200", "--observation-set", tmp_path/"hand.csv")
    assert code == 0
    folds = pd.read_csv(tmp_path/"hand"/"folds.csv")
    assert dropped_session not in set(folds.evaluated_session) and dropped_session not in set(folds.train_end)
    per_session = keys.groupby("session_date").size()
    kept_sessions = sorted(per_session.index)
    for fold in folds.itertuples():
        window = [s for s in kept_sessions if fold.train_start <= s <= fold.train_end]
        assert fold.train_rows == int(per_session.loc[window].sum())       # training counts come from the set alone
        assert fold.evaluation_rows == int(per_session.loc[fold.evaluated_session])
    halved_fold = folds.loc[folds.evaluated_session == halved_session]
    assert len(halved_fold) == 1 and halved_fold.evaluation_rows.iloc[0] == int(per_session.loc[halved_session])
    assert halved_fold.evaluation_rows.iloc[0] < int((frame.session_date == halved_session).sum())
    code, _ = invoke(capsys, "walk-forward", "--config", eod_root["configs"]["K0"], "--output", tmp_path/"free", "--min-train-sessions", "6",
                     "--gap", "1", "--bootstrap", "200")
    free = pd.read_csv(tmp_path/"free"/"folds.csv")
    assert len(free) == len(folds)+1 and not free.train_rows.equals(folds.train_rows)


def test_walk_forward_refuses_a_set_it_cannot_honor(eod_root, capsys, tmp_path):
    frame = store_frame(eod_root)
    keys = frame[["observation_id", "session_date", "symbol"]].copy()
    keys.loc[keys.index[0], "observation_id"] = "not-in-the-store"
    write_observation_set(keys, dict(note="partial"), tmp_path/"partial.csv")
    with pytest.raises(ValueError, match="not honored"):
        invoke(capsys, "walk-forward", "--config", eod_root["configs"]["K0"], "--output", tmp_path/"x", "--min-train-sessions", "6",
               "--observation-set", tmp_path/"partial.csv")
    code, result = invoke(capsys, "walk-forward", "--config", eod_root["configs"]["K0"], "--output", tmp_path/"y", "--min-train-sessions", "6",
                          "--bootstrap", "200", "--observation-set", tmp_path/"partial.csv", "--allow-partial")
    assert code == 0 and result["observation_set"]["problems"][0].startswith("only")
    out = tmp_path/"built.csv"
    invoke(capsys, "observation-set", "build", "--configs", eod_root["configs"]["K0"], "--out", out)
    with pytest.raises(ValueError, match="not among the configs"):                  # K1 was not a builder of this set
        invoke(capsys, "walk-forward", "--config", eod_root["configs"]["K1"], "--output", tmp_path/"z", "--min-train-sessions", "6",
               "--observation-set", out)


def test_refusals(eod_root, capsys, tmp_path):
    configs = eod_root["configs"]
    with pytest.raises(ValueError, match="share one data root"):
        invoke(capsys, "observation-set", "build", "--configs", configs["K0"], configs["K5"], "--out", tmp_path/"a.csv")
    other = dict(json.loads(configs["K0"].read_text()), max_relative_spread=.1)
    (eod_root["base"]/"K6.json").write_text(json.dumps(other))
    with pytest.raises(ValueError, match="identical outside"):
        invoke(capsys, "observation-set", "build", "--configs", configs["K0"], eod_root["base"]/"K6.json", "--out", tmp_path/"b.csv")
    with pytest.raises(ValueError, match="constant rate"):
        invoke(capsys, "import-eod", "--config", configs["K3"], "--chain-csv", "x.csv", "--underlying-csv", "y.csv")
    with pytest.raises(ValueError, match="constant rate"):
        invoke(capsys, "train", "--config", configs["K3"])
    code, exported = invoke(capsys, "export", "--config", configs["K3"], "--output", tmp_path/"obs.csv", "--include-excluded")
    table = pd.read_csv(tmp_path/"obs.csv")
    assert code == 0 and {"effective_r", "effective_q", "carry_failure"} <= set(table.columns) and "stored import-time" in exported["note"]
    first = eod_root["sessions"][0]
    failed = table.loc[table.session_date == first]
    assert (failed.carry_failure == "rate_unavailable").all() and failed.effective_r.isna().all() and failed.effective_q.isna().all()
    assert table.loc[table.session_date != first, ["effective_r", "effective_q"]].notna().all().all()


def test_report_survives_a_degenerate_differential(tmp_path):
    table = pd.DataFrame(dict(evaluated_session=[f"2026-01-{d:02d}" for d in range(1, 13)], baseline_loss=1.0, model_loss=.5,
                              rho=1-math.sqrt(.5), d=.5, learned_coverage=1.0))
    result = dict(folds=table, spec=dict(window="expanding", gap=1), sessions=list(table.evaluated_session),
                  baseline_losses=table.baseline_loss.to_numpy(), model_losses=table.model_loss.to_numpy())
    significance = walk_forward_report(result, tmp_path/"report", n_boot=50)
    assert significance["diebold_mariano"]["degenerate"] and significance["diebold_mariano"]["statistic"] is None
    assert "degenerate" in (tmp_path/"report"/"REPORT.md").read_text()
