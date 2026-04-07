# Hermes GitHub CI/CD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Set up GitHub Actions to build and push `hermes-proxy` and `hermes-discord` ARM64 container images to ghcr.io on every push to `main`, publish versioned releases on tags, and configure Renovate to auto-update dependency digests.

**Architecture:** Two workflows: `build-images.yml` (push to main → build both images, push `:latest` + `:sha-{commit}`) and `release.yml` (tag `v*.*.*` → build, push versioned tag, create GitHub Release). Renovate tracks container image digests in quadlet files and Python packages in requirements.txt files.

**Tech Stack:** GitHub Actions, ghcr.io (GitHub Container Registry), Docker Buildx (ARM64 cross-build), Renovate

---

## File Map

```
hermes-vm/
├── .github/
│   └── workflows/
│       ├── build-images.yml   # push to main → build + push :latest + :sha-{commit}
│       └── release.yml        # tag v*.*.* → build + push versioned tag + GitHub Release
└── renovate.json               # Renovate config
```

---

### Task 1: build-images workflow

**Files:**
- Create: `.github/workflows/build-images.yml`

- [ ] **Step 1: Create `.github/workflows/build-images.yml`**

```yaml
name: Build and push container images

on:
  push:
    branches:
      - main
    paths:
      # Only rebuild when source files or build config actually change
      - "vm/proxy/**"
      - "vm/discord-bot/**"
      - ".github/workflows/build-images.yml"
  # Allow manual triggering from the Actions UI (useful when non-source changes need a rebuild)
  workflow_dispatch:

env:
  REGISTRY: ghcr.io
  OWNER: ${{ github.repository_owner }}

jobs:
  build-proxy:
    name: Build hermes-proxy
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up QEMU (for ARM64 cross-build)
        uses: docker/setup-qemu-action@v3
        with:
          platforms: arm64

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to ghcr.io
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Extract metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.OWNER }}/hermes-proxy
          tags: |
            type=raw,value=latest,enable=${{ github.ref == 'refs/heads/main' }}
            type=sha,prefix=sha-,format=short

      - name: Build and push hermes-proxy
        uses: docker/build-push-action@v6
        with:
          context: vm/proxy
          file: vm/proxy/Dockerfile
          platforms: linux/arm64
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

  build-discord:
    name: Build hermes-discord
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up QEMU (for ARM64 cross-build)
        uses: docker/setup-qemu-action@v3
        with:
          platforms: arm64

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to ghcr.io
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Extract metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.OWNER }}/hermes-discord
          tags: |
            type=raw,value=latest,enable=${{ github.ref == 'refs/heads/main' }}
            type=sha,prefix=sha-,format=short

      - name: Build and push hermes-discord
        uses: docker/build-push-action@v6
        with:
          context: vm/discord-bot
          file: vm/discord-bot/Dockerfile
          platforms: linux/arm64
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

- [ ] **Step 2: Validate the YAML is parseable**

```bash
cd ~/Projects/hermes-vm
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/build-images.yml'))"
echo "OK"
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
cd ~/Projects/hermes-vm
git add .github/workflows/build-images.yml
git commit -m "ci: add build-images workflow for hermes-proxy and hermes-discord"
```

---

### Task 2: release workflow

**Files:**
- Create: `.github/workflows/release.yml`

- [ ] **Step 1: Create `.github/workflows/release.yml`**

```yaml
name: Release

on:
  push:
    tags:
      - "v*.*.*"
  workflow_dispatch:
    inputs:
      tag:
        description: "Tag to release (e.g. v1.0.0)"
        required: true

env:
  REGISTRY: ghcr.io
  OWNER: ${{ github.repository_owner }}

jobs:
  release-images:
    name: Build and push release images
    runs-on: ubuntu-latest
    permissions:
      contents: write    # needed to create GitHub Release
      packages: write

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up QEMU
        uses: docker/setup-qemu-action@v3
        with:
          platforms: arm64

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to ghcr.io
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Extract proxy metadata
        id: proxy-meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.OWNER }}/hermes-proxy
          tags: |
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}
            type=raw,value=latest

      - name: Build and push hermes-proxy release
        uses: docker/build-push-action@v6
        with:
          context: vm/proxy
          file: vm/proxy/Dockerfile
          platforms: linux/arm64
          push: true
          tags: ${{ steps.proxy-meta.outputs.tags }}
          labels: ${{ steps.proxy-meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

      - name: Extract discord metadata
        id: discord-meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.OWNER }}/hermes-discord
          tags: |
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}
            type=raw,value=latest

      - name: Build and push hermes-discord release
        uses: docker/build-push-action@v6
        with:
          context: vm/discord-bot
          file: vm/discord-bot/Dockerfile
          platforms: linux/arm64
          push: true
          tags: ${{ steps.discord-meta.outputs.tags }}
          labels: ${{ steps.discord-meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

      - name: Create GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          generate_release_notes: true
          body: |
            ## Container images

            Pull the released images:
            ```bash
            podman pull ghcr.io/${{ env.OWNER }}/hermes-proxy:${{ github.ref_name }}
            podman pull ghcr.io/${{ env.OWNER }}/hermes-discord:${{ github.ref_name }}
            ```

            Or use `:latest` for the most recent release.
```

- [ ] **Step 2: Validate the YAML**

```bash
cd ~/Projects/hermes-vm
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))"
echo "OK"
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
cd ~/Projects/hermes-vm
git add .github/workflows/release.yml
git commit -m "ci: add release workflow with versioned image tags and GitHub Release"
```

---

### Task 3: Renovate configuration

**Files:**
- Create: `renovate.json`

- [ ] **Step 1: Create `renovate.json`**

```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": [
    "config:recommended"
  ],
  "timezone": "America/New_York",
  "schedule": ["before 6am on monday"],
  "prCreation": "immediate",
  "labels": ["dependencies"],
  "pinDigests": true,
  "packageRules": [
    {
      "description": "Automerge patch-level Python dependency updates",
      "matchManagers": ["pip_requirements"],
      "matchUpdateTypes": ["patch"],
      "automerge": true,
      "automergeType": "pr"
    },
    {
      "description": "Group all container digest updates into a single weekly PR",
      "matchManagers": ["regex"],
      "matchDepTypes": ["container"],
      "groupName": "container digests",
      "schedule": ["before 6am on monday"]
    },
    {
      "description": "Group GitHub Actions updates weekly",
      "matchManagers": ["github-actions"],
      "groupName": "github actions",
      "automerge": false
    }
  ],
  "pip_requirements": {
    "fileMatch": ["vm/proxy/requirements\\.txt$", "vm/discord-bot/requirements\\.txt$"]
  },
  "regexManagers": [
    {
      "description": "Track container image digests in quadlet files. Renovate will open a 'pin digests' PR on first run to add @sha256:... to all Image= lines. Subsequent PRs update those digests when upstream images change.",
      "fileMatch": ["vm/quadlets/.*\\.container$"],
      "matchStrings": [
        "Image=(?<depName>[^@:\\n]+):(?<currentValue>[^@\\n]+)@(?<currentDigest>sha256:[a-f0-9]+)",
        "Image=(?<depName>[^@:\\n]+):(?<currentValue>[^@\\n]+)"
      ],
      "datasourceTemplate": "docker",
      "versioningTemplate": "docker"
    }
  ]
}
```

- [ ] **Step 2: Verify JSON is valid**

```bash
cd ~/Projects/hermes-vm
python3 -c "import json; json.load(open('renovate.json'))"
echo "OK"
```

Expected: `OK`.

- [ ] **Step 3: Commit and push**

```bash
cd ~/Projects/hermes-vm
git add renovate.json
git commit -m "ci: add Renovate config for automated dependency updates"
git push origin main
```

---

### Task 4: Verify CI triggered

- [ ] **Step 1: Check that the push to main triggered the build workflow**

```bash
cd ~/Projects/hermes-vm
gh run list --workflow=build-images.yml --limit=3
```

Expected: A run appears with status `in_progress` or `completed`.

- [ ] **Step 2: Watch the workflow run**

```bash
cd ~/Projects/hermes-vm
gh run watch
```

Expected: Both `Build hermes-proxy` and `Build hermes-discord` jobs complete successfully.

Note: The first run will fail to push `hermes-discord` if the Discord bot Dockerfile doesn't exist yet (it's built in Plan 2). This is expected — the workflow has `paths:` filtering, so once Plan 2 is merged, the next push will pick it up. If Plan 2 is already done, both jobs should pass.

- [ ] **Step 3: Verify images are in ghcr.io**

```bash
gh api /user/packages?package_type=container | python3 -c "
import json, sys
pkgs = json.load(sys.stdin)
for p in pkgs:
    print(p['name'])
"
```

Expected: `hermes-proxy` and `hermes-discord` appear in the list.

- [ ] **Step 4: Enable Renovate on the repo**

Go to the Renovate GitHub App page and install it on the `hermes-vm` repo, or self-host Renovate.

Quick option — add Renovate Bot via GitHub Marketplace:
```bash
gh repo view Gavin-Holliday/hermes-vm --web
# Navigate to Settings → Integrations → Renovate App → Install
```

Once installed, Renovate will open an onboarding PR. Merge it to activate.
