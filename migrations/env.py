"""Commerce migrations only; existing WhatsApp tables are not altered."""
from alembic import context
from sqlalchemy import create_engine
from app.config import settings
from app.db import Base
from app import commerce_models  # noqa: F401

def include_object(obj, name, type_, reflected, compare_to):
    return type_ != "table" or name.startswith("commerce_")

if context.is_offline_mode():
    context.configure(url=settings.database_url, target_metadata=Base.metadata, literal_binds=True, include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(settings.database_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()
