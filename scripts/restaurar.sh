#!/bin/sh
# Restaura um backup do Postgres.
#
#   ./scripts/restaurar.sh backups/batimento_2026-08-20_0300.sql.gz
#
# Rode isto ao menos uma vez antes de confiar na rotina de backup. Não é
# formalidade: o modo mais comum de descobrir que os backups estavam quebrados
# é precisar deles.
#
# Para testar sem risco, crie um banco descartável e restaure nele:
#
#   docker compose -f docker-compose.prod.yml exec db createdb -U finfam teste_restauracao
#   BANCO=teste_restauracao ./scripts/restaurar.sh backups/o_arquivo.sql.gz
#   docker compose -f docker-compose.prod.yml exec db dropdb -U finfam teste_restauracao

set -eu

ARQUIVO="${1:-}"
BANCO="${BANCO:-${POSTGRES_DB:-finfam}}"
USUARIO="${POSTGRES_USER:-finfam}"

if [ -z "$ARQUIVO" ] || [ ! -f "$ARQUIVO" ]; then
    echo "Uso: $0 <arquivo.sql.gz>"
    echo
    echo "Backups disponíveis:"
    ls -lh ./backups/*.sql.gz 2>/dev/null || echo "  nenhum"
    exit 1
fi

if [ "$BANCO" = "${POSTGRES_DB:-finfam}" ]; then
    echo "ATENÇÃO: isto vai SOBRESCREVER o banco de produção '$BANCO'."
    echo "Para ensaiar sem risco, use um banco descartável com BANCO=teste_restauracao."
    printf "Digite o nome do banco para confirmar: "
    read -r confirmacao
    [ "$confirmacao" = "$BANCO" ] || { echo "Cancelado."; exit 1; }
fi

echo "Restaurando $ARQUIVO em '$BANCO'..."
gunzip -c "$ARQUIVO" \
    | docker compose -f docker-compose.prod.yml exec -T db psql -U "$USUARIO" -d "$BANCO"

echo
echo "Restaurado. Confira antes de considerar o teste concluído:"
echo "  docker compose -f docker-compose.prod.yml exec db psql -U $USUARIO -d $BANCO \\"
echo "    -c 'SELECT COUNT(*) AS familias FROM households_household;'"
