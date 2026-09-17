"""SIGNOR causal signaling adapter -- SCAFFOLD ONLY, no real data.

Verified live during Issue #10: SIGNOR's own site states its data is
released under CC BY-SA 4.0 (and, inconsistently, CC BY 4.0 in another
footer) -- either way, an open license. However, ``signor.uniroma2.it/API/``
(its documented bulk-query endpoint) returned ``403 Forbidden`` to a plain
HTTP request; SIGNOR's practical bulk-download path requires a browser
session/form submission this repository's fetch scripts do not attempt to
script around. This is an access-complexity gap, not a licensing one.

This adapter therefore:

- reads a **local** file the caller must already have (e.g. exported via
  SIGNOR's own web interface under its CC BY-SA terms) -- it never calls
  SIGNOR itself;
- is not registered with any fetch script, and is not wired into the
  scheduled data-refresh pipeline;
- preserves SIGNOR's signed/directed causal semantics (ACTIVATES/INHIBITS/
  UNKNOWN, never flattened to a generic undirected interaction), per
  Issue #10's explicit requirement.
"""

import json
from collections.abc import Iterable
from pathlib import Path

from .base import (
    EdgeRecord,
    EntityRecord,
    ExternalIdentifier,
    RedistributionPolicy,
    SourceAdapter,
    SourceDescriptor,
    SourceType,
)
from .registry import registry

_EFFECT_PREDICATES = {
    "up-regulates": "activates",
    "up-regulates activity": "activates",
    "up-regulates quantity": "increases_abundance_of",
    "down-regulates": "inhibits",
    "down-regulates activity": "inhibits",
    "down-regulates quantity": "decreases_abundance_of",
    "unknown": "regulates",
}


@registry.register
class SignorAdapter(SourceAdapter):
    descriptor = SourceDescriptor(
        key="signor",
        name="SIGNOR",
        homepage="https://signor.uniroma2.it/",
        license_url="https://signor.uniroma2.it/",
        redistribution=RedistributionPolicy.RESTRICTED,
        notes=(
            "CC BY-SA 4.0 confirmed live, but the bulk-query API returned 403 to a plain "
            "request (a session/form-based access gap, not a license restriction). This "
            "adapter reads a local, caller-supplied export only; not wired into any "
            "pipeline."
        ),
        source_type=SourceType.CURATED_DATABASE,
    )

    def __init__(self, json_path: str | Path, release: str | None = None):
        self.json_path = Path(json_path)
        self.release = release

    def _records(self) -> list[dict]:
        """Expected local record shape (one per SIGNOR relation row)::

        {
          "idA": "P00533", "nameA": "EGFR", "typeA": "protein",
          "idB": "P62993", "nameB": "GRB2", "typeB": "protein",
          "effect": "up-regulates activity", "mechanism": "binding",
          "signor_id": "SIGNOR-C1", "pmid": "8302543"
        }
        """
        return json.loads(self.json_path.read_text(encoding="utf-8"))

    def iter_entities(self) -> Iterable[EntityRecord]:
        seen: set[str] = set()
        for row in self._records():
            for id_key, name_key in (("idA", "nameA"), ("idB", "nameB")):
                uniprot = (row.get(id_key) or "").strip()
                if uniprot and uniprot not in seen:
                    seen.add(uniprot)
                    yield EntityRecord(
                        entity_type="protein",
                        name=row.get(name_key) or uniprot,
                        identifiers=(ExternalIdentifier("uniprot", uniprot),),
                        metadata={"release": self.release},
                    )

    def iter_edges(self) -> Iterable[EdgeRecord]:
        for row in self._records():
            id_a = (row.get("idA") or "").strip()
            id_b = (row.get("idB") or "").strip()
            if not id_a or not id_b:
                continue
            effect = (row.get("effect") or "unknown").strip().lower()
            pmid = (row.get("pmid") or "").strip()
            yield EdgeRecord(
                subject=ExternalIdentifier("uniprot", id_a),
                predicate=_EFFECT_PREDICATES.get(effect, "regulates"),
                object=ExternalIdentifier("uniprot", id_b),
                source_record_id=row.get("signor_id"),
                evidence_type="signor_causal_signaling",
                context={"effect": row.get("effect"), "mechanism": row.get("mechanism"), "release": self.release},
                publication=ExternalIdentifier("pmid", pmid) if pmid else None,
            )
