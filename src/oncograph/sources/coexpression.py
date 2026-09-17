from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from ..coexpression import CoexpressionRecord, CorrelationMethod


@dataclass(frozen=True, slots=True)
class ExpressionMatrixSpec:
    """Description of a user-provided or otherwise permitted expression matrix.

    The importer deliberately does not download upstream human genomic data. It
    accepts a local matrix plus explicit provenance/access metadata so that a
    caller can use data they are authorized to use.
    """

    path: Path
    source_key: str
    cohort: str
    gene_namespace: str = "hgnc"
    source_version: str | None = None
    tissue: str | None = None
    disease: str | None = None
    access_class: str = "user_provided"


def iter_tsv_expression(spec: ExpressionMatrixSpec) -> Iterator[tuple[str, list[float]]]:
    """Read gene-by-sample TSV: first column is gene identifier."""
    with spec.path.open("r", encoding="utf-8") as handle:
        header = handle.readline().rstrip("\n").split("\t")
        if len(header) < 4:
            raise ValueError("expression matrix needs gene id plus at least 3 samples")
        expected = len(header) - 1
        for line_number, line in enumerate(handle, start=2):
            fields = line.rstrip("\n").split("\t")
            if len(fields) != expected + 1:
                raise ValueError(f"line {line_number}: expected {expected + 1} columns")
            yield fields[0], [float(value) for value in fields[1:]]


def _pearson(x: list[float], y: list[float]) -> float:
    n = len(x)
    if n != len(y) or n < 3:
        raise ValueError("vectors must have equal length >= 3")
    mx, my = sum(x) / n, sum(y) / n
    dx = [v - mx for v in x]
    dy = [v - my for v in y]
    denom = (sum(v * v for v in dx) * sum(v * v for v in dy)) ** 0.5
    if denom == 0:
        return 0.0
    return sum(a * b for a, b in zip(dx, dy, strict=True)) / denom


def compute_pairwise_coexpression(
    rows: Iterable[tuple[str, list[float]]],
    spec: ExpressionMatrixSpec,
    *,
    min_abs_correlation: float = 0.5,
) -> Iterator[CoexpressionRecord]:
    """Reference implementation for small matrices/tests.

    Production-scale imports should replace the O(G^2) loop with a vectorized,
    blocked implementation while preserving this output contract.
    """
    if not 0 <= min_abs_correlation <= 1:
        raise ValueError("min_abs_correlation must be between 0 and 1")
    data = list(rows)
    for i, (gene_a, x) in enumerate(data):
        for gene_b, y in data[i + 1 :]:
            r = _pearson(x, y)
            if abs(r) < min_abs_correlation:
                continue
            yield CoexpressionRecord(
                gene_a_namespace=spec.gene_namespace,
                gene_a_id=gene_a,
                gene_b_namespace=spec.gene_namespace,
                gene_b_id=gene_b,
                correlation=r,
                n_samples=len(x),
                method=CorrelationMethod.PEARSON,
                cohort=spec.cohort,
                tissue=spec.tissue,
                disease=spec.disease,
                source_key=spec.source_key,
                source_version=spec.source_version,
            )
