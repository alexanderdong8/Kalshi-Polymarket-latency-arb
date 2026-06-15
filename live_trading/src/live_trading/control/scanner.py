"""Compatibility import for the scanner's original control-plane location."""

from ..scanner.service import ScannerService

MarketScanner = ScannerService

__all__ = ["MarketScanner", "ScannerService"]
