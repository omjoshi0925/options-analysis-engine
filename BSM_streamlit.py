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
    from options_engine.plots import sensitivity_figure, numerical_error_figure, market_figure, smile_figure
    from options_engine.analysis import analyze_options, grouped_metrics
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
    calculator, verification, market, operations = st.tabs(["Prices & Greeks", "Numerical verification", "Market analysis", "Collection & training"])

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
        else:
            st.info("The exact limiting price is shown. Greek diagnostics require positive time and volatility.")
    with verification:
        if days > 0 and sigma > 0:
            study = pd.concat([greek_error_study(model, choice) for choice in ("call", "put")], ignore_index=True)
            show(numerical_error_figure(study))
            st.caption("Theta = -dV/dT. All comparisons use annual raw Greeks. Very small h can increase cancellation error, especially in Gamma.")
            st.dataframe(study, hide_index=True)
            st.download_button("Download derivative study", study.to_csv(index=False), "greek_step_study.csv", "text/csv")
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
                submitted = st.form_submit_button("Fetch a new snapshot")
            if submitted:
                try:
                    yields = {key.upper(): float(value) for key, value in (part.split("=", 1) for part in yield_text.split())}
                    raw, meta, _ = fetch_options(tickers.split(), r, yields, int(count))
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
                    show(market_figure(results, meta.get("data_kind") == "synthetic"))
                    symbol = st.selectbox("Smile asset", sorted(results.symbol.unique()))
                    show(smile_figure(results, symbol, meta.get("data_kind") == "synthetic"))
                    st.download_button("Download analysis", results.to_csv(index=False), "analyzed_options.csv", "text/csv")
                    st.dataframe(results, hide_index=True)
            except (ValueError, KeyError) as exc:
                st.error(str(exc))
        elif raw is not None:
            st.warning("No quotes acquired. Use the saved acquisition diagnostics to investigate.")
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
