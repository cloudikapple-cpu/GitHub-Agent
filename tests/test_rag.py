"""Retrieval over local documents."""

from jarvis.rag import DocumentIndex, chunk_text, format_context


def test_short_text_stays_in_one_piece():
    assert chunk_text("a short note") == ["a short note"]
    assert chunk_text("   ") == []


def test_long_text_is_split_into_overlapping_chunks():
    text = "\n\n".join(f"Paragraph {index}. " + ("word " * 60) for index in range(6))
    chunks = chunk_text(text, size=400, overlap=50)

    assert len(chunks) > 1
    assert all(chunk.strip() for chunk in chunks)
    assert sum(len(chunk) for chunk in chunks) >= len(text.strip()) - len(chunks) * 4


def test_indexing_a_folder_and_searching_it(tmp_path):
    (tmp_path / "office.md").write_text(
        "The office wifi password is hunter2 and the router lives in the kitchen.",
        encoding="utf-8",
    )
    (tmp_path / "recipe.md").write_text(
        "Pancakes: mix flour, eggs and milk, then fry them.", encoding="utf-8"
    )

    index = DocumentIndex(":memory:")
    report = index.index_path(tmp_path)
    assert report["files"] == 2
    assert report["chunks"] == 2

    hits = index.search("office wifi password", limit=1)
    assert hits
    assert "hunter2" in hits[0].text
    assert "office.md" in format_context(hits)
    index.close()


def test_unchanged_files_are_not_indexed_twice(tmp_path):
    note = tmp_path / "note.md"
    note.write_text("remember the milk", encoding="utf-8")

    index = DocumentIndex(":memory:")
    assert index.index_file(note) == 1
    assert index.index_file(note) == 0
    assert index.index_file(note, force=True) == 1
    assert index.stats() == {"files": 1, "chunks": 1}
    index.close()


def test_files_that_are_not_text_are_ignored(tmp_path):
    (tmp_path / "picture.png").write_bytes(b"\x89PNG\r\n")
    (tmp_path / "archive.zip").write_bytes(b"PK\x03\x04")

    index = DocumentIndex(":memory:")
    assert index.index_path(tmp_path)["files"] == 0
    index.close()


def test_forgetting_a_file_removes_its_passages(tmp_path):
    note = tmp_path / "note.md"
    note.write_text("a fact worth keeping", encoding="utf-8")

    index = DocumentIndex(":memory:")
    index.index_file(note)
    path = index.paths()[0]
    assert index.forget_file(path) == 1
    assert index.stats()["chunks"] == 0
    index.close()


def test_searching_an_empty_index_is_quiet():
    index = DocumentIndex(":memory:")
    assert index.search("anything") == []
    assert index.search("") == []
    assert format_context([]) == ""
    index.close()
