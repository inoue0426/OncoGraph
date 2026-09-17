"""Source adapter framework for OncoGraph."""

from .base import SourceAdapter
from .registry import registry

__all__ = ["SourceAdapter", "registry"]
