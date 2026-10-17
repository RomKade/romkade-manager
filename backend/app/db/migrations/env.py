from alembic import context

from app.db.models import Base

config = context.config
connection = config.attributes.get("connection")

if connection is None:
    # Usage CLI : alembic -x db=/chemin/catalog.sqlite3 revision --autogenerate -m "..."
    from pathlib import Path

    from app.config import data_dir
    from app.db.session import make_engine

    db = context.get_x_argument(as_dictionary=True).get("db")
    engine = make_engine(Path(db) if db else data_dir() / "catalog.sqlite3")
    with engine.begin() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
else:
    context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()
