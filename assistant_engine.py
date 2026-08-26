"""
assistant_engine.py — ChargeGrid Intelligence Hub
Motor de assistente do usuário: reconhecimento de intenção por
pontuação de relevância (keyword scoring), tolerante a variações
de frase, sinônimos e escrita informal ("tá", "pra", sem acentos).

Substitui o modelo anterior (primeira palavra-chave que bate = resposta)
por um sistema que soma pontos por cada gatilho reconhecido na frase e
escolhe a intenção de maior pontuação, com um piso mínimo para evitar
respostas por coincidência de uma palavra solta e genérica.
"""

import re
import unicodedata


def normalizar(texto: str) -> str:
    """Minúsculas, sem acentos, sem pontuação, espaços colapsados."""
    texto = texto.lower().strip()
    texto = unicodedata.normalize('NFKD', texto)
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r'[^\w\s]', ' ', texto)
    texto = re.sub(r'\s+', ' ', texto).strip()
    return texto


# Cada intenção tem um id, uma lista de gatilhos (palavras/frases — sinônimos
# e variações informais incluídos) e uma função que gera a resposta a partir
# do contexto da sessão ativa.
INTENCOES = [
    {
        'id': 'velocidade',
        'gatilhos': [
            'lento', 'devagar', 'esta lento', 'ta lento', 'muito lento',
            'caiu a potencia', 'potencia caiu', 'reduziu', 'diminuiu',
            'baixa potencia', 'potencia baixa', 'carregando devagar',
            'mais devagar', 'perdeu potencia', 'velocidade caiu',
            'porque esta lento', 'por que ta lento', 'esta demorando',
        ],
        'resposta': lambda ctx: (
            f'A velocidade de carregamento foi reduzida para {ctx["potencia_kw"]} kW '
            f'pelo balanceamento dinâmico de carga. Isso acontece quando a demanda total '
            f'do estabelecimento se aproxima do limite contratado. É temporário e automático.'
        ) if ctx['tem_sessao'] else 'Não encontrei uma sessão ativa para checar a velocidade agora.'
    },
    {
        'id': 'custo',
        'gatilhos': [
            'custo', 'preco', 'valor', 'cobranca', 'total',
            'quanto vou pagar', 'quanto custa', 'quanto ja gastei', 'quanto gastei',
            'valor da recarga', 'preco da recarga', 'quanto ta gastando',
            'quanto ta custando',
        ],
        'resposta': lambda ctx: (
            f'Você consumiu {ctx["kwh_sessao"]} kWh até agora. '
            f'Com a tarifa {ctx["faixa"]} (R${ctx["tarifa"]}/kWh), '
            f'o custo acumulado é de R${ctx["custo_atual"]:.2f}.'
        ) if ctx['tem_sessao'] else 'Não encontrei uma sessão ativa para calcular o custo.'
    },
    {
        'id': 'tarifa',
        'gatilhos': [
            'tarifa', 'pico', 'horario', 'faixa', 'preco do kwh', 'valor do kwh',
            'tarifa atual', 'qual a tarifa', 'horario de pico', 'esta no pico',
            'economizar', 'horario mais barato', 'quando e mais barato',
        ],
        'resposta': lambda ctx: (
            f'Tarifa atual: {ctx["faixa"]} — R${ctx["tarifa"]}/kWh. '
            f'Para economizar, prefira recarregar entre 00h e 06h.'
        )
    },
    {
        'id': 'tempo',
        'gatilhos': [
            'tempo', 'termina', 'quando termina', 'restante', 'falta', 'demora',
            'quanto tempo', 'quanto falta', 'ja vai terminar', 'quando acaba',
            'tempo restante', 'quanto tempo falta',
        ],
        'resposta': lambda ctx: (
            f'Sua sessão está ativa há {ctx["duracao_str"]}. '
            f'O tempo restante depende da capacidade restante da bateria do seu veículo.'
        ) if ctx['tem_sessao'] else 'Não encontrei uma sessão ativa no momento.'
    },
    {
        'id': 'bateria',
        'gatilhos': [
            'bateria', 'carga da bateria', 'porcentagem', 'quanto ja carregou',
            'nivel da bateria', 'quanto ta de bateria', 'quanto falta pra encher',
            'esta cheio', 'ja encheu', 'carga atual', 'de bateria',
            'quanto tenho de bateria', 'quanto de bateria',
        ],
        'resposta': lambda ctx: (
            f'Sua bateria está em aproximadamente {ctx["bateria_pct"]}% no momento, '
            f'com base na energia já fornecida nesta sessão.'
        ) if ctx['tem_sessao'] else 'Não encontrei uma sessão ativa para checar a bateria.'
    },
    {
        'id': 'seguranca_cabo',
        'gatilhos': [
            'cabo', 'seguro', 'seguranca', 'posso tocar', 'cabo esquenta',
            'cabo quente', 'e perigoso', 'da choque', 'posso desconectar',
            'posso tirar o cabo',
        ],
        'resposta': lambda ctx: (
            'O cabo e o conector possuem proteção contra choque elétrico e desligam '
            'automaticamente antes de qualquer desconexão manual. Evite apenas puxá-lo '
            'pelo próprio cabo — sempre pelo conector.'
        )
    },
    {
        'id': 'pagamento',
        'gatilhos': [
            'pagamento', 'como pago', 'forma de pagamento', 'cartao', 'pix',
            'aceita pix', 'aceita cartao', 'como faco o pagamento', 'onde pago',
            'pra pagar', 'para pagar', 'quero pagar', 'forma de pagar',
            'pagar a recarga',
        ],
        'resposta': lambda ctx: (
            'O pagamento é feito automaticamente ao encerrar a sessão, com o valor '
            'calculado com base no consumo e na tarifa vigente. O comprovante fica '
            'disponível na tela assim que você encerrar a recarga.'
        )
    },
    {
        'id': 'comparacao_conectores',
        'gatilhos': [
            'outro conector', 'outros conectores', 'tem conector livre',
            'algum conector livre', 'tem vaga', 'vaga livre',
            'conector disponivel', 'outro carregador',
        ],
        'resposta': lambda ctx: (
            'Você pode conferir todos os conectores e a disponibilidade em tempo '
            'real no mapa de conectores do estabelecimento.'
        )
    },
    {
        'id': 'problema',
        'gatilhos': [
            'problema', 'erro', 'parou', 'falhou', 'nao funciona', 'travou',
            'nao esta carregando', 'parou de carregar', 'desconectou sozinho',
            'deu erro', 'algo errado',
        ],
        'resposta': lambda ctx: (
            'Tente desconectar e reconectar o cabo. Se o problema persistir, acione '
            'o suporte do estabelecimento ou verifique se o conector indicado é o correto.'
        )
    },
    {
        'id': 'agradecimento',
        'gatilhos': [
            'obrigado', 'obrigada', 'valeu', 'ok', 'certo', 'entendi',
            'blz', 'beleza', 'show', 'perfeito',
        ],
        'resposta': lambda ctx: 'Fico feliz em ajudar! Qualquer outra dúvida é só perguntar. 😊'
    },
]


def _peso_gatilho(gatilho: str) -> float:
    """Frases com mais palavras pesam mais — reduz falso positivo de palavra solta."""
    n_palavras = len(gatilho.split())
    return 1.0 + (n_palavras - 1) * 0.6


def identificar_intencao(pergunta: str):
    """
    Retorna (intencao_dict, score) da intenção com maior pontuação,
    ou (None, 0) se nada atingiu o piso mínimo.
    """
    texto = normalizar(pergunta)
    if not texto:
        return None, 0

    melhor, melhor_score = None, 0.0
    for intencao in INTENCOES:
        score = 0.0
        for gatilho in intencao['gatilhos']:
            if normalizar(gatilho) in texto:
                score += _peso_gatilho(gatilho)
        if score > melhor_score:
            melhor, melhor_score = intencao, score

    if melhor_score < 1.0:
        return None, 0
    return melhor, melhor_score


def gerar_resposta(pergunta: str, contexto: dict) -> str:
    """Ponto de entrada usado pela rota /api/assistente."""
    intencao, _ = identificar_intencao(pergunta)
    if intencao:
        return intencao['resposta'](contexto)

    if contexto.get('tem_sessao'):
        return (
            f'Posso ajudar com: custo da recarga, tarifa vigente, velocidade de '
            f'carregamento, nível da bateria, tempo de sessão, segurança do cabo, '
            f'pagamento ou problemas técnicos. Sessão atual: '
            f'{contexto["kwh_sessao"]} kWh · {contexto["duracao_str"]}.'
        )
    return (
        'Posso ajudar com dúvidas sobre custo, tarifa, velocidade de carregamento, '
        'bateria, pagamento e segurança. No momento não encontrei uma sessão ativa '
        'neste conector.'
    )


# ── Teste isolado ─────────────────────────────────────────────
if __name__ == '__main__':
    ctx_teste = {
        'tem_sessao': True, 'potencia_kw': 7.2, 'kwh_sessao': 12.4, 'duracao_str': '32min',
        'faixa': 'pico (17h–21h)', 'tarifa': 1.25, 'custo_atual': 15.5, 'bateria_pct': 63.0,
    }
    perguntas_teste = [
        'por que ta tao lento isso?',
        'quanto vou pagar no final?',
        'qual o horario mais barato pra carregar?',
        'quanto tempo falta pra terminar',
        'quanto ja tenho de bateria',
        'posso tocar no cabo sem problema?',
        'como faço pra pagar',
        'tem algum conector livre agora',
        'meu carro parou de carregar do nada',
        'valeu, entendi tudo',
        'oi tudo bem',
        'quanto ta gastando ate agora',
        'aceita pix?',
    ]
    print('[TESTE] Motor de intenções\n')
    for p in perguntas_teste:
        intencao, score = identificar_intencao(p)
        r = gerar_resposta(p, ctx_teste)
        print(f'  [{score:.1f}] "{p}" -> {intencao["id"] if intencao else "FALLBACK"}')
        print(f'        {r[:85]}...')
    print('\n[OK] assistant_engine.py funcionando.')
