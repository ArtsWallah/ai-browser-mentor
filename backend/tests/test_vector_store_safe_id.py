"""
Regression Tests for Phase 2A: Hardened _safe_id() & Vector Store Operations

Verifies:
1. Normal page IDs produce 64-character lowercase hex strings.
2. Windows reserved device names (CON, PRN, AUX, NUL, COM1, LPT1) are mapped safely without OS errors.
3. Illegal characters (* ? < > | ") are mapped safely without OS errors.
4. Forward and backward slashes (/ and \\) are mapped safely.
5. Embedded null bytes (\\x00) are handled safely without raising unhandled ValueError.
6. Empty, whitespace-only, and None IDs raise ValueError and are not mapped to a shared fallback.
7. Very long IDs (5,000 characters) map safely to 64-character filenames without length limits.
8. Deterministic output: same ID produces identical hash every time.
9. Collision resistance: different IDs produce different hashes.
10. Full lifecycle: create_index, load_index, get_metadata, search, delete_index work with SHA-256 mapping.
11. Backward compatibility: pre-existing legacy files are safely read and transparently migrated.
"""

import os
import re
import pytest
import numpy as np

from app.services.vector_store import (
    _safe_id,
    get_index_path,
    get_embeddings_path,
    get_metadata_path,
    get_metadata,
    create_index,
    load_index,
    delete_index,
    search,
    migrate_legacy_index,
    VECTOR_DIR
)


def _make_dummy_embeddings(count=2, dim=384):
    np.random.seed(1337)
    vecs = np.random.randn(count, dim).astype("float32")
    return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)


HEX_64_PATTERN = re.compile(r"^[0-9a-f]{64}$")


# ============================================================
# 1. BASIC FORMAT & VALIDATION TESTS
# ============================================================

def test_normal_page_ids_format():
    """Normal page IDs must produce strictly 64-char lowercase hex strings."""
    ids = [
        "page_12345",
        "page_1793396115595",
        "0d222565-55c2-4fd6-8cd0-a03e8492afb6",
        "article-security-guide-v2"
    ]
    for pid in ids:
        hashed = _safe_id(pid)
        assert len(hashed) == 64
        assert HEX_64_PATTERN.match(hashed)
        assert hashed == hashed.lower()


def test_deterministic_output():
    """Identical inputs must yield identical hash filenames every time."""
    pid = "my-deterministic-page-id-99"
    first = _safe_id(pid)
    for _ in range(20):
        assert _safe_id(pid) == first


def test_different_ids_produce_different_filenames():
    """Distinct IDs must produce distinct 64-char filenames."""
    id1 = "page_alpha"
    id2 = "page_beta"
    id3 = "page_alpha_1"
    assert _safe_id(id1) != _safe_id(id2)
    assert _safe_id(id1) != _safe_id(id3)
    assert _safe_id(id2) != _safe_id(id3)


# ============================================================
# 2. EDGE CASES & OS SECURITY TESTS
# ============================================================

@pytest.mark.parametrize("reserved_name", ["CON", "PRN", "AUX", "NUL", "COM1", "LPT1", "con", "nul"])
def test_windows_reserved_names_safe(reserved_name):
    """Windows device names must be safely hashed without hitting OS device files."""
    hashed = _safe_id(reserved_name)
    assert len(hashed) == 64
    assert HEX_64_PATTERN.match(hashed)

    # Verify actual file path is not a device file
    meta_path = get_metadata_path(reserved_name)
    assert os.path.basename(meta_path) == f"{hashed}.json"
    # Ensure openable on Windows
    with open(meta_path, "w", encoding="utf-8") as f:
        f.write('{"test": true}')
    assert os.path.exists(meta_path)
    os.remove(meta_path)


@pytest.mark.parametrize("illegal_str", [
    "page*with*asterisk",
    "page?question",
    "tag<open>close",
    "pipe|symbol",
    'double"quote',
    "colon:test"
])
def test_illegal_characters_safe(illegal_str):
    """Characters forbidden on Windows NTFS / FAT must be safely hashed."""
    hashed = _safe_id(illegal_str)
    assert len(hashed) == 64
    assert HEX_64_PATTERN.match(hashed)

    meta_path = get_metadata_path(illegal_str)
    with open(meta_path, "w", encoding="utf-8") as f:
        f.write('{"safe": true}')
    assert os.path.exists(meta_path)
    os.remove(meta_path)


def test_slashes_and_path_traversal():
    """Forward and backward slashes, as well as .. traversal, must be safely hashed."""
    traversal_ids = [
        "../../etc/passwd",
        "..\\..\\windows\\system32",
        "/absolute/root/path",
        "nested/deep/sub/dir",
        "..",
        "."
    ]
    for tid in traversal_ids:
        hashed = _safe_id(tid)
        assert len(hashed) == 64
        assert HEX_64_PATTERN.match(hashed)
        # Ensure path stays strictly inside VECTOR_DIR
        meta_path = get_metadata_path(tid)
        assert os.path.dirname(meta_path) == VECTOR_DIR


def test_embedded_null_bytes():
    """Null bytes must be safely hashed without causing OS ValueError."""
    null_id = "page\x00with\x00null\x00bytes"
    hashed = _safe_id(null_id)
    assert len(hashed) == 64
    assert HEX_64_PATTERN.match(hashed)

    meta_path = get_metadata_path(null_id)
    with open(meta_path, "w", encoding="utf-8") as f:
        f.write('{"null_safe": true}')
    assert os.path.exists(meta_path)
    os.remove(meta_path)


def test_very_long_id():
    """5,000-character page IDs must be mapped to 64-char filenames without OS name limit errors."""
    giant_id = "long_id_" + ("a" * 5000)
    hashed = _safe_id(giant_id)
    assert len(hashed) == 64
    assert HEX_64_PATTERN.match(hashed)

    meta_path = get_metadata_path(giant_id)
    assert len(os.path.basename(meta_path)) == 64 + 5  # <64 hex>.json


@pytest.mark.parametrize("empty_val", ["", "   ", "\t\n", None])
def test_empty_and_invalid_ids_raise_value_error(empty_val):
    """Empty, whitespace-only, and None inputs must raise ValueError, never silently colliding."""
    with pytest.raises(ValueError):
        _safe_id(empty_val)


# ============================================================
# 3. VECTOR STORE LIFECYCLE (SAVE, LOAD, METADATA, SEARCH, DELETE)
# ============================================================

def test_vector_store_lifecycle_hardened():
    """Verify full save, load, get_metadata, search, and delete cycle using hardened mapping."""
    test_id = "test-hardened-lifecycle-id-42"
    chunks = [
        {"heading": "Cryptography", "text": "Cryptographic hashes like SHA-256 provide collision resistance."},
        {"heading": "Filesystems", "text": "Filesystems have differing restrictions on paths and naming conventions."}
    ]
    embeddings = _make_dummy_embeddings(count=2)

    # 1. Create / Save
    res = create_index(test_id, embeddings, chunks)
    assert res["page_id"] == test_id
    assert res["count"] == 2

    # Check files on disk
    hashed = _safe_id(test_id)
    assert os.path.exists(os.path.join(VECTOR_DIR, f"{hashed}.json"))
    assert os.path.exists(os.path.join(VECTOR_DIR, f"{hashed}.npy"))

    # 2. Metadata retrieval
    meta = get_metadata(test_id)
    assert meta is not None
    assert meta["page_id"] == test_id
    assert len(meta["chunks"]) == 2

    # 3. Load Index
    loaded = load_index(test_id)
    assert loaded is not None
    assert len(loaded["chunks"]) == 2

    # 4. Search
    hits = search(test_id, embeddings[0], top_k=1)
    assert len(hits) == 1
    assert hits[0]["chunk"]["heading"] == "Cryptography"

    # 5. Delete Index
    deleted = delete_index(test_id)
    assert deleted is True
    assert not os.path.exists(os.path.join(VECTOR_DIR, f"{hashed}.json"))
    assert not os.path.exists(os.path.join(VECTOR_DIR, f"{hashed}.npy"))

    # Verify reload fails after deletion
    assert load_index(test_id) is None
    assert get_metadata(test_id) is None


# ============================================================
# 4. BACKWARD COMPATIBILITY & LEGACY MIGRATION TESTS
# ============================================================

def test_legacy_file_transparent_fallback_and_migration():
    """Verify pre-existing unhashed legacy files are transparently discovered and migrated."""
    legacy_id = "legacy-pre-migration-test-doc"
    legacy_meta_path = os.path.join(VECTOR_DIR, f"{legacy_id}.json")
    legacy_npy_path = os.path.join(VECTOR_DIR, f"{legacy_id}.npy")

    embeddings = _make_dummy_embeddings(count=1)
    chunks = [{"heading": "Legacy Section", "text": "Stored before SHA-256 mapping was introduced."}]

    # Manually write unhashed legacy files directly to disk
    import json
    with open(legacy_meta_path, "w", encoding="utf-8") as f:
        json.dump({"page_id": legacy_id, "chunks": chunks}, f)
    np.save(legacy_npy_path, embeddings)

    assert os.path.exists(legacy_meta_path)
    assert os.path.exists(legacy_npy_path)

    try:
        # Load index should discover legacy file, trigger transparent migration, and succeed
        loaded = load_index(legacy_id)
        assert loaded is not None
        assert len(loaded["chunks"]) == 1
        assert loaded["chunks"][0]["heading"] == "Legacy Section"

        # Hardened SHA-256 files should now exist
        hardened_id = _safe_id(legacy_id)
        hardened_meta_path = os.path.join(VECTOR_DIR, f"{hardened_id}.json")
        hardened_npy_path = os.path.join(VECTOR_DIR, f"{hardened_id}.npy")
        assert os.path.exists(hardened_meta_path)
        assert os.path.exists(hardened_npy_path)

        # Search should also work
        hits = search(legacy_id, embeddings[0], top_k=1)
        assert len(hits) == 1
        assert hits[0]["chunk"]["heading"] == "Legacy Section"

    finally:
        # Clean up both legacy and migrated files
        delete_index(legacy_id)
        if os.path.exists(legacy_meta_path):
            os.remove(legacy_meta_path)
        if os.path.exists(legacy_npy_path):
            os.remove(legacy_npy_path)