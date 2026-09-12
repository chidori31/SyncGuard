from alembic import context
from app import models  # noqa: F401
from app.core import settings
from app.db import Base
from sqlalchemy import create_engine, pool

target_metadata = Base.metadata


def migrate(connection):
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(
        url=settings().database_url.get_secret_value(), target_metadata=target_metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()
elif context.config.attributes.get("connection") is not None:
    migrate(context.config.attributes["connection"])
else:
    engine = create_engine(settings().database_url.get_secret_value(), poolclass=pool.NullPool, hide_parameters=True)
    with engine.connect() as connection:
        migrate(connection)
