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
    "ncbi_gene": "ncbigene",
    "ncbi-gene": "ncbigene",
    "ncbi gene": "ncbigene",
    "geneid": "ncbigene",
    "ncbigene": "ncbigene",
    "mesh": "mesh",
    "doid": "doid",
    "diseaseontology": "doid",
    "chebi": "chebi",
    "mondo": "mondo",
    "efo": "efo",
    "efo_id": "efo",
    "doi": "doi",
    "pmcid": "pmcid",
    "ensembl": "ensembl",
    "ensg": "ensembl",
    "uniprot": "uniprot",
    "uniprotkb": "uniprot",
    "chembl": "chembl",
    "pubchem": "pubchem",
    "pubchem_cid": "pubchem",
    "cid": "pubchem",
    "reactome": "reactome",
    "go": "go",
    "ncit": "ncit",
    "rxcui": "rxcui",
    "rxnorm": "rxcui",
    "cellosaurus": "cellosaurus",
    "cvcl": "cellosaurus",
    "depmap": "depmap",
    "cosmic": "cosmic",
    "uberon": "uberon",
    "signor": "signor",
    "drugcentral": "drugcentral",
    "bindingdb": "bindingdb",
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
    elif namespace == "doi":
        value = value.lower()
    elif namespace in ("pmcid", "chembl", "reactome", "go", "uberon"):
        value = value.upper()
    elif namespace in ("hgnc", "ncbigene", "ensembl", "uniprot", "pubchem"):
        # These namespaces are case-insensitive in their public forms, while
        # preserving punctuation such as HGNC:1234.
        value = value.upper()
        if (
            namespace == "ncbigene" and value.startswith(("NCBIGENE:", "ENTREZ:"))
        ) or namespace == "pubchem" and value.startswith("CID:"):
            value = value.split(":", 1)[1]
    elif namespace in ("doid", "mondo", "efo"):
        # Disease ontology values are often bare numeric IDs. Preserve other
        # free-form values so unresolved diagnostics remain useful.
        prefix = f"{namespace.upper()}:"
        if value.upper().startswith(prefix):
            value = value.split(":", 1)[1]
    return NormalizedIdentifier(namespace=namespace, value=value)
