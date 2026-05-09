#!/bin/bash

REPO_DIR="/mnt/docker/dockge/stacks"
LOGFILE="/var/log/git-sync.log"
ACTION="$1"
COMMIT_MSG="$2"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

cd "$REPO_DIR" || { log "ERROR: Cannot cd to $REPO_DIR"; exit 1; }

if [ "$ACTION" = "push" ]; then
    log "Staging all changes..."
    git add -A

    STATUS=$(git status --porcelain)
    if [ -z "$STATUS" ]; then
        log "Nothing to commit — working tree clean."
        exit 0
    fi

    log "Changes staged:"
    git status --short | while read line; do log "  $line"; done

    log "Committing: \"$COMMIT_MSG\""
    git commit -m "$COMMIT_MSG" --

    log "Pushing to origin/main..."
    git push origin main 2>&1 | while read line; do log "$line"; done

    if [ "${PIPESTATUS[0]}" -eq 0 ]; then
        log "✓ Push complete."
    else
        log "✗ Push failed."
        exit 1
    fi

elif [ "$ACTION" = "pull" ]; then
    log "Pulling from origin/main..."
    git pull origin main 2>&1 | while read line; do log "$line"; done

    if [ "${PIPESTATUS[0]}" -eq 0 ]; then
        log "✓ Pull complete."
    else
        log "✗ Pull failed."
        exit 1
    fi

else
    log "ERROR: Unknown action '$ACTION'. Use 'push' or 'pull'."
    exit 1
fi
