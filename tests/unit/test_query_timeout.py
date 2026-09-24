"""Configurable restricted-mode query timeout (--query-timeout) enforced server-side."""

import sys
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

import postgres_mcp.server as server
from postgres_mcp.server import get_sql_driver
from postgres_mcp.sql.safe_sql import SafeSqlDriver
from postgres_mcp.sql.sql_driver import DbConnPool
from postgres_mcp.sql.sql_driver import SqlDriver


async def _run_main(*extra_args):
    original_argv = sys.argv
    try:
        sys.argv = ["postgres_mcp", "postgresql://user:password@localhost/db", "--access-mode=restricted", *extra_args]
        with (
            patch("postgres_mcp.server.db_connection.pool_connect", AsyncMock()),
            patch("postgres_mcp.server.mcp.run_stdio_async", AsyncMock()),
        ):
            await server.main()
    finally:
        sys.argv = original_argv


@pytest.fixture(autouse=True)
def _restore_globals():
    saved_mode, saved_timeout = server.current_access_mode, getattr(server, "query_timeout", None)
    yield
    server.current_access_mode = saved_mode
    server.query_timeout = saved_timeout


@pytest.mark.asyncio
async def test_query_timeout_flag_sets_restricted_driver_timeout():
    await _run_main("--query-timeout=120")
    with patch("postgres_mcp.server.db_connection", MagicMock(spec=DbConnPool)):
        driver = await get_sql_driver()
    assert isinstance(driver, SafeSqlDriver)
    assert driver.timeout == 120


@pytest.mark.asyncio
async def test_query_timeout_defaults_to_30():
    await _run_main()
    with patch("postgres_mcp.server.db_connection", MagicMock(spec=DbConnPool)):
        driver = await get_sql_driver()
    assert driver.timeout == 30


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["0", "-5", "abc"])
async def test_query_timeout_rejects_non_positive(bad):
    with pytest.raises(SystemExit):
        await _run_main(f"--query-timeout={bad}")


@pytest.mark.asyncio
async def test_safe_driver_passes_statement_timeout_to_server():
    inner = MagicMock(spec=SqlDriver)
    inner.execute_query = AsyncMock(return_value=[])
    driver = SafeSqlDriver(sql_driver=inner, timeout=120)

    await driver.execute_query("SELECT 1")

    kwargs = inner.execute_query.call_args.kwargs
    assert kwargs["force_readonly"] is True
    assert kwargs["statement_timeout"] == 120


@pytest.mark.asyncio
async def test_readonly_transaction_sets_local_statement_timeout():
    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.nextset = MagicMock(return_value=None)
    cursor.description = [("x",)]
    cursor.fetchall = AsyncMock(return_value=[{"x": 1}])
    cursor_cm = MagicMock()
    cursor_cm.__aenter__ = AsyncMock(return_value=cursor)
    cursor_cm.__aexit__ = AsyncMock(return_value=False)
    connection = MagicMock()
    connection.cursor = MagicMock(return_value=cursor_cm)

    driver = SqlDriver(conn=MagicMock())
    await driver._execute_with_connection(connection, "SELECT 1", None, force_readonly=True, statement_timeout=120)

    executed = [c.args[0] for c in cursor.execute.call_args_list]
    assert executed[0] == "BEGIN TRANSACTION READ ONLY"
    assert executed[1] == "SET LOCAL statement_timeout = 120000"
    assert executed[2] == "SELECT 1"
    assert executed[-1] == "ROLLBACK"


@pytest.mark.asyncio
async def test_no_statement_timeout_when_not_requested():
    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.nextset = MagicMock(return_value=None)
    cursor.description = [("x",)]
    cursor.fetchall = AsyncMock(return_value=[])
    cursor_cm = MagicMock()
    cursor_cm.__aenter__ = AsyncMock(return_value=cursor)
    cursor_cm.__aexit__ = AsyncMock(return_value=False)
    connection = MagicMock()
    connection.cursor = MagicMock(return_value=cursor_cm)

    driver = SqlDriver(conn=MagicMock())
    await driver._execute_with_connection(connection, "SELECT 1", None, force_readonly=True)

    executed = [c.args[0] for c in cursor.execute.call_args_list]
    assert not any("statement_timeout" in q for q in executed)
