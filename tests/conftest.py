import os
import sys
from pathlib import Path

os.environ["KIRANA_NO_AUTOAPP"] = "1"  # don't build the module-level app (it would open kirana.db)
os.environ.pop("SARVAM_API_KEY", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from server.ledger import Ledger  # noqa: E402


@pytest.fixture
def ledger():
    L = Ledger(":memory:", shop_name="Test Kirana")
    L.seed_demo()
    return L
