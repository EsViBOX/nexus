#!/bin/bash
# utils/check_inventory.sh

if [ -z "$1" ]; then
    echo "Uso: ./utils/check_inventory.sh [grupo/host]"
    exit 1
fi

TARGET=$1
VAULT_PASS=".vault_pass"
HOSTS_FILE="inventory/hosts.yml"

# Comprobamos si existe en el inventario
if ! uv run ansible-inventory -i $HOSTS_FILE --graph | grep -q "$TARGET"; then
    echo "ERROR: El objetivo '$TARGET' no existe en el inventario."
    exit 1
fi

echo "--- Nexus Inventory Check: $TARGET ---"

# 1. Intentamos primero como HOST (Muestra variables finales heredadas)
# Este es el modo más útil para Nexus
uv run ansible-inventory -i $HOSTS_FILE --host $TARGET --yaml --vault-password-file $VAULT_PASS 2>/dev/null

if [ $? -ne 0 ]; then
    echo "El target '$TARGET' no es un HOST (o no tiene variables directas), probando como GRUPO..."
    # 2. Como GRUPO: El nombre del grupo va al final, sin banderas, usando --list
    uv run ansible-inventory -i $HOSTS_FILE $TARGET --list --yaml --vault-password-file $VAULT_PASS
fi