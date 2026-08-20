#!/bin/sh
# Backup do Postgres, para rodar no cron do servidor.
#
#   0 3 * * * cd /opt/batimento/finfam-backend && ./scripts/backup.sh >> /var/log/batimento-backup.log 2>&1
#
# Guarda os últimos 14 dias em ./backups, que é volume do contêiner do banco.
# Catorze é o suficiente para perceber uma corrupção silenciosa antes de o
# backup bom sair da janela.
#
# IMPORTANTE: backup que nunca foi restaurado não é backup, é esperança. Use o
# scripts/restaurar.sh ao menos uma vez, numa base descartável, antes de
# confiar nesta rotina.

set -eu

DIAS_A_MANTER=14
DESTINO="./backups"
CARIMBO=$(date +%Y-%m-%d_%H%M)
ARQUIVO="$DESTINO/batimento_$CARIMBO.sql.gz"

mkdir -p "$DESTINO"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Iniciando backup..."

# `pg_dump` roda dentro do contêiner do banco, que é quem tem o cliente e as
# credenciais. O gzip é feito aqui fora para não depender do que há na imagem.
docker compose -f docker-compose.prod.yml exec -T db \
    pg_dump -U "${POSTGRES_USER:-finfam}" -d "${POSTGRES_DB:-finfam}" --clean --if-exists \
    | gzip > "$ARQUIVO"

# Um dump que falhou no meio deixa arquivo pequeno e válido em aparência. O
# tamanho mínimo é uma checagem grosseira, mas pega o caso comum de o contêiner
# ter morrido durante a cópia.
TAMANHO=$(wc -c < "$ARQUIVO")
if [ "$TAMANHO" -lt 1024 ]; then
    echo "ERRO: backup com $TAMANHO bytes — pequeno demais para ser real. Removendo."
    rm -f "$ARQUIVO"
    exit 1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup em $ARQUIVO ($((TAMANHO / 1024)) KB)"

# Só apaga o antigo depois de o novo ter dado certo.
find "$DESTINO" -name 'batimento_*.sql.gz' -type f -mtime +$DIAS_A_MANTER -delete
echo "Backups mantidos: $(find "$DESTINO" -name 'batimento_*.sql.gz' | wc -l)"
