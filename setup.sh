#!/bin/bash
# ═══════════════════════════════════════════════════════════
#  Setup completo del sistema RFID - ITSOEH
#  Ejecutar: bash setup.sh
# ═══════════════════════════════════════════════════════════

set -e
echo "═══════════════════════════════════════════════════════"
echo "  RFID System Setup - ITSOEH"
echo "═══════════════════════════════════════════════════════"

BASE="$HOME/rfid-system"

# ── Estructura de carpetas ──────────────────────────────────
mkdir -p $BASE/shared
mkdir -p $BASE/dashboard/templates
mkdir -p $BASE/dashboard/static
mkdir -p $BASE/crud/templates
mkdir -p $BASE/crud/static/fotos

# ── Entorno virtual ─────────────────────────────────────────
echo "📦 Creando entorno virtual..."
cd $BASE
python3 -m venv venv
source venv/bin/activate

echo "📦 Instalando dependencias Python..."
pip install --upgrade pip -q
pip install flask gunicorn mfrc522 RPi.GPIO -q

# ── Base de datos ───────────────────────────────────────────
echo "🗄️  Inicializando base de datos..."
python3 $BASE/shared/init_db.py

# ── Habilitar SPI ───────────────────────────────────────────
echo "🔧 Habilitando SPI..."
if ! grep -q "dtparam=spi=on" /boot/config.txt 2>/dev/null && \
   ! grep -q "dtparam=spi=on" /boot/firmware/config.txt 2>/dev/null; then
    CONFIG=""
    [ -f /boot/firmware/config.txt ] && CONFIG="/boot/firmware/config.txt"
    [ -f /boot/config.txt ]          && CONFIG="/boot/config.txt"
    [ -n "$CONFIG" ] && echo "dtparam=spi=on" | sudo tee -a $CONFIG > /dev/null
    echo "⚠️  SPI habilitado — reinicia la Pi después del setup"
fi

# ── Servicios systemd ───────────────────────────────────────
VENV="$BASE/venv/bin"
USER=$(whoami)

echo "⚙️  Configurando servicios systemd..."

sudo tee /etc/systemd/system/rfid-reader.service > /dev/null <<EOF
[Unit]
Description=RFID Reader Service
After=network.target rfid-dashboard.service

[Service]
Type=simple
User=$USER
WorkingDirectory=$BASE/shared
ExecStart=$VENV/python3 $BASE/shared/rfid_reader.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/rfid-dashboard.service > /dev/null <<EOF
[Unit]
Description=RFID Dashboard Service
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$BASE/dashboard
ExecStart=$VENV/gunicorn -w 4 -b 0.0.0.0:5000 app_dashboard:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/rfid-crud.service > /dev/null <<EOF
[Unit]
Description=RFID CRUD Service
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$BASE/crud
ExecStart=$VENV/gunicorn -w 2 -b 0.0.0.0:5001 app_crud:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable rfid-dashboard rfid-crud rfid-reader
sudo systemctl restart rfid-dashboard rfid-crud
# rfid-reader solo se inicia si hay hardware
# sudo systemctl start rfid-reader

echo ""
echo "═══════════════════════════════════════════════════════"
echo "✅ Setup completo"
echo ""
echo "  Dashboard: http://$(hostname -I | awk '{print $1}'):5000"
echo "  Admin:     http://$(hostname -I | awk '{print $1}'):5001"
echo ""
echo "  Comandos útiles:"
echo "  sudo systemctl status rfid-dashboard"
echo "  sudo systemctl status rfid-crud"
echo "  sudo journalctl -u rfid-dashboard -f"
echo "═══════════════════════════════════════════════════════"
