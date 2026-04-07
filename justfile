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
