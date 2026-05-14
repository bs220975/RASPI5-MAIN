#!/bin/bash

SRC_REMOTE="gdrive:/pi4_drive"
DEST_LOCAL="/home/pi/pi4_drive"

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
    output=$(rclone sync "$from" "$to" --dry-run -v 2>&1)

    # Parse using rclone v1.60+ format
    to_copy=$(echo "$output" | grep -c 'Skipped copy')
    to_delete=$(echo "$output" | grep -c 'Skipped delete')

    # Show files to copy
    if [ "$to_copy" -gt 0 ]; then
        echo -e "${GREEN}Files to copy/update ($to_copy):${NC}"
        echo "$output" | grep 'Skipped copy' | sed 's/.*INFO *: //' | sed 's/: Skipped.*//' | while read -r f; do
            echo -e "  ${GREEN}+${NC} $f"
        done
        echo ""
    fi

    # Show files to delete
    if [ "$to_delete" -gt 0 ]; then
        echo -e "${RED}Files to delete ($to_delete):${NC}"
        echo "$output" | grep 'Skipped delete' | sed 's/.*INFO *: //' | sed 's/: Skipped.*//' | while read -r f; do
            echo -e "  ${RED}-${NC} $f"
        done
        echo ""
    fi

    # Nothing to do
    if [ "$to_copy" -eq 0 ] && [ "$to_delete" -eq 0 ]; then
        echo -e "${GREEN}Everything is already in sync. No changes needed.${NC}"
        echo ""
        return 0
    fi

    echo -e "${BOLD}Summary: ${GREEN}$to_copy to copy/update${NC}  |  ${RED}$to_delete to delete${NC}"
    echo ""
    echo -ne "Proceed with sync? (y/n): "
    read choice

    if [[ "$choice" == "y" || "$choice" == "Y" ]]; then
        echo ""
        echo -e "${CYAN}${BOLD}Syncing $label...${NC}"
        echo "---------------------------------------"
        # -v shows each file transferred; --stats 3s shows periodic totals
        rclone sync "$from" "$to" -v --stats 3s --stats-one-line 2>&1
        echo "---------------------------------------"
        echo -e "${GREEN}${BOLD}Sync complete: $label${NC}"
    else
        echo -e "${YELLOW}Skipped. No changes made.${NC}"
    fi

    echo ""
}

# Direction menu
echo ""
echo -e "${CYAN}${BOLD}=== Pi4 Google Drive Sync ===${NC}"
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
