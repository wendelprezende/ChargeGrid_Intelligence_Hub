"""
load_balancer.py — ChargeGrid Intelligence Hub
Motor de balanceamento dinâmico de carga (Dynamic Load Balancing).

Lógica com HISTERESE (evita oscilação/flapping perto dos limiares):
    entra em alerta em   ≥ 80%  →  só sai de volta ao normal quando < 65%
    entra em crítico em  ≥ 95%  →  só sai do crítico quando       < 85%

Sem histerese, reduzir a potência derruba a demanda abaixo do limiar de
entrada, o que restaura a potência total no próximo ciclo, o que sobe a
demanda de novo acima do limiar — um ciclo de liga/desliga a cada poll.
A histerese cria uma "zona morta" entre entrada e saída, estabilizando
o comportamento visível no painel.

Além da histerese por percentual, existe um COOLDOWN DE TEMPO: uma
transição de estado (ativar ou desativar o balanceamento) só é aceita
se pelo menos 20 segundos se passaram desde a última transição. Isso
garante uma frequência de ocorrência previsível e visualmente estável,
independente de quão rápido a demanda oscile entre os limiares.

O mínimo por conector é 1.4 kW (especificação HCA G2).
"""

import time

from modbus_simulator import simulator
from database import get_config, registrar_balanceamento


THRESHOLD_ALERTA        = 0.80   # entra em alerta a partir daqui
THRESHOLD_ALERTA_SAIDA  = 0.65   # só volta ao normal abaixo daqui
THRESHOLD_CRITICO       = 0.95   # entra em crítico a partir daqui
THRESHOLD_CRITICO_SAIDA = 0.85   # só sai do crítico abaixo daqui (cai para alerta)
POTENCIA_MIN_KW         = 1.4    # mínimo HCA G2
COOLDOWN_TRANSICAO_S    = 20     # intervalo mínimo entre ativação/desativação

_estado_atual        = 'ok'  # memória entre chamadas — 'ok' | 'alerta' | 'critico'
_ultima_transicao_ts = float('-inf')  # garante que a 1ª transição real não espere o cooldown


def verificar_e_balancear() -> dict:
    """
    Avalia a demanda atual e age se necessário.
    Retorna dict com estado da rede para exibição no painel.
    """
    global _estado_atual, _ultima_transicao_ts

    limite_kw      = float(get_config('limite_contratado_kw') or 55.0)
    potencia_total = simulator.get_potencia_total_kw()
    pct            = potencia_total / limite_kw

    estado_calculado = _proximo_estado(_estado_atual, pct)
    agora            = time.time()

    if estado_calculado != _estado_atual:
        if (agora - _ultima_transicao_ts) < COOLDOWN_TRANSICAO_S:
            # Ainda dentro do cooldown — mantém o estado atual por mais tempo,
            # mesmo que a condição de transição já tenha sido satisfeita.
            estado_calculado = _estado_atual
        else:
            _ultima_transicao_ts = agora

    _estado_atual = estado_calculado
    novo_estado   = estado_calculado

    estado = {
        'potencia_total_kw': potencia_total,
        'limite_kw':         limite_kw,
        'percentual':        round(pct * 100, 1),
        'acao':              'normal',
        'nivel':             novo_estado,
        'mensagem':          'Operando dentro do limite.',
    }

    ativos = [c for c in simulator.get_all() if c['status_cod'] == 3]

    if novo_estado == 'critico':
        alvo_total = limite_kw * 0.85
        _redistribuir(ativos, alvo_total)
        estado.update(
            acao     = 'reducao_critica',
            mensagem = f'⚡ Demanda em {estado["percentual"]}% — balanceamento crítico ativo.',
        )
        registrar_balanceamento(potencia_total, 'critico', estado['mensagem'])

    elif novo_estado == 'alerta':
        alvo_total = limite_kw * 0.78
        _redistribuir(ativos, alvo_total)
        estado.update(
            acao     = 'reducao_suave',
            mensagem = f'⚠ Demanda em {estado["percentual"]}% — balanceamento preventivo ativo.',
        )
        registrar_balanceamento(potencia_total, 'alerta', estado['mensagem'])

    else:
        # Dentro do limite (com histerese já aplicada): restaura conectores balanceados
        for c in ativos:
            if c['balanceado']:
                simulator.restaurar_potencia(c['id'])

    return estado


def _proximo_estado(estado_anterior: str, pct: float) -> str:
    """Decide o próximo estado com histerese, evitando flapping perto dos limiares."""
    if estado_anterior == 'critico':
        if pct < THRESHOLD_CRITICO_SAIDA:
            return 'alerta' if pct >= THRESHOLD_ALERTA_SAIDA else 'ok'
        return 'critico'

    if estado_anterior == 'alerta':
        if pct >= THRESHOLD_CRITICO:
            return 'critico'
        if pct < THRESHOLD_ALERTA_SAIDA:
            return 'ok'
        return 'alerta'

    # estado_anterior == 'ok'
    if pct >= THRESHOLD_CRITICO:
        return 'critico'
    if pct >= THRESHOLD_ALERTA:
        return 'alerta'
    return 'ok'


def _redistribuir(ativos: list, alvo_total_kw: float):
    """
    Distribui alvo_total_kw entre os conectores ativos
    de forma proporcional à potência atual de cada um.
    """
    if not ativos:
        return

    soma_atual = sum(c['potencia_kw'] for c in ativos)
    if soma_atual == 0:
        return

    for c in ativos:
        proporcao   = c['potencia_kw'] / soma_atual
        nova_pot    = max(POTENCIA_MIN_KW, round(alvo_total_kw * proporcao, 1))
        simulator.set_potencia_alvo(c['id'], nova_pot)


# ── Teste isolado ─────────────────────────────────────────────
if __name__ == '__main__':
    import time

    print('[LB] Estado inicial:')
    r = verificar_e_balancear()
    print(f'  {r["potencia_total_kw"]} kW / {r["limite_kw"]} kW — {r["percentual"]}% — {r["nivel"]}')
    print('[OK] load_balancer.py funcionando.')
