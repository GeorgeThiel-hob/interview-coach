"""Errors raised by the gateway and its providers."""


class GatewayError(Exception):
    """Base class for gateway errors."""


class UnsafeTextError(GatewayError):
    """Raw (not pseudonymised) text was about to be sent to an external provider."""


class LocalModelOffline(GatewayError):
    """The local Ollama node (the laptop) cannot be reached."""


class BudgetExceeded(GatewayError):
    """A per-run or daily budget cap would be exceeded."""


class ProviderError(GatewayError):
    """A provider call failed and should not be retried (bad request, auth, refusal...)."""


class TransientProviderError(ProviderError):
    """A provider call failed in a way worth retrying (rate limit, timeout, 5xx, network)."""
