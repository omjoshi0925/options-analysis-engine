"""All provider data in this module are deterministic fixtures, never market evidence."""
from dataclasses import replace
from contextlib import closing
import json
import os
from pathlib import Path
from types import SimpleNamespace
import threading
import numpy as np
import pandas as pd
import pytest
import requests
from options_engine import BlackScholesEngine
from options_engine.live_config import LiveConfig
from options_engine.live_utils import atomic_json, process_lock, session_window
from options_engine.data import time_to_expiry, write_snapshot
from options_engine.providers import TradierProvider, ProviderError, provider_timestamp
from options_engine.store import ObservationStore, training_quality
from options_engine.analysis import analyze_options
from options_engine.learning import (basis, fit_ridge, predict_volatility, chronological_splits,
                                     train, load_active_model, select_model)
from options_engine.collector import collect_cycle, retry_delay, recover_snapshots, live_status


def fixture_quotes(day="2026-04-01", capture_offset=0):
    stamp = pd.Timestamp(day+"T14:00:00Z")
    capture = stamp+pd.Timedelta(seconds=capture_offset)
    rows = []
    for days in (30,90):
        expiration = (stamp+pd.Timedelta(days=days)).date().isoformat()
        T = time_to_expiry(expiration, capture)
        for strike in np.linspace(90,110,9):
            m = np.log(100/strike)
            iv = .2*np.exp(.15+.4*m+.6*m*m)
            for kind in ("call","put"):
                mid = BlackScholesEngine(100,strike,T,.04,iv,.01).price(kind)
                rows.append(dict(symbol="TEST",contractSymbol=f"TEST_{expiration}_{strike}_{kind}",
                                 option_type=kind,expiration=expiration,as_of=capture.isoformat(),
                                 spot=100,strike=strike,bid=mid*.99,ask=mid*1.01,lastPrice=mid,
                                 volume=500,openInterest=1000,impliedVolatility=iv,r=.04,q=.01,
                                 baseline_sigma=.2,baseline_source="fixture_fixed",exercise_style="american",
                                 data_kind="market",provider="tradier",feed="production",contract_size=100,
                                 spot_timestamp=stamp.isoformat(),bid_timestamp=stamp.isoformat(),
                                 ask_timestamp=stamp.isoformat(),lastTradeDate=stamp.isoformat(),expiry_hour=16))
    return pd.DataFrame(rows)


def test_config_rejects_credentials_and_invalid_schedule(tmp_path):
    with pytest.raises(ValueError):
        LiveConfig(interval_seconds=0)
    with pytest.raises(ValueError):
        LiveConfig(tickers=("SPY",), dividend_yields={})
    path=tmp_path/"config.json"
    atomic_json(path,{"token":"not-a-real-secret"})
    with pytest.raises(ValueError,match="credentials"):
        LiveConfig.load(path)


def test_session_holiday_early_close_and_dst():
    holiday=session_window("2026-09-07T15:00:00Z")
    assert not holiday["is_open"] and holiday["session"]=="2026-09-08"
    assert session_window("2026-11-27T17:59:00Z")["is_open"]
    assert not session_window("2026-11-27T18:00:00Z")["is_open"]
    assert not session_window("2026-04-01T13:32:00Z")["is_open"]
    assert session_window("2026-04-01T13:36:00Z")["is_open"]
    assert session_window("2026-01-05T14:36:00Z")["is_open"]


def test_process_lock_excludes_second_writer_and_releases(tmp_path):
    with process_lock(tmp_path/"lock"):
        with pytest.raises(RuntimeError):
            with process_lock(tmp_path/"lock"):
                pass
    with process_lock(tmp_path/"lock"):
        pass


@pytest.mark.parametrize("changes,reason", [
    ({"data_kind":"synthetic"},"not_real_market_data"),
    ({"feed":"indicative"},"unverified_feed"),
    ({"bid_timestamp":None},"missing_bid_timestamp"),
    ({"bid_timestamp":"2026-04-01T13:50:00Z"},"stale_bid_timestamp"),
    ({"spot_timestamp":"2026-04-01T14:10:00Z"},"future_spot_timestamp"),
    ({"contract_size":10},"nonstandard_contract_size"),
    ({"iv_brent_poorly_identified":True},"iv_not_identified")])
def test_strict_training_quality(changes,reason):
    frame,_=analyze_options(fixture_quotes().iloc[[8]])
    row=frame.iloc[0].to_dict()
    assert training_quality(row,LiveConfig())==[]
    row.update(changes)
    assert reason in training_quality(row,LiveConfig())


def test_quote_timestamps_seconds_and_milliseconds():
    assert provider_timestamp(1775052000)==provider_timestamp(1775052000000)
    assert provider_timestamp(None) is None
    assert provider_timestamp("2026-04-01 14:00:00") is None
    assert provider_timestamp("2026-04-01T14:00:00Z").endswith("+00:00")


def test_tradier_timestamp_mapping_history_cache_and_auth(monkeypatch,tmp_path):
    monkeypatch.setenv("TRADIER_TOKEN","fixture-token")
    monkeypatch.setattr("options_engine.providers.time.sleep",lambda seconds:None)
    now=pd.Timestamp.now(tz="UTC")
    dates=pd.bdate_range(end=now.tz_localize(None)-pd.Timedelta(days=2),periods=70)
    history=[dict(date=str(date.date()),close=100+i*.1+np.sin(i)*.2) for i,date in enumerate(dates)]
    expiry=str((now+pd.Timedelta(days=30)).date())
    captured=int(now.timestamp()*1000)
    calls=[]
    class Session:
        headers={}
        def get(self,url,params,timeout,allow_redirects):
            assert url.startswith("https://api.tradier.com/v1/markets/")
            assert allow_redirects is False
            calls.append(url)
            if url.endswith("/history"):
                data={"history":{"day":history}}
            elif url.endswith("/expirations"):
                data={"expirations":{"date":[expiry]}}
            elif url.endswith("/chains"):
                data={"options":{"option":[dict(symbol="FIXTURE_OPTION",option_type="call",strike=100,
                         bid=5,ask=5.1,bid_date=captured,ask_date=captured,trade_date=captured,
                         open_interest=100,volume=100,contract_size=100,greeks={"mid_iv":.2})]}}
            else:
                data={"quotes":{"quote":{"last":100,"trade_date":captured}}}
            return SimpleNamespace(status_code=200,json=lambda:data,headers={})
    provider=TradierProvider(LiveConfig(tickers=("TEST",),dividend_yields={"TEST":.01}),tmp_path,Session())
    raw,meta,hist=provider.fetch()
    assert len(raw)==1 and len(hist)==70 and not meta["failures"]
    assert raw.iloc[0].bid_timestamp==provider_timestamp(captured)
    assert raw.iloc[0].impliedVolatility==.2
    assert "fixture-token" not in json.dumps(meta)
    provider.history("TEST",now)
    assert sum(url.endswith("/history") for url in calls)==1
    monkeypatch.delenv("TRADIER_TOKEN")
    with pytest.raises(ProviderError,match="missing"):
        TradierProvider(LiveConfig(),tmp_path)


def test_rate_limit_not_retried_in_a_loop(monkeypatch,tmp_path):
    monkeypatch.setenv("TRADIER_TOKEN","fixture-token")
    class Session:
        headers={}
        def get(self,*args,**kwargs):
            return SimpleNamespace(status_code=429,headers={"Retry-After":"900"})
    p=TradierProvider(LiveConfig(),tmp_path,Session())
    with pytest.raises(ProviderError) as error:
        p.get("quotes",symbols="SPY")
    assert error.value.retry_after==900
    assert retry_delay(LiveConfig(),1,provider_retry=10000)>=10000


def test_store_idempotency_and_unchanged_quote_dedup(tmp_path):
    config=LiveConfig()
    store=ObservationStore(tmp_path/"live")
    raw=fixture_quotes()
    folder=write_snapshot(raw,tmp_path/"snapshot1",{"provider":"tradier","data_kind":"market"})
    first=store.ingest(folder,config)
    assert first["inserted_rows"]>0 and first["training_rows"]>0
    assert store.ingest(folder,config)["status"]=="duplicate_snapshot"
    raw["as_of"]=pd.Timestamp(raw.iloc[0].as_of)+pd.Timedelta(seconds=30)
    second=write_snapshot(raw,tmp_path/"snapshot2",{"provider":"tradier","data_kind":"market"})
    assert store.ingest(second,config)["inserted_rows"]==0
    assert store.status()["training_sessions"]==1


def test_synthetic_archive_never_enters_training(tmp_path):
    raw=fixture_quotes()
    raw["data_kind"]="synthetic"
    folder=write_snapshot(raw,tmp_path/"snapshot",{"provider":"fixture","data_kind":"synthetic"})
    store=ObservationStore(tmp_path/"live")
    result=store.ingest(folder,LiveConfig())
    assert result["inserted_rows"]>0 and result["training_rows"]==0
    assert store.training_frame().empty


def test_worker_timeout_record_and_recovery(tmp_path):
    root=tmp_path/"live"
    store=ObservationStore(root)
    cfg=LiveConfig()
    def timed_out(*args):
        raise TimeoutError("fixture deadline")
    result=collect_cycle(tmp_path/"config",cfg,root,store,threading.Event(),timed_out)
    assert result["status"]=="failed"
    pending=root/"pending"/"completed_fixture"
    write_snapshot(fixture_quotes(),pending,{"provider":"tradier","data_kind":"market","acquisition_finished":"2026-04-01T14:00:00Z"})
    recovered=recover_snapshots(root,cfg,store)
    assert len(recovered)==1 and recovered[0]["inserted_rows"]>0
    assert recover_snapshots(root,cfg,store)==[]


def test_successful_cycle_publishes_snapshot_and_monitor(tmp_path):
    root=tmp_path/"live"
    store=ObservationStore(root)
    def fixture_worker(config_path,destination,timeout,stop):
        write_snapshot(fixture_quotes(),destination,{"provider":"tradier","data_kind":"market","failures":[]})
        return 0
    result=collect_cycle(tmp_path/"config",LiveConfig(),root,store,threading.Event(),fixture_worker)
    assert result["status"]=="ok" and result["training_rows"]>0
    assert (root/"latest_monitor.json").exists()
    assert len(list((root/"snapshots").glob('*/*/metadata.json')))==1


def test_snapshot_metadata_cannot_disguise_synthetic_rows(tmp_path):
    raw=fixture_quotes()
    raw["data_kind"]="synthetic"
    folder=write_snapshot(raw,tmp_path/"snapshot",{"data_kind":"market","provider":"tradier"})
    result=ObservationStore(tmp_path/"live").ingest(folder,LiveConfig())
    assert result["training_rows"]==0
    raw["data_kind"]="market"
    folder=write_snapshot(raw,tmp_path/"snapshot2",{"data_kind":"synthetic","provider":"tradier"})
    result=ObservationStore(tmp_path/"live2").ingest(folder,LiveConfig())
    assert result["training_rows"]==0


def model_frame():
    import exchange_calendars as xc
    sessions=xc.get_calendar("XNYS").sessions_in_range("2026-04-01","2026-04-30")[:12]
    frames=[]
    for day in sessions:
        analyzed,_=analyze_options(fixture_quotes(str(day.date())))
        analyzed["session_date"]=str(day.date())
        analyzed["observation_id"]=[f"{day.date()}_{i}" for i in range(len(analyzed))]
        frames.append(analyzed)
    return pd.concat(frames,ignore_index=True)


@pytest.fixture(scope="module")
def learned_frame():
    return model_frame()


def test_time_splits_have_gaps_and_no_shared_sessions(learned_frame):
    splits,dates=chronological_splits(learned_frame)
    assert len(dates["train"])==6 and len(dates["test"])==2
    assert max(dates["train"])<min(dates["gap_before_validation"])<min(dates["validation"])
    assert max(dates["validation"])<min(dates["gap_before_test"])<min(dates["test"])
    assert set(splits["train"].observation_id).isdisjoint(splits["test"].observation_id)


def test_predictions_ignore_current_quotes_and_target_iv(learned_frame):
    splits,_=chronological_splits(learned_frame)
    model=fit_ridge(splits["train"],1)
    first,_=predict_volatility(model,splits["test"])
    changed=splits["test"].copy()
    for key in ("mid","bid","ask","iv_brent_volatility","impliedVolatility","baseline_delta"):
        changed[key]=999.0
    second,_=predict_volatility(model,changed)
    np.testing.assert_array_equal(first,second)
    changed["symbol"]="UNSEEN"
    fallback,supported=predict_volatility(model,changed)
    assert not supported.any()
    np.testing.assert_array_equal(fallback,changed.baseline_sigma)


def test_validation_data_cannot_change_training_scaler(learned_frame):
    splits,_=chronological_splits(learned_frame)
    model=fit_ridge(splits["train"],1)
    X,_=basis(splits["train"],model["symbols"])
    assert len(model["center"])==X.shape[1]
    assert model["trained_through"]==max(splits["train"].session_date)
    assert not set(model["training_sessions"])&set(splits["test"].session_date)


def test_train_gate_registry_and_fresh_holdout(monkeypatch,tmp_path,learned_frame):
    monkeypatch.setattr(ObservationStore,"training_frame",lambda self,**kwargs:learned_frame.copy())
    cfg=LiveConfig()
    result=train(tmp_path,cfg,now="2026-05-01T14:00:00Z")
    assert result["state"]=="promoted",result
    model=load_active_model(tmp_path)
    assert model and model["evaluated_through"]>model["trained_through"]
    again=train(tmp_path,cfg,now="2026-05-01T15:00:00Z")
    assert again["state"]=="awaiting_fresh_holdout"
    select_model(tmp_path)
    assert load_active_model(tmp_path) is None
    select_model(tmp_path,model["model_id"])
    assert load_active_model(tmp_path)["model_id"]==model["model_id"]
    with pytest.raises(ValueError):
        select_model(tmp_path,"unapproved_candidate")
    (tmp_path/"models"/(model["model_id"]+".json")).write_text('{}')
    with pytest.raises(ValueError,match="checksum"):
        load_active_model(tmp_path)


def test_failed_gate_does_not_promote_and_still_consumes_test(monkeypatch,tmp_path,learned_frame):
    from options_engine.learning import evaluate
    monkeypatch.setattr(ObservationStore,"training_frame",lambda self,**kwargs:learned_frame.copy())
    def bad_model(model,frame):
        metrics,prices,sigmas=evaluate(None,frame)
        if model is not None:
            metrics["spot_normalized_rmse"]*=2
        return metrics,prices,sigmas
    monkeypatch.setattr("options_engine.learning.evaluate",bad_model)
    result=train(tmp_path,LiveConfig(),now="2026-05-01T14:00:00Z")
    assert result["state"]=="candidate_rejected"
    assert load_active_model(tmp_path) is None
    registry=json.loads((tmp_path/"models/registry.json").read_text())
    assert registry["last_evaluated_session"]==max(learned_frame.session_date)


def test_insufficient_data_produces_status_not_a_model(tmp_path):
    result=train(tmp_path,LiveConfig(),now="2026-05-01T14:00:00Z")
    assert result["state"]=="collecting_data"
    assert load_active_model(tmp_path) is None


def test_complete_snapshot_to_database_to_training_path(tmp_path):
    import exchange_calendars as xc
    cfg=LiveConfig()
    store=ObservationStore(tmp_path/"live")
    sessions=xc.get_calendar("XNYS").sessions_in_range("2026-04-01","2026-04-30")[:12]
    for day in sessions:
        folder=write_snapshot(fixture_quotes(str(day.date())),tmp_path/"inputs"/str(day.date()),
                              {"provider":"tradier","data_kind":"market"})
        store.ingest(folder,cfg)
    assert store.status()["training_sessions"]==12
    sampled=store.training_frame(before="2026-04-03",lookback_sessions=1,max_rows_per_symbol_session=2)
    assert len(sampled)==2 and sampled.session_date.eq("2026-04-02").all()
    result=train(tmp_path/"live",cfg,now="2026-05-01T14:00:00Z")
    assert result["state"]=="promoted"
    assert load_active_model(tmp_path/"live") is not None


def test_recovery_quarantines_corruption_and_recovers_other_snapshots(tmp_path):
    root=tmp_path/"live"
    store=ObservationStore(root)
    bad=write_snapshot(fixture_quotes(),root/"pending"/"bad",{"data_kind":"market"})
    (bad/"metadata.json").write_text('{broken')
    good=write_snapshot(fixture_quotes(),root/"pending"/"good",{"data_kind":"market"})
    results=recover_snapshots(root,LiveConfig(),store)
    assert len(results)==1 and results[0]["training_rows"]>0
    assert len(list((root/"quarantine").glob('bad_*')))==1
    assert any(row["status"]=="quarantined" for row in store.status()["recent_runs"])
    assert recover_snapshots(root,LiveConfig(),store)==[]


def test_score_requires_fresh_period_and_honors_synthetic_metadata(monkeypatch,tmp_path,learned_frame):
    from options_engine.learning import score_snapshot
    cfg=LiveConfig()
    root=tmp_path/"live"
    monkeypatch.setattr(ObservationStore,"training_frame",lambda self,**kwargs:learned_frame.copy())
    result=train(root,cfg,now="2026-05-01T14:00:00Z")
    assert result["state"]=="promoted"
    old=write_snapshot(fixture_quotes(max(learned_frame.session_date)),tmp_path/"old",{"data_kind":"market"})
    with pytest.raises(ValueError,match="evaluation period"):
        score_snapshot(root,old,tmp_path/"old_score",cfg)
    fresh=write_snapshot(fixture_quotes("2026-05-01"),tmp_path/"fresh",{"data_kind":"synthetic"})
    result=score_snapshot(root,fresh,tmp_path/"fresh_score",cfg)
    assert result["model_id"] and result["rows_with_quality_issues"]==36
    select_model(root)
    baseline=score_snapshot(root,fresh,tmp_path/"baseline_score",cfg)
    assert baseline["current"]==baseline["baseline"]


def test_worker_deadline_terminates_a_real_child(monkeypatch,tmp_path):
    import subprocess
    import sys
    from options_engine.collector import worker_process
    original=subprocess.Popen
    children=[]
    def sleeping_child(*args,**kwargs):
        child=original([sys.executable,"-c","import time; time.sleep(10)"],**kwargs)
        children.append(child)
        return child
    monkeypatch.setattr("options_engine.collector.subprocess.Popen",sleeping_child)
    with pytest.raises(TimeoutError):
        worker_process(tmp_path/"unused",tmp_path/"unused-output",.05,threading.Event())
    assert len(children)==1 and children[0].poll() is not None


def test_restart_probe_respects_persisted_backoff(monkeypatch,tmp_path):
    from options_engine.collector import run_collector
    cfg=LiveConfig(data_root=str(tmp_path/"live"),auto_train=False)
    path=tmp_path/"config.json"
    atomic_json(path,cfg.public_dict())
    deadline=(pd.Timestamp.now(tz="UTC")+pd.Timedelta(hours=2)).isoformat()
    atomic_json(tmp_path/"live/collector_status.json",dict(next_due=deadline,consecutive_failures=2))
    def unexpected_cycle(*args):
        pytest.fail("Persisted backoff must prevent a provider request")
    monkeypatch.setattr("options_engine.collector.collect_cycle",unexpected_cycle)
    assert run_collector(path,probe=True)==0
    state=json.loads((tmp_path/"live/collector_status.json").read_text())
    assert state["next_due"]==deadline and state["consecutive_failures"]==2
