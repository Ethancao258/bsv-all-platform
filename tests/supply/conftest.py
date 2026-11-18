"""Keep import-time demo files outside the checkout."""
import os
from tempfile import TemporaryDirectory

_state = TemporaryDirectory(prefix="bsv-supply-tests-")
os.environ["BSV_SUPPLY_STATE_DIR"] = _state.name
os.environ["BSV_MODE"] = "demo"
os.environ.pop("BSV_SOURCES_CONFIG", None)
