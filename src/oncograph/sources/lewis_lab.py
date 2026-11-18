"""Fail-closed adapters for selected Lewis Lab ligand-receptor source files.

The upstream compendium is a collection of heterogeneous files, not one
validated database. These adapters therefore require an explicit source
profile and an explicit species-aware identifier map. They never resolve a
gene symbol by name, split a complex into invented pairwise bindings, or infer
an interaction from a downstream-gene list.
"""

from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
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

HUMAN_TAXON = 9606
MOUSE_TAXON = 10090


@dataclass(frozen=True)
class LewisResolvedIdentifier:
    """A previously validated identifier and its graph entity type."""

    identifier: ExternalIdentifier
    entity_type: str = "gene"


@dataclass(frozen=True)
class LewisSourceProfile:
    """Explicit column mapping for one upstream file format."""

    source_key: str
    filename: str
    species: str
    taxon_id: int
    delimiter: str
    ligand_column: str
    receptor_column: str
    file_format: str = "delimited"
    sheet_name: str | None = None
    archive_member: str | None = None
    ligand_component_columns: tuple[str, ...] = ()
    receptor_component_columns: tuple[str, ...] = ()
    ligand_name_column: str | None = None
    receptor_name_column: str | None = None
    record_id_column: str | None = None
    evidence_column: str | None = None
    citation_column: str | None = None
    ligand_kind_column: str | None = None
    receptor_kind_column: str | None = None
    ligand_kind_default: str = "protein"
    receptor_kind_default: str = "protein"
    predicate: str = "ligand_receptor_interaction"
    evidence_type: str = "curated_ligand_receptor"
    interaction_type_column: str | None = None
    complex_separator: str | None = None


@dataclass
class LewisValidationReport:
    """Counts and diagnostics emitted by a single source parser."""

    source_key: str
    input_rows: int = 0
    emitted_interactions: int = 0
    emitted_membership_edges: int = 0
    skipped_rows: int = 0
    duplicate_rows: int = 0
    unresolved_identifiers: int = 0
    ambiguous_identifiers: int = 0
    unresolved_values: list[str] = field(default_factory=list)
    ambiguous_values: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def load_identifier_map(path: str | Path) -> dict[tuple[int, str], tuple[LewisResolvedIdentifier, ...]]:
    """Load an explicit ``taxon_id,symbol,namespace,identifier,entity_type`` map.

    Duplicate keys are retained as ambiguous candidates and are never guessed.
    """
    result: dict[tuple[int, str], list[LewisResolvedIdentifier]] = {}
    with Path(path).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {"taxon_id", "symbol", "namespace", "identifier"}
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Identifier map missing columns: {sorted(missing)}")
        for row in reader:
            key = (int(row["taxon_id"]), row["symbol"].strip().upper())
            result.setdefault(key, []).append(
                LewisResolvedIdentifier(
                    ExternalIdentifier(row["namespace"].strip(), row["identifier"].strip()),
                    row.get("entity_type", "gene").strip() or "gene",
                )
            )
    return {key: tuple(values) for key, values in result.items()}


class LewisDelimitedAdapter(SourceAdapter):
    """Parse one explicitly mapped delimited Lewis source without guessing."""

    descriptor = SourceDescriptor(
        key="lewis_delimited",
        name="Lewis Lab ligand-receptor source (local, permission-gated)",
        homepage="https://github.com/LewisLabUCSD/Ligand-Receptor-Pairs",
        redistribution=RedistributionPolicy.UNKNOWN,
        notes="Local input only; verify per-file permission before any public refresh.",
        source_type=SourceType.CURATED_DATABASE,
    )
    profile: LewisSourceProfile

    def __init__(
        self,
        path: str | Path,
        identifier_map: str | Path | Mapping[tuple[int, str], tuple[LewisResolvedIdentifier, ...]],
        *,
        release: str | None = None,
    ) -> None:
        self.path = Path(path)
        self.release = release
        self.identifier_map = (
            load_identifier_map(identifier_map)
            if isinstance(identifier_map, (str, Path))
            else dict(identifier_map)
        )
        self._prepared = False
        self._entities: list[EntityRecord] = []
        self._edges: list[EdgeRecord] = []
        self._report = LewisValidationReport(self.profile.source_key)

    def validation_report(self) -> LewisValidationReport:
        """Return the parser report after materializing entities and edges."""
        self._prepare()
        return self._report

    def _read_rows(self) -> list[dict[str, str]]:
        if self.path.name != self.profile.filename:
            raise ValueError(
                f"Expected {self.profile.filename!r} for {self.profile.source_key}; "
                f"got {self.path.name!r}"
            )
        rows: list[dict[str, str]]
        if self.profile.file_format == "xlsx":
            try:
                from openpyxl import load_workbook
            except ImportError as exc:
                raise RuntimeError(
                    "Install the optional 'lewis' extra to parse XLSX sources"
                ) from exc
            workbook = load_workbook(self.path, read_only=True, data_only=True)
            try:
                worksheet = (
                    workbook[self.profile.sheet_name]
                    if self.profile.sheet_name
                    else workbook.active
                )
                rows = worksheet.iter_rows(values_only=True)
                headers = [str(value).strip() if value is not None else "" for value in next(rows, ())]
                rows = [
                    {
                        header: value
                        for header, value in zip(headers, row, strict=False)
                        if header
                    }
                    for row in rows
                    if any(value is not None for value in row)
                ]
            finally:
                workbook.close()
        elif self.profile.file_format == "zip_delimited":
            if not self.profile.archive_member:
                raise ValueError(f"{self.profile.source_key} requires an archive member")
            with zipfile.ZipFile(self.path) as archive:
                try:
                    data = archive.read(self.profile.archive_member)
                except KeyError as exc:
                    raise ValueError(
                        f"Archive member not found: {self.profile.archive_member}"
                    ) from exc
            reader = csv.DictReader(
                io.StringIO(data.decode("utf-8-sig")), delimiter=self.profile.delimiter
            )
            rows = list(reader)
        else:
            with self.path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter=self.profile.delimiter))

        for row in rows:
            if self.profile.ligand_component_columns:
                row[self.profile.ligand_column] = "|".join(
                    str(row.get(column)).strip()
                    for column in self.profile.ligand_component_columns
                    if row.get(column) not in (None, "")
                )
            if self.profile.receptor_component_columns:
                row[self.profile.receptor_column] = "|".join(
                    str(row.get(column)).strip()
                    for column in self.profile.receptor_component_columns
                    if row.get(column) not in (None, "")
                )
        required = {
            self.profile.ligand_column,
            self.profile.receptor_column,
            *(column for column in (
                self.profile.ligand_kind_column,
                self.profile.receptor_kind_column,
            ) if column),
        }
        if rows:
            missing = required - set(rows[0])
            if missing:
                raise ValueError(
                    f"{self.profile.source_key} missing required columns: {sorted(missing)}"
                )
        return rows

    def _resolve(self, symbol: str, kind: str) -> tuple[LewisResolvedIdentifier, ...]:
        candidates = self.identifier_map.get((self.profile.taxon_id, symbol.strip().upper()), ())
        if not candidates:
            self._report.unresolved_identifiers += 1
            self._report.unresolved_values.append(symbol.strip())
            return ()
        candidates = tuple({
            (item.identifier.namespace, item.identifier.value, item.entity_type): item
            for item in candidates
        }.values())
        if len(candidates) > 1:
            self._report.ambiguous_identifiers += 1
            self._report.ambiguous_values.append(symbol.strip())
            return ()
        resolved = candidates[0]
        if kind == "metabolite" and resolved.entity_type != "metabolite":
            self._report.errors.append(f"metabolite mapping has non-metabolite type: {symbol}")
            return ()
        return (resolved,)

    def _resolve_side(self, value: str, kind: str) -> tuple[LewisResolvedIdentifier, ...]:
        if not self.profile.complex_separator or self.profile.complex_separator not in value:
            return self._resolve(value, kind)
        components = [part.strip() for part in value.split(self.profile.complex_separator) if part.strip()]
        resolved: list[LewisResolvedIdentifier] = []
        for component in components:
            resolved.extend(self._resolve(component, kind))
        return tuple(resolved) if len(resolved) == len(components) else ()

    def _complex_identifier(self, components: tuple[LewisResolvedIdentifier, ...]) -> ExternalIdentifier:
        members = "|".join(sorted(f"{item.identifier.namespace}:{item.identifier.value}" for item in components))
        digest = hashlib.sha256(members.encode("utf-8")).hexdigest()[:24]
        return ExternalIdentifier("lewis_complex", f"{self.profile.source_key}:{digest}")

    def _prepare(self) -> None:
        if self._prepared:
            return
        self._prepared = True
        rows = self._read_rows()
        seen: set[str] = set()
        entities: dict[tuple[str, str], EntityRecord] = {}
        for index, row in enumerate(rows, start=2):
            self._report.input_rows += 1
            ligand = (row.get(self.profile.ligand_column) or "").strip()
            receptor = (row.get(self.profile.receptor_column) or "").strip()
            if not ligand or not receptor:
                self._report.skipped_rows += 1
                self._report.errors.append(f"row {index}: missing ligand or receptor")
                continue
            ligand_kind = (row.get(self.profile.ligand_kind_column or "") or self.profile.ligand_kind_default).strip().lower()
            receptor_kind = (row.get(self.profile.receptor_kind_column or "") or self.profile.receptor_kind_default).strip().lower()
            ligand_parts = self._resolve_side(ligand, ligand_kind)
            receptor_parts = self._resolve_side(receptor, receptor_kind)
            if not ligand_parts or not receptor_parts:
                self._report.skipped_rows += 1
                continue
            fingerprint = "|".join([
                self.profile.source_key, ligand, receptor, ligand_kind, receptor_kind,
                str(row.get(self.profile.citation_column or "", "")),
            ])
            record_id = row.get(self.profile.record_id_column or "") or hashlib.sha256(
                fingerprint.encode("utf-8")
            ).hexdigest()[:24]
            if fingerprint in seen:
                self._report.duplicate_rows += 1
                continue
            seen.add(fingerprint)
            ligand_id = self._side_identifier(ligand_parts, ligand_kind)
            receptor_id = self._side_identifier(receptor_parts, receptor_kind)
            ligand_entity_type = self._side_entity_type(ligand_parts, ligand_kind)
            receptor_entity_type = self._side_entity_type(receptor_parts, receptor_kind)
            self._add_entity(entities, ligand_id, row.get(self.profile.ligand_name_column or "") or ligand, ligand_entity_type)
            self._add_entity(entities, receptor_id, row.get(self.profile.receptor_name_column or "") or receptor, receptor_entity_type)
            for item in ligand_parts + receptor_parts:
                self._add_entity(entities, item.identifier, item.identifier.value, item.entity_type)
            context = {
                "source_key": self.profile.source_key,
                "source_file": self.profile.filename,
                "release": self.release,
                "species": self.profile.species,
                "taxon_id": self.profile.taxon_id,
                "ligand_kind": ligand_kind,
                "receptor_kind": receptor_kind,
                "citation": row.get(self.profile.citation_column or "") or None,
                "source_evidence": row.get(self.profile.evidence_column or "") or None,
                "interaction_type": row.get(self.profile.interaction_type_column or "") or None,
            }
            self._edges.append(EdgeRecord(
                subject=ligand_id,
                predicate=self.profile.predicate,
                object=receptor_id,
                source_record_id=f"{self.profile.source_key}:{record_id}",
                context=context,
                evidence_type=self.profile.evidence_type,
            ))
            self._report.emitted_interactions += 1
            self._add_membership_edges(ligand_id, ligand_parts, record_id, context)
            self._add_membership_edges(receptor_id, receptor_parts, record_id, context)
        self._entities = list(entities.values())

    def _side_identifier(
        self, parts: tuple[LewisResolvedIdentifier, ...], kind: str
    ) -> ExternalIdentifier:
        if len(parts) == 1:
            return parts[0].identifier
        return self._complex_identifier(parts)

    @staticmethod
    def _side_entity_type(parts: tuple[LewisResolvedIdentifier, ...], kind: str) -> str:
        """Keep complexes opaque; preserve explicit metabolite/protein types."""
        if len(parts) > 1:
            return "molecular_complex"
        if kind == "metabolite":
            return "metabolite"
        return parts[0].entity_type

    def _add_entity(
        self,
        entities: dict[tuple[str, str], EntityRecord],
        identifier: ExternalIdentifier,
        name: str,
        entity_type: str,
    ) -> None:
        key = (identifier.namespace, identifier.value)
        if key in entities:
            return
        metadata = {"source_key": self.profile.source_key, "taxon_id": self.profile.taxon_id}
        if entity_type == "molecular_complex":
            metadata["entity_role"] = "complex"
        entities[key] = EntityRecord(entity_type=entity_type, name=name, identifiers=(identifier,), metadata=metadata)

    def _add_membership_edges(
        self,
        side_identifier: ExternalIdentifier,
        parts: tuple[LewisResolvedIdentifier, ...],
        record_id: str,
        context: dict,
    ) -> None:
        if len(parts) <= 1:
            return
        complex_id = side_identifier
        for part in parts:
            self._edges.append(EdgeRecord(
                subject=complex_id,
                predicate="has_subunit",
                object=part.identifier,
                source_record_id=f"{self.profile.source_key}:{record_id}:member:{part.identifier.value}",
                context={**context, "relationship": "complex_membership"},
                evidence_type="curated_complex_membership",
            ))
            self._report.emitted_membership_edges += 1

    def iter_entities(self) -> Iterable[EntityRecord]:
        self._prepare()
        return iter(self._entities)

    def iter_edges(self) -> Iterable[EdgeRecord]:
        self._prepare()
        return iter(self._edges)


def _profile_descriptor(key: str, name: str, homepage: str = "https://github.com/LewisLabUCSD/Ligand-Receptor-Pairs") -> SourceDescriptor:
    return SourceDescriptor(
        key=key,
        name=name,
        homepage=homepage,
        redistribution=RedistributionPolicy.UNKNOWN,
        notes="Permission-gated local parser; no upstream data is bundled or refreshed publicly.",
        source_type=SourceType.CURATED_DATABASE,
    )


@registry.register
class LewisRamilowskiAdapter(LewisDelimitedAdapter):
    """Parser for the explicitly mapped human Ramilowski text list."""

    descriptor = _profile_descriptor("lewis_ramilowski_2015", "Lewis Lab: Ramilowski 2015")
    profile = LewisSourceProfile(
        source_key="lewis_ramilowski_2015",
        filename="Human-2015-Ramilowski-LR-pairs.txt",
        species="Homo sapiens",
        taxon_id=HUMAN_TAXON,
        delimiter="\t",
        ligand_column="Ligand.ApprovedSymbol",
        receptor_column="Receptor.ApprovedSymbol",
        ligand_name_column="Ligand.Name",
        receptor_name_column="Receptor.Name",
        record_id_column="Pair.Name",
        evidence_column="Pair.Evidence",
        citation_column="PMID.Manual",
    )


@registry.register
class LewisCabelloAguilarAdapter(LewisDelimitedAdapter):
    """Parser for the explicitly mapped human SingleCellSignalR CSV list."""

    descriptor = _profile_descriptor("lewis_cabello_2020", "Lewis Lab: SingleCellSignalR 2020")
    profile = LewisSourceProfile(
        source_key="lewis_cabello_2020",
        filename="Human-2020-Cabello-Aguilar-LR-pairs.csv",
        species="Homo sapiens",
        taxon_id=HUMAN_TAXON,
        delimiter=",",
        ligand_column="ligand",
        receptor_column="receptor",
        evidence_column="sources",
        citation_column="pmid",
    )


@registry.register
class LewisZhaoAdapter(LewisDelimitedAdapter):
    """Parser for the human NeuronChat 2023 TSV list."""

    descriptor = _profile_descriptor("lewis_zhao_2023", "Lewis Lab: NeuronChat 2023")
    profile = LewisSourceProfile(
        source_key="lewis_zhao_2023",
        filename="Human-2023-Zhao-LR-pairs.tsv",
        species="Homo sapiens",
        taxon_id=HUMAN_TAXON,
        delimiter="\t",
        ligand_column="lig_contributor",
        receptor_column="target_subunit",
        record_id_column="interaction_name",
        ligand_kind_column="ligand_type",
        interaction_type_column="interaction_type",
    )


@registry.register
class LewisMetSensorAdapter(LewisDelimitedAdapter):
    """Parser for human MEBOCOST metabolite-to-target associations."""

    descriptor = _profile_descriptor("lewis_zheng_2022", "Lewis Lab: MEBOCOST MetSensor 2022")
    profile = LewisSourceProfile(
        source_key="lewis_zheng_2022",
        filename="Human-2022-Zheng-MetSensor-pairs.tsv",
        species="Homo sapiens",
        taxon_id=HUMAN_TAXON,
        delimiter="\t",
        ligand_column="HMDB_ID",
        receptor_column="Gene_name",
        ligand_name_column="standard_metName",
        receptor_name_column="Protein_name",
        citation_column="Evidence",
        ligand_kind_default="metabolite",
        predicate="metabolite_target_association",
        evidence_type="metabolite_source_association",
    )


@registry.register
class LewisQiaoAdapter(LewisDelimitedAdapter):
    """Parser for the human Qiao 2014 XLSX list."""

    descriptor = _profile_descriptor("lewis_qiao_2014", "Lewis Lab: Qiao 2014")
    profile = LewisSourceProfile(
        source_key="lewis_qiao_2014",
        filename="Human-2014-Qiao-LR-pairs.xlsx",
        species="Homo sapiens",
        taxon_id=HUMAN_TAXON,
        delimiter="",
        file_format="xlsx",
        sheet_name="Sheet1",
        ligand_column="Ligand (Symbol)",
        receptor_column="Receptor (Symbols)",
        record_id_column="#",
        evidence_column="Confidence from iRefWeb",
    )


@registry.register
class LewisPavlicevAdapter(LewisDelimitedAdapter):
    """Parser for the human Pavlicev 2017 XLSX list."""

    descriptor = _profile_descriptor("lewis_pavlicev_2017", "Lewis Lab: Pavlicev 2017")
    profile = LewisSourceProfile(
        source_key="lewis_pavlicev_2017",
        filename="Human-2017-Pavlicev-LR-pairs.xlsx",
        species="Homo sapiens",
        taxon_id=HUMAN_TAXON,
        delimiter="",
        file_format="xlsx",
        sheet_name="Sheet1",
        ligand_column="Ligand",
        receptor_column="Receptor",
    )


@registry.register
class LewisHouAdapter(LewisDelimitedAdapter):
    """Parser for the human NATMI 2020 XLSX list."""

    descriptor = _profile_descriptor("lewis_hou_2020", "Lewis Lab: Hou 2020")
    profile = LewisSourceProfile(
        source_key="lewis_hou_2020",
        filename="Human-2020-Hou-LR-pairs.xlsx",
        species="Homo sapiens",
        taxon_id=HUMAN_TAXON,
        delimiter="",
        file_format="xlsx",
        sheet_name="Sheet1",
        ligand_column="Ligand gene symbol",
        receptor_column="Receptor gene symbol",
        evidence_column="Ligand location",
        citation_column="PMID support",
    )


@registry.register
class LewisWangAdapter(LewisDelimitedAdapter):
    """Parser for the human iTALK 2019 CSV list."""

    descriptor = _profile_descriptor("lewis_wang_2019", "Lewis Lab: Wang iTALK 2019")
    profile = LewisSourceProfile(
        source_key="lewis_wang_2019",
        filename="Human-2019-Wang-LR-pairs.csv",
        species="Homo sapiens",
        taxon_id=HUMAN_TAXON,
        delimiter=",",
        ligand_column="Ligand.ApprovedSymbol",
        receptor_column="Receptor.ApprovedSymbol",
        ligand_name_column="Ligand.Name",
        receptor_name_column="Receptor.Name",
        record_id_column="Pair.Name",
        evidence_column="Classification",
    )


@registry.register
class LewisJinAdapter(LewisDelimitedAdapter):
    """Parser for the human CellChat 2020 CSV list with opaque complexes."""

    descriptor = _profile_descriptor("lewis_jin_2020", "Lewis Lab: Jin CellChat 2020")
    profile = LewisSourceProfile(
        source_key="lewis_jin_2020",
        filename="Human-2020-Jin-LR-pairs.csv",
        species="Homo sapiens",
        taxon_id=HUMAN_TAXON,
        delimiter=",",
        ligand_column="ligand_symbol",
        receptor_column="receptor_symbol",
        record_id_column="interaction_name",
        evidence_column="evidence",
        interaction_type_column="pathway_name",
        complex_separator="&",
    )


@registry.register
class LewisShaoAdapter(LewisDelimitedAdapter):
    """Parser for the human CellTalkDB 2020 TSV list."""

    descriptor = _profile_descriptor("lewis_shao_2020", "Lewis Lab: Shao CellTalkDB 2020")
    profile = LewisSourceProfile(
        source_key="lewis_shao_2020",
        filename="Human-2020-Shao-LR-pairs.txt",
        species="Homo sapiens",
        taxon_id=HUMAN_TAXON,
        delimiter="\t",
        ligand_column="ligand_gene_symbol",
        receptor_column="receptor_gene_symbol",
        record_id_column="lr_pair",
        citation_column="evidence",
    )


@registry.register
class LewisDimitrovAdapter(LewisDelimitedAdapter):
    """Parser for the human LIANA 2022 CSV list."""

    descriptor = _profile_descriptor("lewis_dimitrov_2022", "Lewis Lab: Dimitrov LIANA 2022")
    profile = LewisSourceProfile(
        source_key="lewis_dimitrov_2022",
        filename="Human-2022-Dimitrov-LR-pairs.csv",
        species="Homo sapiens",
        taxon_id=HUMAN_TAXON,
        delimiter=",",
        ligand_column="source_genesymbol",
        receptor_column="target_genesymbol",
        evidence_column="resource",
    )


@registry.register
class LewisNoelAdapter(LewisDelimitedAdapter):
    """Parser for the human ICELLNET 2020 XLSX list with complexes."""

    descriptor = _profile_descriptor("lewis_noel_2020", "Lewis Lab: Noël ICELLNET 2020")
    profile = LewisSourceProfile(
        source_key="lewis_noel_2020",
        filename="Human-2020-Noël-LR-pairs.xlsx",
        species="Homo sapiens",
        taxon_id=HUMAN_TAXON,
        delimiter="",
        file_format="xlsx",
        sheet_name="All",
        ligand_column="__ligand__",
        receptor_column="__receptor__",
        ligand_component_columns=("Ligand 1", "Ligand 2"),
        receptor_component_columns=("Receptor 1", "Receptor 2", "Receptor 3"),
        evidence_column="Source for interaction",
        citation_column="PubMed ID",
        interaction_type_column="Classifications",
        complex_separator="|",
    )


@registry.register
class LewisBrowaeysAdapter(LewisDelimitedAdapter):
    """Parser for the LR member of the human NicheNet 2019 archive."""

    descriptor = _profile_descriptor("lewis_browaeys_2019", "Lewis Lab: Browaeys NicheNet 2019")
    profile = LewisSourceProfile(
        source_key="lewis_browaeys_2019",
        filename="Human-2019-Browaeys-LR-pairs.zip",
        species="Homo sapiens",
        taxon_id=HUMAN_TAXON,
        delimiter=",",
        file_format="zip_delimited",
        archive_member="NicheNet-LR-pairs.csv",
        ligand_column="from",
        receptor_column="to",
        evidence_column="source",
        interaction_type_column="database",
    )
