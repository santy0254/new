#!/usr/bin/env bash
# Instalador de PacketProof para CachyOS / Arch Linux.
# Instala dependencias, copia la config y registra un servicio systemd de usuario.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$HOME/packetproof"

echo "==> Instalando dependencias (Python + matplotlib)"
if command -v pacman >/dev/null 2>&1; then
  sudo pacman -S --needed --noconfirm python python-matplotlib iputils
fi

echo "==> Copiando archivos a $DEST"
mkdir -p "$DEST"
cp -r "$REPO_DIR/packetproof" "$DEST/"
[ -f "$DEST/config.toml" ] || cp "$REPO_DIR/config.example.toml" "$DEST/config.toml"

echo "==> Probando objetivos"
( cd "$DEST" && python -m packetproof -c config.toml test ) || true

echo "==> Instalando servicio systemd de usuario"
mkdir -p "$HOME/.config/systemd/user"
sed "s|%h|$HOME|g; s|%i|$USER|g" "$REPO_DIR/scripts/packetproof.service" \
  > "$HOME/.config/systemd/user/packetproof.service"

systemctl --user daemon-reload
systemctl --user enable --now packetproof.service
# Para que corra aunque no haya sesión iniciada:
loginctl enable-linger "$USER" 2>/dev/null || true

echo
echo "Listo. PacketProof está corriendo en segundo plano."
echo "  Estado:  systemctl --user status packetproof"
echo "  Logs:    journalctl --user -u packetproof -f"
echo "  Reporte: $DEST/packetproof-data/report.html"
