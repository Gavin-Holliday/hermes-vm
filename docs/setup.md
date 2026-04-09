# Setup Guide

Step-by-step first-time setup for hermes-vm on a fresh Apple Silicon Mac.

---

## Prerequisites Checklist

Before starting, confirm you have or can create all of the following:

- [ ] Apple Silicon Mac (M1 or later). Intel Macs are not supported.
- [ ] macOS 13 (Ventura) or later.
- [ ] [ZeroTier](https://www.zerotier.com/) account with a network already created. The Mac must already be joined to that network (`zerotier-cli join <network-id>`).
- [ ] A Discord account with permission to create a bot in your server.
- [ ] A GitHub account (used for `gh auth login` and container image pulls from ghcr.io).
- [ ] `just` installed: `brew install just`.

---

## Step 1: Create a Discord Bot

You need a bot token and a channel ID before you can fill in `.env`.

### Create the application

1. Go to [https://discord.com/developers/applications](https://discord.com/developers/applications) and click **New Application**.
2. Give it a name (e.g. `Hermes`) and click **Create**.
3. In the left sidebar, click **Bot**.
4. Click **Add Bot**, then confirm.
5. Under **Token**, click **Reset Token**, confirm, then copy the token. This is your `DISCORD_TOKEN`. Store it somewhere safe — you will not be able to see it again.

### Enable the Message Content Intent

On the Bot page, scroll to **Privileged Gateway Intents** and enable **Message Content Intent**. Without this the bot cannot read message text.

Click **Save Changes**.

### Invite the bot to your server

1. In the left sidebar, click **OAuth2 > URL Generator**.
2. Under **Scopes**, check `bot`.
3. Under **Bot Permissions**, check `Send Messages`, `Read Message History`, and `Read Messages/View Channels`.
4. Copy the generated URL, open it in a browser, and select your Discord server to invite the bot.

### Get the channel ID

1. In Discord, open **User Settings > Advanced** and enable **Developer Mode**.
2. Right-click the channel you want Hermes to use and click **Copy Channel ID**.
3. This is your `DISCORD_CHANNEL_ID`.

---

## Step 2: Install Just

If you have not already installed `just`:

```bash
brew install just
```

`just setup` will handle all remaining prerequisite installation via Brewfile (Podman, Ollama, Ansible, etc.).

---

## Step 3: Clone the Repository

```bash
git clone https://github.com/<your-github-username>/hermes-vm.git
cd hermes-vm
gh auth login   # if not already authenticated
```

---

## Step 4: Configure .env

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

- `ZT_SUBNET`: The CIDR subnet of your ZeroTier network. Find it in the ZeroTier Central web dashboard under your network's **Managed Routes**, or with `zerotier-cli listnetworks` (the `Network` column). Example: `10.147.18.0/24`.

### Podman Machine Bridge

```bash
VM_SUBNET=192.168.64.0/24
```

- `VM_SUBNET`: The subnet the Mac assigns to the Podman VM bridge. Before the VM exists, the default is `192.168.64.0/24`. You can confirm after setup with:
  ```bash
  ifconfig | grep -A1 bridge100
  ```
  Ansible discovers the actual interface name automatically — you only need to provide the subnet.

### Ollama

```bash
ALLOWED_MODELS=hermes3,gemma4:27b
```

- `ALLOWED_MODELS`: Comma-separated list of Ollama model names that the proxy will permit. Requests for any other model return 403. Model names are case-sensitive and must match Ollama's naming exactly (including tags like `:27b`). These models will be pulled automatically during setup.

### Discord

```bash
DISCORD_TOKEN=your-bot-token-here
DISCORD_CHANNEL_ID=your-channel-id-here
```

- `DISCORD_TOKEN`: The bot token you copied in Step 1.
- `DISCORD_CHANNEL_ID`: The numeric channel ID you copied in Step 1.

### Proxy Tuning

```bash
RATE_LIMIT_BURST=20
RATE_LIMIT_PER_MIN=5
MAX_TOOL_ROUNDS=10
TOOL_TIMEOUT_SECS=120
```

- `RATE_LIMIT_BURST`: Maximum requests that can be made in a short burst (token bucket). `20` is a reasonable default for personal use.
- `RATE_LIMIT_PER_MIN`: Sustained allowed request rate per minute. `5` allows a query roughly every 12 seconds.
- `MAX_TOOL_ROUNDS`: How many times the proxy will execute a web search tool call within a single conversation turn before stopping. Prevents runaway loops.
- `TOOL_TIMEOUT_SECS`: Hard timeout in seconds for a single turn, including all tool call rounds. The connection is closed with an error if this is exceeded.

### GitHub

```bash
GHCR_OWNER=your-github-username
```

- `GHCR_OWNER`: Your GitHub username. Used to construct container image pull URLs: `ghcr.io/<owner>/hermes-proxy:latest`. If you are using the upstream repo without a fork, use the upstream owner's username.

---

## Step 5: Run just setup

```bash
just setup
```

`just setup` runs the following steps in order:

1. **`brew bundle`** — installs all tools listed in `Brewfile`: `podman`, `ollama`, `ansible`, `just`, `gh`, `age`, and `podman-desktop` (optional GUI).

2. **`scripts/gen-inventory.sh` (first pass)** — attempts to generate the Ansible inventory for the VM. This may fail if the VM does not exist yet; that is expected and non-fatal.

3. **Ansible: `prerequisites` and `podman-machine` tags** — verifies installed tools and creates the `hermes-machine` Podman VM (6GB RAM, 4 CPUs, 40GB disk) if it does not already exist.

4. **`scripts/gen-inventory.sh` (second pass)** — now that the VM exists, discovers its SSH port and writes `ansible/inventory/hermes-machine.yml`.

5. **Full Ansible run (`site.yml`)**:
   - `prerequisites`: confirms all required tools are present.
   - `ollama`: deploys the Ollama launchd plist with `OLLAMA_HOST=0.0.0.0` and pulls all models in `ALLOWED_MODELS`.
   - `firewall`: renders the pf rules template with your ZeroTier and VM bridge settings, loads the rules, and installs a launchd plist to reload them on every boot.
   - `podman-machine`: deploys the VM start script and launchd plist for auto-start on login.
   - `vm-quadlets`: SSHs into the VM, deploys all container quadlet files and the env file, and runs `systemctl daemon-reload` to start the containers.
   - `vm-volumes`: creates named volumes (`hermes-webui-data`, `hermes-searxng-config`) and seeds the SearXNG `settings.yml`.
   - `vm-autoupdate`: installs a daily `podman auto-update` timer inside the VM and caps the systemd journal at 500MB.

**Expected output:** Ansible tasks will show `ok` (already correct) or `changed` (just applied). No `failed` tasks. Model pulls during the `ollama` role can take several minutes depending on connection speed — `hermes3` is roughly 5GB and `gemma4:27b` is roughly 18GB.

---

## Step 6: Verify Everything Works

### Check service status

```bash
just status
```

Expected output:
- All `hermes-*` units listed as `active (running)`.
- `hermes pf rules are loaded` (not the WARNING variant).

### Open WebUI

Open a browser and navigate to:
```
http://<your-zerotier-ip>:3000
```

You will be prompted to create an account on first visit (`WEBUI_AUTH=true`). After creating an account, the model selector should list the models from `ALLOWED_MODELS`.

### Test Discord

Send a message in the channel you configured. The bot should reply within a few seconds. Try asking it to search the web to verify tool use is working.

Use `!clear` to reset the conversation history if needed.

### Check logs if something is wrong

```bash
just logs
```

This tails the systemd journal for all `hermes-*` units inside the VM.

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

# Later, on another machine or after a fresh clone:
just decrypt-env
# → restores .env from .env.age using ~/.ssh/id_ed25519
```

The public repo ships only `.env.example`. The age workflow is opt-in. The `.env` and `.env.age` files are both gitignored in the public repo by default.
