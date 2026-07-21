class LLMError(Exception):
    """Base error for all LLM provider failures."""


class LLMConnectionError(LLMError):
    pass


class LLMTimeoutError(LLMError):
    pass


class LLMAuthenticationError(LLMError):
    pass


class LLMRateLimitError(LLMError):
    pass


class LLMOutputError(LLMError):
    """Raised when a structured-output call can't be parsed into the requested schema."""
