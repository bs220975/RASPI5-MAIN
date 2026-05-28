#!/bin/bash

SRC_REMOTE="gdrive:/pi5_drive"
DEST_LOCAL="/home/pi5/pi5_drive"

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
    # Parallel transfers + Drive-optimised listing
    --transfers 8
    --checkers 16
    --fast-list
    # Limit Drive API rate to avoid throttling (requests/sec + burst allowance)
    --tpslimit 10
    --tpslimit-burst 50
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

# Direction menu
echo ""
echo -e "${CYAN}${BOLD}=== Pi5 Google Drive Copy ===${NC}"
echo ""
echo "  1) Drive → Pi  (download from Google Drive to Pi)"
echo "  2) Pi → Drive  (upload from Pi to Google Drive)"
echo ""
echo -ne "Enter choice [1/2]: "
read option

case "$option" in
    1) dry_run_summary "$SRC_REMOTE" "$DEST_LOCAL" "Drive → Pi" ;;
    2) dry_run_summary "$DEST_LOCAL" "$SRC_REMOTE" "Pi → Drive" ;;
    *) echo -e "${RED}Invalid choice. Exiting.${NC}"; exit 1 ;;
esac
