import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from proxy.config import Config, get_config
from proxy.whitelist import endpoint_action, model_allowed, EndpointAction
from proxy.filters import check_jailbreak, check_architecture
from proxy.rate_limit import TokenBucket
from proxy.tool_loop import run_tool_loop
from proxy.streaming import stream_from_ollama


def create_app(config: Config | None = None) -> FastAPI:
    cfg = config or get_config()
    app = FastAPI()
    rate_limiter = TokenBucket(burst=cfg.rate_limit_burst, per_minute=cfg.rate_limit_per_min)

    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        # Blocked API endpoints are rejected before consuming a rate limit token
        path = request.url.path
        if path.startswith("/api/"):
            action = endpoint_action(path)
            if action == EndpointAction.BLOCKED:
                return JSONResponse({"error": "endpoint not permitted"}, status_code=403)
        if not rate_limiter.consume():
            return JSONResponse({"error": "rate limit exceeded"}, status_code=429)
        return await call_next(request)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "DELETE", "PUT", "HEAD"])
    async def proxy_route(path: str, request: Request):
        full_path = f"/api/{path}"
        action = endpoint_action(full_path)

        if action == EndpointAction.BLOCKED:
            return JSONResponse({"error": "endpoint not permitted"}, status_code=403)

        if action == EndpointAction.PASSTHROUGH:
            return await _passthrough(full_path, request, cfg.ollama_host)

        # GENERATION path
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)

        model = body.get("model", "")
        if not model_allowed(model, cfg.allowed_models):
            return JSONResponse({"error": f"model '{model}' not permitted"}, status_code=403)

        messages = body.get("messages", [])
        user_content = _extract_user_content(messages)

        for check_fn in [check_jailbreak, check_architecture]:
            result = check_fn(user_content)
            if result.blocked:
                return JSONResponse({
                    "model": model,
                    "message": {"role": "assistant", "content": result.refusal},
                    "done": True,
                })

        messages = _inject_system_prompt(messages, cfg.system_prompt)
        body["messages"] = messages

        try:
            final_messages, had_tool_calls = await run_tool_loop(messages, model, cfg)
        except Exception as e:
            return JSONResponse({"error": f"tool loop error: {e}"}, status_code=500)

        if had_tool_calls:
            last = final_messages[-1]
            return JSONResponse({
                "model": model,
                "message": last,
                "done": True,
            })

        # No tool calls — stream fresh response
        body["messages"] = final_messages
        return StreamingResponse(
            stream_from_ollama(cfg.ollama_host, full_path, body),
            media_type="application/x-ndjson",
        )

    return app


async def _passthrough(path: str, request: Request, ollama_host: str) -> Response:
    body = await request.body()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.request(
            method=request.method,
            url=f"{ollama_host}{path}",
            content=body,
            headers={"Content-Type": "application/json"} if body else {},
        )
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/json"),
    )


def _extract_user_content(messages: list[dict]) -> str:
    parts = [m.get("content", "") for m in messages if m.get("role") == "user"]
    return " ".join(str(p) for p in parts if p)


def _inject_system_prompt(messages: list[dict], system_prompt: str) -> list[dict]:
    if messages and messages[0].get("role") == "system":
        return messages
    return [{"role": "system", "content": system_prompt}] + messages


# Module-level app instance for uvicorn
app = create_app()
