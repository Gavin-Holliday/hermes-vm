# hermes-vm

Self-hosted Nous Hermes 3 agent running in an isolated Podman VM on Apple Silicon, with Discord and Open WebUI interfaces, web search via SearXNG, and full infrastructure-as-code provisioning via Ansible.

---

## What is this?

hermes-vm runs the Nous Hermes 3 language model locally on your Mac via Ollama with Metal/GPU acceleration. All agent services — a security proxy, Open WebUI, SearXNG, and a Discord bot — run inside an isolated Podman virtual machine, separated from the host by a hypervisor boundary and pf firewall rules. You interact with Hermes over ZeroTier VPN either through Discord or through a browser-based chat UI.

---

## Architecture

```
macOS Host
├── launchd: auto-starts Ollama + hermes-machine on boot
├── Ollama (Metal/GPU, port 11434 — pf firewall-locked)
│
└── hermes-machine (Podman VM, 6GB RAM, 4 CPUs, 40GB disk)
    ├── hermes-proxy   :8000  (security proxy, tool-call loop)
    ├── hermes-webui   :3000  (Open WebUI — VPN-accessible)
    ├── hermes-searxng :8080  (internal only, no external port)
    └── hermes-discord        (outbound only, no inbound ports)
```

**Data flow:** Discord message or WebUI request → `hermes-proxy` → jailbreak/architecture filter → model whitelist check → tool-call loop (proxy calls SearXNG internally if Hermes requests a web search) → Ollama inference with Metal acceleration → streamed response back to caller.

---

## Requirements

- **Apple Silicon Mac only.** Container images are `linux/arm64`. Intel Macs are not supported — there is no GPU passthrough on QEMU regardless of architecture.
- macOS 13 (Ventura) or later
- [ZeroTier](https://www.zerotier.com/) installed and joined to your network
- A Discord bot application (see [docs/setup.md](docs/setup.md))
- `just` task runner (`brew install just`)

---

## Quick Start

```bash
brew install just
gh auth login
cp .env.example .env   # fill in your values (see Configuration below)
just setup
```

`just setup` installs all remaining prerequisites via Brewfile, creates the Podman VM, and runs full Ansible provisioning. On a fresh machine expect it to take 10–15 minutes (model downloads are the long part).

After setup completes:
- Open WebUI: `http://<your-zerotier-ip>:3000`
- Discord: send a message in your configured channel

---

## Configuration

Copy `.env.example` to `.env` and fill in every value before running `just setup`.

| Variable | Description | Example |
|---|---|---|
| `ZT_INTERFACE` | ZeroTier network interface name. Find it with `zerotier-cli listnetworks`. | `ztabcdef12` |
| `ZT_SUBNET` | ZeroTier network subnet in CIDR notation. | `10.147.18.0/24` |
| `VM_SUBNET` | Podman machine bridge subnet. Check with `ifconfig \| grep 192.168`. | `192.168.64.0/24` |
| `ALLOWED_MODELS` | Comma-separated list of Ollama model names the proxy will permit. Any request for a model not in this list returns 403. | `hermes3,gemma4:27b` |
| `DISCORD_TOKEN` | Discord bot token from the developer portal. | `MTExxx...` |
| `DISCORD_CHANNEL_ID` | Numeric ID of the Discord channel the bot listens in. | `1234567890123456789` |
| `RATE_LIMIT_BURST` | Maximum request burst before rate limiting kicks in (token bucket). | `20` |
| `RATE_LIMIT_PER_MIN` | Sustained request rate allowed per minute. | `5` |
| `MAX_TOOL_ROUNDS` | Maximum web search iterations the proxy will execute per conversation turn before returning an error. | `10` |
| `TOOL_TIMEOUT_SECS` | Hard timeout in seconds for a single conversation turn, including all tool call rounds. | `120` |
| `GHCR_OWNER` | Your GitHub username — used to construct container image URLs (`ghcr.io/<owner>/hermes-proxy:latest`). | `your-github-username` |

---

## Available Commands

| Command | Description |
|---|---|
| `just setup` | One-time provisioning: install prerequisites, create Podman VM, run full Ansible playbook. |
| `just update` | Pull latest git changes and re-run Ansible. Use this when `.env`, quadlet files, or Ansible roles change. |
| `just update-images` | Pull latest container images inside the VM via `podman auto-update`. Use this for image-only updates without Ansible. |
| `just pull-models` | Pull all models listed in `ALLOWED_MODELS` via `ollama pull`. |
| `just status` | Show systemd unit status for all hermes services and verify pf firewall rules are loaded. |
| `just logs` | Tail systemd journal from the VM for all hermes services. |
| `just ssh` | Open an SSH session into hermes-machine. |
| `just restart` | Restart all hermes containers in the VM. |
| `just backup-volumes` | Export named volumes to timestamped tar archives in `./backups/`. |
| `just restore-volumes` | Import the most recent backup for each volume into the running VM. |
| `just rebuild` | Full clean rebuild preserving data: backup → teardown → setup → restore. |
| `just teardown --confirm` | Stop and delete the VM and all volume data. Requires `--confirm` flag. Destructive. |
| `just encrypt-env` | Encrypt `.env` to `.env.age` using your `~/.ssh/id_ed25519.pub` key. Safe to commit to a private fork. |
| `just decrypt-env` | Decrypt `.env.age` back to `.env` using `~/.ssh/id_ed25519`. |

---

## How It Works

1. A message arrives at `hermes-proxy` from either the Discord bot container or Open WebUI.
2. The proxy runs a jailbreak filter and an architecture/host-info filter. Blocked prompts receive a canned refusal without reaching Ollama.
3. The proxy checks the requested model against `ALLOWED_MODELS`. Non-whitelisted models return 403.
4. The proxy injects a system prompt and the `web_search` tool definition, then sends the request to Ollama at `host.containers.internal:11434`.
5. If Ollama responds with a `tool_calls` field, the proxy executes the search by calling SearXNG on the internal `hermes.network`, appends the result as a `tool` role message, and re-sends to Ollama. This loop repeats up to `MAX_TOOL_ROUNDS` times.
6. On a plain assistant response (no tool calls), the proxy streams the SSE response directly to the caller.
7. The Discord bot receives the stream, progressively edits its reply message, and splits responses over 1990 characters into sequential messages.

---

## Security Model

**pf firewall:** Port 11434 (Ollama) is reachable only from `localhost`, the ZeroTier subnet, and the Podman VM bridge interface. All other sources are blocked. A launchd plist reloads the rules on every boot. `just status` checks whether the rules are active and warns loudly if they are not.

**VM isolation:** The Podman machine (QEMU) provides hypervisor-level isolation. A compromised agent inside the VM cannot access the host filesystem, execute host commands, reach any host port except 11434, pull Ollama models, or use non-whitelisted models.

**Internal network:** All containers share `hermes.network`. SearXNG has no port forwarded to the VM host — it is reachable only by other containers on that network. Only the proxy (:8000) and WebUI (:3000) are exposed.

**Proxy filters:** The security proxy blocks write endpoints (`/api/pull`, `/api/delete`, `/api/copy`, `/api/push`) unconditionally, enforces the model whitelist on generation endpoints, and applies jailbreak and architecture-info pattern filters before forwarding to Ollama.

---

## Updating

**Pull latest container images** (no Ansible re-run needed):
```bash
just update-images
```
This runs `podman auto-update` inside the VM. A daily systemd timer also does this automatically.

**Apply config or quadlet changes** (after editing `.env` or Ansible roles):
```bash
git pull && just update
```
This re-runs Ansible idempotently — only changed resources are modified. Running services are not restarted unless their quadlet definition changed.

---

## Backup and Restore

```bash
# Back up WebUI history and SearXNG config to ./backups/
just backup-volumes

# Restore most recent backup for each volume
just restore-volumes
```

Backups are timestamped tar archives written to `./backups/`. Named volumes (`hermes-webui-data`, `hermes-searxng-config`) persist across image updates and VM restarts, but are destroyed by `just teardown`.

To do a clean rebuild while preserving data:
```bash
just rebuild
```
This automatically runs backup → teardown → setup → restore in sequence.

---

## Troubleshooting

**pf rules not loaded after reboot:**
```bash
just status   # will warn if hermes rules are not active
sudo pfctl -f /etc/pf.d/hermes.conf -e
```
macOS system updates can silently revert pf to defaults. The launchd plist (`com.hermes.pf.plist`) reloads rules at login, but manual reload may be needed after an update.

**VM not starting:**
```bash
podman machine list
podman machine start hermes-machine
```
If the machine is missing entirely, run `just setup` to recreate it.

**Models not pulling / 403 on model requests:**
Check that the model name in your request exactly matches an entry in `ALLOWED_MODELS` in `.env` (case-sensitive, including tags). After changing `ALLOWED_MODELS`, run `just update` to push the change to the proxy container.

**WebUI can't connect to Ollama:**
The WebUI connects through the proxy at `http://hermes-proxy:8000`. Check proxy health:
```bash
just logs
# look for hermes-proxy errors
```

**Discord bot not responding:**
Verify `DISCORD_TOKEN` and `DISCORD_CHANNEL_ID` in `.env`. The bot only reads messages in the single channel specified by `DISCORD_CHANNEL_ID`. Confirm the Message Content Intent is enabled in the Discord developer portal.

**Tool call loop timing out:**
Increase `TOOL_TIMEOUT_SECS` or reduce `MAX_TOOL_ROUNDS` in `.env`, then run `just update`.
