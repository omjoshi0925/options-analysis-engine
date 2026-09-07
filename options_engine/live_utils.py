"""Atomic JSON, a process lock, and US equity regular-session scheduling."""
from contextlib import contextmanager
from pathlib import Path
import json
import os
import tempfile
import numpy as np
import pandas as pd
from .data import utc_timestamp


def clean_json(value):
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean_json(item) for item in value]
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return clean_json(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, (pd.Timestamp, Path)):
        return str(value)
    return value


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="."+path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(clean_json(value), stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextmanager
def process_lock(path):
    import fcntl  # Supported service platforms: macOS and Linux.
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"Another process holds {path.name}") from exc
        try:
            stream.seek(0)
            stream.truncate()
            stream.write(str(os.getpid()))
            stream.flush()
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def session_window(now):
    import exchange_calendars as xc
    now = utc_timestamp(now)
    calendar = xc.get_calendar("XNYS")
    day = now.tz_convert("America/New_York").date().isoformat()
    session = calendar.date_to_session(day, direction="next")
    opens, closes = calendar.session_open(session), calendar.session_close(session)
    if now >= closes:
        session = calendar.next_session(session)
        opens, closes = calendar.session_open(session), calendar.session_close(session)
    # First five minutes are excluded to allow quote updates after the opening auction.
    start = opens+pd.Timedelta(minutes=5)
    return dict(is_open=bool(start <= now < closes), session=str(session.date()),
                opens=start.isoformat(), closes=closes.isoformat(), next_open=start.isoformat())
