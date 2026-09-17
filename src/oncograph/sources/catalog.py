"""Known source descriptors.

Descriptors document provenance and redistribution expectations. They do not
fetch, bundle, or redistribute upstream datasets.
"""

from .base import RedistributionPolicy, SourceDescriptor, SourceType

PUBMED = SourceDescriptor(
    key="pubmed",
    name="PubMed",
    homepage="https://pubmed.ncbi.nlm.nih.gov/",
    redistribution=RedistributionPolicy.METADATA_ONLY,
    notes="Adapter implementations should preserve PMID/PMCID/DOI provenance.",
    source_type=SourceType.PUBLICATION,
)

CLINICAL_TRIALS = SourceDescriptor(
    key="clinicaltrials_gov",
    name="ClinicalTrials.gov",
    homepage="https://clinicaltrials.gov/",
    redistribution=RedistributionPolicy.METADATA_ONLY,
    notes="Preserve NCT identifiers and source retrieval timestamps.",
    source_type=SourceType.REGISTRY,
)

CTD = SourceDescriptor(
    key="ctd",
    name="Comparative Toxicogenomics Database",
    homepage="https://ctdbase.org/",
    redistribution=RedistributionPolicy.UNKNOWN,
    notes="Potential chemical-gene/disease edge source. Verify current terms before enabling an importer.",
)

DRUGBANK = SourceDescriptor(
    key="drugbank",
    name="DrugBank",
    homepage="https://go.drugbank.com/",
    redistribution=RedistributionPolicy.RESTRICTED,
    notes="Do not commit DrugBank data. Keep credentials/licensed files outside the repository and verify the applicable license.",
)
