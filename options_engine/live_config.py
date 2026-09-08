"""Explicit collector settings. Credentials are environment variables, never JSON."""
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
    rate: float = .04
    dividend_yields: dict = field(default_factory=lambda: {"SPY": .01, "QQQ": .005, "AAPL": .005})
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
        for symbol in self.tickers:
            if not re.fullmatch(r"[A-Z][A-Z0-9.]{0,9}", symbol):
                raise ValueError("Live collection supports US stock/ETF symbols only")
            if symbol not in self.dividend_yields or not math.isfinite(self.dividend_yields[symbol]):
                raise ValueError(f"Explicit dividend yield required for {symbol}")
        if not math.isfinite(self.rate):
            raise ValueError("rate must be finite")
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
        config = cls(**raw)
        root = Path(config.data_root).expanduser()
        if not root.is_absolute():
            root = path.parent/root
        return config, root.resolve()

    def public_dict(self):
        return asdict(self)
