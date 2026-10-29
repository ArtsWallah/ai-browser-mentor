import sys
import time
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
    Avoids redundant writes when tests did not modify the registry.
    """
    registry_path = BACKEND_DIR / "data" / "pattern_registry.json"
    original_content = None
    if registry_path.is_file():
        original_content = registry_path.read_text(encoding="utf-8")

    yield

    if original_content is not None:
        needs_restore = False
        if not registry_path.is_file():
            needs_restore = True
        else:
            try:
                current_content = registry_path.read_text(encoding="utf-8")
                needs_restore = (current_content != original_content)
            except Exception:
                needs_restore = True

        if needs_restore:
            registry_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                registry_path.write_text(original_content, encoding="utf-8")
            except Exception as first_exc:
                time.sleep(0.05)
                try:
                    registry_path.write_text(original_content, encoding="utf-8")
                except Exception as second_exc:
                    raise RuntimeError(
                        f"Failed to restore pattern registry at {registry_path} after retry: {second_exc}"
                    ) from first_exc

