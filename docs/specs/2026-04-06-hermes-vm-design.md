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

Port 11434 (Ollama) is locked to three sources only. All other inbound traffic to that port is blocked.

**Rule order matters:** `quick` rules exit on first match, so passes must come before the block:

```
# /etc/pf.d/hermes.conf
# Variables substituted by Ansible from inventory vars:
# ZT_INTERFACE     = ztXXXXXXXX        (ZeroTier interface name)
# ZT_SUBNET        = 10.x.x.0/24       (ZeroTier network subnet)
# VM_BRIDGE_IFACE  = bridge100          (Podman machine bridge — Ansible discovers this
#                                        via `podman machine inspect hermes-machine`)
# VM_SUBNET        = 192.168.64.0/24   (Podman machine bridge subnet)

# Allow first, block everything else — order is critical with pf quick rules
pass in quick on lo0            proto tcp from 127.0.0.1  to any port 11434
pass in quick on $ZT_INTERFACE  proto tcp from $ZT_SUBNET  to any port 11434
pass in quick on $VM_BRIDGE_IFACE proto tcp from $VM_SUBNET to any port 11434
block in quick                  proto tcp                  to any port 11434
```

The VM bridge interface (`VM_BRIDGE_IFACE`) is pinned to the interface name, not just the subnet, to prevent IP spoofing bypasses. Ansible discovers the actual interface name at provisioning time via `podman machine inspect`.

**pf persistence risk:** macOS does not persist custom pf rules across system updates — they can silently revert to defaults, leaving Ollama exposed on all interfaces. `just status` includes a pf rule check and warns loudly if the hermes rules are not loaded. The Ansible `firewall` role also sets up a launchd plist to reload `hermes.pf.conf` at boot.

WebUI (port 3000) is forwarded from the VM to the host. Existing ZeroTier rules allow VPN clients to reach the host — no additional pf rules needed for WebUI access.

### Ollama Binding

Ollama listens on `0.0.0.0:11434` so the VM bridge can reach it. The `pf` rules above block all sources except the three whitelisted ones. Set via `OLLAMA_HOST=0.0.0.0` in the launchd plist.

**Risk:** If pf rules are ever flushed (macOS update, manual reset), Ollama becomes reachable on all interfaces. The launchd boot plist for pf and the `just status` check together mitigate this.

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
| **System prompt injection** | System prompt is hardcoded in the proxy image; `SYSTEM_PROMPT_OVERRIDE` env var optionally replaces it (plain string, no shell quoting — loaded from a file path to avoid quoting issues) |
| **Architecture/host filter** | Prompts asking about host OS, VM, ports, IP addresses, architecture → canned refusal, not forwarded |
| **Jailbreak filter** | Pattern-based filter (carried over from old proxy) |
| **Endpoint whitelist — write-blocked** | `/api/pull`, `/api/delete`, `/api/copy`, `/api/push` → 403 always |
| **Endpoint whitelist — read-only pass-through** | `/api/tags`, `/api/show`, `/api/version`, `/api/ps` → forwarded without filters (needed by Open WebUI for model listing and health checks); model whitelist still applied to `/api/show` |
| **Generation endpoints** | `/api/chat`, `/api/generate` → full filter stack applied |
| **Model whitelist** | Only models listed in `ALLOWED_MODELS` forwarded on generation endpoints; others → 403 |
| **Rate limiting** | Token bucket (configurable burst + rate, carried over from old proxy) |

### Tool Call Loop

The proxy manages the full multi-turn tool use loop with guards against runaway execution:

1. Send request to Ollama with `tools:` parameter
2. If Ollama responds with a `tool_calls` field → proxy executes the tool (calls SearXNG internally)
3. Proxy appends tool result as a `tool` role message
4. Proxy re-sends to Ollama with updated context
5. Repeat — **maximum 10 tool call rounds per conversation turn** (configurable via `MAX_TOOL_ROUNDS` env var)
6. **Hard timeout of 120 seconds** per full turn (`TOOL_TIMEOUT_SECS` env var) — connection closed with error if exceeded
7. On loop limit or timeout → return an error message to the caller rather than hanging
8. On plain `assistant` response → stream to caller

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

**Two separate update paths:**
- **Image updates** (`just update-images`): runs `podman auto-update` inside the VM. Pulls new container images; containers with `io.containers.autoupdate=registry` are restarted automatically. A daily systemd timer also does this automatically.
- **Config/quadlet updates** (`just update`): re-runs `ansible-playbook site.yml`. Ansible copies updated quadlet files, triggers `systemctl daemon-reload`, and restarts affected services. Required when env vars, volume mounts, or quadlet structure changes — `podman auto-update` does NOT pick these up.

All containers include a `HealthCmd` so systemd can distinguish running-but-broken from running-and-healthy.

**hermes-proxy.container**
- Image: `ghcr.io/{owner}/hermes-proxy:latest`
- Port: `8000:8000`
- Env: `ALLOWED_MODELS`, `OLLAMA_HOST`, `RATE_LIMIT_*`, `MAX_TOOL_ROUNDS`, `TOOL_TIMEOUT_SECS`
- HealthCmd: `curl -f http://localhost:8000/health`
- Network: `hermes.network`
- Restart: `always`

**hermes-webui.container**
- Image: `ghcr.io/open-webui/open-webui:latest`
- Port: `3000:8080`
- Volume: `hermes-webui-data:/app/backend/data`
- Env: `OLLAMA_BASE_URL=http://hermes-proxy:8000`, `WEBUI_AUTH=true`
- HealthCmd: `curl -f http://localhost:8080/health`
- Network: `hermes.network`
- Restart: `always`

**hermes-searxng.container**
- Image: `docker.io/searxng/searxng:latest`
- No external port (internal only)
- Volume: `hermes-searxng-config:/etc/searxng`
- HealthCmd: `curl -f http://localhost:8080/healthz`
- Network: `hermes.network`
- Restart: `always`

**hermes-discord.container**
- Image: `ghcr.io/{owner}/hermes-discord:latest`
- No ports (outbound only)
- Env: `DISCORD_TOKEN`, `DISCORD_CHANNEL_ID`, `PROXY_URL=http://hermes-proxy:8000`
- Network: `hermes.network`
- Restart: `always`

### Discord Bot API Contract

The Discord bot communicates with the proxy using the Ollama `/api/chat` wire format:

- **Endpoint**: `POST http://hermes-proxy:8000/api/chat`
- **Request**: `{ "model": "hermes3", "messages": [...], "stream": true }`
- **Conversation history**: Bot maintains a per-channel in-memory message list (system prompt + rolling history). History is capped at 20 messages to stay within context limits. History is lost on bot container restart (acceptable for personal use).
- **Streaming**: Bot receives SSE stream, buffers tokens, and edits the Discord reply message progressively as chunks arrive (Discord edit-message API).
- **Message length**: Discord messages capped at 2000 characters. Bot splits long responses into sequential messages.
- **Commands**: Bot responds to `!clear` to reset conversation history for a channel.

### Named Volumes

| Volume | Purpose |
|--------|---------|
| `hermes-webui-data` | Open WebUI: user accounts, chat history, settings |
| `hermes-searxng-config` | SearXNG: engine config, settings.yml |

Volumes persist across container image updates and VM restarts. **Warning:** `just teardown` destroys the VM and all volumes inside it. Use `just rebuild` instead of bare teardown when you want a clean VM but need to keep your WebUI history and SearXNG config — it runs backup → teardown → setup → restore automatically.

### SearXNG Configuration

`settings.yml` must explicitly enable the JSON API format — it is disabled by default in upstream SearXNG (anti-scraper measure), which would silently break all proxy tool calls with a 403.

Required settings in `vm/searxng/settings.yml`:
```yaml
search:
  formats:
    - html
    - json          # must be present — proxy uses /search?format=json

engines:
  - name: google
    engine: google
    shortcut: g
  - name: duckduckgo
    engine: duckduckgo
    shortcut: d
  - name: wikipedia
    engine: wikipedia
    shortcut: w
```

### Log Rotation

systemd journal inside the VM capped at 500MB:
```
SystemMaxUse=500M
MaxRetentionSec=2weeks
```

---

## Host Services (launchd)

Three launchd plists deployed by Ansible to `~/Library/LaunchAgents/`:

**com.hermes.ollama.plist**
- Runs: `ollama serve`
- Env: `OLLAMA_HOST=0.0.0.0`
- `KeepAlive: true` — restarts on crash (ollama serve is a long-running daemon, KeepAlive is correct here)
- `RunAtLoad: true` — starts on login

**com.hermes.podman-machine.plist**
- Runs: a wrapper script `scripts/start-hermes-machine.sh` that calls `podman machine start hermes-machine` and polls until the machine reports running
- `RunAtLoad: true` — starts on login
- `KeepAlive: false` — the start command exits after the machine is up; KeepAlive would cause a tight restart loop since `podman machine start` on an already-running machine exits immediately. Instead the script checks state before starting.

**com.hermes.pf.plist**
- Runs: `pfctl -f /etc/pf.d/hermes.conf -e`
- `RunAtLoad: true` — reloads hermes pf rules on every login/reboot
- Ensures rules survive macOS updates that reset pf to defaults

---

## IaC & Tooling

### Ansible

Ansible is the single source of truth for provisioning. All host and VM setup is defined as idempotent playbooks — safe to re-run for updates or fresh installs.

**Inventory generation:** The Podman machine SSH port is dynamic. Before running `ansible-playbook`, `just` runs a script (`scripts/gen-inventory.sh`) that calls `podman machine ssh-config hermes-machine`, extracts the SSH port, and writes `ansible/inventory/hermes-machine.yml` with the correct `ansible_host=127.0.0.1` and `ansible_port=<discovered port>`. This generated file is gitignored.

**Playbook structure:**

```
ansible/
├── site.yml                  # master playbook (runs all roles)
├── inventory/
│   ├── localhost.yml         # static — always localhost
│   └── hermes-machine.yml    # generated by scripts/gen-inventory.sh (gitignored)
├── group_vars/
│   └── all.yml               # non-secret defaults
├── host_vars/
│   └── localhost.yml         # generated from .env by just setup (gitignored)
└── roles/
    ├── prerequisites/        # brew bundle, verify tools installed
    ├── ollama/               # launchd plist, OLLAMA_HOST, model pulls
    ├── firewall/             # pf rules template + load + boot plist
    ├── podman-machine/       # create/start hermes-machine, launchd wrapper script + plist
    ├── vm-quadlets/          # SSH into VM, deploy quadlet files + env file, daemon-reload
    ├── vm-volumes/           # create named volumes, seed SearXNG settings.yml
    └── vm-autoupdate/        # daily podman auto-update timer + journald caps
```

Running `just setup` generates inventory → then executes `ansible-playbook ansible/site.yml`. Running `just update` does the same — Ansible's idempotency means only changed resources are updated.

### Just (task runner)

```makefile
setup:           # one-time: brew install just → brew bundle → gen-inventory → ansible site.yml
update:          # git pull + gen-inventory + ansible site.yml (config + quadlet changes)
update-images:   # SSH into VM and run podman auto-update (image-only updates)
logs:            # tail systemd journal from VM
restart:         # restart all containers in VM
status:          # container status + pf rule verification (warns if hermes pf rules not loaded)
ssh:             # SSH into hermes-machine
pull-models:     # ollama pull for all ALLOWED_MODELS
backup-volumes:  # export hermes-webui-data + hermes-searxng-config to ./backups/
teardown:        # warns about volume loss, requires --confirm flag, then stops + deletes hermes-machine
rebuild:         # backup-volumes → teardown --confirm → setup → restore-volumes (full clean rebuild preserving data)
restore-volumes: # import volume data from ./backups/ into a running hermes-machine
encrypt-env:     # age-encrypt .env → .env.age
decrypt-env:     # age-decrypt .env.age → .env
```

### Brewfile

```ruby
brew "podman"
brew "podman-compose"
brew "ollama"
brew "ansible"
brew "just"
brew "gh"
brew "age"
cask "podman-desktop"   # optional GUI
```

### age (secrets encryption)

`.env` files contain sensitive values (Discord token etc.). `age` encrypts the `.env` so users can optionally commit an encrypted version to a private fork.

- `just encrypt-env` → produces `.env.age` (safe to commit to private fork)
- `just decrypt-env` → restores `.env` from `.env.age` using your age key
- Public repo ships only `.env.example` — age workflow is opt-in

### Renovate (dependency updates)

Renovate tracks digest-pinned image references in quadlet files (not `:latest` — `:latest` gives Renovate nothing to compare). Quadlet files use pinned digests (e.g., `image@sha256:...`) and Renovate opens PRs when upstream digests change. The `just update-images` / `podman auto-update` path handles between-PR drift for the owner; the Renovate PRs keep the repo's pinned digests current for other users cloning it.

`renovate.json` ships in the repo root: automerge patch Python deps, group container digest updates into weekly PRs.

---

## GitHub Repository

### Repo: `hermes-vm`

Public repo. Anyone with an Apple Silicon Mac can clone, fill in `.env`, and run `just setup`. Intel Mac not supported (images are `linux/arm64` only — no Metal, no GPU passthrough on QEMU either way).

```
hermes-vm/
├── README.md
├── justfile
├── Brewfile
├── renovate.json
├── .env.example
├── .gitignore                        # excludes .env, .env.age, ansible/inventory/hermes-machine.yml, ansible/host_vars/localhost.yml
│
├── scripts/
│   ├── gen-inventory.sh              # discovers Podman SSH port, writes ansible inventory
│   └── start-hermes-machine.sh      # polls until hermes-machine is running (used by launchd)
│
├── ansible/
│   ├── site.yml
│   ├── inventory/localhost.yml
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
│   │   ├── system_prompt.txt         # system prompt as a file, not env var string
│   │   └── requirements.txt
│   ├── discord-bot/
│   │   ├── Dockerfile
│   │   ├── bot.py
│   │   └── requirements.txt
│   └── searxng/
│       └── settings.yml
│
├── host/
│   └── firewall/
│       └── hermes.pf.conf.j2         # Jinja2 template, rendered by Ansible
│
└── .github/
    └── workflows/
        ├── build-images.yml
        └── release.yml
```

### .env.example

```bash
# ZeroTier
ZT_INTERFACE=ztXXXXXXXX
ZT_SUBNET=10.x.x.0/24

# Podman machine bridge (Ansible discovers VM_BRIDGE_IFACE automatically)
VM_SUBNET=192.168.64.0/24

# Ollama
ALLOWED_MODELS=hermes3,gemma4:27b

# Discord
DISCORD_TOKEN=your-bot-token-here
DISCORD_CHANNEL_ID=your-channel-id-here

# Proxy tuning
RATE_LIMIT_BURST=20
RATE_LIMIT_PER_MIN=5
MAX_TOOL_ROUNDS=10
TOOL_TIMEOUT_SECS=120

# GitHub (for image pulls + repo)
GHCR_OWNER=your-github-username
```

### GitHub Actions Workflows

**build-images.yml** (on push to `main`):
1. Build `hermes-proxy` + `hermes-discord` images (`linux/arm64`)
2. Push `ghcr.io/{owner}/hermes-proxy:latest` + `:sha-{commit}`
3. Images public — no auth required to pull

**release.yml** (on tag `v*.*.*`):
1. Build both images
2. Push with version tag + `:latest`
3. Create GitHub Release with auto-generated changelog

---

## Setup Flow

```bash
# One-time bootstrap
brew install just
gh auth login
cp .env.example .env    # fill in ZT_INTERFACE, ZT_SUBNET, DISCORD_TOKEN, etc.

# Provision everything
just setup
```

`just setup` execution order:
1. `brew bundle` — install all prerequisites
2. `scripts/gen-inventory.sh` — generates Ansible inventory (after Podman machine created)
3. `ansible-playbook site.yml`:
   - `prerequisites` — verify tools
   - `ollama` — launchd plist + model pulls
   - `firewall` — render + load pf rules + boot plist
   - `podman-machine` — create hermes-machine, deploy start script + launchd plist
   - `vm-quadlets` — SSH, deploy quadlets + env file, daemon-reload
   - `vm-volumes` — create volumes, seed SearXNG settings.yml
   - `vm-autoupdate` — daily timer + journald cap

**Config update flow** (quadlet/env changes):
```bash
git pull && just update
```

**Image-only update** (pull latest container images):
```bash
just update-images
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
- [ ] Open WebUI accessible over ZeroTier, login required, model list populates correctly
- [ ] Port 11434 unreachable from any source except localhost, ZeroTier subnet, VM bridge interface
- [ ] VM reboot → all containers restart automatically via quadlets
- [ ] Host reboot → Ollama + VM + pf rules restart automatically via launchd
- [ ] `just status` warns if pf hermes rules are not loaded
- [ ] Prompt asking about host/VM architecture returns canned refusal
- [ ] Attempt to pull a model via Ollama API returns 403
- [ ] Attempt to use non-whitelisted model returns 403
- [ ] Tool call loop stops at MAX_TOOL_ROUNDS and returns error instead of hanging
- [ ] `git push` to `main` triggers image build + push to ghcr.io
- [ ] `just update-images` pulls new images without requiring full Ansible re-run
- [ ] `just update` re-runs Ansible idempotently without breaking running services
- [ ] `just teardown` requires `--confirm` flag and warns about volume loss
- [ ] Renovate opens PRs for digest-pinned image updates
