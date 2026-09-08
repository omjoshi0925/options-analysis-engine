"""Import free historical end-of-day option chains into the observation store.

Designed for the public DoltHub `post-no-preference/options` database (with
underlying daily bars from `post-no-preference/stocks`), but any CSV with the
same logical columns works. Export locally, with no account:

    dolt clone post-no-preference/options && cd options
    dolt sql -r csv -q "SELECT date, act_symbol, expiration, strike, call_put,
        bid, ask, vol FROM option_chain WHERE act_symbol = 'SPY'" > spy_chain.csv
    dolt clone post-no-preference/stocks && cd ../stocks
    dolt sql -r csv -q "SELECT date, act_symbol, open, high, low, close
        FROM ohlcv WHERE act_symbol = 'SPY'" > spy_underlying.csv

Verify the live column names with `dolt sql -q "DESCRIBE option_chain"` before a
large export; pass --chain-columns / --underlying-columns overrides if they
differ. Every imported quote is timestamped at the exchange close of its
session, labeled provider `dolt_eod`, feed `historical_eod`, and enters the
`daily_eod` training tier only. Nothing in this module can produce a
strict-tier row. Check the dataset's stated license before publishing results
built on it, and cite the source.
"""
from pathlib import Path
import numpy as np
import pandas as pd
from .data import write_snapshot
from .live_utils import clean_json
from .store import ObservationStore
from .volatility import realized_volatility

CHAIN_COLUMNS = dict(date="date", symbol="act_symbol", expiration="expiration", strike="strike",
                     call_put="call_put", bid="bid", ask="ask", iv="vol")
UNDERLYING_COLUMNS = dict(date="date", symbol="act_symbol", open="open", high="high", low="low", close="close")


def _rename(frame, mapping, optional=("iv",)):
    columns = {str(name).strip().lower(): name for name in frame.columns}
    selected = {}
    for logical, source in mapping.items():
        key = str(source).strip().lower()
        if key in columns:
            selected[logical] = frame[columns[key]]
        elif logical not in optional:
            raise ValueError(f"Missing required column '{source}' (for '{logical}'); found {sorted(columns)}")
    return pd.DataFrame(selected)


def load_chain_csv(path, columns=None):
    frame = _rename(pd.read_csv(path), {**CHAIN_COLUMNS, **(columns or {})})
    frame["date"] = pd.to_datetime(frame.date, errors="raise").dt.date.astype(str)
    frame["expiration"] = pd.to_datetime(frame.expiration, errors="raise").dt.date.astype(str)
    frame["symbol"] = frame.symbol.astype(str).str.upper().str.strip()
    kinds = frame.call_put.astype(str).str.lower().str.strip()
    frame["option_type"] = kinds.map({"call": "call", "c": "call", "put": "put", "p": "put"})
    if frame.option_type.isna().any():
        raise ValueError("call_put values must be Call/Put (or C/P)")
    for column in ("strike", "bid", "ask"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if "iv" in frame:
        frame["iv"] = pd.to_numeric(frame.iv, errors="coerce")
    return frame.drop(columns=["call_put"])


def load_underlying_csv(path, columns=None):
    frame = _rename(pd.read_csv(path), {**UNDERLYING_COLUMNS, **(columns or {})}, optional=())
    frame["date"] = pd.to_datetime(frame.date, errors="raise").dt.date.astype(str)
    frame["symbol"] = frame.symbol.astype(str).str.upper().str.strip()
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.sort_values(["symbol", "date"]).reset_index(drop=True)


def session_closes(dates):
    """Exchange close per session date; None marks non-sessions. Cached calendar."""
    import exchange_calendars as xc
    calendar = xc.get_calendar("XNYS")
    closes = {}
    for day in dates:
        try:
            session = calendar.date_to_session(day)
            closes[day] = pd.Timestamp(calendar.session_close(session)).tz_convert("UTC")
        except Exception:  # noqa: BLE001 - calendar rejects non-sessions in several exception types
            closes[day] = None
    return closes


def build_session_snapshots(chain, underlying, config):
    """Yield (session_date, raw_frame, metadata) with baselines from strictly prior sessions only."""
    chain = chain.loc[chain.symbol.isin(config.tickers)]
    if chain.empty:
        raise ValueError("No chain rows match the configured tickers")
    closes = session_closes(sorted(chain.date.unique()))
    bars_by_symbol = {symbol: group.reset_index(drop=True) for symbol, group in underlying.groupby("symbol")}
    for day in sorted(chain.date.unique()):
        close_time = closes[day]
        skipped, frames, assumptions = [], [], {}
        if close_time is None:
            skipped.append(dict(session=day, reason="not_an_xnys_session"))
        else:
            as_of = close_time.isoformat()
            for symbol, quotes in chain.loc[chain.date == day].groupby("symbol"):
                bars = bars_by_symbol.get(symbol, pd.DataFrame())
                prior = bars.loc[bars.date < day] if len(bars) else bars
                spot_row = bars.loc[bars.date == day] if len(bars) else bars
                spot = float(spot_row.close.iloc[0]) if len(spot_row) else np.nan
                if not np.isfinite(spot) or spot <= 0:
                    skipped.append(dict(session=day, symbol=symbol, reason="missing_underlying_close"))
                    continue
                try:
                    estimate = realized_volatility(prior, config.baseline_estimator, config.history_window)
                except ValueError as exc:
                    skipped.append(dict(session=day, symbol=symbol, reason=f"baseline_unavailable: {exc}"))
                    continue
                source = f"dolt_prior_{config.history_window}_session_{config.baseline_estimator}"
                assumptions[symbol] = dict(baseline_sigma=estimate.sigma, baseline_source=source,
                                           history_end=str(prior.date.max()), r=config.rate,
                                           q=config.dividend_yields[symbol])
                rows = quotes.copy()
                expiry_compact = pd.to_datetime(rows.expiration).dt.strftime("%y%m%d")
                letters = rows.option_type.str.upper().str[0]
                pennies = (rows.strike*1000).round().astype(int).astype(str).str.zfill(8)
                rows["contractSymbol"] = symbol+expiry_compact+letters+pennies
                rows = rows.assign(as_of=as_of, spot=spot, spot_timestamp=as_of, bid_timestamp=as_of,
                                   ask_timestamp=as_of, spot_source="dolt_underlying_close",
                                   lastTradeDate=None, volume=np.nan, openInterest=np.nan,
                                   impliedVolatility=rows.iv if "iv" in rows else np.nan,
                                   r=config.rate, q=config.dividend_yields[symbol],
                                   baseline_sigma=estimate.sigma, baseline_source=source,
                                   exercise_style="american", data_kind="market", provider="dolt_eod",
                                   feed="historical_eod", contract_size=100, expiry_hour=16)
                frames.append(rows.drop(columns=[c for c in ("date", "iv") if c in rows]))
        raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        metadata = dict(data_kind="market", provider="dolt_eod", feed="historical_eod", session=day,
                        assumptions=clean_json(assumptions), failures=skipped, config=config.public_dict(),
                        acquisition_started=pd.Timestamp.now(tz="UTC").isoformat(),
                        acquisition_finished=pd.Timestamp.now(tz="UTC").isoformat(),
                        quote_timestamp_available=False,
                        notes=["Historical end-of-day archive. Every quote timestamp is the session close by construction.",
                               "Bid/ask synchrony within the closing snapshot is assumed, not verified: daily_eod tier only.",
                               "The source dataset publishes no volume or open interest; liquidity screens rely on spreads."])
        yield day, raw, metadata


def import_eod(chain_path, underlying_path, config, root, max_sessions=None,
               chain_columns=None, underlying_columns=None):
    """Write one immutable snapshot per session and ingest it; re-imports deduplicate."""
    if getattr(config, "training_tier", "strict") != "daily_eod":
        raise ValueError("import-eod requires a dolt_eod config (training_tier daily_eod)")
    chain = load_chain_csv(chain_path, chain_columns)
    underlying = load_underlying_csv(underlying_path, underlying_columns)
    root = Path(root)
    store = ObservationStore(root)
    summary = dict(sessions_imported=0, sessions_skipped=0, inserted_rows=0, training_rows=0,
                   duplicate_sessions=0, skips=[])
    for count, (day, raw, metadata) in enumerate(build_session_snapshots(chain, underlying, config)):
        if max_sessions is not None and count >= max_sessions:
            break
        summary["skips"].extend(metadata["failures"])
        if raw.empty:
            summary["sessions_skipped"] += 1
            continue
        folder = root/"snapshots"/day/("eod_import_"+day.replace("-", ""))
        if not (folder/"metadata.json").exists():
            write_snapshot(raw, folder, metadata)
        result = store.ingest(folder, config)
        if result["status"] == "duplicate_snapshot":
            summary["duplicate_sessions"] += 1
            continue
        summary["sessions_imported"] += 1
        summary["inserted_rows"] += result["inserted_rows"]
        summary["training_rows"] += result["training_rows"]
    return summary
