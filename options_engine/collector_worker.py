"""One bounded acquisition process. Parent enforces a hard wall-clock deadline."""
from pathlib import Path
import sys
from .data import write_snapshot
from .live_config import LiveConfig
from .live_utils import atomic_json
from .providers import acquire, ProviderError


def main():
    config, root = LiveConfig.load(sys.argv[1])
    target = Path(sys.argv[2])
    try:
        raw, metadata, history = acquire(config, root/"cache")
        if raw.empty:
            atomic_json(target.with_suffix(".failure.json"), metadata)
            return 2
        write_snapshot(raw, target, metadata, history)
        return 0
    except (ProviderError, ValueError, KeyError, OSError) as exc:
        atomic_json(target.with_suffix(".failure.json"),
                    dict(error=str(exc), retry_after_seconds=getattr(exc, "retry_after", 0), provider=config.provider))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
