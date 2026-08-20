#!/bin/sh
# Subida da API em produção.
#
# Isto era um comando multilinha dentro do docker-compose.yml, e o YAML comeu
# os argumentos: no estilo dobrado (`>`), linhas mais indentadas que a primeira
# têm as quebras preservadas em vez de viradas em espaço. O `--bind` virou um
# comando separado, e o gunicorn subiu com os padrões — escutando em
# 127.0.0.1, onde o Nginx não alcança, com um worker em vez de três.
#
# O sintoma foi 502 no navegador e um log que parecia perfeito.
#
# Um script tem outra vantagem: dá para explicar cada etapa, e o erro aparece
# nomeado em vez de sair como "container exited".

set -e

echo "→ Validando a configuração..."
python manage.py check --deploy --fail-level ERROR

echo "→ Aplicando migrações..."
python manage.py migrate --noinput

# 0.0.0.0 e não localhost: o Nginx fala com este processo pela rede do Docker,
# de outro contêiner. Ligado em 127.0.0.1 o gunicorn só atende a si mesmo.
echo "→ Subindo o gunicorn em 0.0.0.0:8000 com ${GUNICORN_WORKERS:-3} trabalhadores..."
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
