"""Long-term semantic memory."""

from __future__ import annotations

from jarvis.knowledge import KnowledgeBase, cosine, hash_embedding


def build(tmp_path):
    return KnowledgeBase(path=str(tmp_path / "knowledge.db"))


def test_hash_embedding_is_deterministic_and_normalised():
    first = hash_embedding("jarvis loves python")
    second = hash_embedding("jarvis loves python")
    assert first == second
    assert abs(sum(value * value for value in first) - 1.0) < 1e-6


def test_similar_texts_score_higher_than_unrelated_ones():
    query = hash_embedding("deploy the backend to production")
    close = hash_embedding("production backend deploy checklist")
    far = hash_embedding("recipe for apple pie")
    assert cosine(query, close) > cosine(query, far)


def test_notes_survive_and_can_be_recalled(tmp_path):
    knowledge = build(tmp_path)
    knowledge.add("The user prefers dark mode in every app.", tags=["preferences"])
    knowledge.add("The staging database runs on port 5433.", tags=["work"])

    hits = knowledge.search("which port does staging use")
    assert hits
    assert "5433" in hits[0].text
    assert knowledge.count() == 2


def test_tag_filter_and_forget(tmp_path):
    knowledge = build(tmp_path)
    note_id = knowledge.add("Weekly review every Friday.", tags=["routine"])
    assert knowledge.search("review", tag="work") == []
    assert knowledge.search("review", tag="routine")
    assert knowledge.forget(note_id) is True
    assert knowledge.forget(note_id) is False
