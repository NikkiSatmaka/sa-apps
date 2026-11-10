"""
Unit test lapisan abstraksi LLM (`app.services.llm_provider`): model respons standar,
registry adapter, pemilihan provider berdasarkan config, hot-reload, dan fallback.

Memakai `LLMProviderFactory()` baru per test (bukan singleton `llm_factory`) dan
`monkeypatch` pada `settings`, sehingga tidak ada state yang bocor antar test.
"""

from types import SimpleNamespace

import pytest
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from app.core.config import settings
from app.services.llm_provider import (
    LLMMetadata,
    LLMProviderFactory,
    LLMProviderInterface,
    LLMResponse,
    TokenUsage,
    llm_factory,
)


class AdapterA:
    """Adapter palsu yang memenuhi protokol; instance dibedakan per pembuatan."""

    async def complete_text(self, prompt, **kwargs):
        return LLMResponse(content="a")

    async def parse_document(self, file_content, mime_type, prompt, max_output_tokens=8192):
        return LLMResponse(content="a")

    async def structure_text(self, text, output_schema):
        return LLMResponse(content={})


class AdapterB(AdapterA):
    pass


class AdapterRusak(AdapterA):
    def __init__(self):
        raise RuntimeError("kredensial tidak valid")


@pytest.fixture
def factory(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "a")
    monkeypatch.setattr(settings, "LLM_MODEL_NAME", "model-1")
    return LLMProviderFactory()


# --------------------------------------------------------------------------- model respons
def test_llm_response_default_adalah_sukses_tanpa_error():
    r = LLMResponse()
    assert r.status == "success"
    assert r.content is None and r.error_type is None and r.error_message is None
    assert r.metadata.finish_reason is None
    assert r.metadata.token_usage == TokenUsage(
        prompt_tokens=0, completion_tokens=0, total_tokens=0
    )


def test_metadata_default_tidak_dibagi_antar_instance():
    a, b = LLMResponse(), LLMResponse()
    a.metadata.token_usage.total_tokens = 99
    assert b.metadata.token_usage.total_tokens == 0


def test_llm_metadata_membawa_finish_reason():
    assert LLMMetadata(finish_reason="MAX_TOKENS").finish_reason == "MAX_TOKENS"


def test_adapter_struktural_memenuhi_protokol_tanpa_pewarisan():
    assert isinstance(AdapterA(), LLMProviderInterface)
    assert not isinstance(object(), LLMProviderInterface)


# --------------------------------------------------------------------------- registry
def test_register_menolak_nama_kosong(factory):
    with pytest.raises(ValueError, match="kosong"):
        factory.register_adapter("", AdapterA)


def test_register_menolak_kelas_none(factory):
    with pytest.raises(ValueError, match="None"):
        factory.register_adapter("a", None)  # type: ignore[arg-type]


def test_register_mengabaikan_kapitalisasi_nama(factory):
    factory.register_adapter("GeMiNi", AdapterA)
    assert factory.registered_adapters == ["gemini"]


def test_register_ulang_nama_sama_menimpa(factory, monkeypatch):
    factory.register_adapter("a", AdapterA)
    factory.register_adapter("a", AdapterB)
    assert factory.registered_adapters == ["a"]
    assert isinstance(factory.get_provider(), AdapterB)


@hyp_settings(max_examples=50, deadline=None)
@given(st.text(min_size=1, max_size=40))
def test_property_nama_adapter_tersimpan_huruf_kecil(nama):
    f = LLMProviderFactory()
    f.register_adapter(nama, AdapterA)
    assert f.registered_adapters == [nama.lower()]


# --------------------------------------------------------------------------- get_provider
def test_get_provider_tanpa_adapter_terdaftar_runtime_error(factory):
    with pytest.raises(RuntimeError, match="Tidak ada adapter"):
        factory.get_provider()


def test_get_provider_provider_tak_terdaftar_menyebut_adapter_tersedia(factory):
    factory.register_adapter("lain", AdapterA)
    with pytest.raises(ValueError, match=r"'a' belum terdaftar.*\[lain\]"):
        factory.get_provider()


def test_get_provider_membuat_instance_sesuai_config_dan_mencatat_nama_aktif(factory):
    factory.register_adapter("a", AdapterA)
    assert factory.active_provider_name is None
    provider = factory.get_provider()
    assert isinstance(provider, AdapterA)
    assert factory.active_provider_name == "a"


def test_get_provider_nama_provider_di_config_tidak_peka_kapitalisasi(factory, monkeypatch):
    factory.register_adapter("a", AdapterA)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "A")
    assert isinstance(factory.get_provider(), AdapterA)


def test_get_provider_memakai_ulang_instance_bila_config_tidak_berubah(factory):
    factory.register_adapter("a", AdapterA)
    assert factory.get_provider() is factory.get_provider()


def test_get_provider_membuat_instance_baru_saat_config_berubah(factory, monkeypatch):
    factory.register_adapter("a", AdapterA)
    factory.register_adapter("b", AdapterB)
    pertama = factory.get_provider()
    monkeypatch.setattr(settings, "LLM_PROVIDER", "b")
    kedua = factory.get_provider()
    assert isinstance(pertama, AdapterA) and isinstance(kedua, AdapterB)
    assert factory.active_provider_name == "b"


def test_ganti_model_saja_memicu_instance_baru(factory, monkeypatch):
    factory.register_adapter("a", AdapterA)
    pertama = factory.get_provider()
    monkeypatch.setattr(settings, "LLM_MODEL_NAME", "model-2")
    assert factory.get_provider() is not pertama


def test_inisialisasi_gagal_tanpa_fallback_runtime_error_berantai(factory):
    factory.register_adapter("a", AdapterRusak)
    with pytest.raises(RuntimeError, match="tidak ada fallback") as err:
        factory.get_provider()
    assert isinstance(err.value.__cause__, RuntimeError)
    assert factory.active_provider_name is None


def test_inisialisasi_gagal_fallback_ke_provider_terakhir_yang_valid(factory, monkeypatch):
    factory.register_adapter("a", AdapterA)
    factory.register_adapter("rusak", AdapterRusak)
    lama = factory.get_provider()
    monkeypatch.setattr(settings, "LLM_PROVIDER", "rusak")
    assert factory.get_provider() is lama


# --------------------------------------------------------------------------- reload_config
async def test_reload_config_membuat_instance_baru_dari_config_terbaru(factory, monkeypatch):
    factory.register_adapter("a", AdapterA)
    factory.register_adapter("b", AdapterB)
    lama = factory.get_provider()
    monkeypatch.setattr(settings, "LLM_PROVIDER", "b")

    await factory.reload_config()

    baru = factory.get_provider()
    assert baru is not lama and isinstance(baru, AdapterB)
    assert factory.active_provider_name == "b"


async def test_reload_config_gagal_mengembalikan_provider_sebelumnya(factory, monkeypatch):
    factory.register_adapter("a", AdapterA)
    lama = factory.get_provider()
    monkeypatch.setattr(settings, "LLM_PROVIDER", "tidak-ada")

    await factory.reload_config()  # tidak boleh melempar

    assert factory._current_provider is lama
    assert factory.active_provider_name == "a"


async def test_reload_config_tanpa_provider_awal_dan_gagal_tidak_melempar(factory):
    await factory.reload_config()  # registry kosong
    assert factory.active_provider_name is None


async def test_reload_config_gagal_melebihi_30_detik_mencatat_critical(
    factory, monkeypatch, caplog
):
    waktu = iter([0.0, 31.0])
    # Ganti referensi `time` di modul (bukan time.time global) agar jam proses lain tak terganggu.
    monkeypatch.setattr("app.services.llm_provider.time", SimpleNamespace(time=lambda: next(waktu)))
    with caplog.at_level("CRITICAL", logger="app.services.llm_provider"):
        await factory.reload_config()
    assert any("30 detik" in r.message for r in caplog.records)


# --------------------------------------------------------------------------- singleton
def test_singleton_factory_adalah_instance_factory():
    assert isinstance(llm_factory, LLMProviderFactory)
