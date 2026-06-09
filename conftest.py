import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for package_root in (
    ROOT / "historical_testing",
    ROOT / "live_trading" / "src",
    ROOT / "trade_system" / "src",
    ROOT / "backtesting" / "src",
):
    value = str(package_root)
    if value not in sys.path:
        sys.path.insert(0, value)
