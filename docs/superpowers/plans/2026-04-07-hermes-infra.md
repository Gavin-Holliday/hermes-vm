# Hermes Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provision the full hermes-vm infrastructure: Brewfile, Justfile, shell scripts, Quadlet container units, SearXNG config, pf firewall template, launchd plists, and Ansible roles that wire everything together idempotently on any Apple Silicon Mac.

**Architecture:** Ansible is the single source of truth. `just setup` orchestrates: brew bundle → gen-inventory.sh (discovers dynamic SSH port) → `ansible-playbook site.yml` (7 roles: prerequisites, ollama, firewall, podman-machine, vm-quadlets, vm-volumes, vm-autoupdate). All services auto-restart via quadlets (VM) and launchd (host). pf firewall locks Ollama to 3 sources only.

**Tech Stack:** Ansible, Just (task runner), Podman quadlets (systemd), launchd, pf (macOS firewall), Bash scripts, Jinja2 templates, age (secrets encryption)

---

## File Map

```
hermes-vm/
├── Brewfile
├── justfile
├── .env.example
├── scripts/
│   ├── gen-inventory.sh              # discovers Podman SSH port → writes ansible/inventory/hermes-machine.yml
│   └── start-hermes-machine.sh      # idempotent: starts hermes-machine if not running (used by launchd)
├── vm/
│   ├── quadlets/
│   │   ├── hermes.network            # Podman network unit
│   │   ├── hermes-proxy.container    # proxy quadlet
│   │   ├── hermes-webui.container    # Open WebUI quadlet
│   │   ├── hermes-searxng.container  # SearXNG quadlet (internal only)
│   │   └── hermes-discord.container  # Discord bot quadlet
│   └── searxng/
│       └── settings.yml              # enables JSON API format (disabled by default)
├── host/
│   └── firewall/
│       └── hermes.pf.conf.j2         # Jinja2 template rendered by Ansible
└── ansible/
    ├── site.yml                       # master playbook
    ├── inventory/
    │   └── localhost.yml              # static host entry
    ├── group_vars/
    │   └── all.yml                    # non-secret defaults
    └── roles/
        ├── prerequisites/
        │   └── tasks/main.yml         # verify brew, ansible, just, podman, gh, age installed
        ├── ollama/
        │   ├── tasks/main.yml         # deploy launchd plist, pull models
        │   └── templates/
        │       └── com.hermes.ollama.plist.j2
        ├── firewall/
        │   ├── tasks/main.yml         # render pf conf, load rules, deploy boot plist
        │   └── templates/
        │       └── com.hermes.pf.plist.j2
        ├── podman-machine/
        │   ├── tasks/main.yml         # create machine, deploy start script + launchd plist
        │   └── templates/
        │       └── com.hermes.podman-machine.plist.j2
        ├── vm-quadlets/
        │   └── tasks/main.yml         # SSH into VM, deploy quadlets + env file, daemon-reload
        ├── vm-volumes/
        │   └── tasks/main.yml         # create named volumes, seed SearXNG settings.yml
        └── vm-autoupdate/
            ├── tasks/main.yml         # daily auto-update timer + journald cap
            └── templates/
                ├── hermes-autoupdate.service.j2
                └── hermes-autoupdate.timer.j2
```

---

### Task 1: Brewfile, .env.example, and project root files

**Files:**
- Create: `Brewfile`
- Create: `.env.example`

- [ ] **Step 1: Create `Brewfile`**

```ruby
# hermes-vm prerequisites — install with: brew bundle
brew "podman"
brew "podman-compose"
brew "ollama"
brew "ansible"
brew "just"
brew "gh"
brew "age"
brew "ansible-lint"
cask "podman-desktop"   # optional GUI — comment out if not wanted
```

- [ ] **Step 2: Create `.env.example`**

```bash
# Copy to .env and fill in your values.
# Run: just encrypt-env   to produce .env.age (safe to commit to a private fork)
# Run: just decrypt-env   to restore .env from .env.age

# ── ZeroTier ──────────────────────────────────────────────────────────────────
# Find your interface name with: zerotier-cli listnetworks
ZT_INTERFACE=ztXXXXXXXX
ZT_SUBNET=10.x.x.0/24

# ── Podman machine bridge ─────────────────────────────────────────────────────
# Ansible discovers VM_BRIDGE_IFACE automatically via podman machine inspect.
# Set the subnet your Mac assigns to the Podman bridge (check: ifconfig | grep 192.168)
VM_SUBNET=192.168.64.0/24

# ── Ollama ────────────────────────────────────────────────────────────────────
# Comma-separated list of allowed model names. Anything not in this list → 403.
ALLOWED_MODELS=hermes3,gemma4:27b

# ── Discord ───────────────────────────────────────────────────────────────────
DISCORD_TOKEN=your-bot-token-here
DISCORD_CHANNEL_ID=your-channel-id-here

# ── Proxy tuning ──────────────────────────────────────────────────────────────
RATE_LIMIT_BURST=20
RATE_LIMIT_PER_MIN=5
MAX_TOOL_ROUNDS=10
TOOL_TIMEOUT_SECS=120

# ── GitHub container registry ─────────────────────────────────────────────────
GHCR_OWNER=your-github-username
```

- [ ] **Step 3: Commit**

```bash
cd ~/Projects/hermes-vm
git add Brewfile .env.example
git commit -m "feat(infra): add Brewfile and .env.example"
```

---

### Task 2: Shell scripts

**Files:**
- Create: `scripts/gen-inventory.sh`
- Create: `scripts/start-hermes-machine.sh`

- [ ] **Step 1: Create `scripts/gen-inventory.sh`**

```bash
#!/usr/bin/env bash
# Discover the hermes-machine SSH port and write the Ansible inventory.
# This file is gitignored — it's generated fresh before each Ansible run.
set -euo pipefail

MACHINE_NAME="hermes-machine"
OUT="ansible/inventory/hermes-machine.yml"

# Extract the SSH port from podman machine's ssh-config output
SSH_PORT=$(podman machine ssh-config "$MACHINE_NAME" 2>/dev/null \
  | awk '/Port / {print $2}')

if [[ -z "$SSH_PORT" ]]; then
  echo "ERROR: Could not determine SSH port for $MACHINE_NAME." >&2
  echo "       Is the machine running? Run: podman machine start $MACHINE_NAME" >&2
  exit 1
fi

# Discover the VM bridge interface by finding which host interface routes to the VM's IP.
# `podman machine inspect` doesn't expose the bridge name directly (Docker schema ≠ Podman schema).
VM_IP=$(podman machine ssh-config "$MACHINE_NAME" 2>/dev/null | awk '/HostName/ {print $2}')
VM_BRIDGE_IFACE=$(route get "$VM_IP" 2>/dev/null | awk '/interface:/ {print $2}')
VM_BRIDGE_IFACE="${VM_BRIDGE_IFACE:-bridge100}"   # fallback: bridge100 is the Podman default on macOS

mkdir -p "$(dirname "$OUT")"
cat > "$OUT" <<EOF
# Generated by scripts/gen-inventory.sh — do not edit by hand
all:
  hosts:
    hermes-machine:
      ansible_host: 127.0.0.1
      ansible_port: ${SSH_PORT}
      ansible_user: core
      ansible_ssh_extra_args: "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
      vm_bridge_iface: "${VM_BRIDGE_IFACE}"
EOF

echo "Wrote $OUT (port=$SSH_PORT, bridge=$VM_BRIDGE_IFACE)"
```

- [ ] **Step 2: Create `scripts/start-hermes-machine.sh`**

```bash
#!/usr/bin/env bash
# Idempotent: start hermes-machine if it is not already running.
# Used by the launchd plist — exits 0 once the machine is confirmed running.
set -euo pipefail

MACHINE_NAME="hermes-machine"
MAX_WAIT=120
INTERVAL=5

state=$(podman machine inspect "$MACHINE_NAME" --format '{{.State}}' 2>/dev/null || echo "unknown")

if [[ "$state" == "running" ]]; then
  echo "$MACHINE_NAME is already running."
  exit 0
fi

echo "Starting $MACHINE_NAME..."
podman machine start "$MACHINE_NAME"

# Poll until running or timeout
elapsed=0
while true; do
  state=$(podman machine inspect "$MACHINE_NAME" --format '{{.State}}' 2>/dev/null || echo "unknown")
  if [[ "$state" == "running" ]]; then
    echo "$MACHINE_NAME is running."
    exit 0
  fi
  if (( elapsed >= MAX_WAIT )); then
    echo "ERROR: $MACHINE_NAME did not reach 'running' state within ${MAX_WAIT}s." >&2
    exit 1
  fi
  sleep "$INTERVAL"
  (( elapsed += INTERVAL ))
done
```

- [ ] **Step 3: Make scripts executable**

```bash
chmod +x ~/Projects/hermes-vm/scripts/gen-inventory.sh
chmod +x ~/Projects/hermes-vm/scripts/start-hermes-machine.sh
```

- [ ] **Step 4: Commit**

```bash
cd ~/Projects/hermes-vm
git add scripts/
git commit -m "feat(infra): add gen-inventory and start-hermes-machine scripts"
```

---

### Task 3: Justfile

**Files:**
- Create: `justfile`

- [ ] **Step 1: Create `justfile`**

```makefile
# hermes-vm task runner — install just: brew install just
# Usage: just <recipe>

# Export all Just variables (including those loaded from .env) as environment variables
# to subprocess recipes. Without this, ansible-playbook won't see DISCORD_TOKEN etc.
set dotenv-load := true
set export := true

machine := "hermes-machine"
ansible_cmd := "ansible-playbook ansible/site.yml -i ansible/inventory/localhost.yml -i ansible/inventory/hermes-machine.yml"

# ── Bootstrap ─────────────────────────────────────────────────────────────────

# One-time setup: install tools, create VM, provision everything
setup:
    brew bundle --no-lock
    scripts/gen-inventory.sh || true
    {{ansible_cmd}} --tags prerequisites,podman-machine
    scripts/gen-inventory.sh
    {{ansible_cmd}}

# ── Day-to-day ────────────────────────────────────────────────────────────────

# Apply config/quadlet changes (re-runs Ansible idempotently)
update:
    git pull
    scripts/gen-inventory.sh
    {{ansible_cmd}}

# Pull latest container images inside the VM (no Ansible needed)
update-images:
    podman machine ssh {{machine}} "sudo podman auto-update"

# Pull all allowed Ollama models on the host
pull-models:
    @echo "Pulling models: $ALLOWED_MODELS"
    @echo "$ALLOWED_MODELS" | tr ',' '\n' | xargs -I{} ollama pull {}

# ── Observability ─────────────────────────────────────────────────────────────

# Show container status + warn if pf hermes rules are not loaded
status:
    @echo "=== Container status ==="
    podman machine ssh {{machine}} "sudo systemctl list-units 'hermes-*' --no-pager"
    @echo ""
    @echo "=== pf firewall check ==="
    @if sudo pfctl -sr 2>/dev/null | grep -q "port 11434"; then \
        echo "✓ hermes pf rules are loaded"; \
    else \
        echo "⚠ WARNING: hermes pf rules are NOT loaded — Ollama may be exposed on all interfaces!"; \
        echo "  Run: sudo pfctl -f /etc/pf.d/hermes.conf -e"; \
    fi

# Tail systemd journal from the VM
logs:
    podman machine ssh {{machine}} "sudo journalctl -f -u 'hermes-*'"

# SSH into hermes-machine
ssh:
    podman machine ssh {{machine}}

# ── Container management ──────────────────────────────────────────────────────

# Restart all hermes containers in the VM
restart:
    podman machine ssh {{machine}} "sudo systemctl restart hermes-proxy hermes-webui hermes-searxng hermes-discord"

# ── Volume management ─────────────────────────────────────────────────────────

# Export volumes to ./backups/ (creates timestamped tar archives)
backup-volumes:
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p backups
    TIMESTAMP=$(date +%Y%m%d-%H%M%S)
    for vol in hermes-webui-data hermes-searxng-config; do
        echo "Backing up $vol..."
        podman machine ssh {{machine}} \
            "sudo podman volume export $vol" > "backups/${vol}-${TIMESTAMP}.tar"
        echo "  → backups/${vol}-${TIMESTAMP}.tar"
    done
    echo "Backup complete."

# Import volumes from ./backups/ (uses most recent backup for each volume)
restore-volumes:
    #!/usr/bin/env bash
    set -euo pipefail
    for vol in hermes-webui-data hermes-searxng-config; do
        backup=$(ls -t backups/${vol}-*.tar 2>/dev/null | head -1)
        if [[ -z "$backup" ]]; then
            echo "No backup found for $vol — skipping."
            continue
        fi
        echo "Restoring $vol from $backup..."
        cat "$backup" | podman machine ssh {{machine}} \
            "sudo podman volume import $vol -"
        echo "  ✓ restored"
    done

# ── VM lifecycle ──────────────────────────────────────────────────────────────

# Destroy the VM and all volumes. Requires --confirm to prevent accidents.
teardown confirm="":
    #!/usr/bin/env bash
    if [[ "{{confirm}}" != "--confirm" ]]; then
        echo "ERROR: This destroys the VM and all volume data (WebUI history, SearXNG config)."
        echo "       Run: just teardown --confirm"
        exit 1
    fi
    echo "Stopping and removing {{machine}}..."
    podman machine stop {{machine}} || true
    podman machine rm -f {{machine}} || true
    echo "Done. Run 'just setup' to recreate."

# Full rebuild preserving volume data: backup → teardown → setup → restore
rebuild:
    just backup-volumes
    just teardown --confirm
    just setup
    just restore-volumes

# ── Secrets ───────────────────────────────────────────────────────────────────

# Encrypt .env with age (output: .env.age — safe to commit to a private fork)
encrypt-env:
    @if [[ ! -f .env ]]; then echo "No .env file found."; exit 1; fi
    age -R ~/.ssh/id_ed25519.pub -o .env.age .env
    echo "Encrypted to .env.age"

# Decrypt .env.age back to .env
decrypt-env:
    @if [[ ! -f .env.age ]]; then echo "No .env.age file found."; exit 1; fi
    age -d -i ~/.ssh/id_ed25519 -o .env .env.age
    echo "Decrypted to .env"
```

- [ ] **Step 2: Verify justfile parses without error**

```bash
cd ~/Projects/hermes-vm
just --list
```

Expected: list of available recipes without errors.

- [ ] **Step 3: Commit**

```bash
cd ~/Projects/hermes-vm
git add justfile
git commit -m "feat(infra): add Justfile with all task recipes"
```

---

### Task 4: Quadlet files and SearXNG settings

**Files:**
- Create: `vm/quadlets/hermes.network`
- Create: `vm/quadlets/hermes-proxy.container`
- Create: `vm/quadlets/hermes-webui.container`
- Create: `vm/quadlets/hermes-searxng.container`
- Create: `vm/quadlets/hermes-discord.container`
- Create: `vm/searxng/settings.yml`

- [ ] **Step 1: Create `vm/quadlets/hermes.network`**

```ini
[Unit]
Description=Hermes internal container network

[Network]
# Internal Podman bridge — containers on this network can reach each other by name.
# hermes-proxy, hermes-webui, hermes-searxng, hermes-discord all join this network.
Driver=bridge
```

- [ ] **Step 2: Create `vm/quadlets/hermes-proxy.container`**

```ini
[Unit]
Description=Hermes security proxy
After=hermes-network.service
Wants=hermes-network.service

[Container]
Image=ghcr.io/{{ ghcr_owner }}/hermes-proxy:latest
ContainerName=hermes-proxy

# Expose proxy port to VM host (Open WebUI and Discord bot reach Ollama through here)
PublishPort=8000:8000

# Env vars injected from the quadlet env file deployed by Ansible
EnvironmentFile=/etc/containers/systemd/hermes.env

Network=hermes.network

# Health check — systemd uses this to distinguish running-but-broken from healthy
HealthCmd=curl -sf http://localhost:8000/health
HealthInterval=30s
HealthRetries=3
HealthStartPeriod=10s

AutoUpdate=registry

[Service]
Restart=always
TimeoutStartSec=120

[Install]
WantedBy=default.target
```

- [ ] **Step 3: Create `vm/quadlets/hermes-webui.container`**

```ini
[Unit]
Description=Hermes Open WebUI
After=hermes-proxy.service
Wants=hermes-proxy.service

[Container]
Image=ghcr.io/open-webui/open-webui:latest
ContainerName=hermes-webui

# Map container's 8080 → VM host port 3000 (forwarded to macOS host by Ansible)
PublishPort=3000:8080

# Point WebUI at the proxy, not directly at Ollama
Environment=OLLAMA_BASE_URL=http://hermes-proxy:8000
Environment=WEBUI_AUTH=true

Volume=hermes-webui-data:/app/backend/data

Network=hermes.network

HealthCmd=curl -sf http://localhost:8080/health
HealthInterval=30s
HealthRetries=3
HealthStartPeriod=30s

AutoUpdate=registry

[Service]
Restart=always
TimeoutStartSec=120

[Install]
WantedBy=default.target
```

- [ ] **Step 4: Create `vm/quadlets/hermes-searxng.container`**

```ini
[Unit]
Description=Hermes SearXNG web search (internal only)
After=hermes-network.service
Wants=hermes-network.service

[Container]
Image=docker.io/searxng/searxng:latest
ContainerName=hermes-searxng

# No published port — only reachable from hermes.network by container name
Volume=hermes-searxng-config:/etc/searxng

Network=hermes.network

HealthCmd=curl -sf http://localhost:8080/healthz
HealthInterval=30s
HealthRetries=3
HealthStartPeriod=15s

AutoUpdate=registry

[Service]
Restart=always
TimeoutStartSec=60

[Install]
WantedBy=default.target
```

- [ ] **Step 5: Create `vm/quadlets/hermes-discord.container`**

```ini
[Unit]
Description=Hermes Discord bot
After=hermes-proxy.service
Wants=hermes-proxy.service

[Container]
Image=ghcr.io/{{ ghcr_owner }}/hermes-discord:latest
ContainerName=hermes-discord

# No published port — outbound connections to Discord only
EnvironmentFile=/etc/containers/systemd/hermes.env

# Bot talks to proxy by container name on the shared network
Environment=PROXY_URL=http://hermes-proxy:8000

Network=hermes.network

# NOTE: No HealthCmd — the Discord bot has no HTTP endpoint to health-check.
# systemd will treat the container as healthy if it stays running (not crash-looping).

AutoUpdate=registry

[Service]
Restart=always
TimeoutStartSec=30

[Install]
WantedBy=default.target
```

- [ ] **Step 6: Create `vm/searxng/settings.yml`**

```yaml
# SearXNG configuration for hermes-vm
# JSON API format must be explicitly enabled — it's disabled upstream (anti-scraper measure).
# Without it, all proxy web_search tool calls silently fail with 403.

use_default_settings: true

server:
  secret_key: "change-me-in-production"   # replaced by Ansible from .env
  limiter: false                            # no rate limiting — internal use only
  image_proxy: false

search:
  safe_search: 0
  autocomplete: ""
  formats:
    - html
    - json           # REQUIRED — proxy uses /search?format=json

engines:
  - name: google
    engine: google
    shortcut: g
    disabled: false
  - name: duckduckgo
    engine: duckduckgo
    shortcut: d
    disabled: false
  - name: wikipedia
    engine: wikipedia
    shortcut: w
    disabled: false
  - name: bing
    engine: bing
    shortcut: b
    disabled: false
```

- [ ] **Step 7: Commit**

```bash
cd ~/Projects/hermes-vm
git add vm/quadlets/ vm/searxng/
git commit -m "feat(infra): add quadlet units and SearXNG config"
```

---

### Task 5: pf firewall template

**Files:**
- Create: `host/firewall/hermes.pf.conf.j2`

- [ ] **Step 1: Create `host/firewall/hermes.pf.conf.j2`**

```
# /etc/pf.d/hermes.conf
# Rendered by Ansible from host/firewall/hermes.pf.conf.j2
# Restricts Ollama (port 11434) to three sources only:
#   1. localhost
#   2. ZeroTier VPN subnet
#   3. Podman machine VM bridge interface
#
# WARNING: macOS system updates can reset pf rules.
# A launchd plist (com.hermes.pf) reloads these rules on every boot/login.
# Run: just status  — to verify rules are currently loaded.

# Allow from localhost
pass in quick on lo0 proto tcp from 127.0.0.1 to any port 11434

# Allow from ZeroTier VPN subnet
pass in quick on {{ zt_interface }} proto tcp from {{ zt_subnet }} to any port 11434

# Allow from Podman machine VM bridge
pass in quick on {{ vm_bridge_iface }} proto tcp from {{ vm_subnet }} to any port 11434

# Block everything else reaching Ollama
block in quick proto tcp to any port 11434
```

- [ ] **Step 2: Commit**

```bash
cd ~/Projects/hermes-vm
git add host/
git commit -m "feat(infra): add pf firewall Jinja2 template for Ollama port restriction"
```

---

### Task 6: Ansible inventory and group vars

**Files:**
- Create: `ansible/inventory/localhost.yml`
- Create: `ansible/group_vars/all.yml`

- [ ] **Step 1: Create `ansible/inventory/localhost.yml`**

```yaml
# Static inventory — always localhost. Never commit hermes-machine.yml (it's generated).
all:
  hosts:
    localhost:
      ansible_connection: local
```

- [ ] **Step 2: Create `ansible/group_vars/all.yml`**

```yaml
# Non-secret defaults. Override in host_vars/localhost.yml (generated from .env by just setup).

# Ollama
ollama_host: "0.0.0.0"
ollama_port: 11434

# Podman machine
podman_machine_name: "hermes-machine"
podman_machine_cpus: 4
podman_machine_memory_mb: 6144
podman_machine_disk_gb: 40

# Container image registry
ghcr_owner: "{{ lookup('env', 'GHCR_OWNER') }}"

# Allowed models (comma-separated string from env)
allowed_models: "{{ lookup('env', 'ALLOWED_MODELS') | default('hermes3') }}"

# Discord
discord_token: "{{ lookup('env', 'DISCORD_TOKEN') }}"
discord_channel_id: "{{ lookup('env', 'DISCORD_CHANNEL_ID') }}"

# Proxy tuning
rate_limit_burst: "{{ lookup('env', 'RATE_LIMIT_BURST') | default('20') }}"
rate_limit_per_min: "{{ lookup('env', 'RATE_LIMIT_PER_MIN') | default('5') }}"
max_tool_rounds: "{{ lookup('env', 'MAX_TOOL_ROUNDS') | default('10') }}"
tool_timeout_secs: "{{ lookup('env', 'TOOL_TIMEOUT_SECS') | default('120') }}"

# Network
zt_interface: "{{ lookup('env', 'ZT_INTERFACE') }}"
zt_subnet: "{{ lookup('env', 'ZT_SUBNET') }}"
vm_subnet: "{{ lookup('env', 'VM_SUBNET') | default('192.168.64.0/24') }}"
# vm_bridge_iface is discovered at runtime by the firewall role via `route get`.
# This default is used if discovery fails (bridge100 is the Podman machine default on macOS).
vm_bridge_iface: "bridge100"
```

- [ ] **Step 3: Commit**

```bash
cd ~/Projects/hermes-vm
git add ansible/
git commit -m "feat(infra): add Ansible inventory and group vars"
```

---

### Task 7: Ansible role — prerequisites

**Files:**
- Create: `ansible/roles/prerequisites/tasks/main.yml`

- [ ] **Step 1: Create `ansible/roles/prerequisites/tasks/main.yml`**

```yaml
---
# Verify all required tools are installed before any other role runs.
# brew bundle was already run by `just setup` before Ansible is invoked.

- name: Check that required binaries are on PATH
  ansible.builtin.command: "which {{ item }}"
  changed_when: false
  loop:
    - podman
    - ollama
    - just
    - gh
    - age
    - ansible

- name: Check Podman version meets minimum (4.x)
  ansible.builtin.command: podman --version
  register: podman_version
  changed_when: false

- name: Assert Podman 4 or higher
  ansible.builtin.assert:
    that: podman_version.stdout | regex_search('podman version ([0-9]+)', '\\1') | first | int >= 4
    fail_msg: "Podman 4+ required. Got: {{ podman_version.stdout }}"
    success_msg: "Podman version OK: {{ podman_version.stdout }}"
```

- [ ] **Step 2: Commit**

```bash
cd ~/Projects/hermes-vm
git add ansible/roles/prerequisites/
git commit -m "feat(infra): add Ansible prerequisites role"
```

---

### Task 8: Ansible role — ollama (launchd)

**Files:**
- Create: `ansible/roles/ollama/tasks/main.yml`
- Create: `ansible/roles/ollama/templates/com.hermes.ollama.plist.j2`

- [ ] **Step 1: Create `ansible/roles/ollama/templates/com.hermes.ollama.plist.j2`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.hermes.ollama</string>

    <key>ProgramArguments</key>
    <array>
        <!-- ollama_bin.stdout is registered by `which ollama` in tasks/main.yml.
             On Apple Silicon with Homebrew this is /opt/homebrew/bin/ollama, not /usr/local/bin/ollama. -->
        <string>{{ ollama_bin.stdout | trim }}</string>
        <string>serve</string>
    </array>

    <key>EnvironmentVariables</key>
    <dict>
        <key>OLLAMA_HOST</key>
        <string>{{ ollama_host }}:{{ ollama_port }}</string>
        <key>HOME</key>
        <string>{{ ansible_env.HOME }}</string>
        <key>PATH</key>
        <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
    </dict>

    <!-- KeepAlive=true: ollama serve is a long-running daemon; restart on crash -->
    <key>KeepAlive</key>
    <true/>

    <key>RunAtLoad</key>
    <true/>

    <key>StandardOutPath</key>
    <string>/tmp/com.hermes.ollama.out.log</string>

    <key>StandardErrorPath</key>
    <string>/tmp/com.hermes.ollama.err.log</string>
</dict>
</plist>
```

- [ ] **Step 2: Create `ansible/roles/ollama/tasks/main.yml`**

```yaml
---
- name: Find ollama binary path
  ansible.builtin.command: which ollama
  register: ollama_bin
  changed_when: false

- name: Deploy Ollama launchd plist
  ansible.builtin.template:
    src: com.hermes.ollama.plist.j2
    dest: "{{ ansible_env.HOME }}/Library/LaunchAgents/com.hermes.ollama.plist"
    mode: "0644"
  notify: reload ollama launchd

- name: Load Ollama launchd service
  ansible.builtin.command: >
    launchctl load -w
    {{ ansible_env.HOME }}/Library/LaunchAgents/com.hermes.ollama.plist
  register: load_result
  changed_when: load_result.rc == 0
  failed_when: load_result.rc != 0 and "already loaded" not in load_result.stderr

- name: Pull allowed Ollama models
  ansible.builtin.command: "ollama pull {{ item }}"
  loop: "{{ allowed_models.split(',') | map('trim') | list }}"
  register: pull_result
  changed_when: "'already up to date' not in pull_result.stdout"
  environment:
    OLLAMA_HOST: "http://{{ ollama_host }}:{{ ollama_port }}"
```

- [ ] **Step 3: Create `ansible/roles/ollama/handlers/main.yml`**

```yaml
---
- name: reload ollama launchd
  ansible.builtin.command: >
    launchctl unload
    {{ ansible_env.HOME }}/Library/LaunchAgents/com.hermes.ollama.plist
  ignore_errors: true
  notify: load ollama launchd

- name: load ollama launchd
  ansible.builtin.command: >
    launchctl load -w
    {{ ansible_env.HOME }}/Library/LaunchAgents/com.hermes.ollama.plist
```

- [ ] **Step 4: Commit**

```bash
cd ~/Projects/hermes-vm
git add ansible/roles/ollama/
git commit -m "feat(infra): add Ansible ollama role with launchd plist"
```

---

### Task 9: Ansible role — firewall

**Files:**
- Create: `ansible/roles/firewall/tasks/main.yml`
- Create: `ansible/roles/firewall/templates/com.hermes.pf.plist.j2`

- [ ] **Step 1: Create `ansible/roles/firewall/templates/com.hermes.pf.plist.j2`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.hermes.pf</string>

    <key>ProgramArguments</key>
    <array>
        <string>/sbin/pfctl</string>
        <string>-f</string>
        <string>/etc/pf.d/hermes.conf</string>
        <string>-e</string>
    </array>

    <!-- RunAtLoad: reloads hermes pf rules on every login/reboot.
         This ensures rules survive macOS updates that reset pf to defaults. -->
    <key>RunAtLoad</key>
    <true/>

    <key>StandardOutPath</key>
    <string>/tmp/com.hermes.pf.out.log</string>

    <key>StandardErrorPath</key>
    <string>/tmp/com.hermes.pf.err.log</string>
</dict>
</plist>
```

- [ ] **Step 2: Create `ansible/roles/firewall/tasks/main.yml`**

```yaml
---
- name: Ensure /etc/pf.d directory exists
  ansible.builtin.file:
    path: /etc/pf.d
    state: directory
    mode: "0755"
  become: true

- name: Get VM SSH hostname (to locate the bridge interface)
  ansible.builtin.shell: >
    podman machine ssh-config {{ podman_machine_name }} | awk '/HostName/ {print $2}'
  register: vm_ip_result
  changed_when: false
  failed_when: false

- name: Discover VM bridge interface via route lookup
  ansible.builtin.shell: >
    route get {{ vm_ip_result.stdout | trim }} | awk '/interface:/ {print $2}'
  register: bridge_result
  changed_when: false
  failed_when: false
  when: vm_ip_result.stdout | trim | length > 0

- name: Set vm_bridge_iface fact (falls back to bridge100 if discovery fails)
  ansible.builtin.set_fact:
    vm_bridge_iface: "{{ (bridge_result.stdout | default('') | trim) or 'bridge100' }}"

- name: Render hermes pf rules
  ansible.builtin.template:
    src: "{{ playbook_dir }}/../host/firewall/hermes.pf.conf.j2"
    dest: /etc/pf.d/hermes.conf
    mode: "0644"
  become: true
  notify: reload pf rules

- name: Load pf rules now
  ansible.builtin.command: pfctl -f /etc/pf.d/hermes.conf -e
  become: true
  changed_when: true
  ignore_errors: true   # pfctl -e fails if pf is already enabled — that's fine

- name: Deploy pf boot launchd plist
  ansible.builtin.template:
    src: com.hermes.pf.plist.j2
    dest: "{{ ansible_env.HOME }}/Library/LaunchAgents/com.hermes.pf.plist"
    mode: "0644"

- name: Load pf launchd plist
  ansible.builtin.command: >
    launchctl load -w
    {{ ansible_env.HOME }}/Library/LaunchAgents/com.hermes.pf.plist
  register: pf_load
  changed_when: pf_load.rc == 0
  failed_when: pf_load.rc != 0 and "already loaded" not in pf_load.stderr
```

- [ ] **Step 3: Create `ansible/roles/firewall/handlers/main.yml`**

```yaml
---
- name: reload pf rules
  ansible.builtin.command: pfctl -f /etc/pf.d/hermes.conf
  become: true
  ignore_errors: true
```

- [ ] **Step 4: Commit**

```bash
cd ~/Projects/hermes-vm
git add ansible/roles/firewall/
git commit -m "feat(infra): add Ansible firewall role with pf rules and boot plist"
```

---

### Task 10: Ansible role — podman-machine

**Files:**
- Create: `ansible/roles/podman-machine/tasks/main.yml`
- Create: `ansible/roles/podman-machine/templates/com.hermes.podman-machine.plist.j2`

- [ ] **Step 1: Create `ansible/roles/podman-machine/templates/com.hermes.podman-machine.plist.j2`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.hermes.podman-machine</string>

    <key>ProgramArguments</key>
    <array>
        <!-- playbook_dir is the ansible/ directory; go up one level to reach the repo root -->
        <string>{{ playbook_dir }}/../scripts/start-hermes-machine.sh</string>
    </array>

    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key>
        <string>{{ ansible_env.HOME }}</string>
        <key>PATH</key>
        <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
    </dict>

    <!-- KeepAlive=false: the script exits after the machine is up.
         KeepAlive=true would cause a tight restart loop since
         `podman machine start` exits immediately on an already-running machine. -->
    <key>KeepAlive</key>
    <false/>

    <key>RunAtLoad</key>
    <true/>

    <key>StandardOutPath</key>
    <string>/tmp/com.hermes.podman-machine.out.log</string>

    <key>StandardErrorPath</key>
    <string>/tmp/com.hermes.podman-machine.err.log</string>
</dict>
</plist>
```

- [ ] **Step 2: Create `ansible/roles/podman-machine/tasks/main.yml`**

```yaml
---
- name: Check if hermes-machine already exists
  ansible.builtin.command: podman machine inspect {{ podman_machine_name }}
  register: machine_inspect
  changed_when: false
  failed_when: false

- name: Create hermes-machine if it does not exist
  ansible.builtin.command: >
    podman machine init {{ podman_machine_name }}
    --cpus {{ podman_machine_cpus }}
    --memory {{ podman_machine_memory_mb }}
    --disk-size {{ podman_machine_disk_gb }}
    --now
  when: machine_inspect.rc != 0

- name: Start hermes-machine if not running
  ansible.builtin.command: scripts/start-hermes-machine.sh
  args:
    chdir: "{{ playbook_dir }}/.."
  register: start_result
  changed_when: "'Starting' in start_result.stdout"

- name: Deploy podman-machine start script (ensures launchd plist target is always current)
  ansible.builtin.copy:
    src: "{{ playbook_dir }}/../scripts/start-hermes-machine.sh"
    dest: "{{ playbook_dir }}/../scripts/start-hermes-machine.sh"
    mode: "0755"
    remote_src: true

- name: Deploy podman-machine launchd plist
  ansible.builtin.template:
    src: com.hermes.podman-machine.plist.j2
    dest: "{{ ansible_env.HOME }}/Library/LaunchAgents/com.hermes.podman-machine.plist"
    mode: "0644"

- name: Load podman-machine launchd plist
  ansible.builtin.command: >
    launchctl load -w
    {{ ansible_env.HOME }}/Library/LaunchAgents/com.hermes.podman-machine.plist
  register: pm_load
  changed_when: pm_load.rc == 0
  failed_when: pm_load.rc != 0 and "already loaded" not in pm_load.stderr
```

- [ ] **Step 3: Commit**

```bash
cd ~/Projects/hermes-vm
git add ansible/roles/podman-machine/
git commit -m "feat(infra): add Ansible podman-machine role with launchd plist"
```

---

### Task 11: Ansible role — vm-quadlets

**Files:**
- Create: `ansible/roles/vm-quadlets/tasks/main.yml`

This role SSHes into the running VM and deploys all quadlet files plus an env file containing the runtime secrets/config. It then reloads systemd so the new units are picked up.

- [ ] **Step 1: Create `ansible/roles/vm-quadlets/tasks/main.yml`**

```yaml
---
# Render quadlet files on the Ansible controller (localhost), substituting {{ ghcr_owner }}.
# The quadlet files use Jinja2 syntax ({{ ghcr_owner }}) — template renders them locally,
# then copy uploads them to the VM target.
- name: Ensure staging directory exists on controller
  ansible.builtin.file:
    path: /tmp/hermes-quadlets
    state: directory
    mode: "0755"
  delegate_to: localhost

- name: Render quadlet files on controller (substitutes ghcr_owner)
  ansible.builtin.template:
    src: "{{ playbook_dir }}/../vm/quadlets/{{ item }}"
    dest: "/tmp/hermes-quadlets/{{ item }}"
    mode: "0644"
  delegate_to: localhost
  loop:
    - hermes.network
    - hermes-proxy.container
    - hermes-webui.container
    - hermes-searxng.container
    - hermes-discord.container

- name: Ensure /etc/containers/systemd exists in VM
  ansible.builtin.file:
    path: /etc/containers/systemd
    state: directory
    mode: "0755"
  become: true

- name: Copy quadlet files into VM
  ansible.builtin.copy:
    src: "/tmp/hermes-quadlets/{{ item }}"
    dest: "/etc/containers/systemd/{{ item }}"
    mode: "0644"
  become: true
  loop:
    - hermes.network
    - hermes-proxy.container
    - hermes-webui.container
    - hermes-searxng.container
    - hermes-discord.container
  notify: reload systemd daemon

- name: Write hermes.env into VM
  ansible.builtin.copy:
    content: |
      ALLOWED_MODELS={{ allowed_models }}
      OLLAMA_HOST=http://host.containers.internal:11434
      RATE_LIMIT_BURST={{ rate_limit_burst }}
      RATE_LIMIT_PER_MIN={{ rate_limit_per_min }}
      MAX_TOOL_ROUNDS={{ max_tool_rounds }}
      TOOL_TIMEOUT_SECS={{ tool_timeout_secs }}
      DISCORD_TOKEN={{ discord_token }}
      DISCORD_CHANNEL_ID={{ discord_channel_id }}
    dest: /etc/containers/systemd/hermes.env
    mode: "0600"
  become: true
  notify: reload systemd daemon
```

- [ ] **Step 2: Create `ansible/roles/vm-quadlets/handlers/main.yml`**

```yaml
---
- name: reload systemd daemon
  ansible.builtin.command: systemctl daemon-reload
  become: true
  notify: restart hermes services

- name: restart hermes services
  ansible.builtin.systemd:
    name: "{{ item }}"
    state: restarted
    enabled: true
  become: true
  loop:
    - hermes-proxy
    - hermes-webui
    - hermes-searxng
    - hermes-discord
  ignore_errors: true   # some may not be running yet on first deploy
```

- [ ] **Step 3: Commit**

```bash
cd ~/Projects/hermes-vm
git add ansible/roles/vm-quadlets/
git commit -m "feat(infra): add Ansible vm-quadlets role"
```

---

### Task 12: Ansible role — vm-volumes

**Files:**
- Create: `ansible/roles/vm-volumes/tasks/main.yml`

- [ ] **Step 1: Create `ansible/roles/vm-volumes/tasks/main.yml`**

```yaml
---
# This play runs on hermes-machine as the `core` user (rootless Podman).
# Do NOT use `become: true` for podman volume commands — escalating to root creates
# root-owned volumes that the rootless containers cannot access.

- name: Create hermes-webui-data volume
  ansible.builtin.command: podman volume create hermes-webui-data
  register: webui_vol
  changed_when: webui_vol.rc == 0
  failed_when: webui_vol.rc != 0 and "already exists" not in webui_vol.stderr

- name: Create hermes-searxng-config volume
  ansible.builtin.command: podman volume create hermes-searxng-config
  register: searxng_vol
  changed_when: searxng_vol.rc == 0
  failed_when: searxng_vol.rc != 0 and "already exists" not in searxng_vol.stderr

- name: Get SearXNG volume mountpoint
  ansible.builtin.command: >
    podman volume inspect hermes-searxng-config --format "{{ '{{' }}.Mountpoint{{ '}}' }}"
  register: searxng_mount
  changed_when: false

- name: Copy SearXNG settings.yml into volume (no become — rootless volume owned by core)
  ansible.builtin.copy:
    src: "{{ playbook_dir }}/../vm/searxng/settings.yml"
    dest: "{{ searxng_mount.stdout | trim }}/settings.yml"
    mode: "0644"
```

- [ ] **Step 2: Commit**

```bash
cd ~/Projects/hermes-vm
git add ansible/roles/vm-volumes/
git commit -m "feat(infra): add Ansible vm-volumes role with SearXNG seed config"
```

---

### Task 13: Ansible role — vm-autoupdate

**Files:**
- Create: `ansible/roles/vm-autoupdate/tasks/main.yml`
- Create: `ansible/roles/vm-autoupdate/templates/hermes-autoupdate.service.j2`
- Create: `ansible/roles/vm-autoupdate/templates/hermes-autoupdate.timer.j2`

- [ ] **Step 1: Create `ansible/roles/vm-autoupdate/templates/hermes-autoupdate.service.j2`**

```ini
[Unit]
Description=Hermes auto-update container images
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/podman auto-update
StandardOutput=journal
StandardError=journal
```

- [ ] **Step 2: Create `ansible/roles/vm-autoupdate/templates/hermes-autoupdate.timer.j2`**

```ini
[Unit]
Description=Daily Hermes container image auto-update

[Timer]
# Run daily at 3 AM to pull and restart containers with new images
OnCalendar=daily
RandomizedDelaySec=1800
Persistent=true

[Install]
WantedBy=timers.target
```

- [ ] **Step 3: Create `ansible/roles/vm-autoupdate/tasks/main.yml`**

```yaml
---
- name: Configure journald log rotation (cap at 500MB, 2 weeks)
  ansible.builtin.copy:
    content: |
      [Journal]
      SystemMaxUse=500M
      MaxRetentionSec=2weeks
    dest: /etc/systemd/journald.conf.d/hermes.conf
    mode: "0644"
  become: true
  notify: restart journald

- name: Deploy auto-update systemd service
  ansible.builtin.template:
    src: hermes-autoupdate.service.j2
    dest: /etc/systemd/system/hermes-autoupdate.service
    mode: "0644"
  become: true
  notify: reload systemd

- name: Deploy auto-update systemd timer
  ansible.builtin.template:
    src: hermes-autoupdate.timer.j2
    dest: /etc/systemd/system/hermes-autoupdate.timer
    mode: "0644"
  become: true
  notify: reload systemd

- name: Enable and start the auto-update timer
  ansible.builtin.systemd:
    name: hermes-autoupdate.timer
    state: started
    enabled: true
    daemon_reload: true
  become: true
```

- [ ] **Step 4: Create `ansible/roles/vm-autoupdate/handlers/main.yml`**

```yaml
---
- name: reload systemd
  ansible.builtin.command: systemctl daemon-reload
  become: true

- name: restart journald
  ansible.builtin.systemd:
    name: systemd-journald
    state: restarted
  become: true
```

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/hermes-vm
git add ansible/roles/vm-autoupdate/
git commit -m "feat(infra): add Ansible vm-autoupdate role with daily timer and journald cap"
```

---

### Task 14: Ansible site.yml and lint check

**Files:**
- Create: `ansible/site.yml`

- [ ] **Step 1: Create `ansible/site.yml`**

```yaml
---
# Master playbook — runs all hermes-vm roles in dependency order.
# Run via: just setup   (first time)   or   just update   (subsequent runs)

# ── Host roles (run on macOS localhost) ───────────────────────────────────────
- name: Provision macOS host
  hosts: localhost
  gather_facts: true
  roles:
    - prerequisites
    - ollama
    - firewall
    - podman-machine

# ── VM roles (run inside hermes-machine via SSH) ──────────────────────────────
- name: Provision hermes-machine VM
  hosts: hermes-machine
  gather_facts: true
  roles:
    - vm-quadlets
    - vm-volumes
    - vm-autoupdate
```

- [ ] **Step 2: Run ansible-lint to catch syntax errors**

```bash
cd ~/Projects/hermes-vm
ansible-lint ansible/site.yml
```

Expected: No errors (warnings about `changed_when: false` or deprecated syntax are OK, but `ERROR` lines must be fixed before continuing).

Common fixes:
- `ansible.builtin.` prefix required for all modules (already added above)
- `become: true` required for tasks that write to system paths
- Handler names must match exactly

- [ ] **Step 3: Validate YAML syntax on all role files**

```bash
cd ~/Projects/hermes-vm
find ansible/ -name "*.yml" | xargs python3 -c "
import sys, yaml
for f in sys.argv[1:]:
    try:
        yaml.safe_load(open(f))
        print(f'OK: {f}')
    except yaml.YAMLError as e:
        print(f'ERROR: {f}: {e}')
        sys.exit(1)
"
```

Expected: all files print `OK:`.

- [ ] **Step 4: Commit**

```bash
cd ~/Projects/hermes-vm
git add ansible/site.yml
git commit -m "feat(infra): add Ansible site.yml master playbook"
```

- [ ] **Step 5: Push to GitHub**

```bash
cd ~/Projects/hermes-vm
git push origin main
```
