"""Explicit collector settings. Credentials are environment variables, never JSON.

Rate and dividend inputs take two forms. The flat v1 fields `rate: 0.04` and
`dividend_yields: {...}` stay valid and mean constant mode. The structured
forms are `rate: {"mode": "constant", "value": 0.04}` or
`{"mode": "series", "path": ..., "alignment": "strictly_prior"}` and
`dividend: {"mode": "constant", "yields": {...}}` or
`{"mode": "series", "path": ..., "bars": ..., "splits": ...}`. Series mode is
for evaluation (observation sets, walk-forward, export); imports and live
collection need constants and refuse series-mode configs.
"""
from dataclasses import asdict, dataclass, field
from pathlib import Path
import json
import math
import re
from .volatility import ESTIMATORS


@dataclass(frozen=True)
class LiveConfig:
    provider: str = "yahoo"
    tickers: tuple = ("SPY", "QQQ", "AAPL")
    rate: float | dict = .04
    dividend_yields: dict = field(default_factory=lambda: {"SPY": .01, "QQQ": .005, "AAPL": .005})
    dividend: dict | None = None
    volatility: float | None = None
    baseline_estimator: str = "close_to_close"
    training_tier: str = "strict"
    data_root: str = "../data/live"
    interval_seconds: int = 900
    expirations: int = 4
    history_window: int = 60
    request_timeout_seconds: int = 15
    cycle_timeout_seconds: int = 180
    max_backoff_seconds: int = 7200
    max_quote_age_seconds: int = 180
    max_spot_age_seconds: int = 120
    max_timestamp_skew_seconds: int = 120
    min_open_interest: int = 25
    max_relative_spread: float = .25
    min_days: float = 2.0
    max_days: float = 365.0
    min_training_sessions: int = 12
    min_training_rows: int = 300
    training_lookback_sessions: int = 60
    max_rows_per_symbol_session: int = 500
    min_free_disk_mb: int = 500
    min_split_rows: int = 50
    retrain_every_sessions: int = 2
    promotion_min_improvement: float = .02
    auto_train: bool = True
    assumptions_note: str = "Illustrative constant rate/yield inputs. Replace for your research observation period."

    def __post_init__(self):
        if self.provider not in ("yahoo", "tradier", "dolt_eod"):
            raise ValueError("provider must be yahoo, tradier, or dolt_eod")
        if self.training_tier not in ("strict", "daily_eod"):
            raise ValueError("training_tier must be strict or daily_eod")
        if (self.provider == "dolt_eod") != (self.training_tier == "daily_eod"):
            raise ValueError("The dolt_eod provider and the daily_eod training tier must be used together; tiers are never mixed in one data root")
        if self.provider == "dolt_eod" and self.min_open_interest > 0:
            raise ValueError("The dolt_eod dataset publishes no open interest; set min_open_interest to 0 for the daily_eod tier")
        object.__setattr__(self, "tickers", tuple(dict.fromkeys(self.tickers)))
        if not self.tickers or len(self.tickers) > 20:
            raise ValueError("Configure between 1 and 20 symbols")
        rate_spec = _rate_spec(self.rate)
        object.__setattr__(self, "rate", rate_spec["value"] if rate_spec["mode"] == "constant" else rate_spec)
        dividend_spec = _dividend_spec(self.dividend, self.dividend_yields)
        if dividend_spec["mode"] == "constant":
            object.__setattr__(self, "dividend_yields", dict(dividend_spec["yields"]))
            object.__setattr__(self, "dividend", None)
        else:
            object.__setattr__(self, "dividend_yields", {})
            object.__setattr__(self, "dividend", dividend_spec)
        for symbol in self.tickers:
            if not re.fullmatch(r"[A-Z][A-Z0-9.]{0,9}", symbol):
                raise ValueError("Live collection supports US stock/ETF symbols only")
            if dividend_spec["mode"] == "constant" and (symbol not in self.dividend_yields or not math.isfinite(self.dividend_yields[symbol])):
                raise ValueError(f"Explicit dividend yield required for {symbol}")
        if self.volatility is not None and (not math.isfinite(self.volatility) or self.volatility <= 0):
            raise ValueError("volatility must be positive or null for historical estimation")
        if self.baseline_estimator not in ESTIMATORS:
            raise ValueError(f"baseline_estimator must be one of {ESTIMATORS}")
        minimums = dict(interval_seconds=60, expirations=1, history_window=5, request_timeout_seconds=1,
                        cycle_timeout_seconds=5, max_backoff_seconds=60, max_quote_age_seconds=1,
                        max_spot_age_seconds=1, max_timestamp_skew_seconds=1, min_open_interest=0,
                        min_training_sessions=12, min_training_rows=50, min_split_rows=10,
                        retrain_every_sessions=1, training_lookback_sessions=12,
                        max_rows_per_symbol_session=10, min_free_disk_mb=100)
        for key, minimum in minimums.items():
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{key} must be an integer >= {minimum}")
        if self.expirations > 12 or self.max_backoff_seconds < self.interval_seconds:
            raise ValueError("expirations must be <= 12 and max_backoff_seconds >= interval_seconds")
        if self.training_lookback_sessions < self.min_training_sessions:
            raise ValueError("Training lookback cannot be shorter than minimum training history")
        if not all(math.isfinite(x) for x in (self.min_days, self.max_days, self.max_relative_spread, self.promotion_min_improvement)):
            raise ValueError("Filter and promotion settings must be finite")
        if not 0 < self.min_days < self.max_days or not 0 < self.max_relative_spread <= 1:
            raise ValueError("Invalid maturity or spread settings")
        if not 0 <= self.promotion_min_improvement < 1 or not isinstance(self.auto_train, bool):
            raise ValueError("Invalid training settings")

    @classmethod
    def load(cls, path):
        path = Path(path).resolve()
        raw = json.loads(path.read_text())
        if extra := set(raw)-set(cls.__dataclass_fields__):
            raise ValueError(f"Unknown config keys (credentials belong in the environment): {sorted(extra)}")
        if "dividend" in raw and "dividend_yields" in raw:
            raise ValueError("Give either the flat dividend_yields or a dividend block, not both")
        config = cls(**raw)
        object.__setattr__(config, "base_dir", str(path.parent))   # series paths resolve like data_root
        root = Path(config.data_root).expanduser()
        if not root.is_absolute():
            root = path.parent/root
        return config, root.resolve()

    def public_dict(self):
        public = asdict(self)
        if public["dividend"] is None:
            del public["dividend"]   # constant mode keeps the v1 shape
        return public

    @property
    def rate_spec(self):
        return _rate_spec(self.rate)

    @property
    def dividend_spec(self):
        return _dividend_spec(self.dividend, self.dividend_yields)

    @property
    def constant_rate(self):
        """The v1-style constant; imports and live collection have no dated inputs."""
        if self.rate_spec["mode"] != "constant":
            raise ValueError("This config uses a rate series; imports and live collection need a constant rate")
        return float(self.rate)

    @property
    def constant_dividend_yields(self):
        if self.dividend_spec["mode"] != "constant":
            raise ValueError("This config uses a dividend series; imports and live collection need constant yields")
        return dict(self.dividend_yields)


def _rate_spec(value):
    if isinstance(value, dict):
        mode = value.get("mode")
        if mode == "constant":
            if not isinstance(value.get("value"), (int, float)) or isinstance(value["value"], bool) or not math.isfinite(value["value"]):
                raise ValueError("Constant rate needs a finite numeric value")
            if extra := set(value)-{"mode", "value"}:
                raise ValueError(f"Unknown constant rate keys {sorted(extra)}")
            return dict(mode="constant", value=float(value["value"]))
        if mode == "series":
            if not isinstance(value.get("path"), str) or not value["path"]:
                raise ValueError("Series rate needs a path")
            if value.get("alignment", "strictly_prior") != "strictly_prior":
                raise ValueError("Only strictly_prior rate alignment is supported")
            if value.get("units", "percent") not in ("percent", "decimal"):
                raise ValueError("Rate series units must be percent or decimal")
            spec = dict(mode="series", path=value["path"], alignment="strictly_prior", units=value.get("units", "percent"),
                        stale_days=value.get("stale_days", 10))
            if isinstance(spec["stale_days"], bool) or not isinstance(spec["stale_days"], int) or spec["stale_days"] < 1:
                raise ValueError("stale_days must be a positive integer")
            if value.get("column"):
                spec["column"] = str(value["column"])
            if extra := set(value)-{"mode", "path", "alignment", "units", "column", "stale_days"}:
                raise ValueError(f"Unknown rate series keys {sorted(extra)}")
            return spec
        raise ValueError("rate mode must be constant or series")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("rate must be finite")
    return dict(mode="constant", value=float(value))


def _dividend_spec(dividend, dividend_yields):
    if dividend is None:
        if not isinstance(dividend_yields, dict) or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                                                         for v in dividend_yields.values()):
            raise ValueError("dividend_yields must map symbols to finite numbers")
        return dict(mode="constant", yields={k: float(v) for k, v in dividend_yields.items()})
    if not isinstance(dividend, dict):
        raise ValueError("dividend must be an object with a mode")
    mode = dividend.get("mode")
    if mode == "constant":
        yields = dividend.get("yields")
        if not isinstance(yields, dict) or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in yields.values()):
            raise ValueError("Constant dividend mode needs a yields mapping of finite numbers")
        if extra := set(dividend)-{"mode", "yields"}:
            raise ValueError(f"Unknown constant dividend keys {sorted(extra)}")
        return dict(mode="constant", yields={k: float(v) for k, v in yields.items()})
    if mode == "series":
        for key in ("path", "bars"):
            if not isinstance(dividend.get(key), str) or not dividend[key]:
                raise ValueError(f"Series dividend mode needs a {key}")
        spec = dict(mode="series", path=dividend["path"], bars=dividend["bars"], splits=dividend.get("splits"),
                    window_days=dividend.get("window_days", 365), stale_days=dividend.get("stale_days", 100),
                    history_start=dividend.get("history_start"), history_end=dividend.get("history_end"),
                    max_bar_gap_days=dividend.get("max_bar_gap_days", 10))
        for key in ("history_start", "history_end"):
            if spec[key] is not None and not isinstance(spec[key], str):
                raise ValueError(f"{key} must be an ISO date string")
        for key in ("window_days", "stale_days", "max_bar_gap_days"):
            if isinstance(spec[key], bool) or not isinstance(spec[key], int) or spec[key] < 1:
                raise ValueError(f"{key} must be a positive integer")
        if extra := set(dividend)-{"mode", "path", "bars", "splits", "window_days", "stale_days", "history_start", "history_end", "max_bar_gap_days"}:
            raise ValueError(f"Unknown dividend series keys {sorted(extra)}")
        return spec
    raise ValueError("dividend mode must be constant or series")
