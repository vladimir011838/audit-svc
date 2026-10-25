#!/bin/sh
# Ключ ansible-vault для --vault-password-file.
# В CI — из секрета окружения production (переменная ANSIBLE_VAULT_PASSWORD),
# локально — из файла vault-pass рядом со скриптом (он в .gitignore).
if [ -n "${ANSIBLE_VAULT_PASSWORD:-}" ]; then
  printf '%s\n' "$ANSIBLE_VAULT_PASSWORD"
else
  cat "$(dirname "$0")/vault-pass"
fi
