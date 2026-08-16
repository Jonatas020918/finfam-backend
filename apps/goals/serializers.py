from rest_framework import serializers

from .models import Goal


class GoalSerializer(serializers.ModelSerializer):
    progresso_percentual = serializers.DecimalField(
        max_digits=6, decimal_places=2, read_only=True
    )
    compartilhada = serializers.BooleanField(read_only=True)
    membro_nome = serializers.CharField(source="membro.nome", read_only=True)

    class Meta:
        model = Goal
        fields = [
            "id",
            "membro",
            "membro_nome",
            "objetivo",
            "descricao",
            "valor_alvo",
            "valor_atual",
            "data_alvo",
            "concluida",
            "compartilhada",
            "progresso_percentual",
        ]

    def validate_membro(self, membro):
        if membro is None:
            return membro
        household = self.context.get("household")
        if household and membro.household_id != household.id:
            raise serializers.ValidationError("Membro não pertence a este núcleo familiar.")
        return membro

    def validate(self, attrs):
        alvo = attrs.get("valor_alvo", getattr(self.instance, "valor_alvo", None))
        atual = attrs.get("valor_atual", getattr(self.instance, "valor_atual", 0))
        if alvo is not None and atual is not None and atual > alvo * 10:
            raise serializers.ValidationError(
                {"valor_atual": "Valor acumulado parece inconsistente com o valor-alvo."}
            )
        return attrs
