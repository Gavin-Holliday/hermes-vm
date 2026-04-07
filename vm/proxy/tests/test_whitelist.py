from proxy.whitelist import endpoint_action, model_allowed, EndpointAction


# --- Endpoint whitelist ---

def test_pull_is_blocked():
    assert endpoint_action("/api/pull") == EndpointAction.BLOCKED

def test_delete_is_blocked():
    assert endpoint_action("/api/delete") == EndpointAction.BLOCKED

def test_copy_is_blocked():
    assert endpoint_action("/api/copy") == EndpointAction.BLOCKED

def test_push_is_blocked():
    assert endpoint_action("/api/push") == EndpointAction.BLOCKED

def test_unknown_endpoint_is_blocked():
    assert endpoint_action("/api/unknown") == EndpointAction.BLOCKED

def test_chat_is_generation():
    assert endpoint_action("/api/chat") == EndpointAction.GENERATION

def test_generate_is_generation():
    assert endpoint_action("/api/generate") == EndpointAction.GENERATION

def test_tags_is_passthrough():
    assert endpoint_action("/api/tags") == EndpointAction.PASSTHROUGH

def test_show_is_passthrough():
    assert endpoint_action("/api/show") == EndpointAction.PASSTHROUGH

def test_version_is_passthrough():
    assert endpoint_action("/api/version") == EndpointAction.PASSTHROUGH

def test_ps_is_passthrough():
    assert endpoint_action("/api/ps") == EndpointAction.PASSTHROUGH


# --- Model whitelist ---

def test_allowed_model_passes():
    assert model_allowed("hermes3", ["hermes3", "gemma4:27b"]) is True

def test_second_allowed_model_passes():
    assert model_allowed("gemma4:27b", ["hermes3", "gemma4:27b"]) is True

def test_unlisted_model_blocked():
    assert model_allowed("llama3", ["hermes3", "gemma4:27b"]) is False

def test_model_whitelist_strips_whitespace():
    assert model_allowed("hermes3", [" hermes3 ", "gemma4:27b"]) is True

def test_empty_allowed_list_blocks_all():
    assert model_allowed("hermes3", []) is False
