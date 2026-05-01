"""Shared exception types for the AI-DLC Strands Agent."""


class ConfigurationError(Exception):
    """Raised when required environment variables are missing at startup."""

    def __init__(self, missing_vars: list[str]) -> None:
        self.missing_vars = missing_vars
        vars_str = ", ".join(missing_vars)
        super().__init__(
            f"Missing required environment variable(s): {vars_str}. "
            "Set them before running the agent."
        )


class SkillOutputError(Exception):
    """Raised when a skill's retry loop is exhausted without producing valid output."""

    def __init__(self, operation_name: str, attempts: int, last_error: str) -> None:
        self.operation_name = operation_name
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(
            f"Skill '{operation_name}' failed after {attempts} attempt(s). "
            f"Last error: {last_error}"
        )
