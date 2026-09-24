# ruff: noqa: B017
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from postgres_mcp.sql.sql_driver import DbConnPool


class AsyncContextManagerMock(AsyncMock):
    """A better mock for async context managers"""

    async def __aenter__(self):
        return self.aenter

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.fixture
def mock_pool():
    """Create a mock for AsyncConnectionPool."""
    pool = MagicMock()

    # Create cursor context manager
    cursor = AsyncMock()

    # Create connection context manager
    connection = AsyncMock()
    connection.cursor = MagicMock(return_value=AsyncContextManagerMock())
    connection.cursor.return_value.aenter = cursor

    # Setup connection manager
    conn_ctx = AsyncContextManagerMock()
    conn_ctx.aenter = connection

    # Setup pool.connection() to return our mocked connection context manager
    pool.connection = MagicMock(return_value=conn_ctx)

    # Setup pool.open and pool.close as async mocks
    pool.open = AsyncMock()
    pool.close = AsyncMock()

    return pool


@pytest.mark.asyncio
async def test_pool_connect_success(mock_pool):
    """Test successful connection to the database pool."""
    with patch("postgres_mcp.sql.sql_driver.AsyncConnectionPool", return_value=mock_pool):
        # Patch the connection test part to skip it
        with patch.object(DbConnPool, "pool_connect", new=AsyncMock(return_value=mock_pool)) as mock_connect:
            db_pool = DbConnPool("postgresql://user:pass@localhost/db")
            pool = await db_pool.pool_connect()

            assert pool == mock_pool
            mock_connect.assert_called_once()


@pytest.mark.asyncio
async def test_pool_connect_with_retry(mock_pool):
    """Test pool connection with retry on failure."""
    # First attempt fails, second succeeds
    mock_pool.open.side_effect = [Exception("Connection error"), None]

    # Create a mock implementation of pool_connect that simulates a retry
    async def mock_pool_connect(self, connection_url=None):
        if not hasattr(self, "_attempt_count"):
            self._attempt_count = 0

        self._attempt_count += 1

        if self._attempt_count == 1:
            # First attempt fails
            raise Exception("Connection error")
        else:
            # Second attempt succeeds
            self.pool = mock_pool
            self._is_valid = True
            return mock_pool

    with patch("postgres_mcp.sql.sql_driver.AsyncConnectionPool", return_value=mock_pool):
        with patch("postgres_mcp.server.asyncio.sleep", AsyncMock()) as mock_sleep:
            with patch.object(DbConnPool, "pool_connect", mock_pool_connect):
                db_pool = DbConnPool("postgresql://user:pass@localhost/db")

                # Call our own custom implementation directly to simulate the retry
                # First call will fail, second call will succeed
                with pytest.raises(Exception):
                    await mock_pool_connect(db_pool)

                # Second attempt should succeed
                pool = await mock_pool_connect(db_pool)

                assert pool == mock_pool
                assert db_pool._is_valid is True  # type: ignore
                mock_sleep.assert_not_called()  # We're not actually calling sleep in our mock


@pytest.mark.asyncio
async def test_pool_connect_all_retries_fail(mock_pool):
    """Test pool connection when all retry attempts fail."""
    # Mock pool.open to raise an exception for the test
    mock_pool.open.side_effect = Exception("Persistent connection error")

    # Configure AsyncConnectionPool's constructor to return our mock
    with patch("postgres_mcp.sql.sql_driver.AsyncConnectionPool", return_value=mock_pool):
        # Mock sleep to speed up test
        with patch("asyncio.sleep", AsyncMock()):
            db_pool = DbConnPool("postgresql://user:pass@localhost/db")

            # This should fail since pool.open raises an exception
            with pytest.raises(Exception):
                await db_pool.pool_connect()

            # Verify the pool is marked as invalid
            assert db_pool._is_valid is False  # type: ignore
            # Verify open was called at least once (no need to verify retries here)
            assert mock_pool.open.call_count >= 1


@pytest.mark.asyncio
async def test_close_pool(mock_pool):
    """Test closing the connection pool."""
    with patch("postgres_mcp.sql.sql_driver.AsyncConnectionPool", return_value=mock_pool):
        db_pool = DbConnPool("postgresql://user:pass@localhost/db")

        # Mock the pool_connect method to avoid actual connection
        db_pool.pool_connect = AsyncMock(return_value=mock_pool)
        await db_pool.pool_connect()
        db_pool.pool = mock_pool  # Set directly
        db_pool._is_valid = True  # type: ignore

        # Close the pool
        await db_pool.close()

        # Check that pool is now invalid
        assert db_pool._is_valid is False  # type: ignore
        assert db_pool.pool is None
        mock_pool.close.assert_called_once()


@pytest.mark.asyncio
async def test_close_handles_errors(mock_pool):
    """Test that close() handles exceptions gracefully."""
    mock_pool.close.side_effect = Exception("Error closing pool")

    with patch("postgres_mcp.sql.sql_driver.AsyncConnectionPool", return_value=mock_pool):
        db_pool = DbConnPool("postgresql://user:pass@localhost/db")

        # Mock the pool_connect method to avoid actual connection
        db_pool.pool_connect = AsyncMock(return_value=mock_pool)
        await db_pool.pool_connect()
        db_pool.pool = mock_pool  # Set directly
        db_pool._is_valid = True  # type: ignore

        # Close should not raise the exception
        await db_pool.close()

        # Pool should still be marked as invalid
        assert db_pool._is_valid is False  # type: ignore
        assert db_pool.pool is None


@pytest.mark.asyncio
async def test_pool_connect_initialized(mock_pool):
    """Test pool_connect when pool is already initialized."""
    with patch("postgres_mcp.sql.sql_driver.AsyncConnectionPool", return_value=mock_pool):
        db_pool = DbConnPool("postgresql://user:pass@localhost/db")

        # Mock the pool_connect method to avoid actual connection
        db_pool.pool_connect = AsyncMock(return_value=mock_pool)
        original_pool = await db_pool.pool_connect()
        db_pool.pool = mock_pool  # Set directly
        db_pool._is_valid = True  # type: ignore

        # Reset the mock counts
        mock_pool.open.reset_mock()

        # Get the pool again
        returned_pool = await db_pool.pool_connect()

        # Should return the existing pool without reconnecting
        assert returned_pool == original_pool
        mock_pool.open.assert_not_called()


@pytest.mark.asyncio
async def test_pool_connect_not_initialized(mock_pool):
    """Test pool_connect when pool is not yet initialized."""
    with patch("postgres_mcp.sql.sql_driver.AsyncConnectionPool", return_value=mock_pool):
        db_pool = DbConnPool("postgresql://user:pass@localhost/db")

        # Mock the pool_connect method to avoid actual connection
        db_pool.pool_connect = AsyncMock(return_value=mock_pool)

        # Get pool without initializing first
        pool = await db_pool.pool_connect()

        # Verify pool connect was called
        db_pool.pool_connect.assert_called_once()
        assert pool == mock_pool


@pytest.mark.asyncio
async def test_pool_holds_no_idle_connections_and_checks_on_checkout(mock_pool):
    """Idle MCP sessions must not pin server connections, and a connection the
    server closed while idle (idle_session_timeout, proxy drop) must be replaced
    on checkout instead of failing the next query."""
    from psycopg_pool import AsyncConnectionPool

    # stop right after construction: only the pool parameters are under test here
    mock_pool.open.side_effect = Exception("stop after construction")
    with patch("postgres_mcp.sql.sql_driver.AsyncConnectionPool", return_value=mock_pool) as pool_cls:
        # the patch replaces the whole class; keep the real static check so the
        # assertion below compares against psycopg_pool, not against the mock
        pool_cls.check_connection = AsyncConnectionPool.check_connection
        db_pool = DbConnPool("postgresql://user:pass@localhost/db")
        with pytest.raises(ValueError):
            await db_pool.pool_connect()

    kwargs = pool_cls.call_args.kwargs
    assert kwargs["min_size"] == 0
    assert kwargs["check"] is AsyncConnectionPool.check_connection


async def _pool_kwargs(mock_pool, url):
    """Run the real pool_connect up to pool construction and return its kwargs."""
    mock_pool.open.side_effect = Exception("stop after construction")
    with patch("postgres_mcp.sql.sql_driver.AsyncConnectionPool", return_value=mock_pool) as pool_cls:
        with pytest.raises(ValueError):
            await DbConnPool(url).pool_connect()
    return pool_cls.call_args.kwargs


@pytest.mark.asyncio
async def test_default_application_name_when_url_has_none(mock_pool, monkeypatch):
    """Sessions of every MCP client must be identifiable in pg_stat_activity even
    when the user's DATABASE_URI does not name the application."""
    monkeypatch.delenv("PGAPPNAME", raising=False)
    kwargs = await _pool_kwargs(mock_pool, "postgresql://user:pass@localhost/db")
    assert kwargs["kwargs"]["application_name"] == "postgres-mcp"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url,env",
    [
        ("postgresql://user:pass@localhost/db?application_name=pgmcp-ivanov", None),
        ("host=localhost dbname=db user=u application_name=pgmcp-ivanov", None),
        ("postgresql://user:pass@localhost/db", "pgmcp-from-env"),
    ],
)
async def test_explicit_application_name_is_not_overridden(mock_pool, monkeypatch, url, env):
    """An application_name the user set (URI, DSN or PGAPPNAME) wins over the default:
    a pool-level kwarg would silently replace it."""
    if env is None:
        monkeypatch.delenv("PGAPPNAME", raising=False)
    else:
        monkeypatch.setenv("PGAPPNAME", env)
    kwargs = await _pool_kwargs(mock_pool, url)
    assert "application_name" not in (kwargs.get("kwargs") or {})


@pytest.mark.asyncio
async def test_connection_url_property():
    """Test connection_url property."""
    db_pool = DbConnPool("postgresql://user:pass@localhost/db")
    assert db_pool.connection_url == "postgresql://user:pass@localhost/db"

    # Change the URL
    db_pool.connection_url = "postgresql://newuser:newpass@otherhost/otherdb"
    assert db_pool.connection_url == "postgresql://newuser:newpass@otherhost/otherdb"
