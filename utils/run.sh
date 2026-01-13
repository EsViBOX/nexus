#!/bin/bash
# =================================================================
# Esvibox NEXUS - Dev Environment Launcher
# =================================================================

# Colores para legibilidad
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}Nexus: Preparing environment...${NC}"

# 1. Asegurar que estamos en la raíz del proyecto
PROJECT_ROOT=$(dirname $(dirname $(realpath $0)))
cd "$PROJECT_ROOT"

# 2. Verificar existencia de archivos clave
if [ ! -f ".vault_pass" ]; then
    echo -e "${RED}Error: .vault_pass not found in root.${NC}"
    exit 1
fi

# 3. Inicializar DB si no existe
if [ ! -f "data/registrator.db" ]; then
    echo -e "${BLUE}Nexus: Database not found. Initializing...${NC}"
    uv run init_db.py
fi

# 4. Matar procesos zombies en el puerto 8000
PORT=8000
EXISTING_PID=$(lsof -t -i:$PORT)
if [ ! -z "$EXISTING_PID" ]; then
    echo -e "${BLUE}Nexus: Cleaning port $PORT (PID $EXISTING_PID)...${NC}"
    kill -9 $EXISTING_PID 2>/dev/null
fi

# 5. Lanzar la API en segundo plano o directamente
# Usamos uvicorn directamente para tener control total del reload
echo -e "${GREEN}Nexus: Starting API Server on http://0.0.0.0:$PORT${NC}"
echo -e "${BLUE}Nexus: Logs will appear below...${NC}"

# Ejecutamos con uv y uvicorn
# --host 0.0.0.0 para permitir conexiones desde la VM
uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT --reload
