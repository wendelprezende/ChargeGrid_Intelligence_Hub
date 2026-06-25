"""
load_balancer.py — ChargeGrid Intelligence Hub
Motor de balanceamento dinâmico de carga (Dynamic Load Balancing).

Lógica:
    < 80% do limite  → operação normal, restaura potência se estava balanceado
    80–95% do limite → redução proporcional suave (alvo: 78% do limite)
    ≥ 95% do limite  → redução proporcional crítica (alvo: 85% do limite)

O mínimo por conector é 1.4 kW (especificação HCA G2).
"""

from modbus_simulator import simulator
from database import get_config, registrar_balanceamento


THRESHOLD_ALERTA   = 0.80   # 80%
THRESHOLD_CRITICO  = 0.95   # 95%
POTENCIA_MIN_KW    = 1.4    # mínimo HCA G2


def verificar_e_balancear() -> dict:
    """
    Avalia a demanda atual e age se necessário.
    Retorna dict com estado da rede para exibição no painel.
    """
    limite_kw     = float(get_config('limite_contratado_kw') or 55.0)
    potencia_total = simulator.get_potencia_total_kw()
    pct           = potencia_total / limite_kw

    estado = {
        'potencia_total_kw': potencia_total,
        'limite_kw':         limite_kw,
        'percentual':        round(pct * 100, 1),
        'acao':              'normal',
        'nivel':             'ok',           # ok | alerta | critico
        'mensagem':          'Operando dentro do limite.',
    }

    ativos = [c for c in simulator.get_all() if c['status_cod'] == 3]

    if pct >= THRESHOLD_CRITICO:
        alvo_total = limite_kw * 0.85
        _redistribuir(ativos, alvo_total)
        estado.update(
            acao     = 'reducao_critica',
            nivel    = 'critico',
            mensagem = f'⚡ Demanda em {estado["percentual"]}% — balanceamento crítico ativo.',
        )
        registrar_balanceamento(potencia_total, 'critico', estado['mensagem'])

    elif pct >= THRESHOLD_ALERTA:
        alvo_total = limite_kw * 0.78
        _redistribuir(ativos, alvo_total)
        estado.update(
            acao     = 'reducao_suave',
            nivel    = 'alerta',
            mensagem = f'⚠ Demanda em {estado["percentual"]}% — balanceamento preventivo ativo.',
        )
        registrar_balanceamento(potencia_total, 'alerta', estado['mensagem'])

    else:
        # Dentro do limite: restaura conectores que estavam balanceados
        for c in ativos:
            if c['balanceado']:
                simulator.restaurar_potencia(c['id'])

    return estado


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
    print(f'  {r["potencia_total_kw"]} kW / {r["limite_kw"]} kW — {r["percentual"]}% — {r["acao"]}')
    print('[OK] load_balancer.py funcionando.')