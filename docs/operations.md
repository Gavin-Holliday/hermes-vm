# Operations Reference

Day-to-day operations for a running hermes-vm deployment.

---

## Daily Usage

### Discord

Send any message in the configured channel. The bot responds to the single channel specified by `DISCORD_CHANNEL_ID`. It ignores all other channels and all other bots.

**Commands:**

| Command | Effect |
|---|---|
| `!clear` | Clears the in-memory conversation history for the current channel. Use this to start a fresh context. |

The bot maintains a rolling per-channel message history capped at 20 messages (system prompt + alternating user/assistant turns). History is held in memory and lost when the bot container restarts. This is acceptable for personal use — if you need persistent history, use the WebUI instead.

Long responses (over 1990 characters) are automatically split into sequential messages.

### Open WebUI

Access the web interface over ZeroTier:
```
http://<your-zerotier-ip>:3000
```

Login is required (`WEBUI_AUTH=true`). Create your account on first visit. The model selector is populated by the proxy's `/api/tags` endpoint — it shows only models in `ALLOWED_MODELS`.

---

## Monitoring

### Service status

```bash
just status
```

Shows the systemd unit status for all `hermes-*` services inside the VM and checks whether the pf firewall rules are loaded. If the pf check shows a WARNING, Ollama may be reachable on all network interfaces — address it immediately (see [pf Firewall](#pf-firewall) below).

### Logs

```bash
just logs
```

Tails the systemd journal for all `hermes-*` units inside the VM in real time. Press `Ctrl+C` to exit. The journal is capped at 500MB with a 2-week retention window.

To inspect logs for a specific service after SSHing in:
```bash
just ssh
sudo journalctl -u hermes-proxy -n 100 --no-pager
```

---

## Updating

### Update container images only

```bash
just update-images
```

Runs `podman auto-update` inside the VM. Containers with `io.containers.autoupdate=registry` in their quadlet are restarted automatically when a newer image is pulled from the registry.

Use this when you want to pick up a new image release without changing any configuration. A daily systemd timer inside the VM also runs this automatically — `just update-images` is for on-demand pulls.

### Update configuration and quadlets

```bash
just update
```

Runs `git pull` followed by the full Ansible playbook (`ansible/site.yml`). Ansible is idempotent — only resources that differ from the desired state are changed. Running services are not restarted unless their quadlet definition or env file changed.

Use this when:
- You edited `.env` (model list, rate limits, Discord token, etc.)
- You pulled a new version of the repo that changed Ansible roles or quadlet files
- You manually edited any Ansible configuration

**Do not** use `just update` for image-only updates — it is slower than `just update-images` and unnecessary for that case.

---

## Pulling New Models

```bash
just pull-models
```

Pulls all models listed in `ALLOWED_MODELS` on the host via `ollama pull`. Run this after adding a new model to `ALLOWED_MODELS`.

### Adding a new model

1. Add the model name to `ALLOWED_MODELS` in `.env`. Use the exact Ollama model name including any tag (e.g., `gemma4:27b`).
2. Run `just update` to push the updated `ALLOWED_MODELS` to the proxy container.
3. Run `just pull-models` to download the model on the host.

The proxy will start accepting requests for the new model once the container restarts with the updated env (handled by `just update`).

---

## Restarting Services

```bash
just restart
```

Restarts all four hermes containers (`hermes-proxy`, `hermes-webui`, `hermes-searxng`, `hermes-discord`) inside the VM via systemd.

To restart a single service, SSH in and use systemctl directly:
```bash
just ssh
sudo systemctl restart hermes-proxy
```

---

## SSH Into the VM

```bash
just ssh
```

Opens an interactive SSH session into `hermes-machine`. Useful for inspecting container state, checking volume contents, or running one-off `podman` commands.

Useful commands once inside:
```bash
sudo podman ps                        # list running containers
sudo podman logs hermes-proxy         # last logs for a container
sudo systemctl status hermes-discord  # systemd unit details
sudo podman volume ls                 # list volumes
```

---

## Backup Volumes

```bash
just backup-volumes
```

Exports `hermes-webui-data` and `hermes-searxng-config` to timestamped tar archives in `./backups/`:
```
backups/hermes-webui-data-20260409-120000.tar
backups/hermes-searxng-config-20260409-120000.tar
```

Named volumes contain:
- `hermes-webui-data`: Open WebUI user accounts, chat history, and settings.
- `hermes-searxng-config`: SearXNG `settings.yml` with engine configuration.

These volumes persist across container image updates and VM restarts. They are destroyed by `just teardown`. Back up before any teardown.

---

## Full Rebuild

```bash
just rebuild
```

Runs a complete clean rebuild in one command:
1. `just backup-volumes` — exports current volume data to `./backups/`
2. `just teardown --confirm` — stops and deletes the VM and all volumes
3. `just setup` — creates a fresh VM and provisions everything
4. `just restore-volumes` — imports the most recent backup for each volume

Use `just rebuild` when:
- The VM is in an unrecoverable state
- You need to apply a major infrastructure change (e.g., VM disk size)
- You want a clean OS inside the VM without losing WebUI history

Do not use bare `just teardown` + `just setup` unless you intend to lose all volume data.

---

## Teardown

```bash
just teardown --confirm
```

Stops and permanently deletes `hermes-machine` and all volume data inside it. The `--confirm` flag is required to prevent accidental data loss. Running without it prints a warning and exits.

After teardown, run `just setup` to recreate the VM, or `just rebuild` if you backed up volumes first and want to restore them.

---

## Secrets Management

### Encrypt .env

```bash
just encrypt-env
```

Encrypts `.env` to `.env.age` using your `~/.ssh/id_ed25519.pub` SSH public key. The resulting `.env.age` is safe to commit to a private fork of the repo.

### Decrypt .env

```bash
just decrypt-env
```

Decrypts `.env.age` back to `.env` using `~/.ssh/id_ed25519`. Run this after cloning a private fork that contains `.env.age`.

### Key requirements

- `just encrypt-env` reads `~/.ssh/id_ed25519.pub`. This key must exist.
- `just decrypt-env` reads `~/.ssh/id_ed25519`. The private key must be present on the machine doing the decryption.
- `age` must be installed (`brew install age`, included in the Brewfile).

---

## pf Firewall

### Check status

```bash
just status
```

The status command includes a pf rule check. If the hermes rules are not active, it prints:
```
WARNING: hermes pf rules are NOT loaded — Ollama may be exposed on all interfaces!
  Run: sudo pfctl -f /etc/pf.d/hermes.conf -e
```

### Manually reload rules

```bash
sudo pfctl -f /etc/pf.d/hermes.conf -e
```

### Why rules may be missing

macOS system updates can silently revert pf to defaults, removing any custom rules. A launchd plist (`com.hermes.pf.plist`, deployed by Ansible) reloads `hermes.pf.conf` on every login, but a system update that runs before login may leave a window where the rules are absent.

If you find the rules missing after an update, reload them manually with the command above and then verify:
```bash
sudo pfctl -sr | grep 11434
```

You should see `pass` rules for `lo0`, your ZeroTier interface, and the Podman bridge, followed by a `block` rule.

### What the rules protect

Port 11434 (Ollama) accepts connections only from:
- `127.0.0.1` (localhost)
- Your ZeroTier subnet (`ZT_SUBNET`)
- The Podman VM bridge interface

All other inbound connections to port 11434 are blocked. If the rules are missing, Ollama is reachable from any network interface on your Mac.
