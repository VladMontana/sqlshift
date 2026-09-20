from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from sqlshift.server import create_app


def test_health_check() -> None:
    """Проверяем эндпоинт healthcheck."""
    app = create_app()
    client = TestClient(app)

    response = client.get("/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"
    assert data["postgres_conf"] is False
    assert data["clickhouse_conf"] is False


def test_route_oltp_query() -> None:
    """Транзакционный запрос отправляется в PostgreSQL без изменений."""
    app = create_app()
    client = TestClient(app)

    response = client.post("/v1/route", json={"sql": "SELECT id, name FROM users WHERE id = 42"})
    assert response.status_code == 200
    data = response.json()
    assert data["target"] == "postgresql"
    assert data["is_analytical"] is False
    assert "users WHERE id = 42" in data["sql"]


def test_route_olap_query() -> None:
    """Аналитический запрос маршрутизируется в ClickHouse с транспайлингом."""
    app = create_app()
    client = TestClient(app)

    sql = "SELECT date_trunc('month', created_at), count(*) FROM events GROUP BY 1"
    response = client.post("/v1/route", json={"sql": sql})
    assert response.status_code == 200
    data = response.json()
    assert data["target"] == "clickhouse"
    assert data["is_analytical"] is True
    # Проверяем, что в ClickHouse попал соответствующий диалект
    assert "toStartOfMonth" in data["sql"] or "dateTrunc" in data["sql"]


def test_route_invalid_sql_returns_400() -> None:
    """Синтаксическая ошибка в SQL возвращает HTTP 400 и структурированный JSON."""
    app = create_app()
    client = TestClient(app)

    response = client.post("/v1/route", json={"sql": "SELECT FROM WHERE"})
    assert response.status_code == 400
    data = response.json()
    assert data["error"] == "SQLParsingError"
    assert "message" in data


def test_query_without_db_returns_503() -> None:
    """Попытка выполнить запрос без настроенных БД возвращает 503."""
    app = create_app()
    client = TestClient(app)

    response = client.post("/v1/query", json={"sql": "SELECT 1"})
    assert response.status_code == 503
    assert "Database client not configured" in response.json()["detail"]


def test_query_with_mock_client() -> None:
    """Исполнение запроса с внедрением mock-клиента (Dependency Injection)."""
    mock_client = AsyncMock()
    mock_client.fetch.return_value = [{"id": 1, "username": "alex"}]

    # Передаем мок в фабрику!
    app = create_app(client=mock_client)
    client = TestClient(app)

    response = client.post("/v1/query", json={"sql": "SELECT id, username FROM users WHERE id = 1"})
    assert response.status_code == 200
    data = response.json()
    assert data["target"] == "postgresql"
    assert data["row_count"] == 1
    assert data["data"] == [{"id": 1, "username": "alex"}]
    assert data["exec_time_ms"] >= 0.0

    # Проверяем, что мок был вызван с нужным запросом
    mock_client.fetch.assert_awaited_once_with("SELECT id, username FROM users WHERE id = 1")
