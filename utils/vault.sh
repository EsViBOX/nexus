#!/bin/bash
# =================================================================
# Esvibox NEXUS - Ansible Vault Manager
# =================================================================

# Colores para la terminal
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

# Rutas del proyecto
PROJECT_ROOT=$(dirname $(dirname $(realpath "$0")))
VAULT_FILE="$PROJECT_ROOT/inventory/group_vars/all/vault.yml"
TEMPLATE_FILE="${VAULT_FILE}.template"
PASS_FILE="$PROJECT_ROOT/.vault_pass"

cd "$PROJECT_ROOT"

# Función de ayuda
usage() {
    echo "Uso: $0 {init|edit|view|encrypt}"
    echo "  init    : Crea el vault.yml a partir de la plantilla y lo cifra."
    echo "  edit    : Abre el vault cifrado para edición."
    echo "  view    : Muestra el contenido del vault descifrado en pantalla."
    echo "  encrypt : Cifra el archivo vault.yml si está en texto plano."
    exit 1
}

# Verificar existencia del archivo de contraseña
if [ ! -f "$PASS_FILE" ]; then
    echo -e "${RED}Error: No se encuentra el archivo $PASS_FILE${NC}"
    echo "Crea un archivo con tu contraseña maestra antes de continuar."
    exit 1
fi

case "$1" in
    init)
        if [ -f "$VAULT_FILE" ]; then
            echo -e "${RED}El archivo vault.yml ya existe.${NC}"
            exit 1
        fi
        echo -e "${BLUE}Inicializando vault desde plantilla...${NC}"
        cp "$TEMPLATE_FILE" "$VAULT_FILE"
        uv run ansible-vault encrypt "$VAULT_FILE" --vault-password-file "$PASS_FILE"
        echo -e "${GREEN}Vault creado y cifrado con éxito.${NC}"
        ;;

    edit)
        echo -e "${BLUE}Abriendo vault para edición...${NC}"
        uv run ansible-vault edit "$VAULT_FILE" --vault-password-file "$PASS_FILE"
        ;;

    view)
        echo -e "${BLUE}Contenido del Vault:${NC}"
        uv run ansible-vault view "$VAULT_FILE" --vault-password-file "$PASS_FILE"
        ;;

    encrypt)
        echo -e "${BLUE}Cifrando archivo vault.yml...${NC}"
        uv run ansible-vault encrypt "$VAULT_FILE" --vault-password-file "$PASS_FILE"
        echo -e "${GREEN}Archivo protegido.${NC}"
        ;;

    *)
        usage
        ;;
esac
