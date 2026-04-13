"""Persistent cron scheduler for agent-created tasks.

Tasks are stored in DATA_PATH/schedules.json and survive container restarts.
Each task fires by running its prompt through the proxy tool loop and posting
the result to a Discord channel.
"""
import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime

import httpx
from croniter import croniter

log = logging.getLogger("hermes.scheduler")

_STORE_FILE = None  # Set at startup from config


def _store_path(config) -> str:
    return os.path.join(config.data_path, "schedules.json")


def _load(config) -> dict:
    path = _store_path(config)
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(config, store: dict) -> None:
    path = _store_path(config)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(store, f, indent=2)


def schedule_create(config, cron: str, prompt: str, channel: str, label: str = "") -> dict:
    """Create a new scheduled task. Returns the job dict."""
    if not croniter.is_valid(cron):
        raise ValueError(f"Invalid cron expression: {cron!r}")
    store = _load(config)
    job_id = str(uuid.uuid4())[:8]
    now = time.time()
    next_run = croniter(cron, now).get_next(float)
    job = {
        "id": job_id,
        "cron": cron,
        "prompt": prompt,
        "channel": channel,
        "label": label or prompt[:60],
        "created_at": datetime.utcnow().isoformat(),
        "last_run": None,
        "next_run": next_run,
        "run_count": 0,
    }
    store[job_id] = job
    _save(config, store)
    return job


def schedule_list(config) -> list:
    """Return all scheduled tasks."""
    return list(_load(config).values())


def schedule_delete(config, job_id: str) -> bool:
    """Delete a task by ID. Returns True if found and deleted."""
    store = _load(config)
    if job_id not in store:
        return False
    del store[job_id]
    _save(config, store)
    return True


async def _run_job(job: dict, config) -> None:
    """Execute a job by sending its prompt through the proxy tool loop."""
    from proxy.tool_loop import run_tool_loop
    messages = [
        {"role": "system", "content": config.system_prompt},
        {"role": "user", "content": job["prompt"]},
    ]
    model = os.getenv("MODEL", config.allowed_models[0])
    try:
        final_messages, _ = await run_tool_loop(messages, model, config)
        last = final_messages[-1]
        response_text = last.get("content", "") if isinstance(last, dict) else str(last)
    except Exception as e:
        log.error("Scheduled job %s failed in tool loop: %s", job["id"], e)
        response_text = f"Scheduled task failed: {e}"

    # Post result to Discord
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{config.discord_bot_api_url}/send",
                json={"channel_name": job["channel"], "content": response_text[:2000]},
            )
    except Exception as e:
        log.warning("Scheduler could not post job %s result to Discord: %s", job["id"], e)


async def scheduler_loop(config) -> None:
    """Background loop — checks every 30s, fires any jobs whose next_run has passed."""
    log.info("Scheduler started")
    while True:
        try:
            now = time.time()
            store = _load(config)
            changed = False
            for job_id, job in list(store.items()):
                if job["next_run"] <= now:
                    log.info("Firing scheduled job %s: %s", job_id, job["label"])
                    asyncio.create_task(_run_job(job, config))
                    job["last_run"] = datetime.utcnow().isoformat()
                    job["run_count"] += 1
                    job["next_run"] = croniter(job["cron"], now).get_next(float)
                    changed = True
            if changed:
                _save(config, store)
        except Exception as e:
            log.error("Scheduler loop error: %s", e)
        await asyncio.sleep(30)
