"""Middleware bot. Urutan pemasangan penting: error_handler terluar, lalu
auth, lalu rate_limit."""

from app.bot.middlewares.auth import AuthMiddleware  # noqa: F401
from app.bot.middlewares.error_handler import ErrorHandlerMiddleware  # noqa: F401
from app.bot.middlewares.rate_limit import RateLimitMiddleware  # noqa: F401
