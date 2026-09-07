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
    app.sidebar.selectbox[0].set_value("put").run()
    assert not app.exception
    assert float(next(x for x in app.metric if x.label=="Delta").value)<0
    app.sidebar.number_input[2].set_value(0.0).run()
    assert not app.exception
    assert next(x for x in app.metric if x.label=="Call price").value=="0.000000"
