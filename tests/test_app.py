from pathlib import Path
import pytest
from options_engine import BlackScholesEngine


def test_dashboard_delta_put_and_boundary_behavior():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_file(str(Path(__file__).parents[1]/"BSM_streamlit.py"),default_timeout=40).run()
    assert not app.exception
    delta=next(x for x in app.metric if x.label=="Delta")
    expected=BlackScholesEngine(100,100,30/365,.04,.2,.01).analytical_greeks()["Delta"]
    assert float(delta.value)==pytest.approx(expected,abs=1e-6)
    labels={x.label for x in app.metric}
    assert {"American price","Early-exercise premium","Monte Carlo price","Max profit","Breakevens"}<=labels
    american=float(next(x for x in app.metric if x.label=="American price").value)
    european_tree=float(next(x for x in app.metric if x.label=="European tree price").value)
    assert american>=european_tree-1e-6
    assert abs(european_tree-float(next(x for x in app.metric if x.label=="Call price").value))<0.02  # 200-step discretization
    app.sidebar.selectbox[0].set_value("put").run()
    assert not app.exception
    assert float(next(x for x in app.metric if x.label=="Delta").value)<0
    app.sidebar.number_input[2].set_value(0.0).run()
    assert not app.exception
    assert next(x for x in app.metric if x.label=="Call price").value=="0.000000"
    assert "Max profit" in {x.label for x in app.metric} and "American price" not in {x.label for x in app.metric}
