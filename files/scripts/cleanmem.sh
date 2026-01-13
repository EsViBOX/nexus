#!/bin/bash
if [ $UID -ne "0" ]
then
    echo "Error: no dispone de permisos para ejecutar $0 como superusuario"
    exit 1
fi

echo "Limpieza de Swap y Cache"
swapoff -a
sync; sysctl -w vm.drop_caches=3 >/dev/null; sync
swapon -a
