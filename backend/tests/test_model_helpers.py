"""Unit test untuk helper pembentuk model yang dipakai test backend."""

from tests.integration.model_helpers import bangun_user


def test_bangun_user_admin_menggunakan_role_lead_sa_dan_flag_admin():
    user = bangun_user(role="Admin")

    assert (user.role, user.is_admin) == ("Lead_SA", True)
