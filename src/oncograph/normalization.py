from dataclasses import dataclass

from .sources.base import ExternalIdentifier

NAMESPACE_ALIASES = {
    "drugbank": "drugbank",
    "pmid": "pubmed",
    "pubmed": "pubmed",
    "nct": "clinicaltrials.gov",
    "clinicaltrials.gov": "clinicaltrials.gov",
    "hgnc": "hgnc",
    "entrez": "ncbigene",
    "ncbigene": "ncbigene",
    "mesh": "mesh",
    "doid": "doid",
    "chebi": "chebi",
}


@dataclass(frozen=True)
class NormalizedIdentifier:
    namespace: str
    value: str


def normalize_identifier(identifier: ExternalIdentifier) -> NormalizedIdentifier:
    namespace = identifier.namespace.strip().lower()
    namespace = NAMESPACE_ALIASES.get(namespace, namespace)
    value = identifier.value.strip()
    if not namespace or not value:
        raise ValueError("Identifier namespace and value are required")
    if namespace == "clinicaltrials.gov":
        value = value.upper()
    return NormalizedIdentifier(namespace=namespace, value=value)
