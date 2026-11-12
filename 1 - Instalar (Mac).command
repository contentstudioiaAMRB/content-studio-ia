#!/bin/bash
cd "$(dirname "$0")" || exit 1
bash instalador/instalar_mac.sh
echo
read -r -p "Pulsa Enter para cerrar esta ventana."
