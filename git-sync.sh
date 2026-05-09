#!/bin/bash

# -------------------------------------------------------
# git-sync.sh
# Actions: push <message> | pull | autosave
# -------------------------------------------------------

REPO_DIR="${REPO_PATH}"
MAIN_BRANCH="${MAIN_BRANCH:-main}"
AUTOSAVE_BRANCH="${AUTOSAVE_BRANCH:-autosave}"
ACTION="$1"
COMMIT_MSG="$2"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# -------------------------------------------------------
# Validate environment
# -------------------------------------------------------
if [ -z "$REPO_DIR" ]; then
    log "ERROR: REPO_PATH environment variable is not set."
    exit 1
fi

cd "$REPO_DIR" || { log "ERROR: Cannot cd to $REPO_DIR — check your volume mount."; exit 1; }

# -------------------------------------------------------
# Ensure autosave branch exists (local + remote)
# -------------------------------------------------------
ensure_autosave_branch() {
    if ! git ls-remote --heads origin "$AUTOSAVE_BRANCH" | grep -q "$AUTOSAVE_BRANCH"; then
        log "Autosave branch '$AUTOSAVE_BRANCH' not found on remote — creating..."
        git checkout -b "$AUTOSAVE_BRANCH" 2>&1
        timeout 60 git push -u origin "$AUTOSAVE_BRANCH" 2>&1
        EXIT_CODE=$?
        git checkout "$MAIN_BRANCH" 2>&1
        if [ $EXIT_CODE -ne 0 ]; then
            log "✗ Failed to create autosave branch on remote."
            exit 1
        fi
        log "✓ Autosave branch created."
    fi
}

# -------------------------------------------------------
# PUSH — manual push to main branch
# -------------------------------------------------------
if [ "$ACTION" = "push" ]; then
    log "Staging all changes..."
    git add -A

    STATUS=$(git status --porcelain)
    if [ -z "$STATUS" ]; then
        log "Nothing to commit — working tree clean."
        exit 0
    fi

    log "Changes staged:"
    git status --short | while IFS= read -r line; do log "  $line"; done

    log "Committing: \"$COMMIT_MSG\""
    git commit -m "${COMMIT_MSG}" --
    EXIT_CODE=$?
    if [ $EXIT_CODE -ne 0 ]; then
        log "✗ Commit failed."
        exit 1
    fi

    log "Pushing to origin/$MAIN_BRANCH..."
    timeout 60 git push origin "$MAIN_BRANCH" 2>&1
    EXIT_CODE=$?
    if [ $EXIT_CODE -eq 0 ]; then
        log "✓ Push complete."
    elif [ $EXIT_CODE -eq 124 ]; then
        log "✗ Push timed out after 60 seconds."
        exit 1
    else
        log "✗ Push failed. If the remote has changes you don't have locally, run a Pull first."
        exit 1
    fi

# -------------------------------------------------------
# PULL — pull from main branch
# -------------------------------------------------------
elif [ "$ACTION" = "pull" ]; then
    log "Pulling from origin/$MAIN_BRANCH..."
    timeout 60 git pull origin "$MAIN_BRANCH" 2>&1
    EXIT_CODE=$?
    if [ $EXIT_CODE -eq 0 ]; then
        log "✓ Pull complete."
    elif [ $EXIT_CODE -eq 124 ]; then
        log "✗ Pull timed out after 60 seconds."
        exit 1
    else
        log "✗ Pull failed."
        exit 1
    fi

# -------------------------------------------------------
# AUTOSAVE — commit and push to autosave branch
# -------------------------------------------------------
elif [ "$ACTION" = "autosave" ]; then
    ensure_autosave_branch

    log "Checking for changes..."
    git add -A
    STATUS=$(git status --porcelain)

    if [ -z "$STATUS" ]; then
        log "Nothing to commit — skipping autosave."
        exit 0
    fi

    log "Changes detected:"
    git status --short | while IFS= read -r line; do log "  $line"; done

    CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)

    git stash 2>&1
    git checkout "$AUTOSAVE_BRANCH" 2>&1
    git stash pop 2>&1
    git add -A

    TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
    git commit -m "autosave: ${TIMESTAMP}" --
    EXIT_CODE=$?
    if [ $EXIT_CODE -ne 0 ]; then
        git checkout "$CURRENT_BRANCH" 2>&1
        log "✗ Autosave commit failed."
        exit 1
    fi

    timeout 60 git push origin "$AUTOSAVE_BRANCH" 2>&1
    EXIT_CODE=$?
    git checkout "$CURRENT_BRANCH" 2>&1

    if [ $EXIT_CODE -eq 0 ]; then
        log "✓ Autosave complete."
    elif [ $EXIT_CODE -eq 124 ]; then
        log "✗ Autosave push timed out after 60 seconds."
        exit 1
    else
        log "✗ Autosave push failed."
        exit 1
    fi

else
    log "ERROR: Unknown action '$ACTION'. Use 'push', 'pull', or 'autosave'."
    exit 1
fi
