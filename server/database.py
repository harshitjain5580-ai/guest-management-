from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from server.config import DATABASE_URL

engine_options = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_options)
if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def initialize_database() -> None:
    from server import models  # noqa: F401

    Base.metadata.create_all(engine)
    if "user_id" not in {column["name"] for column in inspect(engine).get_columns("guests")}:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE guests ADD COLUMN user_id INTEGER"))
