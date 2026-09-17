"""Source adapter framework for OncoGraph."""

from . import clinicaltrials as _clinicaltrials  # noqa: F401
from . import gene_ontology as _gene_ontology  # noqa: F401
from . import gtopdb as _gtopdb  # noqa: F401
from . import hgnc as _hgnc  # noqa: F401
from . import open_targets as _open_targets  # noqa: F401
from .base import SourceAdapter
from .registry import registry

__all__ = ["SourceAdapter", "registry"]
