# Setup Guide

Step-by-step first-time setup for hermes-vm on a fresh Apple Silicon Mac.

---

## Prerequisites Checklist

Before starting, confirm you have or can create all of the following:

- [ ] Apple Silicon Mac (M1 or later). Intel Macs are not supported.
- [ ] macOS 13 (Ventura) or later.
- [ ] [ZeroTier](https://www.zerotier.com/) account with a network already created. The Mac must already be joined to that network (`zerotier-cli join <network-id>`).
- [ ] A Discord account with permission to create a bot in your server.
- [ ] A GitHub account (used for `gh auth login`, container image pulls from ghcr.io, and optional GitHub issue integration).
- [ ] `just` installed: `brew install just`.

---

## Step 1: Create a Discord Bot

You need a bot token and a channel ID before you can fill in `.env`.

### Create the application

1. Go to [https://discord.com/developers/applications](https://discord.com/developers/applications) and click **New Application**.
2. Give it a name (e.g. `Hermes`) and click **Create**.
3. In the left sidebar, click **Bot**.
4. Click **Add Bot**, then confirm.
5. Under **Token**, click **Reset Token**, confirm, then copy the token. This is your `DISCORD_TOKEN`. Store it somewhere safe — you cannot view it again.

### Enable the Message Content Intent

On the Bot page, scroll to **Privileged Gateway Intents** and enable **Message Content Intent**. Without this the bot cannot read message text.

Click **Save Changes**.

### Invite the bot to your server

1. In the left sidebar, click **OAuth2 > URL Generator**.
2. Under **Scopes**, check `bot`.
3. Under **Bot Permissions**, check `Send Messages`, `Read Message History`, `Read Messages/View Channels`, and `Manage Channels` (needed to create research report channels automatically).
4. Copy the generated URL, open it in a browser, and select your Discord server.

### Get the channel ID

1. In Discord, open **User Settings > Advanced** and enable **Developer Mode**.
2. Right-click the channel you want Hermes to use and click **Copy Channel ID**.
3. This is your `DISCORD_CHANNEL_ID`.

---

## Step 2: Create a GitHub Token (Optional but Recommended)

A GitHub personal access token lets Hermes create and manage GitHub issues on your behalf. Without it, the GitHub tools (`github_create_issue`, `github_list_issues`, etc.) will not work, but everything else functions normally.

### Create a fine-grained personal access token

1. Go to [https://github.com/settings/personal-access-tokens/new](https://github.com/settings/personal-access-tokens/new).
2. Give it a name (e.g. `hermes-vm`).
3. Under **Repository access**, select **Only select repositories** and add any repos you want Hermes to manage issues on.
4. Under **Permissions**, expand **Repository permissions** and set **Issues** to **Read and write**.
5. Click **Generate token** and copy the result. This is your `GITHUB_TOKEN`.

> **Scope note:** A fine-grained token scoped only to Issues read+write is the minimum required. Do not grant broader permissions than you need.

---

## Step 3: Install Just

If you have not already installed `just`:

```bash
brew install just
```

`just setup` will handle all remaining prerequisite installation via Brewfile (Podman, Ollama, Ansible, etc.).

---

## Step 4: Clone the Repository

```bash
git clone https://github.com/<your-github-username>/hermes-vm.git
cd hermes-vm
gh auth login   # if not already authenticated
```

---

## Step 5: Configure .env

Copy the example file and fill in every variable:

```bash
cp .env.example .env
```

Open `.env` in your editor. Each variable is explained below.

### ZeroTier

```bash
ZT_INTERFACE=ztXXXXXXXX
ZT_SUBNET=10.x.x.0/24
```

- `ZT_INTERFACE`: The name of your ZeroTier network interface. Find it with:
  ```bash
  zerotier-cli listnetworks
  # or: ifconfig | grep zt
  ```
  It looks like `ztabcdef12`.

- `ZT_SUBNET`: The CIDR subnet of your ZeroTier network. Find it in the ZeroTier Central web dashboard under **Managed Routes**, or with `zerotier-cli listnetworks` (the `Network` column). Example: `10.147.18.0/24`.

### Podman Machine Bridge

```bash
VM_SUBNET=192.168.64.0/24
```

- `VM_SUBNET`: The subnet Podman assigns to the VM bridge interface. The default `192.168.64.0/24` is correct for most setups. You can confirm after setup with:
  ```bash
  ifconfig | grep -A1 bridge100
  ```

### Ollama

```bash
ALLOWED_MODELS=gemma4:e4b,gemma4:26b
OLLAMA_NUM_PARALLEL=5
```

- `ALLOWED_MODELS`: Comma-separated list of Ollama model names the proxy will permit. Requests for any other model return 403. Model names are case-sensitive and must match Ollama's naming exactly (including tags like `:e4b`). These models are pulled automatically during setup.
- `OLLAMA_NUM_PARALLEL`: How many concurrent inference slots Ollama exposes. Must match what the proxy uses. `5` is a good default for M-series Macs with ≥16GB unified memory.

**Common model choices:**

| Model | Size | Use |
|---|---|---|
| `gemma4:e4b` | ~3GB | Fast, efficient — good default chat model |
| `gemma4:26b` | ~16GB | Higher quality — used for research report synthesis |
| `hermes3` | ~5GB | Original Nous Hermes 3 model |
| `qwen3-coder:30b` | ~18GB | Code-focused tasks |

### Research Pipeline Models

The deep research tool uses three separate model roles. The defaults are sensible and work well; only change these if you want to experiment:

```bash
# RESEARCH_AGENT_MODEL=gemma4:e4b         # Per-query research agents (fast, runs many in parallel)
# RESEARCH_ORCHESTRATOR_MODEL=gemma4:e4b  # Decides coverage gaps between rounds
# RESEARCH_REPORT_MODEL=gemma4:26b        # Synthesizes the final cited report (quality matters)
# RESEARCH_OLLAMA_PARALLEL=3              # Max concurrent agent calls (lower = fewer GPU timeouts)
# RESEARCH_REPORT_CHANNEL=research        # Discord channel to post reports to
```

All three are commented out in `.env.example` — the proxy uses these defaults automatically. Uncomment only what you want to change.

> **GPU contention note:** `RESEARCH_OLLAMA_PARALLEL` is intentionally lower than `OLLAMA_NUM_PARALLEL`. Running too many concurrent agents causes GPU memory bandwidth contention and Ollama request timeouts. Keep this at 3–4 unless you have tested higher values on your hardware.

### Discord

```bash
DISCORD_TOKEN=your-bot-token-here
DISCORD_CHANNEL_ID=your-channel-id-here
```

- `DISCORD_TOKEN`: The bot token you copied in Step 1.
- `DISCORD_CHANNEL_ID`: The numeric channel ID you copied in Step 1.

### GitHub

```bash
GITHUB_TOKEN=your-github-token-here
```

- `GITHUB_TOKEN`: The fine-grained personal access token from Step 2. Leave blank or omit if you don't need GitHub issue integration.

### Default Model

```bash
# MODEL=gemma4:e4b
```

- `MODEL`: The Ollama model used for regular Discord chat. Defaults to `gemma4:e4b` if unset. Must be in `ALLOWED_MODELS`. Uncomment and change to switch the default.

### GitHub Container Registry

```bash
GHCR_OWNER=your-github-username
```

- `GHCR_OWNER`: Your GitHub username. Used to pull container images from `ghcr.io/<owner>/hermes-proxy:latest` and `ghcr.io/<owner>/hermes-discord:latest`. If using the upstream repo without a fork, use the upstream owner's username.

### Proxy Tuning

```bash
RATE_LIMIT_BURST=20
RATE_LIMIT_PER_MIN=5
MAX_TOOL_ROUNDS=10
TOOL_TIMEOUT_SECS=120
```

These control rate limiting and tool-call behavior. The defaults are appropriate for personal use — no need to change them unless you're hitting limits.

---

## Step 6: Run just setup

```bash
just setup
```

`just setup` runs the following steps in order:

1. **`brew bundle`** — installs all tools in `Brewfile`: `podman`, `ollama`, `ansible`, `just`, `gh`, `age`.
2. **`scripts/gen-inventory.sh` (first pass)** — attempts to generate the Ansible inventory for the VM. This may fail if the VM doesn't exist yet — that is expected and non-fatal.
3. **Ansible: `prerequisites` and `podman-machine` tags** — creates the `hermes-machine` Podman VM (2GB RAM, 4 CPUs, 40GB disk) if it doesn't exist.
4. **`scripts/gen-inventory.sh` (second pass)** — now that the VM exists, discovers its SSH port and writes `ansible/inventory/hermes-machine.yml`.
5. **Full Ansible run (`site.yml`)**:
   - `prerequisites`: confirms required tools are present.
   - `ollama`: deploys Ollama with `OLLAMA_HOST=0.0.0.0` and pulls all models in `ALLOWED_MODELS`.
   - `firewall`: configures pf rules to restrict Ollama access to localhost, ZeroTier, and the VM bridge.
   - `podman-machine`: deploys the VM start script and launchd plist for auto-start on login.
   - `vm-quadlets`: SSHs into the VM, deploys container quadlet files and the env file, runs `systemctl daemon-reload` to start services.
   - `vm-volumes`: creates named volumes and seeds SearXNG configuration.
   - `vm-autoupdate`: installs a daily image update timer and caps the systemd journal at 500MB.

**Expected output:** Ansible tasks show `ok` (already correct) or `changed` (just applied). No `failed` tasks. Model pulls can take several minutes depending on connection speed — `gemma4:26b` is roughly 16GB.

---

## Step 7: Verify Everything Works

### Check service status

```bash
just status
```

Expected output:
- All `hermes-*` units listed as `active (running)`.
- `hermes pf rules are loaded` (not the WARNING variant).

### Test Discord

Send a message in your configured channel. Hermes should reply within a few seconds. Try:
- A plain question to test basic chat
- `!search <query>` or asking Hermes to look something up to test web search
- `!model` to see the active model

Use `!clear` to reset conversation history.

### Check logs if something is wrong

```bash
just logs
```

Tails the systemd journal for all `hermes-*` units inside the VM.

---

## Optional: Enable Open WebUI

Open WebUI is disabled by default to keep the VM lean (2GB RAM). To enable it:

1. In `ansible/group_vars/all.yml`, set `enable_webui: true`. This allocates an extra 1GB to the VM (total 3GB).
2. Run `just update` to apply the change.
3. Access via `http://<your-zerotier-ip>:3000`. You will be prompted to create an account on first visit.

---

## Optional: Configure age Secrets Encryption

If you want to commit your `.env` to a private fork without exposing secrets in plaintext:

```bash
# Encrypt .env using your SSH public key
just encrypt-env
# → produces .env.age

# Commit .env.age to your private fork
git add .env.age
git commit -m "chore: add encrypted env"
git push

# On another machine or after a fresh clone:
just decrypt-env
# → restores .env from .env.age using ~/.ssh/id_ed25519
```

The public repo ships only `.env.example`. The `.env` and `.env.age` files are both gitignored.

---

## Troubleshooting

### pf rules not loaded after reboot

```bash
just status   # warns if hermes rules are not active
sudo pfctl -f /etc/pf.d/hermes.conf -e
```

macOS system updates can silently revert pf to defaults. The launchd plist (`com.hermes.pf.plist`) reloads rules at login but manual reload may be needed after an OS update.

### VM not starting

```bash
podman machine list
podman machine start hermes-machine
```

If the machine is missing entirely, run `just setup` to recreate it.

### 403 on model requests

The model name in your request must exactly match an entry in `ALLOWED_MODELS` (case-sensitive, tags included). After changing `ALLOWED_MODELS`, run `just update` to push the change into the proxy container.

### Discord bot not responding

Verify `DISCORD_TOKEN` and `DISCORD_CHANNEL_ID` in `.env`. The bot only reads messages in the single channel specified by `DISCORD_CHANNEL_ID`. Also confirm **Message Content Intent** is enabled in the Discord developer portal.

### Research jobs failing with timeouts

The most common cause is GPU contention from too many concurrent agents. Try reducing `RESEARCH_OLLAMA_PARALLEL` to `2` or `3` in `.env`, then run `just update`. Also verify `OLLAMA_NUM_PARALLEL` on the host matches what's in `.env`.

### GitHub tools returning errors

Check that `GITHUB_TOKEN` is set in `.env` and that the token has **Issues** read+write permission on the target repository. The token is injected into the container via `hermes.env` during `just update`.

### Containers not found / just restart failing

The containers run at system level inside the VM, not as a user service. Commands that SSH into the VM use `sudo systemctl`. If you are manually inspecting:

```bash
just ssh
sudo systemctl status hermes-proxy hermes-discord hermes-searxng
```
