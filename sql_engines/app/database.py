"""Engine creation and Alembic wiring shared by the app and the tests."""

from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import URL, Engine, create_engine, event

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def make_engine(url: URL) -> Engine:
    """Create an engine with the per-engine settings the suite relies on."""
    backend = url.get_backend_name()
    if backend == "sqlite":
        return _make_sqlite_engine(url)

    connect_args: dict[str, Any] = {}
    if backend == "postgresql":
        # Safety net: a test that unexpectedly waits on a lock fails in 5 s, not never.
        connect_args["options"] = "-c lock_timeout=5000"
    elif backend == "mysql":
        connect_args["init_command"] = "SET SESSION innodb_lock_wait_timeout = 5"
    engine = create_engine(url, connect_args=connect_args)
    if backend == "mssql":

        @event.listens_for(engine, "connect")
        def _set_lock_timeout(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("SET LOCK_TIMEOUT 5000")
            cursor.close()

    return engine


def _make_sqlite_engine(url: URL) -> Engine:
    # timeout=0: a locked database file fails at once instead of waiting 5 s. The suite
    # never waits on locks; tests that touch locking expect the error.
    # check_same_thread=False: the API serves requests on worker threads, and in tests it
    # uses the test's connection. Access is never concurrent, which is what the check
    # guards against.
    engine = create_engine(url, connect_args={"timeout": 0, "check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection: Any, _record: Any) -> None:
        # Python's sqlite3 driver delays BEGIN until the first write, so a SELECT runs
        # outside any transaction, and SAVEPOINTs misbehave. Turning that off and issuing
        # BEGIN ourselves (below) gives real transactions; this is SQLAlchemy's
        # documented recipe for pysqlite.
        dbapi_connection.isolation_level = None
        # SQLite ignores foreign keys unless this is switched on, per connection.
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    @event.listens_for(engine, "begin")
    def _on_begin(connection: Any) -> None:
        connection.exec_driver_sql("BEGIN")

    return engine


def alembic_config(engine: Engine) -> Config:
    """An Alembic config that runs against `engine`, with no alembic.ini needed."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.attributes["engine"] = engine
    return config


def upgrade(engine: Engine, revision: str = "head") -> None:
    command.upgrade(alembic_config(engine), revision)


def downgrade(engine: Engine, revision: str) -> None:
    command.downgrade(alembic_config(engine), revision)
