from enum import Enum


class EndpointAction(Enum):
    BLOCKED = "blocked"
    GENERATION = "generation"
    PASSTHROUGH = "passthrough"


_BLOCKED = {"/api/pull", "/api/delete", "/api/copy", "/api/push"}
_GENERATION = {"/api/chat", "/api/generate"}
_PASSTHROUGH = {"/api/tags", "/api/show", "/api/version", "/api/ps", "/api/blobs"}


def endpoint_action(path: str) -> EndpointAction:
    if path in _BLOCKED:
        return EndpointAction.BLOCKED
    if path in _GENERATION:
        return EndpointAction.GENERATION
    if path in _PASSTHROUGH:
        return EndpointAction.PASSTHROUGH
    return EndpointAction.BLOCKED


def model_allowed(model: str, allowed_models: list[str]) -> bool:
    return model.strip() in [m.strip() for m in allowed_models]
