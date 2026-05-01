"""Exponential backoff retry decorator for the AI-DLC Strands Agent."""

import functools
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

from app.errors import SkillOutputError

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def retry_with_backoff(
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    operation_name: str | None = None,
) -> Callable[[F], F]:
    """
    Decorator factory that retries a callable with exponential backoff.

    Args:
        max_attempts: Maximum number of invocation attempts (default 3).
        initial_delay: Delay in seconds before the second attempt (default 1.0).
                       Subsequent delays double: 1s, 2s, 4s, ...
        operation_name: Human-readable name for the operation (defaults to function name).

    Returns:
        Decorator that wraps the callable with retry logic.

    Raises:
        SkillOutputError: When all attempts are exhausted.
    """

    def decorator(func: F) -> F:
        op_name = operation_name or func.__name__

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_error: Exception | None = None
            delay = initial_delay

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    timestamp = datetime.now(timezone.utc).isoformat()
                    if attempt < max_attempts:
                        logger.warning(
                            "Retry attempt %d/%d for '%s' — reason: %s — timestamp: %s",
                            attempt,
                            max_attempts,
                            op_name,
                            str(exc),
                            timestamp,
                        )
                        time.sleep(delay)
                        delay *= 2
                    else:
                        logger.error(
                            "All %d attempts exhausted for '%s' — last error: %s — timestamp: %s",
                            max_attempts,
                            op_name,
                            str(exc),
                            timestamp,
                        )

            raise SkillOutputError(
                operation_name=op_name,
                attempts=max_attempts,
                last_error=str(last_error),
            )

        return wrapper  # type: ignore[return-value]

    return decorator
