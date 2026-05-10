# git-sync

A lightweight self-hosted web UI for pushing and pulling a Docker Compose stack repository to and from GitHub. Built for homelabbers managing stacks with [Dockge](https://github.com/louislam/dockge) or similar tools.

Two buttons. Live terminal output. Optional scheduled autosave to a separate branch.

---

## How it works

git-sync runs a small Flask web server inside a Docker container. It exposes a browser UI with **Push** and **Pull** buttons that run git commands against a repo on your host machine. Your git identity and credentials stay on the host and are mounted read-only into the container — no tokens or passwords are stored in the image or container environment.

When autosave is enabled, the container automatically commits and pushes changes to a dedicated `autosave` branch on a user-defined interval, starting 30 seconds after container startup. The last autosave time is displayed in the UI and updates automatically.

---

## Prerequisites

- Docker installed on your host
- A GitHub account
- A folder on your host containing the files you want to version (e.g. your Dockge stacks directory)

---

## Part 1 — Host setup

All steps in this section are run on your **host machine**, not inside a container. This is intentional — keeping git installed and configured on the host ensures credentials are under your control and avoids file ownership conflicts between the container and host filesystem.

---

### Step 1 — Install git

**Ubuntu / Debian:**
```bash
sudo apt update && sudo apt install git -y
```

**Verify:**
```bash
git --version
```

---

### Step 2 — Configure git identity

Git requires a name and email before it will make commits. These are stored in `~/.gitconfig`. Use the email associated with your GitHub account so commits are attributed correctly.

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

**Verify:**
```bash
cat ~/.gitconfig
```

Expected output:
```
[user]
    name = Your Name
    email = you@example.com
```

---

### Step 3 — Configure the git credential store

This tells git to save credentials to `~/.git-credentials` after the first authenticated operation, so it never prompts again.

```bash
git config --global credential.helper store
```

Credentials are saved automatically the first time you push in Step 8. You do not need to manually create the file.

**Default credential file locations:**

| OS | Path |
|---|---|
| Linux | `/home/YOUR_USERNAME/.git-credentials` |
| macOS | `/Users/YOUR_USERNAME/.git-credentials` |

---

### Step 4 — Create a GitHub repository

1. Go to **GitHub → New repository**
2. Name it (e.g. `homelab-stacks`)
3. Set visibility to **Private** — recommended for files containing hostnames and service names
4. **Do not** initialize with a README, .gitignore, or license — you will push existing files
5. Copy the HTTPS clone URL (e.g. `https://github.com/yourusername/homelab-stacks.git`)

---

### Step 5 — Initialize the local repository

Navigate to the folder you want to version. For Dockge users this is your stacks directory:

```bash
cd /path/to/your/stacks
git init
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
```

**Verify the remote is set correctly:**
```bash
git remote -v
```

Expected output:
```
origin  https://github.com/YOUR_USERNAME/YOUR_REPO.git (fetch)
origin  https://github.com/YOUR_USERNAME/YOUR_REPO.git (push)
```

---

### Step 6 — Create a .gitignore

This prevents secrets from being accidentally committed. Create the file in the root of your repo:

```bash
nano /path/to/your/stacks/.gitignore
```

Recommended contents:

```gitignore
# Environment files — never commit secrets
*.env*
!**/.env.example

# Python cache
__pycache__/
*.pyc
*.pyo

# OS noise
.DS_Store
Thumbs.db
```

Save and exit (`Ctrl+X`, `Y`, `Enter` in nano).

---

### Step 7 — Create .env.example files (optional but recommended)

If any of your stacks use environment variables, document the required variable names without values alongside each `compose.yaml`. This is useful for anyone (including future you) setting up the stack from scratch.

Example for a DuckDNS stack:
```bash
nano /path/to/your/stacks/duckdns/.env.example
```

```
DUCKDNS_TOKEN=
DUCKDNS_DOMAINS=
TZ=
```

> **Note for Dockge users:** Dockge stores environment variables in its own internal database, not as `.env` files on disk. You will not find `.env` files in your stacks folder — this is expected. The `.env.example` files are documentation only.

---

### Step 8 — Create a GitHub Personal Access Token (PAT) and make the initial push

GitHub no longer accepts your account password for git operations over HTTPS. A Personal Access Token is used instead. Create it immediately before your first push so it is fresh in your clipboard.

**Create the PAT:**
1. Go to **GitHub → Settings → Developer Settings → Personal Access Tokens → Tokens (classic)**
2. Click **Generate new token (classic)**
3. Give it a descriptive name (e.g. `homelab-git-sync`)
4. Set an expiration — 90 days is a reasonable default
5. Under **Scopes**, check **`repo`** only — no broader permissions are needed
6. Click **Generate token**
7. **Copy the token immediately** — GitHub will not show it again

**Make the initial commit and push:**
```bash
cd /path/to/your/stacks
git add -A
git commit -m "initial commit"
git push -u origin main
```

When prompted:
- **Username:** your GitHub username
- **Password:** your PAT (not your GitHub account password)

Git will save these credentials to `~/.git-credentials` automatically. You will not be prompted again.

**Verify on GitHub** that your files appear in the repository before continuing.

---

### Step 9 — Find your uid and gid

The container must run as your host user so that any files it touches in your repo are owned by you, not root.

```bash
id YOUR_USERNAME
```

Example output:
```
uid=1000(ae) gid=1000(ae) groups=1000(ae)...
```

Note your `uid` and `gid` — you will need them in Part 2.

---

## Part 2 — Deploy git-sync

### Step 10 — Deploy with Dockge

Paste the following into Dockge and edit the values marked `# <-- edit`:

```yaml
services:
  git-sync:
    image: ghcr.io/aigleheart/git-sync:latest
    container_name: git-sync
    restart: unless-stopped
    user: "1000:1000"               # <-- edit: your uid:gid from Step 9

    ports:
      - "8585:8585"                 # change left side if 8585 conflicts

    environment:
      # ── Required ──────────────────────────────────────────────────────────
      - REPO_DISPLAY_PATH=/mnt/docker/dockge/stacks   # <-- edit: your host repo path
      - HOME=/home/YOUR_USERNAME                       # <-- edit: your host home directory

      # ── Optional: branch names (defaults shown) ───────────────────────────
      - MAIN_BRANCH=main
      - AUTOSAVE_BRANCH=autosave

      # ── Optional: autosave (disabled by default) ──────────────────────────
      - AUTOSAVE_ENABLED=false
      - AUTOSAVE_INTERVAL=24h       # supports: 1h 6h 12h 24h 1d 1w 2w etc.

    volumes:
      - /path/to/your/stacks:/repo                                          # <-- edit left side: your host repo path
      - /home/YOUR_USERNAME/.gitconfig:/home/YOUR_USERNAME/.gitconfig:ro    # <-- edit: your host username
      - /home/YOUR_USERNAME/.git-credentials:/home/YOUR_USERNAME/.git-credentials:ro  # <-- edit: your host username
```

Start the stack. The UI will be available at:

```
http://YOUR_SERVER_IP:8585
```

---

### Step 11 — Test the deployment

Test in this order — pull is non-destructive and confirms credentials are working before you attempt a push.

**1. Test Pull first:**
Click **Pull from GitHub** in the UI. You should see timestamped output in the log window ending with `✓ Pull complete.`

**2. Test Push:**
Make a small harmless change (e.g. add a blank line to any file), enter a commit message, and click **Push to GitHub**. Verify the commit appears on GitHub.

**3. Check file ownership:**
After a successful push, verify files are not being created as root:
```bash
ls -la /path/to/your/stacks/.git/
```
The owner should be your host username, not `root`. If you see `root`, check that your `user:` value in the compose matches the output of `id YOUR_USERNAME`.

---

## Autosave

When `AUTOSAVE_ENABLED=true`, git-sync automatically commits and pushes changes to a dedicated branch (default: `autosave`) on the configured interval. The first autosave run happens 30 seconds after container startup — subsequent runs follow the configured interval.

The autosave branch is created automatically on first run if it does not already exist on the remote — no manual setup required.

The last autosave time is shown in the UI and updates automatically. It resets if the container is restarted, which is expected behavior.

**The autosave branch is intentionally separate from `main`.** It accumulates timestamped snapshots and should never be merged back into main. Think of it as a rolling safety net:

```
main      ── "add VPN killswitch to qbittorrent"
              "update Jellyfin port mapping"

autosave  ── "autosave: 2026-05-07 14:00:00"
              "autosave: 2026-05-08 14:00:00"
              "autosave: 2026-05-09 14:00:00"
```

---

## Updating git-sync

When a new version is published, update by pulling the latest image and recreating the container. In Dockge, use the **Pull** and **Recreate** buttons on the git-sync stack.

---

## Troubleshooting

**Push or pull fails with authentication error**

Your `.git-credentials` file may not exist yet if you have not completed Step 8. Run a manual push from the host:
```bash
cd /path/to/your/stacks && git push
```
Enter your GitHub username and PAT when prompted, then restart the git-sync container in Dockge.

**"Cannot cd to /repo" error in the log**

The volume mount path in your compose is incorrect or the directory does not exist on the host. Verify the left side of the `/repo` volume mapping points to your actual stacks directory.

**Files created by the container are owned by root**

The `user:` value in your compose does not match your host user. Run `id YOUR_USERNAME`, update the `user:` line in Dockge, and recreate the container.

**Port 8585 is already in use**

Change the left side of the ports mapping to any free port:
```yaml
ports:
  - "9090:8585"
```

**PAT has expired**

1. Generate a new PAT on GitHub (Step 8)
2. Remove the old credentials file from your host:
   ```bash
   rm ~/.git-credentials
   ```
3. Trigger a new credential save with a manual push:
   ```bash
   cd /path/to/your/stacks && git push
   ```
   Enter your username and new PAT when prompted.
4. Restart the git-sync container in Dockge.

**Autosave push fails with "non-fast-forward" error**

The autosave branch on GitHub has commits your local copy does not have — this can happen if the branch is edited directly on GitHub. From your host:
```bash
cd /path/to/your/stacks
git fetch origin
git checkout autosave
git pull origin autosave
git checkout main
```
Then restart the git-sync container.

---

## Security notes

- Keep your GitHub repository **private** if your compose files contain hostnames, service names, or internal network details
- The `.gitconfig` and `.git-credentials` files are mounted **read-only** — git-sync cannot modify them
- Your PAT should have only the **`repo`** scope
- Rotate your PAT periodically and update using the PAT expiry steps above
- git-sync is designed for **local network use only** — place it behind a reverse proxy with local-only access rules if exposing via a custom domain
