#!/bin/bash
# =================================================================
# Esvibox NEXUS - Systemd Manager (Smart Binary Detection)
# =================================================================

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: Ejecuta este script como ROOT (#)."
    exit 1
fi

PROJECT_DIR=$(dirname $(dirname $(realpath "$0")))
SERVICE_NAME="nexus"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

# 1. Detectar el dueño de la carpeta
APP_USER=$(stat -c '%U' "$PROJECT_DIR")
APP_GROUP=$(stat -c '%G' "$PROJECT_DIR")

# 2. Localizar el binario 'uv' del usuario
# Le preguntamos al entorno del usuario dónde está su 'uv'
UV_BIN=$(su - "$APP_USER" -c "which uv" 2>/dev/null)

# Si no lo encuentra con 'which', probamos la ruta por defecto de la instalación de uv
if [ -z "$UV_BIN" ]; then
    USER_HOME=$(getent passwd "$APP_USER" | cut -d: -f6)
    if [ -f "$USER_HOME/.cargo/bin/uv" ]; then
        UV_BIN="$USER_HOME/.cargo/bin/uv"
    fi
fi

if [ -z "$UV_BIN" ]; then
    USER_HOME=$(getent passwd "$APP_USER" | cut -d: -f6)
    if [ -f "$USER_HOME/.local/bin/uv" ]; then
        UV_BIN="$USER_HOME/.local/bin/uv"
    fi
fi

# Colores
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

case "$1" in
    install)
        echo -e "${BLUE}Nexus: Configurando servicio para el usuario '$APP_USER'...${NC}"

        if [ -z "$UV_BIN" ]; then
            echo -e "${RED}Error: No se pudo localizar el binario 'uv' del usuario $APP_USER.${NC}"
            echo "Asegúrate de que $APP_USER tenga uv instalado."
            exit 1
        fi

        echo -e "${BLUE}Nexus: Usando binario en $UV_BIN${NC}"

        # Generación del archivo de servicio con rutas absolutas reales
        cat << EOF > "$SERVICE_FILE"
[Unit]
Description=Esvibox Nexus API Service
After=network.target

[Service]
User=$APP_USER
Group=$APP_GROUP
WorkingDirectory=$PROJECT_DIR
# Cargamos el .env directamente
EnvironmentFile=$PROJECT_DIR/.env
# WATCHDOG NATIVO
Restart=always
RestartSec=5
# Usamos la ruta absoluta del uv del usuario para que funcione siempre
# --proxy-headers: Indica a Uvicorn que confíe en las cabeceras X-Forwarded-For
# --forwarded-allow-ips: Lista de IPs en las que confiamos (Localhost y tu HAProxy)
ExecStart=$UV_BIN run uvicorn app.main:app \
    --host 127.0.0.1 \
    --port 8000 \
    --proxy-headers \
    --forwarded-allow-ips='127.0.0.1,172.19.101.60'

[Install]
WantedBy=multi-user.target
EOF

        systemctl daemon-reload
        systemctl enable $SERVICE_NAME
        echo -e "${GREEN}Nexus: Instalación completada con éxito.${NC}"
        ;;

    uninstall)
        echo -e "${RED}Nexus: Eliminando servicio...${NC}"
        systemctl stop $SERVICE_NAME 2>/dev/null
        systemctl disable $SERVICE_NAME 2>/dev/null
        rm -f "$SERVICE_FILE"
        systemctl daemon-reload
        echo -e "${GREEN}Nexus: Limpieza terminada.${NC}"
        ;;

    restart)
        systemctl stop $SERVICE_NAME && echo -e "${BLUE}Nexus: OFF${NC}"
        sleep 3
        systemctl start $SERVICE_NAME && echo -e "${GREEN}Nexus: ON${NC}"
        ;;

    start) systemctl start $SERVICE_NAME && echo -e "${GREEN}Nexus: ON${NC}" ;;
    stop)  systemctl stop $SERVICE_NAME && echo -e "${BLUE}Nexus: OFF${NC}" ;;
    status) systemctl status $SERVICE_NAME ;;
    logs) journalctl -u $SERVICE_NAME -f ;;
    *) echo "Uso: $0 {install|uninstall|start|stop|restart|status|logs}"; exit 1 ;;
esac
