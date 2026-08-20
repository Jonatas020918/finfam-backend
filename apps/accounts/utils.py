def ip_da_requisicao(request) -> str | None:
    """O IP de quem fez o pedido, atrás do proxy reverso.

    Em produção há Caddy e Nginx na frente, então `REMOTE_ADDR` traz o endereço
    do contêiner vizinho, não o do cliente. O primeiro item do
    `X-Forwarded-For` é o que interessa: os seguintes são os próprios proxies.

    Serve como evidência de origem do aceite dos termos — por isso o valor
    precisa ser o do titular, e não o da nossa própria rede.
    """
    encaminhado = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if encaminhado:
        return encaminhado.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
