import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Keep QSettings written by UI tests out of the user's real configuration.
_cfg = tempfile.mkdtemp(prefix="quirewright-test-config-")
os.environ["XDG_CONFIG_HOME"] = _cfg
os.environ["XDG_DATA_HOME"] = _cfg
