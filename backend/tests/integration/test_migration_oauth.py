"""Constraint untuk one-time handoff dan rotasi refresh pada Postgres."""

import pytest
from sqlalchemy.exc import IntegrityError

from tests.integration.conftest import jalankan_alembic
from tests.integration.test_migration import _sql


@pytest.mark.integration
def test_migration_oauth_membuat_tabel_dan_constraint(database_kosong_url):
    url = database_kosong_url
    jalankan_alembic(url, "upgrade", "head")
    tables = _sql(
        url,
        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
        "AND tablename IN ('auth_refresh_tokens', 'auth_handoffs')",
    )
    assert {row[0] for row in tables} == {"auth_refresh_tokens", "auth_handoffs"}

    constraints = _sql(
        url,
        "SELECT conname FROM pg_constraint WHERE conrelid='auth_refresh_tokens'::regclass",
    )
    assert "uq_auth_refresh_tokens_jti" in {row[0] for row in constraints}
    assert "chk_auth_refresh_tokens_status" in {row[0] for row in constraints}

    with pytest.raises(IntegrityError):
        _sql(
            url,
            "INSERT INTO auth_handoffs "
            "(code_hash,purpose,expires_at,created_at) "
            "VALUES ('x','unknown',now(),now())",
        )
    jalankan_alembic(url, "downgrade", "023")
    remaining = _sql(
        url,
        "SELECT to_regclass('public.auth_handoffs'), "
        "to_regclass('public.auth_refresh_tokens')",
    )
    assert remaining == [(None, None)]
    jalankan_alembic(url, "upgrade", "head")
