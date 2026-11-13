"""`__repr__` model memuat identitas yang berguna untuk log/debug dan tidak melempar error."""

import uuid

import pytest

from tests.integration.model_helpers import (
    bangun_audit,
    bangun_document,
    bangun_kolaborator,
    bangun_log,
    bangun_notifikasi,
    bangun_project,
    bangun_sla,
    bangun_subtask,
    bangun_user,
)

U = uuid.uuid4()


@pytest.mark.parametrize(
    "objek,harus_memuat",
    [
        (bangun_user(email="a@x.com", role="Product"), ["a@x.com", "Product"]),
        (
            bangun_project(U, id_project="PRJ-9", project_name="Nama", status="Lost"),
            ["PRJ-9", "Nama", "Lost"],
        ),
        (
            bangun_document("PRJ-1", U, id_doc="DOC-9", doc_type="HLD", status="Final"),
            ["DOC-9", "HLD", "Final"],
        ),
        (bangun_log(U, "PRJ-1", id_log="LOG-9", subtask_category="Exam"), ["LOG-9", "Exam"]),
        (
            bangun_notifikasi(U, id="N-9", event_type="handover", status="sent"),
            ["N-9", "handover", "sent"],
        ),
        (
            bangun_audit(U, id="A-9", entity_type="project", entity_id="PRJ-1", action="create"),
            ["A-9", "project:PRJ-1", "create"],
        ),
        (bangun_kolaborator("PRJ-1", U, U, role="contributor"), ["PRJ-1", "contributor"]),
        (bangun_sla("PRJ-1", id="S-9", current_status="red"), ["S-9", "PRJ-1", "red"]),
        (bangun_subtask("PRJ-1", id_subtask="ST-9", status="done"), ["ST-9", "PRJ-1", "done"]),
    ],
)
def test_repr_memuat_identitas(objek, harus_memuat):
    teks = repr(objek)
    for bagian in harus_memuat:
        assert str(bagian) in teks
