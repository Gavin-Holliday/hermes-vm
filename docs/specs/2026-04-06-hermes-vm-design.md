# Hermes VM Design

**Date**: 2026-04-06  
**Status**: Approved  
**Scope**: Secure, self-hosted Hermes (Nous Hermes 3) agent with Ollama on Apple Silicon Mac Mini, isolated in a Podman VM, with Discord + WebUI interfaces, SearXNG for free web search, persistent services, Ansible IaC, and a public GitHub repo with pre-built container images and automated CI/CD.

---

## Context & Requirements

**Goal:** Replace the broken OpenClaw setup with a clean, secure Hermes agent that:
- Uses Nous Hermes 3 (via Ollama on the host with Metal acceleration)
- Runs all agent services in an isolated Podman VM
- Supports tool use (web search via SearXNG)
- Is accessible via Discord and Open WebUI (over ZeroTier VPN)
- Persists and auto-restarts on both host and VM reboot
- Is fully provisioned via Ansible — reproducible on any Apple Silicon Mac
- Is publishable as a public GitHub repo with pre-built container images

**Host:** Mac Mini, Apple Silicon, 48GB RAM, macOS, ZeroTier VPN

---

## Architecture

```
macOS Host (48GB RAM)
├── launchd: auto-starts Ollama + hermes-machine on boot
├── Ollama (Metal, OLLAMA_HOST=0.0.0.0:11434)
├── pf firewall: port 11434 only reachable from localhost + ZeroTier + VM bridge
│
└── hermes-machine (Podman VM, 6GB RAM, 4 CPUs, 40GB disk)
    ├── systemd + quadlets: auto-restarts all containers
    ├── hermes.network (internal Podman network)
    ├── hermes-proxy     (FastAPI, :8000 — only port exposed to VM host)
    ├── hermes-webui     (Open WebUI, :3000 — forwarded to host, VPN-accessible)
    ├── hermes-searxng   (SearXNG, :8080 — internal network only)
    └── hermes-discord   (Discord bot — outbound only)
```

**Data flow:**
1. User sends Discord message or opens WebUI over ZeroTier
2. Request hits `hermes-proxy`
3. Proxy runs: jailbreak filter → architecture/host-info block → model whitelist check → endpoint whitelist check
4. If Hermes requests a tool call → proxy calls SearXNG internally on `hermes.network`
5. Proxy injects tool schema + system prompt, forwards to `host.containers.internal:11434`
6. Ollama runs inference with Metal acceleration, streams response back
7. Proxy streams response to Discord/WebUI

---

## Security Model

### Host Firewall (pf)

Port 11434 (Ollama) is locked to three sources only. All other inbound traffic to that port is blocked regardless of existing ZeroTier rules.

```
# /etc/pf.d/hermes.conf
# Variables substituted by Ansible from inventory vars
# ZT_INTERFACE = ztXXXXXXXX  (your ZeroTier interface name)
# ZT_SUBNET    = 10.x.x.0/24  (your ZeroTier network subnet)
# VM_SUBNET    = 192.168.64.0/24  (Podman machine bridge subnet)

# Block Ollama from everything by default
block in quick proto tcp to any port 11434

# Allow: localhost, ZeroTier, VM bridge only
pass in quick on lo0 proto tcp from 127.0.0.1 to any port 11434
pass in quick on $ZT_INTERFACE proto tcp from $ZT_SUBNET to any port 11434
pass in quick proto tcp from $VM_SUBNET to any port 11434
```

WebUI (port 3000) is forwarded from the VM to the host. Existing ZeroTier rules allow VPN clients to reach the host — no additional pf rules needed for WebUI access.

### Ollama Binding

Ollama must listen on `0.0.0.0:11434` so the VM bridge can reach it. The `pf` rules above compensate by blocking all other sources. Set via `OLLAMA_HOST=0.0.0.0` in the launchd plist, managed by Ansible.

### VM Isolation

The Podman machine (QEMU) provides hypervisor-level isolation. A compromised Hermes agent inside the VM:
- Cannot access the host filesystem
- Cannot execute commands on the host Mac
- Cannot reach any host port except 11434 (enforced by `pf`)
- Cannot pull new Ollama models (blocked by proxy endpoint whitelist)
- Cannot use non-whitelisted models (blocked by proxy model whitelist)

### Internal Network

All VM containers run on `hermes.network` (internal Podman network). Only `hermes-proxy` (:8000) and `hermes-webui` (:3000) have ports forwarded to the VM host. SearXNG is never reachable from outside the VM.

---

## Security Proxy (Rebuilt)

The old proxy was broken — it forwarded raw prompts to Ollama without tool-call handling. Full rebuild with these layers:

| Layer | Behavior |
|-------|----------|
| **Streaming passthrough** | SSE streaming from Ollama forwarded in real time (not buffered) |
| **Tool schema injection** | Injects SearXNG `web_search` tool definition into every `/api/chat` request |
| **System prompt injection** | Injects hardcoded system prompt defining Hermes's role and capabilities |
| **Architecture/host filter** | Prompts asking about host OS, VM, ports, IP addresses, architecture → canned refusal, not forwarded |
| **Jailbreak filter** | Pattern-based filter (carried over from old proxy) |
| **Endpoint whitelist** | Only `/api/chat` and `/api/generate` forwarded; `/api/pull`, `/api/delete`, `/api/copy`, `/api/push` → 403 |
| **Model whitelist** | Only models listed in `ALLOWED_MODELS` forwarded; others → 403 |
| **Rate limiting** | Token bucket (configurable burst + rate, carried over from old proxy) |

### Tool Call Loop

The proxy manages the full multi-turn tool use loop:
1. Send request to Ollama with `tools:` parameter
2. If Ollama responds with a `tool_calls` field → proxy executes the tool (calls SearXNG internally)
3. Proxy appends tool result as a `tool` role message
4. Proxy re-sends to Ollama with updated context
5. Loop until Ollama responds with a plain `assistant` message
6. Stream final response to caller

---

## VM Components

### hermes-machine (Podman Machine)

| Setting | Value |
|---------|-------|
| RAM | 6GB |
| CPUs | 4 |
| Disk | 40GB |
| Name | `hermes-machine` |

### Quadlets (systemd units)

Each container is defined as a `.container` quadlet file in `/etc/containers/systemd/` inside the VM. systemd manages lifecycle — auto-start on boot, restart on failure. Ansible deploys all quadlet files via SSH into the VM.

All containers carry `io.containers.autoupdate=registry` label so a daily systemd timer running `podman auto-update` pulls fresh images from ghcr.io automatically.

**hermes-proxy.container**
- Image: `ghcr.io/{owner}/hermes-proxy:latest`
- Port: `8000:8000`
- Env: `ALLOWED_MODELS`, `OLLAMA_HOST`, `RATE_LIMIT_*`, `SYSTEM_PROMPT`
- Network: `hermes.network`
- Restart: `always`

**hermes-webui.container**
- Image: `ghcr.io/open-webui/open-webui:latest`
- Port: `3000:8080`
- Volume: `hermes-webui-data:/app/backend/data`
- Env: `OLLAMA_BASE_URL=http://hermes-proxy:8000`, `WEBUI_AUTH=true`
- Network: `hermes.network`
- Restart: `always`

**hermes-searxng.container**
- Image: `docker.io/searxng/searxng:latest`
- No external port (internal only)
- Volume: `hermes-searxng-config:/etc/searxng`
- Network: `hermes.network`
- Restart: `always`

**hermes-discord.container**
- Image: `ghcr.io/{owner}/hermes-discord:latest`
- No ports (outbound only)
- Env: `DISCORD_TOKEN`, `DISCORD_CHANNEL_ID`, `PROXY_URL=http://hermes-proxy:8000`
- Network: `hermes.network`
- Restart: `always`

### Named Volumes

| Volume | Purpose |
|--------|---------|
| `hermes-webui-data` | Open WebUI: user accounts, chat history, settings |
| `hermes-searxng-config` | SearXNG: engine config, settings.yml |

Volumes persist across container image updates and VM restarts.

### Log Rotation

systemd journal inside the VM capped at 500MB:
```
SystemMaxUse=500M
MaxRetentionSec=2weeks
```

---

## Host Services (launchd)

Two launchd plists deployed by Ansible to `~/Library/LaunchAgents/`:

**com.hermes.ollama.plist**
- Runs: `ollama serve`
- Env: `OLLAMA_HOST=0.0.0.0`
- `KeepAlive: true` — restarts on crash
- `RunAtLoad: true` — starts on login

**com.hermes.podman-machine.plist**
- Runs: `podman machine start hermes-machine`
- `RunAtLoad: true` — starts on login
- `KeepAlive: true` — restarts if the machine exits unexpectedly

---

## IaC & Tooling

### Ansible

Ansible is the single source of truth for provisioning. All host and VM setup is defined as idempotent playbooks — safe to re-run for updates or fresh installs.

**Playbook structure:**

```
ansible/
├── site.yml                  # master playbook (runs all roles)
├── inventory/
│   └── host.yml              # localhost + hermes-machine (SSH via 127.0.0.1:$(podman machine ssh-config hermes-machine | grep Port))
├── group_vars/
│   └── all.yml               # non-secret defaults
├── host_vars/
│   └── localhost.yml         # host-specific vars (auto-generated from .env by just setup)
└── roles/
    ├── prerequisites/        # brew bundle, verify tools installed
    ├── ollama/               # launchd plist, OLLAMA_HOST, model pulls
    ├── firewall/             # pf rules template + load
    ├── podman-machine/       # create/start hermes-machine, launchd plist
    ├── vm-quadlets/          # SSH into VM, deploy quadlet files + env file
    ├── vm-volumes/           # create named volumes, seed SearXNG config
    └── vm-autoupdate/        # systemd timer for podman auto-update + journald caps
```

Running `just setup` executes `ansible-playbook ansible/site.yml`. Running `just update` runs the same playbook — Ansible's idempotency means only what changed gets updated.

### Just (task runner)

`justfile` provides simple commands so contributors don't need to remember Ansible syntax:

```makefile
setup:          # first-time install (brew bundle + ansible-playbook site.yml)
update:         # pull latest + re-run playbook
logs:           # tail systemd journal from VM
restart:        # restart all containers in VM
status:         # show container + service status
ssh:            # SSH into hermes-machine
pull-models:    # ollama pull for all ALLOWED_MODELS
teardown:       # stop + delete hermes-machine (keeps volumes)
```

### Brewfile

Lists all required host prerequisites — one `brew bundle` installs everything:

```ruby
brew "podman"
brew "podman-compose"
brew "ollama"
brew "ansible"
brew "just"
brew "gh"
brew "age"        # secrets encryption
cask "podman-desktop"   # optional GUI
```

### age (secrets encryption)

`.env` files contain sensitive values (Discord token etc.). `age` encrypts the `.env` so users can optionally commit an encrypted version to a private fork without exposing secrets.

- `just encrypt-env` → produces `.env.age` (safe to commit to private fork)
- `just decrypt-env` → restores `.env` from `.env.age` using your age key
- Public repo ships only `.env.example` — the age workflow is opt-in

### Renovate (dependency updates)

Renovate GitHub App is configured on the repo to open automatic PRs when:
- Container image digests update (Open WebUI, SearXNG)
- Python dependency versions in `requirements.txt` update
- GitHub Actions runner versions update

`renovate.json` ships in the repo root with sensible defaults (automerge patch versions, group minor updates into weekly PRs).

---

## GitHub Repository

### Repo: `hermes-vm`

Public repo. Anyone with an Apple Silicon Mac can clone, fill in `.env`, and run `just setup`.

```
hermes-vm/
├── README.md
├── justfile                          # just commands
├── Brewfile                          # brew bundle prerequisites
├── .env.example                      # all config as placeholders
├── .gitignore                        # excludes .env, .env.age
├── renovate.json                     # Renovate dependency update config
│
├── ansible/
│   ├── site.yml
│   ├── inventory/host.yml
│   ├── group_vars/all.yml
│   └── roles/
│       ├── prerequisites/
│       ├── ollama/
│       ├── firewall/
│       ├── podman-machine/
│       ├── vm-quadlets/
│       ├── vm-volumes/
│       └── vm-autoupdate/
│
├── vm/
│   ├── quadlets/
│   │   ├── hermes.network
│   │   ├── hermes-proxy.container
│   │   ├── hermes-webui.container
│   │   ├── hermes-searxng.container
│   │   └── hermes-discord.container
│   ├── proxy/
│   │   ├── Dockerfile
│   │   ├── main.py
│   │   ├── filters.py
│   │   ├── tools.py
│   │   └── requirements.txt
│   ├── discord-bot/
│   │   ├── Dockerfile
│   │   ├── bot.py
│   │   └── requirements.txt
│   └── searxng/
│       └── settings.yml              # reused from existing project
│
├── host/
│   └── firewall/
│       └── hermes.pf.conf.j2         # Jinja2 template, rendered by Ansible
│
└── .github/
    └── workflows/
        ├── build-images.yml          # push to main → build + push to ghcr.io
        └── release.yml               # tag v*.*.* → versioned release + GitHub Release
```

### .env.example

```bash
# ZeroTier
ZT_INTERFACE=ztXXXXXXXX
ZT_SUBNET=10.x.x.0/24

# Podman machine bridge (default for Apple Silicon: 192.168.64.0/24)
VM_SUBNET=192.168.64.0/24

# Ollama
OLLAMA_HOST=0.0.0.0
ALLOWED_MODELS=hermes3,gemma4:27b

# Discord
DISCORD_TOKEN=your-bot-token-here
DISCORD_CHANNEL_ID=your-channel-id-here

# Proxy
RATE_LIMIT_BURST=20
RATE_LIMIT_PER_MIN=5
SYSTEM_PROMPT="You are Hermes, a helpful assistant..."

# GitHub (for image pulls + repo)
GHCR_OWNER=your-github-username
```

### GitHub Actions Workflows

**build-images.yml** (on push to `main`):
1. Build `hermes-proxy` image (linux/arm64 — Apple Silicon only; Intel Mac not supported)
2. Build `hermes-discord` image (linux/arm64)
3. Push to `ghcr.io/{owner}/hermes-proxy:latest` + `:sha-{commit}`
4. Images public — no auth required to pull

**release.yml** (on tag `v*.*.*`):
1. Build both images
2. Push with version tag (`:v1.0.0`) + `:latest`
3. Create GitHub Release with auto-generated changelog

### Auto-Update in VM

A systemd timer runs `podman auto-update` daily. Containers with `io.containers.autoupdate=registry` are checked against ghcr.io — if a newer image exists the container restarts with it. Zero manual intervention.

---

## Setup Flow

```bash
# One-time bootstrap (just isn't available yet)
brew install just
gh auth login
cp .env.example .env    # fill in your values

# Install all other prerequisites + provision everything
just setup              # runs brew bundle then ansible-playbook site.yml end-to-end
```

Ansible `site.yml` execution order:
1. `prerequisites` role — verify all tools present
2. `ollama` role — deploy launchd plist, set `OLLAMA_HOST=0.0.0.0`, pull allowed models
3. `firewall` role — render pf template with env vars, load rules, persist across reboots
4. `podman-machine` role — create `hermes-machine` (6GB/4CPU/40GB), deploy launchd plist
5. `vm-quadlets` role — SSH into VM, write quadlet files + systemd env file, daemon-reload
6. `vm-volumes` role — create named volumes, seed SearXNG `settings.yml`
7. `vm-autoupdate` role — install systemd timer, cap journald

**Update flow:**
```bash
git pull && just update    # idempotent — only changed resources are updated
```

---

## Resource Budget

| Component | Location | RAM |
|-----------|----------|-----|
| Ollama (Metal inference) | Host | ~2GB active |
| macOS + other host processes | Host | ~10GB |
| hermes-proxy | VM | ~300MB |
| hermes-webui | VM | ~800MB |
| hermes-searxng | VM | ~500MB |
| hermes-discord | VM | ~200MB |
| VM OS + systemd | VM | ~1.5GB |
| **VM Total** | | **~3.3GB / 6GB** |
| **Host Total** | | **~12GB / 48GB** |

Gemma 4 27B (~18GB in 4-bit quantization): loaded into Apple Silicon unified memory on demand by Ollama, released when idle. Fits comfortably within 48GB.

---

## Success Criteria

- [ ] `just setup` completes end-to-end on a fresh Apple Silicon Mac
- [ ] Hermes responds in Discord with working tool use (web search via SearXNG)
- [ ] Open WebUI accessible over ZeroTier, login required
- [ ] Port 11434 unreachable from any source except localhost, ZeroTier subnet, VM bridge
- [ ] VM reboot → all containers restart automatically via quadlets
- [ ] Host reboot → Ollama + VM restart automatically via launchd
- [ ] Prompt asking about host/VM architecture returns canned refusal
- [ ] Attempt to pull a model via Ollama API returns 403
- [ ] Attempt to use non-whitelisted model returns 403
- [ ] `git push` to `main` triggers image build + push to ghcr.io
- [ ] `podman auto-update` timer pulls new images daily without intervention
- [ ] `just update` re-runs Ansible idempotently without breaking running services
- [ ] Renovate opens PRs for dependency updates automatically
