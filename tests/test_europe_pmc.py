import json

from sqlmodel import Session, SQLModel, create_engine, select

from oncograph.importing import import_adapter, import_entities
from oncograph.models import Entity, Evidence, Relation
from oncograph.sources import registry
from oncograph.sources.base import EntityRecord, ExternalIdentifier
from oncograph.sources.europe_pmc import EuropePmcAdapter

METADATA = [
    {
        "pmid": "42691523",
        "doi": "10.1016/J.RESINV.2026.101508",
        "pmcid": None,
        "title": "Gefitinib response after acquisition of C797S in EGFR-mutated NSCLC.",
        "journal": "Respiratory investigation",
        "year": "2026",
        "authors": ["Tagawa Y", "Katakura S"],
        "pub_types": ["Journal Article", "Case Reports"],
        "source_url": "https://pubmed.ncbi.nlm.nih.gov/42691523/",
    },
    {
        "pmid": "42734867",
        "doi": "10.1186/s43046-026-00414-2",
        "pmcid": "pmc13574751",
        "title": "Comparative efficacy and safety of EGFR TKIs in NSCLC.",
        "journal": "Journal of the Egyptian National Cancer Institute",
        "year": "2026",
        "authors": ["Mahato S"],
        "pub_types": ["Journal Article", "Systematic Review"],
        "source_url": "https://pubmed.ncbi.nlm.nih.gov/42734867/",
    },
    {
        "pmid": "",
        "doi": "10.9999/no-pmid-example",
        "pmcid": None,
        "title": "A publication known only by DOI.",
        "journal": "Example Journal",
        "year": "2025",
        "authors": ["Someone S"],
        "pub_types": ["Journal Article"],
        "source_url": None,
    },
]

CITATIONS = [
    {
        "pmid": "42691523",
        "subject_namespace": "gtopdb",
        "subject_id": "4941",
        "predicate": "targets",
        "object_namespace": "hgnc",
        "object_id": "HGNC:3236",
        "evidence_type": "target_interaction",
        "extraction_method": "curated",
    },
    {
        "pmid": "42734867",
        "subject_namespace": "gtopdb",
        "subject_id": "4941",
        "predicate": "targets",
        "object_namespace": "hgnc",
        "object_id": "HGNC:3236",
        "evidence_type": "target_interaction",
        "extraction_method": "curated",
    },
    {
        "pmid": "00000000",
        "subject_namespace": "gtopdb",
        "subject_id": "4941",
        "predicate": "targets",
        "object_namespace": "hgnc",
        "object_id": "HGNC:3236",
        "evidence_type": "target_interaction",
        "extraction_method": "curated",
    },
]


def _memory_session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _write_fixtures(tmp_path):
    metadata_path = tmp_path / "publications.json"
    metadata_path.write_text(json.dumps(METADATA), encoding="utf-8")
    citations_path = tmp_path / "publication_citations.json"
    citations_path.write_text(json.dumps(CITATIONS), encoding="utf-8")
    return citations_path, metadata_path


def _seed_drug_and_gene(session: Session) -> None:
    import_entities(
        session,
        [
            EntityRecord(
                entity_type="drug", name="gefitinib", identifiers=(ExternalIdentifier("gtopdb", "4941"),)
            ),
            EntityRecord(
                entity_type="gene", name="EGFR", identifiers=(ExternalIdentifier("hgnc", "HGNC:3236"),)
            ),
        ],
    )


def test_europe_pmc_adapter_is_registered():
    assert registry.get("europe_pmc") is EuropePmcAdapter


def test_europe_pmc_imports_publication_entity_with_pmid_and_metadata(tmp_path):
    citations_path, metadata_path = _write_fixtures(tmp_path)
    adapter = EuropePmcAdapter(citations_path, metadata_path, release="2026-09-17")

    entities = {e.identifiers[0]: e for e in adapter.iter_entities()}
    pmid_entity = entities[ExternalIdentifier("pmid", "42691523")]

    assert pmid_entity.entity_type == "paper"
    assert pmid_entity.name == "Gefitinib response after acquisition of C797S in EGFR-mutated NSCLC."
    assert pmid_entity.metadata["journal"] == "Respiratory investigation"
    assert pmid_entity.metadata["year"] == "2026"
    assert pmid_entity.metadata["authors"] == ["Tagawa Y", "Katakura S"]


def test_europe_pmc_falls_back_to_doi_when_pmid_is_missing(tmp_path):
    citations_path, metadata_path = _write_fixtures(tmp_path)
    adapter = EuropePmcAdapter(citations_path, metadata_path, release="2026-09-17")

    with _memory_session() as session:
        report = import_entities(session, adapter.iter_entities())
        doi_entity = session.exec(
            select(Entity).where(Entity.canonical_id == "doi:10.9999/no-pmid-example")
        ).one()

    assert report.entities_created == 3
    assert doi_entity.name == "A publication known only by DOI."


def test_europe_pmc_links_evidence_to_publication_entity(tmp_path):
    citations_path, metadata_path = _write_fixtures(tmp_path)
    adapter = EuropePmcAdapter(citations_path, metadata_path, release="2026-09-17")

    with _memory_session() as session:
        _seed_drug_and_gene(session)
        report = import_adapter(session, adapter)

        drug = session.exec(select(Entity).where(Entity.canonical_id == "gtopdb:4941")).one()
        gene = session.exec(select(Entity).where(Entity.canonical_id == "hgnc:HGNC:3236")).one()
        publication = session.exec(
            select(Entity).where(Entity.canonical_id == "pubmed:42691523")
        ).one()
        relation = session.exec(select(Relation)).one()
        evidence_rows = session.exec(
            select(Evidence).where(Evidence.source_id == "42691523")
        ).all()

    assert relation.subject_id == drug.id
    assert relation.predicate == "targets"
    assert relation.object_id == gene.id

    assert len(evidence_rows) == 1
    evidence = evidence_rows[0]
    assert evidence.publication_id == publication.id
    assert evidence.evidence_type == "target_interaction"
    assert evidence.extraction_method == "curated"
    assert evidence.source_type == "publication"
    assert evidence.source_url == "https://pubmed.ncbi.nlm.nih.gov/42691523/"
    # Report includes the third citation's unresolved PMID (00000000: no fetched metadata).
    assert report.errors == []


def test_europe_pmc_supports_multiple_publications_per_relation(tmp_path):
    citations_path, metadata_path = _write_fixtures(tmp_path)
    adapter = EuropePmcAdapter(citations_path, metadata_path, release="2026-09-17")

    with _memory_session() as session:
        _seed_drug_and_gene(session)
        report = import_adapter(session, adapter)

        relations = session.exec(select(Relation)).all()
        evidence_rows = session.exec(select(Evidence)).all()
        publication_ids = {e.publication_id for e in evidence_rows}

    # Both PMIDs support the same (drug, targets, gene) triple: one relation,
    # two evidence rows, each citing a distinct publication.
    assert len(relations) == 1
    assert report.edges_created == 1
    assert len(evidence_rows) == 2
    assert len(publication_ids) == 2
    assert None not in publication_ids


def test_europe_pmc_citation_with_unresolved_pmid_is_skipped_without_error(tmp_path):
    """The third citation cites a PMID absent from the fetched metadata file."""
    citations_path, metadata_path = _write_fixtures(tmp_path)
    adapter = EuropePmcAdapter(citations_path, metadata_path, release="2026-09-17")

    with _memory_session() as session:
        _seed_drug_and_gene(session)
        report = import_adapter(session, adapter)
        evidence_rows = session.exec(
            select(Evidence).where(Evidence.source_id == "00000000")
        ).all()

    assert evidence_rows == []
    assert report.edges_skipped == 0
    assert report.errors == []


def test_europe_pmc_reimport_is_idempotent(tmp_path):
    citations_path, metadata_path = _write_fixtures(tmp_path)

    with _memory_session() as session:
        _seed_drug_and_gene(session)
        first = import_adapter(session, EuropePmcAdapter(citations_path, metadata_path))
        second = import_adapter(session, EuropePmcAdapter(citations_path, metadata_path))

        publications = session.exec(select(Entity).where(Entity.type == "paper")).all()
        evidence_rows = session.exec(select(Evidence)).all()

    assert first.edges_created == 1
    assert first.evidence_created == 2
    assert second.edges_created == 0
    assert second.evidence_created == 0
    assert len(publications) == 3
    assert len(evidence_rows) == 2
