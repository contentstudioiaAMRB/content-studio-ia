#!/bin/bash
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  echo 'Content Studio IA todavía no está instalado. Abre «1 - Instalar (Mac).command».'
  read -r -p "Pulsa Enter para cerrar."; exit 1
fi
.venv/bin/python content_studio.py
