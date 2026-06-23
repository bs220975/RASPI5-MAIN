#!/bin/bash
# Pull all Git repos found in *_drive/Git_projects on this Pi.

GIT_PROJECTS=$(ls -d "$HOME"/*_drive/Git_projects 2>/dev/null | head -1)

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

if [ -z "$GIT_PROJECTS" ]; then
    echo -e "${RED}No *_drive/Git_projects found under $HOME${NC}"
    exit 1
fi

echo ""
echo -e "${CYAN}${BOLD}=== Git Pull All — ${GIT_PROJECTS} ===${NC}"

ok=0; fail=0

for repo in "$GIT_PROJECTS"/*/; do
    [ -d "$repo/.git" ] || continue
    name=$(basename "$repo")
    echo ""
    echo -e "  ${BOLD}── ${name} ──${NC}"
    echo -ne "    pull  ... "
    out=$(git -C "$repo" pull 2>&1)
    rc=$?
    if [ $rc -eq 0 ]; then
        summary=$(echo "$out" | grep -E "Already up to date|files? changed|Fast-forward" | head -1)
        echo -e "${GREEN}OK${NC}  ${summary:-done}"
        ((ok++))
    else
        echo -e "${RED}FAILED${NC}"
        echo "$out" | sed 's/^/        /' | head -8
        ((fail++))
    fi
done

echo ""
echo -e "${CYAN}${BOLD}──────────────────────────────────────────${NC}"
echo -e "  ${GREEN}${ok} pulled OK${NC}   ${RED}${fail} failed${NC}"
echo -e "${CYAN}${BOLD}──────────────────────────────────────────${NC}"
echo ""
