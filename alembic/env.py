from logging.config import fileConfig
import os
from sqlalchemy import engine_from_config, pool
from alembic import context

# --- Import Base and Models ---
from database import Base  # Base = declarative_base()
from db_models import User, Administration, AdministrationZone, SweetSpot  # make sure all models are imported

# this is the Alembic Config object, which provides access to .ini file values
config = context.config

# set sqlalchemy.url from .env (DATABASE_URL)
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:jumon000@localhost:5432/sih2k25"
)
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# Interpret config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for 'autogenerate'
target_metadata = Base.metadata


def run_migrations_offline():
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=True  # safe for sqlite, fine for postgres too
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=True
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()