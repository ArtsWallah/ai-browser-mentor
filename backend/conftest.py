import sys
from pathlib import Path
import pytest

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture(autouse=True)
def isolate_rate_limiter_state():
    """
    Ensure rate-limiter state is deterministic and isolated between tests.
    Resets the SlowAPI in-memory storage before and after each test using
    the official supported Limiter.reset() API.
    Does not weaken production rate limits or alter application behavior outside tests.
    """
    try:
        from app.main import limiter
        limiter.reset()
    except Exception:
        pass
    yield
    try:
        from app.main import limiter
        limiter.reset()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def preserve_pattern_registry():
    """
    Ensure pattern_registry.json on disk is preserved across tests that mutate it.
    """
    registry_path = BACKEND_DIR / "data" / "pattern_registry.json"
    content = None
    if registry_path.is_file():
        content = registry_path.read_text(encoding="utf-8")
    yield
    if content is not None:
        registry_path.write_text(content, encoding="utf-8")

