"""Start a disposable database server per engine, and hand out databases on it.

PostgreSQL, MySQL and SQL Server run in containers (testcontainers). SQLite needs no
server: a "database" is a file in a temp directory.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.exc import OperationalError
from testcontainers.community.mssql import SqlServerContainer
from testcontainers.community.mysql import MySqlContainer
from testcontainers.community.postgres import PostgresContainer

from common.credentials import generate_password
from common.polling import wait_until
from sql_engines.app.database import make_engine

# Pinned so a new upstream release can't change results under us. Dependabot doesn't
# read Python files, so these are bumped by hand. CI pulls them before the tests start.
IMAGES = {
    "postgres": "postgres:18.7",
    "mysql": "mysql:8.4.13",
    # The free Developer edition (the image's default MSSQL_PID). A specific CU, not "latest".
    "mssql": "mcr.microsoft.com/mssql/server:2022-CU28-ubuntu-22.04",
}

# SQL Server can take a minute to accept logins on a busy CI runner.
CONNECT_TIMEOUT_SECONDS = 180


@dataclass(frozen=True)
class EngineInfo:
    key: str  # pytest param id and marker name: `pytest -m mssql`
    label: str  # shown in the Allure report


ENGINES = {
    "sqlite": EngineInfo("sqlite", "SQLite"),
    "postgres": EngineInfo("postgres", "PostgreSQL 18"),
    "mysql": EngineInfo("mysql", "MySQL 8.4"),
    "mssql": EngineInfo("mssql", "SQL Server 2022"),
}


@dataclass
class DatabaseServer:
    """One running server. `create_database` returns an engine for a fresh database."""

    info: EngineInfo
    create_database: Callable[[str], sa.Engine]


@contextmanager
def start_server(key: str, tmp_dir: Path) -> Iterator[DatabaseServer]:
    info = ENGINES[key]
    if key == "sqlite":
        yield DatabaseServer(info, lambda name: make_engine(sa.make_url(f"sqlite:///{tmp_dir / name}.db")))
        return

    password = generate_password()
    container: PostgresContainer | MySqlContainer | SqlServerContainer
    if key == "postgres":
        container = PostgresContainer(IMAGES["postgres"], password=password, driver="psycopg")
    elif key == "mysql":
        # Connect as root so the suite can CREATE DATABASE. It's a throwaway server.
        container = MySqlContainer(IMAGES["mysql"], dialect="pymysql", username="root", password=password)
    else:
        container = SqlServerContainer(IMAGES["mssql"], password=password)

    with container:
        server_url = sa.make_url(container.get_connection_url())
        if key == "mysql":
            server_url = server_url.update_query_dict({"charset": "utf8mb4"})
        admin = sa.create_engine(server_url, isolation_level="AUTOCOMMIT")
        _wait_for_connection(admin)

        def create_database(name: str) -> sa.Engine:
            with admin.connect() as conn:
                conn.exec_driver_sql(f"CREATE DATABASE {name}")
                if key == "mssql":
                    # Off by default. Lets a transaction ask for SNAPSHOT isolation;
                    # see test_engine_differences.py.
                    conn.exec_driver_sql(f"ALTER DATABASE {name} SET ALLOW_SNAPSHOT_ISOLATION ON")
            return make_engine(server_url.set(database=name))

        yield DatabaseServer(info, create_database)
        admin.dispose()


def _wait_for_connection(engine: sa.Engine) -> None:
    """Retry the first connection only (the server may still be starting).

    This is the one retry in the SQL suite. Tests themselves are never retried: a test
    that fails once is a real failure or a real flake, and both deserve a look.
    """

    def can_connect() -> bool:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return True

    wait_until(
        can_connect,
        timeout=CONNECT_TIMEOUT_SECONDS,
        description=f"{engine.dialect.name} to accept connections",
        interval=1.0,
        ignore=(OperationalError,),
    )
