"""Conservative chemical identity resolution for the LINCS consensus export.

A source-local consensus label is not a globally resolved chemical identity.
Names and connectivity-only InChIKey prefixes never establish equivalence.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from .base import EntityRecord, ExternalIdentifier
from .sigma_sources import file_sha256, table_rows

COMPOUNDINFO_URL = (
    "https://s3.amazonaws.com/macchiato.clue.io/builds/LINCS2020/compoundinfo_beta.txt"
)
GENEINFO_URL = "https://s3.amazonaws.com/macchiato.clue.io/builds/LINCS2020/geneinfo_beta.txt"
FULL_INCHIKEY = re.compile(r"[A-Z]{14}-[A-Z]{10}-[A-Z]")
NATIVE_NAMESPACE = "lincs_consensus"


@dataclass(frozen=True)
class CompoundResolution:
    """An endpoint plus the evidence for, or limitations of, its chemical identity."""

    identifier: ExternalIdentifier
    provenance: dict


def compound_resolutions(
    compoundinfo: Path, gse92742: Path
) -> tuple[dict[str, CompoundResolution], list[EntityRecord], dict]:
    """Resolve native IDs and complete structure keys, preserving all other keys.

    Args:
        compoundinfo: Frozen official LINCS2020 compoundinfo_beta.txt.
        gse92742: Frozen original GSE92742 perturbagen metadata.

    Returns:
        Source-key resolutions, unique endpoint entities, and mapping audit.
        Exact cmap_name membership is descriptive only, never a global ID match.
    """
    native = defaultdict(list)
    labels = defaultdict(list)
    old_native = defaultdict(list)
    structure_cids = defaultdict(set)
    cid_structures = defaultdict(set)
    legacy = defaultdict(set)
    for row in table_rows(gse92742):
        required = {"pert_id", "pert_iname", "pert_type", "pubchem_cid", "inchi_key"}
        if not required <= row.keys():
            raise ValueError("Unrecognized GSE92742 metadata schema")
        if row["pert_type"] != "trt_cp":
            continue
        old_native[row["pert_id"]].append(row)
        cid = row["pubchem_cid"]
        if cid.isdigit() and int(cid) > 0:
            cid = str(int(cid))
            for token in (row["pert_id"], row["pert_iname"]):
                legacy[token].add(cid)
            if FULL_INCHIKEY.fullmatch(row["inchi_key"]):
                structure_cids[row["inchi_key"]].add(cid)
                cid_structures[cid].add(row["inchi_key"])
    for row in table_rows(compoundinfo):
        if not {"pert_id", "cmap_name", "inchi_key"} <= row.keys():
            raise ValueError("Unrecognized LINCS2020 compound metadata schema")
        if not row["pert_id"] or not row["cmap_name"]:
            raise ValueError("Missing source-native perturbagen identity")
        native[row["pert_id"]].append(row)
        labels[row["cmap_name"]].append(row)
    fingerprints = {"LINCS2020": file_sha256(compoundinfo), "GSE92742": file_sha256(gse92742)}
    resolutions, entities = {}, {}
    for token in sorted(native.keys() | labels.keys()):
        # A name collision with an actual native ID is not resolved by precedence.
        rows = native.get(token, []) + labels.get(token, [])
        members = sorted({row["pert_id"] for row in rows})
        keys = {row["inchi_key"] for row in rows if FULL_INCHIKEY.fullmatch(row["inchi_key"])}
        missing_key = any(not FULL_INCHIKEY.fullmatch(row["inchi_key"]) for row in rows)
        candidates = set()
        strategy = "source_native_consensus"
        reason = (
            "source_label_only" if token not in native else "no_verified_global_cross_reference"
        )
        conflict = len(keys) > 1
        if token in native and token in labels:
            conflict |= {row["pert_id"] for row in labels[token]} != {token}
        if token in native and len(keys) == 1 and not missing_key and not conflict:
            full_key = next(iter(keys))
            old = old_native.get(token, [])
            old_keys = {r["inchi_key"] for r in old if FULL_INCHIKEY.fullmatch(r["inchi_key"])}
            conflict |= bool(old_keys - keys)
            native_cids = {
                str(int(r["pubchem_cid"]))
                for r in old
                if r["pubchem_cid"].isdigit() and int(r["pubchem_cid"]) > 0
            }
            structural = structure_cids.get(full_key, set())
            candidates = native_cids | structural
            conflict |= len(candidates) > 1
            conflict |= any(cid_structures[cid] != keys for cid in candidates)
            if not conflict and len(candidates) == 1:
                # Native cross-reference must also carry the same complete key.
                if native_cids and old_keys == keys:
                    strategy, reason = (
                        "native_id_and_full_inchikey",
                        "verified_GSE92742_cross_reference",
                    )
                elif not native_cids and structural:
                    strategy, reason = "full_inchikey", "unique_GSE92742_structure_cross_reference"
        if conflict:
            strategy, reason = "source_native_consensus", "conflicting_metadata"
        resolved = strategy != "source_native_consensus"
        endpoint = (
            ExternalIdentifier("pubchem", next(iter(candidates)))
            if resolved
            else ExternalIdentifier(NATIVE_NAMESPACE, token)
        )
        provenance = {
            "strategy": strategy,
            "identity_status": "globally_resolved" if resolved else "source_native_only",
            "reason": reason,
            "native_perturbagen_ids": members,
            "full_inchikeys": sorted(keys),
            "missing_structure_metadata": missing_key,
            "pubchem_candidates": sorted(candidates),
            "metadata_conflict": conflict,
            "metadata_sha256": fingerprints,
            "metadata_release": "LINCS2020 beta / GSE92742 frozen snapshots",
            "metadata_license_scope": "local research; CLUE terms and NIH/GEO exception; see documentation",
            "consensus_label_is_global_identity": False,
            "formulation_equivalence_asserted": False,
        }
        resolutions[token] = CompoundResolution(endpoint, provenance)
        identity = (endpoint.namespace, endpoint.value)
        entities.setdefault(
            identity,
            EntityRecord(
                entity_type="drug",
                name=token,
                identifiers=(endpoint,),
                metadata={"source": "LINCS consensus identity resolution", **provenance},
            ),
        )
    audit = {
        "metadata_sha256": fingerprints,
        "strategies_over_metadata_keys": dict(
            Counter(r.provenance["strategy"] for r in resolutions.values())
        ),
        "legacy_mapping": {k: sorted(v) for k, v in legacy.items()},
    }
    return resolutions, list(entities.values()), audit
