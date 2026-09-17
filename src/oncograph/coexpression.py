from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CorrelationMethod(StrEnum):
    PEARSON = "pearson"
    SPEARMAN = "spearman"


@dataclass(frozen=True, slots=True)
class CoexpressionRecord:
    """A derived gene-gene association, independent of any upstream source."""

    gene_a_namespace: str
    gene_a_id: str
    gene_b_namespace: str
    gene_b_id: str
    correlation: float
    n_samples: int
    method: CorrelationMethod
    cohort: str
    tissue: str | None = None
    disease: str | None = None
    source_key: str = "unknown"
    source_version: str | None = None

    def __post_init__(self) -> None:
        if not -1.0 <= self.correlation <= 1.0:
            raise ValueError("correlation must be between -1 and 1")
        if self.n_samples < 3:
            raise ValueError("n_samples must be >= 3")
        if (self.gene_a_namespace, self.gene_a_id) == (self.gene_b_namespace, self.gene_b_id):
            raise ValueError("coexpression requires two distinct genes")

    @property
    def canonical_pair(self) -> tuple[tuple[str, str], tuple[str, str]]:
        a = (self.gene_a_namespace.lower().strip(), self.gene_a_id.strip())
        b = (self.gene_b_namespace.lower().strip(), self.gene_b_id.strip())
        return tuple(sorted((a, b)))  # type: ignore[return-value]
