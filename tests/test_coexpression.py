from pathlib import Path

import pytest

from oncograph.coexpression import CoexpressionRecord, CorrelationMethod
from oncograph.sources.coexpression import ExpressionMatrixSpec, compute_pairwise_coexpression


def test_canonical_pair_is_order_independent():
    record = CoexpressionRecord(
        gene_a_namespace="HGNC",
        gene_a_id="B",
        gene_b_namespace="hgnc",
        gene_b_id="A",
        correlation=0.8,
        n_samples=10,
        method=CorrelationMethod.PEARSON,
        cohort="demo",
    )
    assert record.canonical_pair == (("hgnc", "A"), ("hgnc", "B"))


def test_pairwise_coexpression_filters_weak_edges():
    spec = ExpressionMatrixSpec(path=Path("unused.tsv"), source_key="test", cohort="demo")
    rows = [
        ("A", [1.0, 2.0, 3.0, 4.0]),
        ("B", [2.0, 4.0, 6.0, 8.0]),
        ("C", [1.0, 0.0, 1.0, 0.0]),
    ]
    edges = list(compute_pairwise_coexpression(rows, spec, min_abs_correlation=0.9))
    assert [(e.gene_a_id, e.gene_b_id) for e in edges] == [("A", "B")]
    assert edges[0].correlation == pytest.approx(1.0)
