"""Source adapter framework for OncoGraph."""

from . import bindingdb as _bindingdb  # noqa: F401
from . import chembl as _chembl  # noqa: F401
from . import civic as _civic  # noqa: F401
from . import clinicaltrials as _clinicaltrials  # noqa: F401
from . import depmap as _depmap  # noqa: F401
from . import dgidb as _dgidb  # noqa: F401
from . import drug_response as _drug_response  # noqa: F401
from . import drugcentral as _drugcentral  # noqa: F401
from . import drugmechdb as _drugmechdb  # noqa: F401
from . import europe_pmc as _europe_pmc  # noqa: F401
from . import gene_ontology as _gene_ontology  # noqa: F401
from . import gtex as _gtex  # noqa: F401
from . import gtopdb as _gtopdb  # noqa: F401
from . import hgnc as _hgnc  # noqa: F401
from . import ligand_receptor as _ligand_receptor  # noqa: F401
from . import oncokb as _oncokb  # noqa: F401
from . import open_targets as _open_targets  # noqa: F401
from . import open_targets_indications as _open_targets_indications  # noqa: F401
from . import reactome as _reactome  # noqa: F401
from . import signor as _signor  # noqa: F401
from . import trrust as _trrust  # noqa: F401
from .base import SourceAdapter
from .registry import registry

__all__ = ["SourceAdapter", "registry"]
