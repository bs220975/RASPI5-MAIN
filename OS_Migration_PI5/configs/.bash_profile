# Source .bashrc for interactive login shells (loads aliases, functions, PATH).
# Without this, .bashrc is skipped when bash finds .bash_profile on login.
if [ -f "$HOME/.bashrc" ]; then
    . "$HOME/.bashrc"
fi

export PATH=~/.npm-global/bin:$PATH
