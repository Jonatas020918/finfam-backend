"""O compose de produção.

Estes testes existem porque os dois defeitos que quebraram o primeiro deploy
não eram de código: eram do arquivo de composição, e só apareceram no servidor,
com o operador esperando.

O primeiro foi um dois-pontos sem aspas numa mensagem de ajuda, que impedia o
YAML de carregar. O segundo foi um volume usado por um serviço e nunca
declarado no topo. Nenhum dos dois é pego por suíte de aplicação, e ambos são
triviais de verificar aqui.
"""

from pathlib import Path

import pytest
import yaml

COMPOSE = Path(__file__).resolve().parent.parent / "docker-compose.prod.yml"


@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_o_arquivo_carrega(compose):
    """Um dois-pontos sem aspas derruba o arquivo inteiro."""
    assert compose["services"], "nenhum serviço definido"


def test_todo_volume_usado_esta_declarado(compose):
    """Volume citado num serviço e ausente do topo invalida o projeto.

    O Docker recusa subir com "refers to undefined volume" — e a mensagem só
    aparece no primeiro `up`, que costuma ser no servidor novo.
    """
    declarados = set(compose.get("volumes") or {})

    usados = set()
    for servico in compose["services"].values():
        for montagem in servico.get("volumes", []):
            origem = montagem.split(":")[0]
            # Caminho relativo é bind mount, não volume nomeado.
            if not origem.startswith((".", "/")):
                usados.add(origem)

    faltando = usados - declarados
    assert not faltando, f"volumes usados mas não declarados: {sorted(faltando)}"


def test_todo_servico_referenciado_existe(compose):
    """`depends_on` apontando para serviço inexistente também invalida."""
    servicos = set(compose["services"])

    for nome, servico in compose["services"].items():
        dependencias = servico.get("depends_on") or {}
        alvos = dependencias if isinstance(dependencias, list) else list(dependencias)
        for alvo in alvos:
            assert alvo in servicos, f"'{nome}' depende de '{alvo}', que não existe"


def test_banco_e_fila_nao_sao_publicados(compose):
    """Postgres e Redis só podem ser alcançáveis pela rede interna.

    Publicar 5432 na internet é o jeito mais rápido de perder a base.
    """
    for nome in ("db", "redis"):
        assert not compose["services"][nome].get("ports"), (
            f"'{nome}' está publicando porta para fora"
        )


def test_apenas_o_caddy_fala_com_a_internet(compose):
    """Uma única porta de entrada, que é onde o TLS termina."""
    publicam = [n for n, s in compose["services"].items() if s.get("ports")]
    assert publicam == ["caddy"], f"esperado só o caddy, veio {publicam}"


def test_a_api_usa_a_imagem_de_producao(compose):
    """`target: dev` traria o runserver — um processo, sem concorrência."""
    for nome in ("api", "worker", "beat"):
        alvo = compose["services"][nome]["build"]["target"]
        assert alvo == "base", f"'{nome}' compila com target '{alvo}'"


def test_a_api_sobe_com_gunicorn_depois_de_migrar(compose):
    comando = compose["services"]["api"]["command"]
    assert "check --deploy" in comando, "subir sem validar a configuração"
    assert "migrate" in comando
    assert "gunicorn" in comando
    assert comando.index("migrate") < comando.index("gunicorn")


def test_o_frontend_e_compilado_do_repositorio_vizinho(compose):
    """Os dois repositórios precisam estar lado a lado no servidor."""
    assert compose["services"]["web"]["build"]["context"] == "../finfam-frontend"


def test_o_caddyfile_e_montado_somente_leitura(compose):
    montagens = compose["services"]["caddy"]["volumes"]
    caddyfile = [m for m in montagens if "Caddyfile" in m]
    assert caddyfile and caddyfile[0].endswith(":ro")


def test_os_segredos_obrigatorios_travam_a_subida(compose):
    """`:?` faz o compose recusar subir sem o valor, em vez de usar vazio."""
    caddy = compose["services"]["caddy"]["environment"]
    assert ":?" in caddy["DOMINIO"]
    assert ":?" in caddy["EMAIL_ACME"]
    assert ":?" in compose["services"]["db"]["environment"]["POSTGRES_PASSWORD"]


def test_a_senha_do_banco_entra_na_url_de_conexao(compose):
    for nome in ("api", "worker", "beat"):
        url = compose["services"][nome]["environment"]["DATABASE_URL"]
        assert "${POSTGRES_PASSWORD}" in url, f"'{nome}' não recebe a senha"
        assert url.startswith("postgres://")
