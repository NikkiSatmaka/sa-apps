"""
Konfigurasi environment Alembic untuk Portal SA.
Mendukung async migrations dengan SQLAlchemy 2.0+.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.core.config import settings
from app.core.database import Base

# Import semua model agar terdaftar di metadata Base
from app.models import (  # noqa: F401
    CalendarOAuthSession,
    ActivityLog,
    AuditLog,
    Document,
    NotificationLog,
    Project,
    SLATracking,
    Subtask,
    User,
)

# Konfigurasi Alembic dari .ini file
config = context.config

# Override sqlalchemy.url dari settings aplikasi.
# Escape '%' menjadi '%%' karena ConfigParser (dipakai set_main_option)
# memperlakukan '%' sebagai sintaks interpolasi. Tanpa ini, password yang
# mengandung '%' (mis. hasil URL-encoding seperti %2A) membuat Alembic gagal
# dengan "invalid interpolation syntax". ConfigParser akan meng-unescape
# '%%' -> '%' saat nilai dibaca kembali, sehingga URL ke engine tetap benar.
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("%", "%%"))

# Setup logging dari config file
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata untuk autogenerate
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Jalankan migrations dalam mode 'offline'.
    Menghasilkan SQL tanpa koneksi ke database.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Helper untuk menjalankan migrations dengan koneksi yang sudah ada."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """
    Jalankan migrations dalam mode async.
    Membuat engine async dan menjalankan migrations di dalamnya.
    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """
    Jalankan migrations dalam mode 'online'.
    Menggunakan async engine untuk koneksi ke database.
    """
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
