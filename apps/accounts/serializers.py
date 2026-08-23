from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from rest_framework import serializers

from .models import User
from .services import provisionar_conta
from .utils import ip_da_requisicao


class UserSerializer(serializers.ModelSerializer):
    household_id = serializers.SerializerMethodField()
    membro_id = serializers.SerializerMethodField()
    # Propriedade do modelo: compara a versão aceita com a que está em vigor.
    termos_aceitos = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "nome_completo",
            "telefone",
            "papel",
            "household_id",
            "membro_id",
            "aceite_disclaimer_educacional_em",
            # A tela usa isto para decidir se pede o aceite de novo — o que
            # acontece sempre que uma versão nova dos termos é publicada.
            "termos_aceitos",
            "aceite_termos_em",
        ]
        read_only_fields = ["id", "email", "papel"]

    def get_household_id(self, obj):
        membro = getattr(obj, "membro", None)
        return str(membro.household_id) if membro else None

    def get_membro_id(self, obj):
        membro = getattr(obj, "membro", None)
        return str(membro.id) if membro else None


class SolicitarRedefinicaoSerializer(serializers.Serializer):
    email = serializers.EmailField()


class ConfirmarRedefinicaoSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    password = serializers.CharField(write_only=True, validators=[validate_password])


class SignupSerializer(serializers.Serializer):
    """Cadastro self-service (Fase 1).

    Um único POST cria: usuário, núcleo familiar no tenant "plataforma" e o
    membro titular já vinculado ao login. O onboarding detalhado vem depois.
    """

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, validators=[validate_password])
    nome_completo = serializers.CharField(max_length=180)
    telefone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    nome_familia = serializers.CharField(max_length=180, required=False, allow_blank=True)

    # Sem aceite não há base legal para tratar os dados. É obrigatório e não
    # tem valor-padrão: a caixa precisa ser marcada por quem se cadastra, e um
    # `default=True` aqui transformaria o consentimento em ficção.
    aceite_termos = serializers.BooleanField(write_only=True)

    def validate_aceite_termos(self, value):
        if not value:
            raise serializers.ValidationError(
                "É necessário aceitar os termos de uso e a política de privacidade."
            )
        return value

    def validate_email(self, value):
        value = value.lower()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Já existe uma conta com este e-mail.")
        return value

    def create(self, validated_data):
        pedido = self.context.get("request")
        # O aceite é gravado junto com a criação, na mesma transação (dentro de
        # `provisionar_conta`): uma conta que existe sem registro de
        # consentimento é exatamente o que a lei não admite.
        return provisionar_conta(
            email=validated_data["email"],
            password=validated_data["password"],
            nome_completo=validated_data["nome_completo"],
            telefone=validated_data.get("telefone", ""),
            nome_familia=validated_data.get("nome_familia", ""),
            aceite_termos_versao=settings.VERSAO_TERMOS,
            aceite_termos_em=timezone.now(),
            aceite_termos_ip=ip_da_requisicao(pedido) if pedido else None,
        )


class GoogleAuthSerializer(serializers.Serializer):
    """Entrada do login com Google: só o token que o botão do Google devolve.

    Chama-se `credential` porque é o nome do campo que o Google Identity
    Services já usa no retorno do próprio botão — manter o mesmo nome evita
    uma tradução sem propósito entre front e back.
    """

    credential = serializers.CharField(write_only=True)
