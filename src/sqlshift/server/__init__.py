"""Standalone HTTP gateway server on FastAPI."""

try:
    from sqlshift.server.app import app, create_app
    from sqlshift.server.config import ServerSettings
except ImportError as exc:
    raise ImportError(
        "Для использования Gateway API необходимо установить зависимости сервера: "
        "pip install 'sqlshift[server]'"
    ) from exc

__all__ = ["app", "create_app", "ServerSettings"]
