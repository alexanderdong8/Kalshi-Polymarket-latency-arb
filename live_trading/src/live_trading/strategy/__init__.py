"""Shared multi-outcome strategy used by live, paper, and historical replay."""

from .bridge import StrategyBookBridge
from .detector import BasketEvaluation, Detector, FireEvent
from .manifest import EventManifest, ManifestError, load_event_manifest
from .models import BookSnapshot, DepthLevel, EventSpec, OutcomeSpec

__all__ = [
    "BasketEvaluation",
    "BookSnapshot",
    "DepthLevel",
    "Detector",
    "EventManifest",
    "EventSpec",
    "FireEvent",
    "ManifestError",
    "OutcomeSpec",
    "StrategyBookBridge",
    "load_event_manifest",
]
