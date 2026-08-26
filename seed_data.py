"""
seed_data.py — ChargeGrid Intelligence Hub
Gera sessões históricas simuladas do dia corrente, como se o eletroposto
já estivesse operando desde a meia-noite. Roda uma única vez por dia, na
inicialização do servidor — se já existem sessões para hoje, não faz nada.

Regra de negócio: quanto mais cedo no dia, menos sessões e menos receita
acumulada. O volume por hora segue o mesmo perfil das faixas de tarifa
(pico das 17h–21h concentra mais sessões, madrugada tem poucas).
"""

import random
from datetime import datetime, timedelta

from database import contar_sessoes_do_dia, inserir_sessoes_historicas, get_all_config
from billing_engine import get_tarifa_para_hora

# Peso relativo de cada faixa horária — reflete o mesmo padrão de demanda
# usado nas tarifas (madrugada baixa, comercial normal, pico alto, noite reduzida).
PESO_POR_FAIXA = {
    range(0, 6):   0.3,   # fora de ponta — baixa demanda
    range(6, 17):  1.0,   # normal
    range(17, 21): 2.4,   # pico — maior concentração de sessões
    range(21, 24): 0.7,   # reduzido
}

BASE_SESSOES_POR_HORA_PESO = 1.3  # ajusta o volume total gerado por dia

CONECTORES     = ['C-01', 'C-02', 'C-03', 'C-04', 'C-05', 'C-06']
POTENCIA_CONECTOR = {  # kW médios plausíveis por conector (mesmo padrão do simulador)
    'C-01': 7.0, 'C-02': 11.0, 'C-03': 22.0, 'C-04': 11.0, 'C-05': 7.0, 'C-06': 7.0,
}

NOMES = [
    'Ana Beatriz Souza', 'Carlos Eduardo Lima', 'Fernanda Alves', 'Gustavo Ribeiro',
    'Juliana Martins', 'Marcos Paulo Rocha', 'Patrícia Gomes', 'Rafael Nunes',
    'Camila Torres', 'Bruno Cardoso', 'Larissa Fernandes', 'Thiago Barbosa',
    'Beatriz Carvalho', 'Diego Almeida', 'Vanessa Pereira',
]
VEICULOS = [
    'BYD Seal 2024', 'BYD Dolphin', 'Tesla Model 3', 'Volvo XC40 Recharge',
    'Chery Tiggo 8 PHEV', 'Renault Kwid E-Tech', 'GWM Ora 03', 'Fiat E-Ulysse',
    'Nissan Leaf', 'BMW iX1',
]


def _peso_da_hora(hora: int) -> float:
    for faixa, peso in PESO_POR_FAIXA.items():
        if hora in faixa:
            return peso
    return 1.0


def _gerar_placa() -> str:
    letras = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ', k=3))
    numeros = ''.join(random.choices('0123456789', k=1))
    letra_meio = random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')
    numeros2 = ''.join(random.choices('0123456789', k=2))
    return f'{letras}-{numeros}{letra_meio}{numeros2}'


def _gerar_sessoes_da_hora(hora: int, minuto_max: int, hoje: datetime, config: dict) -> list:
    """Gera sessões sintéticas para uma hora específica do dia."""
    peso = _peso_da_hora(hora)
    n_sessoes = round(peso * BASE_SESSOES_POR_HORA_PESO * random.uniform(0.7, 1.3))
    # Hora corrente (parcial): proporcional aos minutos já passados
    if minuto_max < 60:
        n_sessoes = round(n_sessoes * (minuto_max / 60))

    tarifa_valor, tarifa_nome, tarifa_faixa = get_tarifa_para_hora(hora, config)
    tarifa_str = f'{tarifa_nome} — R${tarifa_valor:.2f}/kWh ({tarifa_faixa})'

    sessoes = []
    for _ in range(max(0, n_sessoes)):
        conector = random.choice(CONECTORES)
        pmax     = POTENCIA_CONECTOR[conector]

        minuto_inicio = random.randint(0, max(0, minuto_max - 5))
        duracao_min   = random.randint(15, 75)
        inicio_dt = hoje.replace(hour=hora, minute=0, second=0, microsecond=0) + timedelta(minutes=minuto_inicio)
        fim_dt    = inicio_dt + timedelta(minutes=duracao_min)

        # Nunca deixa uma sessão histórica terminar no futuro
        agora = datetime.now()
        if fim_dt > agora:
            fim_dt = agora
        if fim_dt <= inicio_dt:
            continue

        duracao_h    = (fim_dt - inicio_dt).total_seconds() / 3600
        potencia_media = pmax * random.uniform(0.55, 0.92)  # carregamento real oscila abaixo do máximo
        kwh_total    = round(potencia_media * duracao_h, 2)
        valor_total  = round(kwh_total * tarifa_valor, 2)

        sessoes.append((
            conector,
            random.choice(NOMES),
            random.choice(VEICULOS),
            _gerar_placa(),
            inicio_dt.strftime('%Y-%m-%d %H:%M:%S'),
            fim_dt.strftime('%Y-%m-%d %H:%M:%S'),
            kwh_total,
            valor_total,
            tarifa_str,
        ))
    return sessoes


def seed_historico_do_dia_se_necessario():
    """
    Ponto de entrada — chamado uma vez na inicialização do app.py.
    Só gera dados se ainda não houver nenhuma sessão registrada hoje.
    """
    if contar_sessoes_do_dia() > 0:
        print('[SEED] Sessões de hoje já existem — nada a gerar.')
        return

    agora  = datetime.now()
    config = get_all_config()
    todas_sessoes = []

    for hora in range(0, agora.hour + 1):
        minuto_max = agora.minute if hora == agora.hour else 60
        todas_sessoes.extend(_gerar_sessoes_da_hora(hora, minuto_max, agora, config))

    if todas_sessoes:
        inserir_sessoes_historicas(todas_sessoes)

    receita_total = sum(s[7] for s in todas_sessoes)
    print(f'[SEED] {len(todas_sessoes)} sessões históricas geradas '
          f'(00h–{agora.strftime("%Hh%M")}) — receita simulada: R${receita_total:.2f}')


# ── Teste isolado ─────────────────────────────────────────────
if __name__ == '__main__':
    seed_historico_do_dia_se_necessario()
