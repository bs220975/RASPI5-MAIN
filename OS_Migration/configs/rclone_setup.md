# rclone Google Drive Setup (post-install)

Do NOT store rclone.conf in git — it contains OAuth tokens.

## Quick Setup After Reimage

```bash
# Install rclone (already done by post_install script)
# Configure Google Drive remote:
rclone config

# Steps in the wizard:
# n) New remote
# name> gdrive
# Storage type: drive (Google Drive)
# client_id: (leave blank)
# client_secret: (leave blank)
# scope: 1 (full access)
# Use auto config: y  (opens browser)
# Configure as shared drive: n
```

## Verify
```bash
rclone lsd gdrive:/
rclone ls gdrive:/pi4_drive/
```

## Sync (using existing sync.sh)
```bash
bash /home/pi/pi4_drive/Git_projects/RASPI4-MAIN/shell_scripts/sync.sh
```

## Restore from Google Drive (first sync after reimage)
```bash
rclone sync gdrive:/pi4_drive /home/pi/pi4_drive --progress
```
