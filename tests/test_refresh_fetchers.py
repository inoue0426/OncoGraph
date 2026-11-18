"""Regression tests for refresh failures and conservative drug name resolution."""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load_script(name: str):
    """Load a fetcher without making network requests.

    Args:
        name: Python module filename without its suffix.

    Returns:
        Loaded script module.
    """
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_civic_hgvs_failure_retries_complete_query(tmp_path: Path, monkeypatch) -> None:
    """Retain accepted evidence with explicit missing HGVS provenance.

    Args:
        tmp_path: Output directory.
        monkeypatch: Pytest patch fixture.

    Returns:
        None.
    """
    module = load_script("fetch_civic_evidence")
    module.OUTPUT_PATH = tmp_path / "civic.json"
    module.GENES = ["BRAF"]
    queries = []
    item = {"id": 123, "status": "ACCEPTED", "evidenceType": "PREDICTIVE"}
    success = {
        "data": {
            "genes": {
                "nodes": [
                    {
                        "name": "BRAF",
                        "entrezId": 673,
                        "variants": {
                            "nodes": [
                                {
                                    "id": 12,
                                    "name": "V600E",
                                    "molecularProfiles": {
                                        "nodes": [
                                            {
                                                "id": 34,
                                                "name": "BRAF V600E",
                                                "evidenceItems": {"nodes": [item]},
                                            }
                                        ]
                                    },
                                }
                            ]
                        },
                    }
                ]
            }
        }
    }
    genes = success["data"]["genes"]
    variants = genes["nodes"][0]["variants"]
    profiles = variants["nodes"][0]["molecularProfiles"]
    evidence = profiles["nodes"][0]["evidenceItems"]
    profiles["nodes"][0]["variants"] = [{"id": 12, "name": "V600E", "feature": {"name": "BRAF"}}]
    for connection in (genes, variants, profiles, evidence):
        connection["pageInfo"] = {"hasNextPage": False}
    responses = iter(({"errors": [{"message": module._HGVS_NULL_ERROR}]}, success))

    def post(query: str, variables: dict) -> dict:
        """Capture queries and return successive simulated API responses.

        Args:
            query: GraphQL document.
            variables: Requested gene symbols.

        Returns:
            Next simulated response.
        """
        queries.append(query)
        assert variables == {"symbols": module.GENES}
        return next(responses)

    monkeypatch.setattr(module, "_post_json", post)
    module.main()
    records = json.loads(module.OUTPUT_PATH.read_text())
    assert len(records) == 1
    assert records[0]["evidence_id"] == 123
    assert records[0]["variant_hgvs"] is None
    assert records[0]["molecular_profile_id"] == 34
    assert "variantHgvs" in queries[0] and "variantHgvs" not in queries[1]
    manifest = json.loads((tmp_path / "manifest_civic.json").read_text())
    assert manifest["omitted_fields"] == ["EvidenceItem.variantHgvs"]
    assert manifest["omission_reason"] == module._HGVS_NULL_ERROR


@pytest.mark.parametrize("fallback", [False, True])
def test_civic_other_errors_preserve_existing_snapshot(
    tmp_path: Path,
    monkeypatch,
    fallback: bool,
) -> None:
    """Do not publish partial results or suppress errors from the retry.

    Args:
        tmp_path: Output directory.
        monkeypatch: Pytest patch fixture.
        fallback: Whether to fail after the specific HGVS retry.

    Returns:
        None.
    """
    module = load_script("fetch_civic_evidence")
    module.OUTPUT_PATH = tmp_path / "civic.json"
    module.GENES = ["BRAF"]
    module.OUTPUT_PATH.write_text("existing snapshot")
    responses = [{"errors": [{"message": "different failure"}]}]
    if fallback:
        responses.insert(0, {"errors": [{"message": module._HGVS_NULL_ERROR}]})
    iterator = iter(responses)
    monkeypatch.setattr(module, "_post_json", lambda *_: next(iterator))
    with pytest.raises(RuntimeError, match="different failure"):
        module.main()
    assert module.OUTPUT_PATH.read_text() == "existing snapshot"
    assert not (tmp_path / "manifest_civic.json").exists()


@pytest.mark.parametrize(
    "names, expected",
    [
        (["Other drug"], None),
        (["Other drug", " Drug A "], "CHEMBL1"),
        (["drug a", "DRUG A"], None),
        ([], None),
    ],
)
def test_chembl_requires_unique_exact_name(
    monkeypatch, names: list[str], expected: str | None
) -> None:
    """Do not attach another drug's mechanism from a fuzzy or ambiguous search hit.

    Args:
        monkeypatch: Pytest patch fixture.
        names: Search result preferred names.
        expected: Unambiguous expected identifier, if any.

    Returns:
        None.
    """
    module = load_script("fetch_chembl_mechanisms")
    monkeypatch.setattr(
        module,
        "_get_json",
        lambda _: {
            "molecules": [
                {"pref_name": name, "molecule_chembl_id": f"CHEMBL{index}"}
                for index, name in enumerate(names)
            ]
        },
    )
    assert module._resolve_chembl_id("drug a") == expected


@pytest.mark.parametrize("page_info", [{"hasNextPage": True}, {}, None])
def test_civic_incomplete_nested_page_preserves_snapshot(
    tmp_path: Path,
    monkeypatch,
    page_info: dict | None,
) -> None:
    """Do not silently publish the first page of a gene's variants.

    Args:
        tmp_path: Output directory.
        monkeypatch: Pytest patch fixture.
        page_info: Incomplete or missing pagination metadata.

    Returns:
        None.
    """
    module = load_script("fetch_civic_evidence")
    module.OUTPUT_PATH = tmp_path / "civic.json"
    module.GENES = ["BRAF"]
    module.OUTPUT_PATH.write_text("existing snapshot")
    payload = {
        "data": {
            "genes": {
                "pageInfo": {"hasNextPage": False},
                "nodes": [{"name": "BRAF", "variants": {"nodes": [], "pageInfo": page_info}}],
            }
        }
    }
    monkeypatch.setattr(module, "_post_json", lambda *_: payload)
    with pytest.raises(RuntimeError, match="pagination incomplete"):
        module.main()
    assert module.OUTPUT_PATH.read_text() == "existing snapshot"


def test_chembl_complex_is_not_reduced_to_first_subunit(monkeypatch) -> None:
    """Skip a multi-component target instead of inventing a single-protein mechanism.

    Args:
        monkeypatch: Pytest patch fixture.

    Returns:
        None.
    """
    module = load_script("fetch_chembl_mechanisms")
    monkeypatch.setattr(
        module,
        "_get_json",
        lambda _: {
            "targets": [
                {
                    "target_components": [{"accession": "P00001"}, {"accession": "P00002"}],
                }
            ]
        },
    )
    assert module._target_uniprot_and_symbol("CHEMBL1") == (None, None)


@pytest.mark.parametrize(
    "path",
    [
        ("genes",),
        ("gene", "variants"),
        ("variant", "molecularProfiles"),
        ("molecularProfile", "evidenceItems"),
    ],
)
def test_civic_follows_each_connection_cursor(monkeypatch, path: tuple[str, ...]) -> None:
    """Fetch the second page using its parent selector and cursor.

    Args:
        monkeypatch: Pytest patch fixture.
        path: Connection path returned by the API.

    Returns:
        None.
    """
    module = load_script("fetch_civic_evidence")
    connection = {"nodes": [{"id": 1}], "pageInfo": {"hasNextPage": True, "endCursor": "next"}}
    page = {"nodes": [{"id": 2}], "pageInfo": {"hasNextPage": False, "endCursor": "end"}}
    response = page
    for key in reversed(path):
        response = {key: response}

    def post(query: str, variables: dict) -> dict:
        """Verify the parent selector is preserved when paging.

        Args:
            query: Query document.
            variables: Query variables.

        Returns:
            Simulated next page.
        """
        assert variables == {"id": 7, "after": "next"}
        return {"data": response}

    monkeypatch.setattr(module, "_post_json", post)
    module.complete_connection(connection, "query", {"id": 7}, path, set())
    assert connection["nodes"] == [{"id": 1}, {"id": 2}]
    module.require_complete_connections(connection)


@pytest.mark.parametrize("duplicate", [True, False])
def test_civic_rejects_overlapping_or_stalled_pages(monkeypatch, duplicate: bool) -> None:
    """Do not accept unstable pagination or loop forever.

    Args:
        monkeypatch: Pytest patch fixture.
        duplicate: Return a duplicate ID rather than a stalled cursor.

    Returns:
        None.
    """
    module = load_script("fetch_civic_evidence")
    connection = {"nodes": [{"id": 1}], "pageInfo": {"hasNextPage": True, "endCursor": "next"}}
    page = {
        "nodes": [{"id": 1 if duplicate else 2}],
        "pageInfo": {"hasNextPage": True, "endCursor": "next"},
    }
    monkeypatch.setattr(module, "_post_json", lambda *_: {"data": {"genes": page}})
    with pytest.raises(RuntimeError, match="duplicate|stalled"):
        module.complete_connection(connection, "query", {}, ("genes",), set())


def test_profile_membership_includes_unrequested_features() -> None:
    """Retain a compound profile member outside the curated gene list.

    Args:
        None.

    Returns:
        None.
    """
    module = load_script("fetch_civic_evidence")
    profile = {
        "variants": [
            {"name": "V600E", "feature": {"name": "BRAF"}},
            {"name": "Mutation", "feature": {"name": "UNREQUESTED"}},
        ]
    }
    assert module.profile_variant_labels(profile) == ["BRAF V600E", "UNREQUESTED Mutation"]
