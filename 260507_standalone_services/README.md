# Git Stack Sync — Setup Guide

## Files in this project

```
git-sync.sh          # Shell script — does the actual git push/pull
server.py            # Flask web server — runs on port 8585
static/index.html    # Web UI
git-sync.service     # systemd unit — runs server on boot
```

---

## Step 1 — Install Flask

```bash
pip install flask --break-system-packages
```

---

## Step 2 — Copy files to server

```bash
sudo mkdir -p /opt/git-sync/static

sudo cp server.py        /opt/git-sync/server.py
sudo cp index.html /opt/git-sync/static/index.html
sudo cp git-sync.sh      /usr/local/bin/git-sync.sh
sudo chmod +x            /usr/local/bin/git-sync.sh
```

---

## Step 3 — Test the script manually

```bash
# Test a pull first (safe, no changes)
bash /usr/local/bin/git-sync.sh pull

# Test a push (only if you have changes staged or want to test)
bash /usr/local/bin/git-sync.sh push "test commit"
```

---

## Step 4 — Install and start the systemd service

```bash
sudo cp git-sync.service /etc/systemd/system/git-sync.service

# Reload systemd, enable on boot, start now
sudo systemctl daemon-reload
sudo systemctl enable git-sync
sudo systemctl start git-sync

# Check it's running
sudo systemctl status git-sync
```

---

## Step 5 — Open the UI

Navigate to: **http://your-server-ip:8585**

Or add an NPM proxy pass to give it a nice hostname like `git-sync.yourdomain.com`.

---

## Troubleshooting

**Check service logs:**
```bash
journalctl -u git-sync -f
```

**Git push fails with auth error:**
Make sure your repo uses an SSH remote (not HTTPS), and that the SSH key for
the `austin` user is added to GitHub:
```bash
# Check remote type
cd /mnt/docker/dockge/stacks
git remote -v

# If it shows https://, switch to SSH:
git remote set-url origin git@github.com:YOUR_USERNAME/YOUR_REPO.git

# Test SSH auth
ssh -T git@github.com
```

**Permission denied on /mnt/docker/dockge/stacks:**
The service runs as user `ae`. Make sure that user owns or has write access:
```bash
ls -la /mnt/docker/dockge/
# If needed:
sudo chown -R ae:ae /mnt/docker/dockge/stacks
```

**Port 8585 not reachable from other machines:**
Check UFW:
```bash
sudo ufw allow 8585/tcp
```
