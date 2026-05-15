#!/bin/bash

SOURCE="/home/pi5/pi5_drive"
DEST_ROOT="/home/pi5/Non-Sync_backup_folder"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

DATE=$(date +"%Y-%m-%d")
TIME=$(date +"%H-%M")
BACKUP_PATH="$DEST_ROOT/backup_${DATE}_${TIME}"

echo ""
echo -e "${CYAN}${BOLD}=== Pi5 Local Backup ===${NC}"
echo ""

# Check source exists
if [ ! -d "$SOURCE" ]; then
    echo -e "${RED}ERROR: Source folder not found: $SOURCE${NC}"
    exit 1
fi

# Show pre-backup info
SOURCE_SIZE=$(du -sh "$SOURCE" 2>/dev/null | cut -f1)
echo -e "  Source      : ${YELLOW}$SOURCE${NC} (${SOURCE_SIZE})"
echo -e "  Destination : ${YELLOW}$BACKUP_PATH${NC}"
echo ""

# Show existing backups
EXISTING=$(ls "$DEST_ROOT" 2>/dev/null | grep "^backup_")
if [ -n "$EXISTING" ]; then
    echo -e "${CYAN}Existing backups:${NC}"
    echo "$EXISTING" | while read -r b; do
        SIZE=$(du -sh "$DEST_ROOT/$b" 2>/dev/null | cut -f1)
        echo "  $b  ($SIZE)"
    done
    echo ""
fi

# Confirm before starting
echo -ne "Start backup? (y/n): "
read choice
if [[ "$choice" != "y" && "$choice" != "Y" ]]; then
    echo -e "${YELLOW}Backup cancelled.${NC}"
    exit 0
fi

echo ""
echo -e "${CYAN}${BOLD}Backing up...${NC}"
echo "---------------------------------------"

mkdir -p "$BACKUP_PATH"

# rsync: archive mode + show each file + overall progress + human readable sizes
rsync -ah --info=progress2 --stats "$SOURCE/" "$BACKUP_PATH/"
EXIT_CODE=$?

echo "---------------------------------------"

if [ $EXIT_CODE -eq 0 ]; then
    BACKUP_SIZE=$(du -sh "$BACKUP_PATH" 2>/dev/null | cut -f1)
    echo ""
    echo -e "${GREEN}${BOLD}Backup complete!${NC}"
    echo -e "  Saved to : ${YELLOW}$BACKUP_PATH${NC}"
    echo -e "  Size     : ${BACKUP_SIZE}"
else
    echo ""
    echo -e "${RED}${BOLD}Backup failed! (rsync exit code: $EXIT_CODE)${NC}"
    echo -e "${RED}Partial backup may exist at: $BACKUP_PATH${NC}"
    exit $EXIT_CODE
fi

echo ""
