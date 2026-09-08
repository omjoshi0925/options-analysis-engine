"""Streamlit entry point; all calculations use the same tested package as the CLI."""
import io
import pandas as pd
import matplotlib.pyplot as plt
from options_engine import BlackScholesEngine, greek_error_study


# Compatibility helpers for the version 2 API.
def _kind(value):
    if value not in ("c", "p"):
        raise ValueError("type must be c or p")
    return "call" if value == "c" else "put"


def blackScholes(S, K, r, T, sigma, type="c", q=0.0):
    return BlackScholesEngine(S, K, T, r, sigma, q).price(_kind(type))


def optionDelta(S, K, r, T, sigma, type="c", q=0.0):
    return BlackScholesEngine(S, K, T, r, sigma, q).analytical_greeks(_kind(type), "market")["Delta"]


def optionGamma(S, K, r, T, sigma, q=0.0):
    return BlackScholesEngine(S, K, T, r, sigma, q).analytical_greeks(units="market")["Gamma"]


def optionTheta(S, K, r, T, sigma, type="c", q=0.0):
    return BlackScholesEngine(S, K, T, r, sigma, q).analytical_greeks(_kind(type), "market")["Theta"]


def optionVega(S, K, r, T, sigma, q=0.0):
    return BlackScholesEngine(S, K, T, r, sigma, q).analytical_greeks(units="market")["Vega"]


def optionRho(S, K, r, T, sigma, type="c", q=0.0):
    return BlackScholesEngine(S, K, T, r, sigma, q).analytical_greeks(_kind(type), "market")["Rho"]


def main():
    import streamlit as st
    from options_engine import ESTIMATORS, PRESETS, binomial_analysis, binomial_greeks, monte_carlo_price, preset
    from options_engine.plots import sensitivity_figure, numerical_error_figure, market_figure, smile_figure, strategy_figure
    from options_engine.analysis import analyze_options, grouped_metrics, implied_forward_diagnostics
    from options_engine.data import FilterConfig, fetch_options
    from options_engine.demo import synthetic_snapshot
    st.set_page_config(page_title="Options Analysis Engine", layout="wide")
    st.title("Options Analysis Engine")
    st.caption("European Black-Scholes-Merton pricing, numerical derivatives, and reproducible quote diagnostics")
    st.sidebar.header("Pricing inputs")
    S = st.sidebar.number_input("Underlying price S", min_value=.01, value=100.0, step=1.0)
    K = st.sidebar.number_input("Strike K", min_value=.01, value=100.0, step=1.0)
    days = st.sidebar.number_input("Calendar days to expiry", min_value=0.0, value=30.0, step=1.0)
    r = st.sidebar.number_input("Risk-free rate (annual decimal)", min_value=-.5, max_value=1.0, value=.04, step=.005, format="%.4f")
    sigma = st.sidebar.number_input("Volatility (annual decimal)", min_value=0.0, max_value=5.0, value=.20, step=.01)
    q = st.sidebar.number_input("Continuous dividend yield (decimal)", min_value=-.5, max_value=1.0, value=.01, step=.005, format="%.4f")
    kind = st.sidebar.selectbox("Option type", ["call", "put"])
    st.sidebar.caption("0.20 = 20%. Prices and Greeks are per share, not per option contract.")
    model = BlackScholesEngine(S, K, days/365, r, sigma, q)
    calculator, verification, market, strategies, operations = st.tabs(
        ["Prices & Greeks", "Numerical verification", "Market analysis", "Strategies", "Collection & training"])

    def show(fig):
        st.pyplot(fig)
        plt.close(fig)

    with calculator:
        columns = st.columns(3)
        columns[0].metric("Call price", f"{model.price('call'):.6f}")
        columns[1].metric("Put price", f"{model.price('put'):.6f}")
        columns[2].metric("Put-call parity residual", f"{model.verify_parity():.2e}")
        st.dataframe(pd.DataFrame([dict(d1=model.d1, d2=model.d2, dividend_adjusted_spot=model.adjusted_spot,
                                       discounted_strike=model.discounted_strike)]), hide_index=True)
        if days > 0 and sigma > 0:
            greeks = model.analytical_greeks(kind, "market")
            labels = ["Delta", "Gamma", "Theta / day", "Vega / 1 vol point", "Rho / 1 rate point"]
            for col, label, value in zip(st.columns(5), labels, greeks.values(), strict=True):
                col.metric(label, f"{value:.6f}")
            parameter = st.selectbox("Vary the input", ["S", "K", "T", "sigma"])
            st.caption("Sensitivity plots use raw derivative units; time is in years.")
            show(sensitivity_figure(model, parameter))
            with st.expander("American exercise on a CRR binomial tree"):
                steps = int(st.slider("Tree steps", min_value=50, max_value=1000, value=200, step=50))
                try:
                    tree = binomial_analysis(S, K, days/365, r, sigma, q, kind, steps)
                    cells = st.columns(4)
                    cells[0].metric("American price", f"{tree.price:.6f}")
                    cells[1].metric("European tree price", f"{tree.european_tree_price:.6f}")
                    cells[2].metric("Early-exercise premium", f"{tree.early_exercise_premium:.6f}")
                    cells[3].metric("Tree minus closed form", f"{tree.discretization_error:+.2e}")
                    st.dataframe(pd.DataFrame([{"source": "closed-form European", **greeks},
                                               {"source": f"tree American ({steps} steps)",
                                                **binomial_greeks(S, K, days/365, r, sigma, q, kind, steps, True, "market")}]), hide_index=True)
                    st.caption("Both exercise styles are priced on one lattice with the same inputs, so the premium is American minus "
                               "European tree value and the discretization error cancels. US equity and ETF options are American.")
                except ValueError as exc:
                    st.info(str(exc))
        else:
            st.info("The exact limiting price is shown. Greek diagnostics require positive time and volatility.")
    with verification:
        if days > 0 and sigma > 0:
            study = pd.concat([greek_error_study(model, choice) for choice in ("call", "put")], ignore_index=True)
            show(numerical_error_figure(study))
            st.caption("Theta = -dV/dT. All comparisons use annual raw Greeks. Very small h can increase cancellation error, especially in Gamma.")
            st.dataframe(study, hide_index=True)
            st.download_button("Download derivative study", study.to_csv(index=False), "greek_step_study.csv", "text/csv")
            st.subheader("Monte Carlo check")
            paths = int(st.number_input("Simulated paths (antithetic pairs, fixed seed)", min_value=2000, max_value=2_000_000, value=100_000, step=50_000))
            simulation = monte_carlo_price(S, K, days/365, r, sigma, q, kind, paths=paths-paths % 2)
            cells = st.columns(4)
            cells[0].metric("Monte Carlo price", f"{simulation.price:.6f}")
            cells[1].metric("Standard error", f"{simulation.standard_error:.2e}")
            cells[2].metric("Closed form", f"{simulation.bsm_price:.6f}")
            cells[3].metric("z-score", f"{simulation.z_score:+.2f}")
            st.caption("Terminal-value simulation under the same lognormal dynamics. |z| above about 3 would indicate disagreement beyond sampling error.")
        else:
            st.info("Set positive time and volatility to verify the derivatives.")
    with market:
        st.write("Compare bid-ask midpoints with an independent constant-volatility baseline. Stock and ETF IVs are European-equivalent estimates when the contract permits American exercise.")
        source = st.radio("Data source", ["Synthetic demonstration", "Upload raw snapshot CSV", "Fetch Yahoo Finance"], horizontal=True)
        raw, meta = None, {}
        if source == "Synthetic demonstration":
            raw, meta = synthetic_snapshot()
            st.info("Synthetic data: useful for checking the software; these are not observed market results.")
        elif source == "Upload raw snapshot CSV":
            st.caption("Upload raw_options.csv from the CLI snapshot. Use the CLI analyze command to verify its metadata checksums.")
            upload = st.file_uploader("Raw snapshot", type="csv")
            if upload is not None:
                try:
                    raw = pd.read_csv(io.BytesIO(upload.getvalue()))
                    meta = {"data_kind": "synthetic" if "data_kind" in raw and raw.data_kind.eq("synthetic").all() else "uploaded"}
                except (ValueError, pd.errors.ParserError) as exc:
                    st.error(str(exc))
        else:
            with st.form("acquisition"):
                tickers = st.text_input("Symbols, separated by spaces", "SPY QQQ AAPL")
                yield_text = st.text_input("Explicit scenario dividend yields (decimal)", "SPY=0.01 QQQ=0.005 AAPL=0.005")
                st.caption("Rates and dividend yields are assumptions to edit, not current estimates. The sidebar rate applies to all symbols; volatility uses prior 60-session realized returns.")
                count = st.number_input("Expirations per asset", min_value=1, max_value=12, value=3)
                estimator = st.selectbox("Baseline volatility estimator", ESTIMATORS,
                                         help="Close-to-close uses adjusted closes; the range estimators use unadjusted OHLC bars.")
                submitted = st.form_submit_button("Fetch a new snapshot")
            if submitted:
                try:
                    yields = {key.upper(): float(value) for key, value in (part.split("=", 1) for part in yield_text.split())}
                    raw, meta, _ = fetch_options(tickers.split(), r, yields, int(count), estimator=estimator)
                    st.session_state["last_snapshot"] = (raw, meta)
                except (ValueError, ImportError) as exc:
                    st.error(str(exc))
            if "last_snapshot" in st.session_state:
                raw, meta = st.session_state["last_snapshot"]
            if meta.get("failures"):
                st.warning("Some data could not be acquired. Acquisition details follow.")
                st.json(meta["failures"])
        if raw is not None and not raw.empty:
            try:
                results, audit = analyze_options(raw, FilterConfig())
                st.write(f"Accepted {len(results)} of {len(raw)} contracts.")
                st.download_button("Download raw quotes", raw.to_csv(index=False), "raw_options.csv", "text/csv")
                st.download_button("Download quote audit", audit.to_csv(index=False), "filter_audit.csv", "text/csv")
                if not results.empty:
                    st.dataframe(grouped_metrics(results), hide_index=True)
                    forwards = implied_forward_diagnostics(results)
                    fitted = forwards.loc[forwards.status == "ok", ["symbol", "expiration", "n_pairs", "implied_rate", "r", "implied_yield", "q",
                                                                    "implied_forward", "fit_rmse", "r_squared"]]
                    st.write("Implied forward, rate, and yield from put-call parity. Compare with the assumed r and q; American early exercise biases the fit.")
                    st.dataframe(fitted if not fitted.empty else forwards[["symbol", "expiration", "n_pairs", "status"]], hide_index=True)
                    st.write("Early-exercise premium from a 200-step CRR tree with the same independent volatility, by option type.")
                    st.dataframe(results.groupby("option_type").agg(n=("early_exercise_premium", "size"), mean_premium=("early_exercise_premium", "mean"),
                                                                   max_premium=("early_exercise_premium", "max"), european_mae=("absolute_error", "mean"),
                                                                   american_mae=("american_error", lambda x: x.abs().mean())).reset_index(), hide_index=True)
                    show(market_figure(results, meta.get("data_kind") == "synthetic"))
                    symbol = st.selectbox("Smile asset", sorted(results.symbol.unique()))
                    show(smile_figure(results, symbol, meta.get("data_kind") == "synthetic"))
                    st.download_button("Download analysis", results.to_csv(index=False), "analyzed_options.csv", "text/csv")
                    st.dataframe(results, hide_index=True)
            except (ValueError, KeyError) as exc:
                st.error(str(exc))
        elif raw is not None:
            st.warning("No quotes acquired. Use the saved acquisition diagnostics to investigate.")
    with strategies:
        st.write("Multi-leg positions on the sidebar's underlying, expiry, rate, volatility, and yield. "
                 "Premiums are closed-form marks per share, not executable quotes; no contract multiplier is applied.")
        names = sorted(PRESETS)
        chosen = st.selectbox("Preset", names, index=names.index("long_straddle"))
        cells = st.columns(2)
        strike = cells[0].number_input("Central strike", min_value=.01, value=float(K), step=1.0)
        width = cells[1].number_input("Wing width", min_value=.01, value=float(round(.05*S, 2)), step=.5)
        try:
            position = preset(chosen, S, days/365, r, sigma, q, strike, width)
            structure = position.summary()
            cells = st.columns(4)
            cells[0].metric("Net premium / share", f"{structure['net_premium']:+.4f}")
            cells[1].metric("Max profit", "unbounded" if structure["unbounded_profit"] else f"{structure['max_profit']:.4f}")
            cells[2].metric("Max loss", "unbounded" if structure["unbounded_loss"] else f"{structure['max_loss']:.4f}")
            cells[3].metric("Breakevens", ", ".join(f"{x:.2f}" for x in structure["breakevens"]) or "none")
            show(strategy_figure(position, S, days/365, r, sigma, q))
            st.dataframe(pd.DataFrame(structure["legs"]), hide_index=True)
            if days > 0 and sigma > 0:
                st.write("Position Greeks in market units: Theta per calendar day, Vega and Rho per point.")
                st.dataframe(pd.DataFrame([position.greeks(S, days/365, r, sigma, q, "market")]), hide_index=True)
            else:
                st.info("Greeks need positive time and volatility; the expiry structure above is exact.")
        except ValueError as exc:
            st.error(str(exc))
    with operations:
        from pathlib import Path
        from options_engine.collector import live_status
        from options_engine.live_config import LiveConfig
        from options_engine.learning import train
        st.subheader("Continuous collection and model progress")
        config_path = st.text_input("Collector configuration", "config/collector.json")
        st.caption("The collector runs as a separate process so closing this dashboard does not stop collection. Start it with the commands in docs/CONTINUOUS_COLLECTION.md.")
        if Path(config_path).is_file():
            st.button("Refresh collection status")
            try:
                health = live_status(config_path)
                database = health.get("database", {})
                cols = st.columns(3)
                cols[0].metric("Distinct observations", database.get("observations", 0))
                cols[1].metric("Strict-quality training rows", database.get("training_rows", 0))
                cols[2].metric("Training sessions", database.get("training_sessions", 0))
                collector = health.get("collector", {})
                st.write("Collector:", collector.get("state", "not started"))
                if health.get("heartbeat_stale"):
                    st.warning("The collector heartbeat is stale. Check the service and collector.log.")
                st.write("Training:", health.get("training", {}).get("state", "collecting data"))
                active = health.get("registry", {}).get("active")
                st.write("Active model:", active["model_id"] if active else "Independent Black-Scholes baseline")
                if st.button("Evaluate a new candidate from collected data"):
                    cfg, data_root = LiveConfig.load(config_path)
                    with st.spinner("Checking data and chronological holdout..."):
                        st.json(train(data_root, cfg))
                if database.get("recent_runs"):
                    st.dataframe(pd.DataFrame(database["recent_runs"]), hide_index=True)
                if database.get("quality_exclusions"):
                    st.write("Observations excluded from training")
                    st.dataframe(pd.DataFrame(database["quality_exclusions"]), hide_index=True)
                if health.get("monitoring"):
                    monitor = health["monitoring"]
                    st.write("Latest strict-quality batch comparison")
                    st.dataframe(pd.DataFrame([{"model": "baseline", **monitor["baseline"]},
                                               {"model": "current", **monitor["current"]}]), hide_index=True)
                    if monitor.get("batch_degradation_warning"):
                        st.warning("The current model underperformed the baseline on the latest batch. Review subsequent batches before concluding there is persistent drift.")
                with st.expander("Detailed status"):
                    st.json(health)
            except (ValueError, RuntimeError, OSError, KeyError) as exc:
                st.error(str(exc))
        else:
            st.info("Create config/collector.json with the init-live command to begin. Real model training requires timestamp-verified quotes; synthetic demos never enter the training store.")
    st.caption("Options Analysis Engine · Research and model evaluation")


if __name__ == "__main__":
    main()
