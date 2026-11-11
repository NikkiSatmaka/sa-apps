"""
Fixture fake boundary. Terdaftar untuk seluruh `tests/integration/` lewat impor di
`tests/integration/conftest.py`; test unit dapat mengimpornya eksplisit. Pemulihan otomatis
karena semua pemasangan memakai `monkeypatch`; objek fake dibuat baru per test (tanpa state sisa).
"""

from __future__ import annotations

import pytest

from tests.integration.fakes.calendar import FakeCalendar
from tests.integration.fakes.drive import FakeDrive
from tests.integration.fakes.gmail import FakeGmail
from tests.integration.fakes.llm import FakeLLM


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> FakeLLM:
    fake = FakeLLM()
    fake.pasang(monkeypatch)
    return fake


@pytest.fixture
def fake_drive(monkeypatch: pytest.MonkeyPatch) -> FakeDrive:
    fake = FakeDrive()
    fake.pasang(monkeypatch)
    return fake


@pytest.fixture
def fake_gmail(monkeypatch: pytest.MonkeyPatch) -> FakeGmail:
    fake = FakeGmail()
    fake.pasang(monkeypatch)
    return fake


@pytest.fixture
def fake_calendar(monkeypatch: pytest.MonkeyPatch) -> FakeCalendar:
    fake = FakeCalendar()
    fake.pasang(monkeypatch)
    return fake
