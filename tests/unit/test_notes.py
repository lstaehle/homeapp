import json
from unittest.mock import patch, mock_open

import pytest

from app.notes import add_note, delete_note, get_notes


@pytest.fixture(autouse=True)
def no_file_io(tmp_path, monkeypatch):
    notes_file = tmp_path / "notes.json"
    import app.notes as n
    monkeypatch.setattr(n, "_FILE", notes_file)


def test_get_notes_empty():
    assert get_notes() == []


def test_add_note_persists():
    add_note("Milch kaufen", "Lorenz")
    notes = get_notes()
    assert len(notes) == 1
    assert notes[0]["text"] == "Milch kaufen"
    assert notes[0]["author"] == "Lorenz"
    assert "id" in notes[0]
    assert "created_at" in notes[0]


def test_add_multiple_notes():
    add_note("Erste Notiz")
    add_note("Zweite Notiz")
    assert len(get_notes()) == 2


def test_delete_note_removes_it():
    add_note("Zu löschen")
    note_id = get_notes()[0]["id"]
    delete_note(note_id)
    assert get_notes() == []


def test_delete_nonexistent_note_is_safe():
    add_note("Bleibt")
    delete_note("nonexistent-id")
    assert len(get_notes()) == 1
