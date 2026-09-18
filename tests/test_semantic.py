"""oncograph.semantic: dependency-free local TF-IDF + cosine similarity."""

import math

from oncograph.semantic import TfidfSpace, cosine_similarity, tokenize


def test_tokenize_lowercases_and_splits():
    assert tokenize("EGFR-targeting Drug!") == ["egfr", "targeting", "drug"]


def test_tfidf_idf_is_higher_for_rarer_terms():
    space = TfidfSpace(["gene target egfr", "gene target braf", "gene target kras", "gene rare egfr"])
    # "gene" appears in all 4 docs; "rare" appears in only 1 -- rarer terms must score higher IDF.
    assert space.idf("rare") > space.idf("gene")


def test_tfidf_idf_never_negative_and_handles_unseen_terms():
    space = TfidfSpace(["a b c"])
    assert space.idf("never_seen_before") > 0
    assert space.idf("a") > 0


def test_vectorize_empty_text_returns_empty_vector():
    space = TfidfSpace(["a b c"])
    assert space.vectorize("") == {}
    assert space.vectorize("   ") == {}


def test_cosine_similarity_identical_texts_is_high():
    space = TfidfSpace(["drug targets gene", "trial evaluates drug", "gene is_a term"])
    a = space.vectorize("drug targets gene")
    b = space.vectorize("drug targets gene")
    assert math.isclose(cosine_similarity(a, b), 1.0, rel_tol=1e-9)


def test_cosine_similarity_unrelated_texts_is_low():
    space = TfidfSpace(["drug targets gene", "trial evaluates drug", "gene is_a term", "tissue expresses gene"])
    a = space.vectorize("drug targets gene")
    b = space.vectorize("tissue expresses gene")
    unrelated_score = cosine_similarity(a, b)
    identical_score = cosine_similarity(a, space.vectorize("drug targets gene"))
    assert unrelated_score < identical_score


def test_cosine_similarity_empty_vectors_is_zero():
    assert cosine_similarity({}, {"a": 1.0}) == 0.0
    assert cosine_similarity({}, {}) == 0.0
