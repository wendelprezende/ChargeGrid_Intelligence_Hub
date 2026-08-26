"""
billing_engine.py — ChargeGrid Intelligence Hub
Motor de tarifação dinâmica, cálculo de custo em tempo real e geração de comprovante.
"""

from datetime import datetime
from database import get_all_config, encerrar_sessao


# ── Bateria simulada por conector (% inicial assumida) ────────
_BATERIA_BASE = {'C-01': 35, 'C-02': 22, 'C-03': 58, 'C-04': 45, 'C-05': 0, 'C-06': 0}
_BATERIA_CAP  = 60  # kWh — capacidade assumida para simulação


def get_bateria_pct(conector_id: str, kwh_sessao: float) -> float:
    base  = _BATERIA_BASE.get(conector_id, 30)
    added = (kwh_sessao / _BATERIA_CAP) * 100
    return round(min(100, base + added), 1)


# ── Tarifa vigente ────────────────────────────────────────────

def get_tarifa_para_hora(hora: int, config: dict = None):
    """
    Retorna (valor_float, nome, faixa_horaria) para uma hora específica (0-23).
    Usado tanto para a tarifa vigente quanto para gerar sessões históricas
    simuladas em outros horários do dia.
    """
    if config is None:
        config = get_all_config()
    if   hora <  6: return float(config['tarifa_00_06']), 'Fora de ponta', '00h–06h'
    elif hora < 17: return float(config['tarifa_06_17']), 'Normal',        '06h–17h'
    elif hora < 21: return float(config['tarifa_17_21']), 'Pico',          '17h–21h'
    else:           return float(config['tarifa_21_00']), 'Reduzido',      '21h–00h'


def get_tarifa_atual(config: dict = None):
    """
    Retorna (valor_float, nome, faixa_horaria) com base na hora atual.
    """
    return get_tarifa_para_hora(datetime.now().hour, config)


# ── Cálculo de custo ──────────────────────────────────────────

def calcular_custo(kwh: float, tarifa_valor: float) -> float:
    return round(kwh * tarifa_valor, 2)


# ── Dados em tempo real para o painel do usuário ──────────────

def get_dados_sessao(conector_id: str) -> dict | None:
    """
    Retorna todos os dados necessários para o painel do usuário:
    conector, tarifa vigente, custo acumulado e % de bateria simulada.
    """
    from modbus_simulator import simulator

    c = simulator.get_conector(conector_id)
    if not c or c['status_cod'] not in (2, 3):
        return None

    config      = get_all_config()
    t_val, t_nome, t_faixa = get_tarifa_atual(config)
    kwh         = c['kwh_sessao']
    custo       = calcular_custo(kwh, t_val)
    bat_pct     = get_bateria_pct(conector_id, kwh)

    # Estimativa de custo final (assumindo mais 30 min na potência atual)
    kwh_est     = kwh + c['potencia_kw'] * 0.5
    custo_est   = calcular_custo(kwh_est, t_val)

    return {
        'conector':      c,
        'bateria_pct':   bat_pct,
        'tarifa_valor':  t_val,
        'tarifa_nome':   t_nome,
        'tarifa_faixa':  t_faixa,
        'custo_atual':   custo,
        'custo_estimado': custo_est,
    }


# ── Encerramento de sessão + comprovante ──────────────────────

def encerrar_e_gerar_comprovante(conector_id: str) -> dict:
    """
    Encerra a sessão ativa do conector, persiste no banco e
    retorna o comprovante completo para exibição ao usuário.
    """
    from modbus_simulator import simulator

    c       = simulator.get_conector(conector_id)
    config  = get_all_config()
    t_val, t_nome, t_faixa = get_tarifa_atual(config)

    kwh     = c['kwh_sessao'] if c else 0
    valor   = calcular_custo(kwh, t_val)
    tarifa_str = f'{t_nome} — R${t_val:.2f}/kWh ({t_faixa})'

    # Persiste no banco SQLite
    encerrar_sessao(conector_id, kwh, valor, tarifa_str)

    # Libera o conector no simulador — volta a ficar disponível
    simulator.encerrar_sessao_manual(conector_id)

    return {
        'conector_id':     conector_id,
        'usuario':         c['usuario'] if c else {},
        'duracao':         c['duracao_str'] if c else '--',
        'kwh_total':       kwh,
        'tarifa_aplicada': tarifa_str,
        'valor_total':     valor,
        'bateria_final':   get_bateria_pct(conector_id, kwh),
        'timestamp':       datetime.now().strftime('%d/%m/%Y %H:%M'),
    }


# ── Teste isolado ─────────────────────────────────────────────
if __name__ == '__main__':
    t_val, t_nome, t_faixa = get_tarifa_atual()
    print(f'[BILLING] Tarifa atual: {t_nome} ({t_faixa}) — R${t_val:.2f}/kWh')

    dados = get_dados_sessao('C-01')
    if dados:
        print(f'[BILLING] C-01 → {dados["kwh_sessao"] if "kwh_sessao" in dados else dados["conector"]["kwh_sessao"]} kWh'
              f' | custo: R${dados["custo_atual"]:.2f}'
              f' | bateria: {dados["bateria_pct"]}%')
    else:
        print('[BILLING] C-01 sem sessão ativa.')
    print('[OK] billing_engine.py funcionando.')
