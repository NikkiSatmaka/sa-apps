"""Constraint untuk one-time handoff dan rotasi refresh pada Postgres."""

import pytest
from sqlalchemy.exc import IntegrityError

from tests.integration.test_migration import _sql


@pytest.mark.integration
def test_migration_oauth_membuat_tabel_dan_constraint(database_kosong_url):
    url = database_kosong_url
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
