#!/bin/bash

SRC_REMOTE="gdrive:/pi5_drive"
DEST_LOCAL="/home/pi5/pi5_drive"
GIT_PROJECTS="/home/pi5/pi5_drive/Git_projects"
BACKUP_REMOTE="gdrive:/pi5_drive/Git_projects_backups"
KEEP_BACKUPS=5   # number of dated zips to keep on Drive

# Exclude git internals, build artifacts, caches at any directory depth.
# Use --filter "- dir/" so rclone skips the directory entirely (faster than --exclude).
EXCLUDES=(
    --filter "- .git/"
    --filter "- .pio/"
    --filter "- node_modules/"
    --filter "- __pycache__/"
    --filter "- build/"
    --filter "- .firebase/"
    --filter "- .vscode/"
    --exclude "*.pyc"
    # Single transfer + slow pacer avoids Google Drive 429 back-off explosions.
    # With 1000+ small files each needing ~3 API calls, bursting always triggers
    # rate limits; a 500ms floor keeps us under the per-user quota ceiling.
    --transfers 1
    --checkers 4
    --fast-list
    --tpslimit 2
    --tpslimit-burst 2
    --drive-pacer-min-sleep 500ms
    --drive-pacer-burst 2
)

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

function dry_run_summary() {
    local from="$1"
    local to="$2"
    local label="$3"

    echo ""
    echo -e "${CYAN}${BOLD}==== Dry Run: $label ====${NC}"
    echo -e "  From : ${YELLOW}$from${NC}"
    echo -e "  To   : ${YELLOW}$to${NC}"
    echo ""

    # Capture both stdout and stderr — rclone logs to stderr
    output=$(rclone copy "$from" "$to" "${EXCLUDES[@]}" --dry-run -v 2>&1)

    to_copy=$(echo "$output" | grep -c 'Skipped copy')

    # Show files to copy
    if [ "$to_copy" -gt 0 ]; then
        echo -e "${GREEN}Files to copy/update ($to_copy):${NC}"
        echo "$output" | grep 'Skipped copy' | sed 's/.*INFO *: //' | sed 's/: Skipped.*//' | while read -r f; do
            echo -e "  ${GREEN}+${NC} $f"
        done
        echo ""
    fi

    # Nothing to do
    if [ "$to_copy" -eq 0 ]; then
        echo -e "${GREEN}Everything is already up to date. No files to copy.${NC}"
        echo ""
        return 0
    fi

    echo -e "${BOLD}Summary: ${GREEN}$to_copy file(s) to copy/update${NC}"
    echo ""
    echo -ne "Proceed with copy? (y/n): "
    read choice

    if [[ "$choice" == "y" || "$choice" == "Y" ]]; then
        echo ""
        echo -e "${CYAN}${BOLD}Copying $label...${NC}"
        echo "---------------------------------------"
        rclone copy "$from" "$to" "${EXCLUDES[@]}" -v --stats 3s --stats-one-line 2>&1
        echo "---------------------------------------"
        echo -e "${GREEN}${BOLD}Copy complete: $label${NC}"
    else
        echo -e "${YELLOW}Skipped. No changes made.${NC}"
    fi

    echo ""
}

function zip_and_upload() {
    local timestamp
    timestamp=$(date +%Y%m%d_%H%M%S)
    local zip_name="Git_projects_${timestamp}.zip"
    local zip_path="/tmp/${zip_name}"

    echo ""
    echo -e "${CYAN}${BOLD}==== Zip & Upload: Git_projects → Drive ====${NC}"
    echo -e "  Source  : ${YELLOW}${GIT_PROJECTS}${NC}"
    echo -e "  Archive : ${YELLOW}${zip_path}${NC}"
    echo -e "  Remote  : ${YELLOW}${BACKUP_REMOTE}/${zip_name}${NC}"
    echo ""

    # Show what will be zipped (uncompressed size, excluding junk dirs)
    raw_size=$(du -sh --exclude=".git" --exclude=".pio" --exclude="node_modules" \
        --exclude="__pycache__" --exclude="build" "$GIT_PROJECTS" 2>/dev/null | cut -f1)
    echo -e "  Uncompressed : ${YELLOW}${raw_size}${NC} (source code compresses ~75%)"
    echo ""
    echo -ne "Proceed? (y/n): "
    read choice
    [[ "$choice" != "y" && "$choice" != "Y" ]] && { echo -e "${YELLOW}Skipped.${NC}"; return 0; }

    # Create zip — exclude build artefacts
    echo ""
    echo -e "${CYAN}${BOLD}Compressing...${NC}"
    zip -r "$zip_path" "$GIT_PROJECTS" \
        -x "*/.git/*" \
        -x "*/.pio/*" \
        -x "*/node_modules/*" \
        -x "*/__pycache__/*" \
        -x "*/build/*" \
        -x "*/.firebase/*" \
        -x "*/.vscode/*" \
        -x "*.pyc" \
        -q
    zip_size=$(du -sh "$zip_path" | cut -f1)
    echo -e "  Compressed size: ${GREEN}${zip_size}${NC}"

    # Upload — single file → no per-file API overhead, no rate limiting
    echo ""
    echo -e "${CYAN}${BOLD}Uploading to Drive...${NC}"
    echo "---------------------------------------"
    rclone copy "$zip_path" "$BACKUP_REMOTE" --progress 2>&1
    echo "---------------------------------------"

    # Remove local temp zip
    rm -f "$zip_path"
    echo -e "${GREEN}${BOLD}Upload complete: ${zip_name}${NC}"

    # Prune old backups on Drive — keep only the newest KEEP_BACKUPS zips
    echo ""
    echo -e "${CYAN}Pruning old backups (keeping last ${KEEP_BACKUPS})...${NC}"
    mapfile -t old_backups < <(
        rclone lsf "$BACKUP_REMOTE" --files-only 2>/dev/null \
        | grep "^Git_projects_" | sort -r | tail -n +$((KEEP_BACKUPS + 1))
    )
    if [ "${#old_backups[@]}" -gt 0 ]; then
        for f in "${old_backups[@]}"; do
            rclone deletefile "${BACKUP_REMOTE}/${f}" 2>/dev/null
            echo -e "  ${RED}-${NC} Deleted old backup: $f"
        done
    else
        echo -e "  ${GREEN}No old backups to remove.${NC}"
    fi

    echo ""
}

function upload_specific() {
    echo ""
    echo -e "${CYAN}${BOLD}==== Upload Specific File/Folder → Drive ====${NC}"
    echo ""
    echo -e "  Enter path relative to ${YELLOW}${DEST_LOCAL}${NC} or an absolute path."
    echo -e "  Examples: ${YELLOW}Git_projects/RASPI5-MAIN${NC}"
    echo -e "            ${YELLOW}Git_projects/RASPI5-MAIN/main.py${NC}"
    echo -e "            ${YELLOW}/home/pi5/pi5_drive/Git_projects/ESP32-CAM${NC}"
    echo ""

    # List top-level contents of pi5_drive as a hint
    echo -e "  Contents of ${YELLOW}${DEST_LOCAL}${NC}:"
    ls "$DEST_LOCAL" | sed 's/^/    /'
    echo ""
    echo -ne "Path: "
    read user_path

    # Resolve to absolute path
    if [[ "$user_path" == /* ]]; then
        local_path="$user_path"
    else
        local_path="${DEST_LOCAL}/${user_path}"
    fi

    # Validate
    if [ ! -e "$local_path" ]; then
        echo -e "${RED}Error: Not found: ${local_path}${NC}"
        return 1
    fi

    # Compute matching remote path (strip DEST_LOCAL prefix, prepend SRC_REMOTE)
    rel_path="${local_path#${DEST_LOCAL}/}"

    echo ""
    if [ -f "$local_path" ]; then
        # ── Single file ──────────────────────────────────────────────
        remote_dir="${SRC_REMOTE}/$(dirname "$rel_path")"
        file_size=$(du -sh "$local_path" | cut -f1)
        echo -e "  Type   : ${YELLOW}file${NC}"
        echo -e "  Local  : ${YELLOW}${local_path}${NC}"
        echo -e "  Remote : ${YELLOW}${remote_dir}/$(basename "$local_path")${NC}"
        echo -e "  Size   : ${YELLOW}${file_size}${NC}"
        echo ""
        echo -ne "Proceed? (y/n): "
        read choice
        [[ "$choice" != "y" && "$choice" != "Y" ]] && { echo -e "${YELLOW}Skipped.${NC}"; return 0; }
        echo ""
        echo -e "${CYAN}${BOLD}Uploading...${NC}"
        echo "---------------------------------------"
        rclone copy "$local_path" "$remote_dir" --progress 2>&1
        echo "---------------------------------------"
        echo -e "${GREEN}${BOLD}Upload complete.${NC}"
    else
        # ── Directory ────────────────────────────────────────────────
        remote_path="${SRC_REMOTE}/${rel_path}"
        dir_size=$(du -sh "$local_path" 2>/dev/null | cut -f1)
        file_count=$(find "$local_path" -type f \
            ! -path "*/.git/*" ! -path "*/.pio/*" ! -path "*/node_modules/*" \
            ! -path "*/__pycache__/*" ! -path "*/build/*" ! -name "*.pyc" \
            | wc -l)
        echo -e "  Type       : ${YELLOW}directory${NC}"
        echo -e "  Local      : ${YELLOW}${local_path}${NC}"
        echo -e "  Remote     : ${YELLOW}${remote_path}${NC}"
        echo -e "  Size       : ${YELLOW}${dir_size}${NC}"
        echo -e "  File count : ${YELLOW}${file_count}${NC} (excluding build artefacts)"
        echo ""
        if [ "$file_count" -gt 50 ]; then
            echo -e "  ${YELLOW}Tip: >50 files may hit Drive rate limits."
            echo -e "  Consider option 3 (zip) for large folders.${NC}"
            echo ""
        fi
        echo -ne "Proceed? (y/n): "
        read choice
        [[ "$choice" != "y" && "$choice" != "Y" ]] && { echo -e "${YELLOW}Skipped.${NC}"; return 0; }
        echo ""
        echo -e "${CYAN}${BOLD}Uploading...${NC}"
        echo "---------------------------------------"
        rclone copy "$local_path" "$remote_path" "${EXCLUDES[@]}" \
            -v --stats 3s --stats-one-line 2>&1
        echo "---------------------------------------"
        echo -e "${GREEN}${BOLD}Upload complete.${NC}"
    fi

    echo ""
}

# Direction menu
echo ""
echo -e "${CYAN}${BOLD}=== Pi5 Google Drive Copy ===${NC}"
echo ""
echo "  1) Drive → Pi       (download from Google Drive to Pi)"
echo "  2) Pi → Drive       (upload from Pi to Google Drive, file-by-file)"
echo "  3) Zip → Drive      (zip Git_projects, upload as single archive — fast)"
echo "  4) Upload specific  (choose a file or folder to upload)"
echo ""
echo -ne "Enter choice [1/2/3/4]: "
read option

case "$option" in
    1) dry_run_summary "$SRC_REMOTE" "$DEST_LOCAL" "Drive → Pi" ;;
    2) dry_run_summary "$DEST_LOCAL" "$SRC_REMOTE" "Pi → Drive" ;;
    3) zip_and_upload ;;
    4) upload_specific ;;
    *) echo -e "${RED}Invalid choice. Exiting.${NC}"; exit 1 ;;
esac
