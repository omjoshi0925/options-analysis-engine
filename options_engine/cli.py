import argparse
from pathlib import Path
import json
import sys
from .core import BlackScholesEngine
from .data import FilterConfig, fetch_options, read_snapshot, write_snapshot
from .analysis import analyze_options, write_report
from .demo import synthetic_snapshot
from .volatility import ESTIMATORS
from .strategies import PRESETS


def parser():
    p = argparse.ArgumentParser(description="European BSM engine and reproducible quote analysis")
    commands = p.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Run a labeled synthetic demonstration, offline")
    demo.add_argument("--output", default="results/demo")
    fetch = commands.add_parser("fetch", help="Capture real Yahoo chains and raw history")
    fetch.add_argument("--tickers", nargs="+", required=True)
    fetch.add_argument("--rate", type=float, required=True, help="Continuously compounded annual decimal scenario rate")
    fetch.add_argument("--dividend-yields", nargs="+", required=True, metavar="SYMBOL=DECIMAL")
    fetch.add_argument("--expirations", type=int, default=3)
    fetch.add_argument("--volatility", type=float, help="Fixed independent baseline; otherwise prior 60-session realized vol")
    fetch.add_argument("--history-window", type=int, default=60)
    fetch.add_argument("--estimator", choices=ESTIMATORS, default="close_to_close",
                       help="Realized-volatility estimator for the baseline; range estimators use unadjusted OHLC")
    fetch.add_argument("--expiry-hour", type=int, choices=range(24), default=16)
    fetch.add_argument("--output", required=True, help="New snapshot directory; never overwritten")
    replay = commands.add_parser("analyze", help="Replay a saved, checksum-verified snapshot")
    replay.add_argument("--snapshot", required=True)
    replay.add_argument("--output", required=True)
    for command in (demo, replay):
        command.add_argument("--min-volume", type=int, default=0)
        command.add_argument("--min-open-interest", type=int, default=10)
        command.add_argument("--max-relative-spread", type=float, default=.5)
        command.add_argument("--min-mid", type=float, default=.10, help="Minimum midpoint included in percentage metrics")
        command.add_argument("--max-last-trade-age-days", type=float)
        command.add_argument("--no-plots", action="store_true")
    price = commands.add_parser("price", help="Price one option: closed form, Greeks, American tree, optional Monte Carlo check")
    iv = commands.add_parser("iv", help="Invert implied volatility from a price with full solver diagnostics")
    strategy = commands.add_parser("strategy", help="Summarize a preset multi-leg strategy: breakevens, bounds, mark, Greeks")
    for command in (price, iv, strategy):
        command.add_argument("--S", type=float, required=True, help="Underlying price")
        command.add_argument("--r", type=float, required=True, help="Continuously compounded annual decimal rate")
        command.add_argument("--q", type=float, default=0.0, help="Continuous dividend yield (decimal)")
        horizon = command.add_mutually_exclusive_group()
        horizon.add_argument("--T", type=float, help="Time to expiry in years")
        horizon.add_argument("--days", type=float, help="Calendar days to expiry (ACT/365)")
    for command in (price, iv):
        command.add_argument("--K", type=float, required=True, help="Strike")
        command.add_argument("--type", choices=["call", "put"], default="call")
    price.add_argument("--sigma", type=float, required=True, help="Annual decimal volatility")
    price.add_argument("--steps", type=int, default=200, help="Binomial tree steps for the American comparison")
    price.add_argument("--paths", type=int, default=0, help="Monte Carlo paths; 0 skips the simulation")
    iv.add_argument("--price", type=float, required=True, help="Observed option price per share")
    iv.add_argument("--method", choices=["brent", "newton"], default="brent")
    strategy.add_argument("--preset", choices=sorted(PRESETS), required=True)
    strategy.add_argument("--sigma", type=float, required=True, help="Annual decimal volatility used to mark every leg")
    strategy.add_argument("--strike", type=float, help="Central strike; defaults to the spot")
    strategy.add_argument("--width", type=float, help="Wing width; defaults to 5%% of the spot")
    strategy.add_argument("--plot", help="Optional PNG path for the payoff figure")
    init = commands.add_parser("init-live", help="Write an editable continuous collection configuration")
    init.add_argument("--provider", choices=["yahoo", "tradier", "dolt_eod"], default="yahoo")
    init.add_argument("--config", default="config/collector.json")
    eod = commands.add_parser("import-eod", help="Import historical end-of-day chains (DoltHub CSV export) into the daily_eod tier")
    eod.add_argument("--config", default="config/collector.json")
    eod.add_argument("--chain-csv", required=True, help="CSV export of option_chain rows")
    eod.add_argument("--underlying-csv", required=True, help="CSV export of daily underlying OHLC bars")
    eod.add_argument("--max-sessions", type=int, help="Import at most this many sessions (for a trial run)")
    forward = commands.add_parser("walk-forward", help="Rolling-origin evaluation with Diebold-Mariano and bootstrap significance")
    forward.add_argument("--config", default="config/collector.json")
    forward.add_argument("--output", required=True, help="New report directory; never overwritten")
    forward.add_argument("--min-train-sessions", type=int, default=12)
    forward.add_argument("--gap", type=int, default=1)
    forward.add_argument("--validation-sessions", type=int, default=2)
    forward.add_argument("--window", choices=["expanding", "rolling"], default="expanding")
    forward.add_argument("--max-train-sessions", type=int)
    forward.add_argument("--lookback-sessions", type=int, default=100000, help="How much stored history to load")
    forward.add_argument("--bootstrap", type=int, default=2000)
    collect = commands.add_parser("collect", help="Run the continuous collector; Ctrl+C stops it")
    collect.add_argument("--config", default="config/collector.json")
    collect.add_argument("--once", action="store_true", help="One scheduled check, respecting market hours")
    collect.add_argument("--probe", action="store_true", help="One acquisition outside market hours; still respects persisted backoff")
    status = commands.add_parser("status", help="Show collection health and training progress")
    status.add_argument("--config", default="config/collector.json")
    fit = commands.add_parser("train", help="Fit and evaluate a volatility model on complete prior sessions")
    fit.add_argument("--config", default="config/collector.json")
    ingest = commands.add_parser("ingest", help="Add an existing checksum-verified snapshot to the observation store")
    ingest.add_argument("--config", default="config/collector.json")
    ingest.add_argument("--snapshot", required=True)
    select = commands.add_parser("select-model", help="Return to the baseline or roll back to a previously promoted model")
    select.add_argument("--config", default="config/collector.json")
    choice = select.add_mutually_exclusive_group(required=True)
    choice.add_argument("--baseline", action="store_true")
    choice.add_argument("--model-id")
    score = commands.add_parser("score-snapshot", help="Compare a later snapshot using the active model and baseline")
    score.add_argument("--config", default="config/collector.json")
    score.add_argument("--snapshot", required=True)
    score.add_argument("--output", required=True)
    return p


def years(args):
    if args.T is None and args.days is None:
        raise ValueError("Provide --T or --days")
    return float(args.T) if args.T is not None else float(args.days)/365.0


def run(args):
    if args.command in ("price", "iv", "strategy"):
        from dataclasses import asdict
        from .live_utils import clean_json
        T = years(args)
        if args.command == "price":
            from .american import binomial_analysis
            from .montecarlo import monte_carlo_price
            model = BlackScholesEngine(args.S, args.K, T, args.r, args.sigma, args.q)
            result = dict(inputs=dict(S=model.S, K=model.K, T=model.T, r=model.r, sigma=model.sigma, q=model.q, option_type=args.type),
                          call=model.price("call"), put=model.price("put"), d1=model.d1, d2=model.d2,
                          parity_residual=model.verify_parity(),
                          bounds={kind: dict(zip(("lower", "upper"), model.bounds(kind), strict=True)) for kind in ("call", "put")})
            if model.T > 0 and model.sigma > 0:
                result["greeks"] = {kind: dict(raw=model.analytical_greeks(kind), market=model.analytical_greeks(kind, "market")) for kind in ("call", "put")}
                result["american"] = dict(option_type=args.type, **asdict(binomial_analysis(model.S, model.K, model.T, model.r, model.sigma, model.q, args.type, args.steps)))
            if args.paths:
                result["monte_carlo"] = dict(option_type=args.type, **asdict(monte_carlo_price(model.S, model.K, model.T, model.r, model.sigma, model.q, args.type, paths=args.paths)))
            print(json.dumps(clean_json(result), indent=2))
            return 0
        if args.command == "iv":
            from .iv import implied_volatility
            result = implied_volatility(args.price, args.S, args.K, T, args.r, args.q, args.type, args.method)
            print(json.dumps(clean_json(dict(inputs=dict(price=args.price, S=args.S, K=args.K, T=T, r=args.r, q=args.q, option_type=args.type), **asdict(result))), indent=2))
            return 0 if result.converged else 2
        from .strategies import preset
        position = preset(args.preset, args.S, T, args.r, args.sigma, args.q, args.strike, args.width)
        summary = position.summary()
        if T > 0 and args.sigma > 0:
            summary.update(spot=args.S, current_value=position.value(args.S, T, args.r, args.sigma, args.q),
                           greeks=position.greeks(args.S, T, args.r, args.sigma, args.q, "market"))
        if args.plot:
            import matplotlib
            matplotlib.use("Agg")
            from .plots import strategy_figure
            target = Path(args.plot)
            target.parent.mkdir(parents=True, exist_ok=True)
            figure = strategy_figure(position, args.S, T, args.r, args.sigma, args.q)
            figure.savefig(target, dpi=160, bbox_inches="tight")
            summary["plot"] = str(target)
        print(json.dumps(clean_json(summary), indent=2))
        return 0
    if args.command in ("init-live", "collect", "status", "train", "ingest", "select-model", "score-snapshot", "import-eod", "walk-forward"):
        from .live_config import LiveConfig
        from .live_utils import atomic_json, process_lock
        if args.command == "init-live":
            target = Path(args.config)
            if target.exists():
                raise ValueError("Config already exists; edit it or select another filename")
            overrides = dict(training_tier="daily_eod", min_open_interest=0) if args.provider == "dolt_eod" else {}
            config = LiveConfig(provider=args.provider, **overrides)
            atomic_json(target, config.public_dict())
            print(f"Created {target}. Edit rate/yield assumptions before collection.")
            if args.provider == "yahoo":
                print("Yahoo data have unverified bid/ask timestamps and will not enter strict-quality model training.")
            elif args.provider == "tradier":
                print("Set TRADIER_TOKEN in the local environment. Production data entitlement is required.")
            else:
                print("Historical EOD tier: import with the import-eod command; the collector does not poll this provider.")
            return 0
        if args.command == "collect":
            from .collector import run_collector
            return run_collector(args.config, args.once, args.probe)
        config, root = LiveConfig.load(args.config)
        if args.command == "status":
            from .collector import live_status
            result = live_status(args.config)
        elif args.command == "train":
            from .learning import train
            result = train(root, config)
        elif args.command == "ingest":
            from .store import ObservationStore
            with process_lock(root/"collector.lock"):
                result = ObservationStore(root).ingest(args.snapshot, config)
        elif args.command == "score-snapshot":
            from .learning import score_snapshot
            result = score_snapshot(root, args.snapshot, args.output, config)
        elif args.command == "import-eod":
            from .eod_import import import_eod
            with process_lock(root/"collector.lock"):
                result = import_eod(args.chain_csv, args.underlying_csv, config, root, args.max_sessions)
        elif args.command == "walk-forward":
            from .store import ObservationStore
            from .walkforward import WalkForwardSpec, walk_forward, walk_forward_report
            frame = ObservationStore(root).training_frame(before="9999-12-31", lookback_sessions=args.lookback_sessions,
                                                          max_rows_per_symbol_session=config.max_rows_per_symbol_session)
            spec = WalkForwardSpec(min_train_sessions=args.min_train_sessions, gap=args.gap,
                                   validation_sessions=args.validation_sessions, window=args.window,
                                   max_train_sessions=args.max_train_sessions)
            result = walk_forward_report(walk_forward(frame, spec), args.output, n_boot=args.bootstrap)
        else:
            from .learning import select_model
            result = select_model(root, args.model_id)
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "fetch":
        yields = {}
        for item in args.dividend_yields:
            symbol, value = item.split("=", 1)
            yields[symbol.upper()] = float(value)
        if Path(args.output).exists():
            raise ValueError("Snapshot output exists; choose a new directory")
        raw, meta, history = fetch_options(args.tickers, args.rate, yields, args.expirations,
                                           args.volatility, args.history_window, args.expiry_hour, args.estimator)
        if raw.empty:
            failure = Path(args.output+"-failure.json")
            failure.parent.mkdir(parents=True, exist_ok=True)
            with failure.open("x") as stream:
                json.dump(meta, stream, indent=2)
            print(f"No real quotes acquired. Diagnostics: {failure}", file=sys.stderr)
            return 2
        write_snapshot(raw, args.output, meta, history)
        print(f"Saved {len(raw)} raw option quotes to {args.output}; acquisition failures: {len(meta['failures'])}")
        return 0
    config = FilterConfig(min_volume=args.min_volume, min_open_interest=args.min_open_interest,
                          max_relative_spread=args.max_relative_spread,
                          max_last_trade_age_days=args.max_last_trade_age_days)
    if args.min_mid <= 0:
        raise ValueError("--min-mid must be positive")
    output = Path(args.output)
    # Refuse stale plots from an older run; analysis outputs are immutable run folders.
    if output.exists():
        raise ValueError("Analysis output exists; choose a new run directory")
    if args.command == "demo":
        raw, meta = synthetic_snapshot()
        write_snapshot(raw, output/"snapshot", meta)
        raw, meta = read_snapshot(output/"snapshot")
    else:
        raw, meta = read_snapshot(args.snapshot)
    df, audit = analyze_options(raw, config, args.min_mid)
    write_report(df, audit, meta, output, config, args.min_mid)
    if not args.no_plots:
        import matplotlib
        matplotlib.use("Agg")
        from .plots import save_figures
        model = BlackScholesEngine(100, 100, .25, .04, .2, .01)
        save_figures(df, model, output/"plots", meta.get("data_kind") == "synthetic")
    print(f"{'SYNTHETIC DEMO' if meta.get('data_kind') == 'synthetic' else 'MARKET SNAPSHOT'}: {len(df)}/{len(audit)} accepted. Report: {output/'REPORT.md'}")
    return 0 if len(df) else 2


def main():
    args = parser().parse_args()
    try:
        return run(args)
    except (ValueError, OSError, KeyError, ImportError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
