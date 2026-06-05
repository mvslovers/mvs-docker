FROM debian:trixie-slim

ARG USERNAME=dev
ARG USER_UID=1000
ARG USER_GID=1000

# ── Pinned tool versions (bump deliberately; keeps builds reproducible) ──
# C2ASM370_VERSION is also the image's "core" version used for tagging in CI.
ARG C2ASM370_VERSION=1.2
ARG NEOVIM_VERSION=v0.12.2
ARG LAZYGIT_VERSION=0.62.2
ARG ZOWE_VERSION=8.32.2
ARG TREE_SITTER_VERSION=0.26.9

# ── System packages ──────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential clang clangd gcc make \
    python3 python3-pip python3-venv \
    curl wget jq ca-certificates gnupg \
    git vim zsh sudo locales unzip \
    fzf ripgrep fd-find \
    libc6-i386 gosu \
    && sed -i 's/^# *en_US.UTF-8/en_US.UTF-8/' /etc/locale.gen \
    && locale-gen \
    && ln -sf "$(which fdfind)" /usr/local/bin/fd \
    && rm -rf /var/lib/apt/lists/*

ENV LANG=en_US.UTF-8

# ── GitHub CLI ───────────────────────────────────────────────────
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# ── Docker CLI (no daemon — Docker-outside-Docker via socket) ───
RUN apt-get update && apt-get install -y --no-install-recommends \
    docker-cli \
    && rm -rf /var/lib/apt/lists/*

# ── Node.js 22 LTS ──────────────────────────────────────────────
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# ── Zowe CLI ─────────────────────────────────────────────────────
RUN npm install -g @zowe/cli@${ZOWE_VERSION}

# ── Neovim (pinned stable binary) ───────────────────────────────
RUN curl -fsSL -o /tmp/nvim.tar.gz \
      https://github.com/neovim/neovim/releases/download/${NEOVIM_VERSION}/nvim-linux-x86_64.tar.gz \
    && tar xzf /tmp/nvim.tar.gz -C /opt \
    && ln -s /opt/nvim-linux-x86_64/bin/nvim /usr/local/bin/nvim \
    && rm /tmp/nvim.tar.gz

# ── lazygit (pinned release binary) ─────────────────────────────
RUN curl -fsSL -o /tmp/lazygit.tar.gz \
      "https://github.com/jesseduffield/lazygit/releases/download/v${LAZYGIT_VERSION}/lazygit_${LAZYGIT_VERSION}_linux_x86_64.tar.gz" \
    && tar xzf /tmp/lazygit.tar.gz -C /usr/local/bin lazygit \
    && rm /tmp/lazygit.tar.gz

# ── tree-sitter CLI (for nvim-treesitter) ────────────────────────
RUN npm install -g tree-sitter-cli@${TREE_SITTER_VERSION}

# ── c2asm370 (C → S/370 cross-compiler) ─────────────────────────
ADD https://github.com/mvslovers/c2asm370/releases/download/v${C2ASM370_VERSION}/c2asm370-linux-x86.tar.gz /tmp/c2asm370.tar.gz
RUN tar xzf /tmp/c2asm370.tar.gz -C /usr/local/bin \
    && chmod +x /usr/local/bin/c2asm370 \
    && rm /tmp/c2asm370.tar.gz

# ── User setup ───────────────────────────────────────────────────
RUN groupadd --gid ${USER_GID} ${USERNAME} \
    && useradd -s /bin/zsh --uid ${USER_UID} --gid ${USER_GID} -m ${USERNAME} \
    && echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/${USERNAME} \
    && chmod 0440 /etc/sudoers.d/${USERNAME}

# ── Entrypoint (creates docker group + adds dev user at runtime) ──
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 755 /usr/local/bin/entrypoint.sh
ENTRYPOINT ["entrypoint.sh"]

USER ${USERNAME}
WORKDIR /home/${USERNAME}

# ── oh-my-zsh + plugins ─────────────────────────────────────────
RUN sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended \
    && git clone --depth=1 https://github.com/zsh-users/zsh-autosuggestions \
       ~/.oh-my-zsh/custom/plugins/zsh-autosuggestions \
    && git clone --depth=1 https://github.com/zsh-users/zsh-syntax-highlighting \
       ~/.oh-my-zsh/custom/plugins/zsh-syntax-highlighting \
    && sed -i 's/^plugins=.*/plugins=(git docker zsh-autosuggestions zsh-syntax-highlighting)/' ~/.zshrc

# ── LazyVim starter config ──────────────────────────────────────
RUN git clone --depth=1 https://github.com/LazyVim/starter ~/.config/nvim \
    && rm -rf ~/.config/nvim/.git

# ── Default workspace ───────────────────────────────────────────
RUN mkdir -p /home/${USERNAME}/workspace
WORKDIR /home/${USERNAME}/workspace

# ── Switch to root for entrypoint (drops to dev via gosu) ────────
USER root

CMD ["zsh"]
