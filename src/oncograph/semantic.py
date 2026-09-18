"""Minimal, dependency-free local "semantic" similarity: TF-IDF + cosine.

Not a neural or LLM embedding. This repository has no embedding/ML
dependency today (see ``pyproject.toml``: FastAPI/SQLModel/uvicorn/typer
only), and adding one (torch, sentence-transformers, an API-based
embedding call) would be exactly the "heavy runtime/deployment cost" this
project's own design principle says to avoid for something used only by a
benchmark script, never by the live site or API. A classical sparse
vector-space model (TF-IDF + cosine similarity) is the "minimal, well-
documented local embedding option" chosen instead: pure Python standard
library, fully deterministic, and -- deliberately -- re-fit fresh for
*each* retrieval query over that query's own small local candidate corpus
(see ``oncograph.rank.HybridPathRanker``), rather than a persisted global
model trained once over the whole graph. This means there is no "model
version" artifact to snapshot beyond this module's own source code -- the
"embedding" is entirely a function of the query's local neighborhood text,
recomputed identically every time.

Called "semantic" advisedly: TF-IDF/cosine captures topical similarity via
term weighting (rare, informative words count more than common ones) that
plain token-overlap (``oncograph.rank``'s existing lexical scorer) does
not -- but it is still a lexical/statistical method, not a claim of deep
semantic understanding.
"""

import math
import re

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, order/repetition preserved (unlike
    ``oncograph.rank._tokenize``'s deduplicated token *set*) -- term
    frequency needs repetition to be meaningful."""
    return _TOKEN_RE.findall(text.lower())


class TfidfSpace:
    """A TF-IDF vector space fit over a small, fixed corpus of documents --
    typically one retrieval query's candidate relation/path texts plus the
    question itself. Rebuilt fresh per query; never persisted.
    """

    def __init__(self, documents: list[str]):
        self.doc_count = len(documents)
        self._document_frequency: dict[str, int] = {}
        for doc in documents:
            for term in set(tokenize(doc)):
                self._document_frequency[term] = self._document_frequency.get(term, 0) + 1

    def idf(self, term: str) -> float:
        """Smoothed IDF (always positive; an unseen term gets the max weight
        this space can assign, so a novel word is never treated as
        irrelevant)."""
        document_frequency = self._document_frequency.get(term, 0)
        return math.log((1 + self.doc_count) / (1 + document_frequency)) + 1.0

    def vectorize(self, text: str) -> dict[str, float]:
        """TF-IDF weighted sparse vector for ``text`` (term -> weight)."""
        tokens = tokenize(text)
        if not tokens:
            return {}
        term_counts: dict[str, int] = {}
        for token in tokens:
            term_counts[token] = term_counts.get(token, 0) + 1
        return {term: (count / len(tokens)) * self.idf(term) for term, count in term_counts.items()}


def cosine_similarity(vector_a: dict[str, float], vector_b: dict[str, float]) -> float:
    """Cosine similarity between two sparse TF-IDF vectors, in [0, 1] for
    non-negative TF-IDF weights (always the case here)."""
    if not vector_a or not vector_b:
        return 0.0
    shared_terms = set(vector_a) & set(vector_b)
    if not shared_terms:
        return 0.0
    dot_product = sum(vector_a[term] * vector_b[term] for term in shared_terms)
    norm_a = math.sqrt(sum(weight * weight for weight in vector_a.values()))
    norm_b = math.sqrt(sum(weight * weight for weight in vector_b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot_product / (norm_a * norm_b)


__all__ = ["TfidfSpace", "cosine_similarity", "tokenize"]
