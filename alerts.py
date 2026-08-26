"""
alerts.py — ChargeGrid Intelligence Hub
Fila de eventos do sistema. Fonte única de verdade tanto para a central
de notificações acumuladas quanto para os toasts temporários do operador —
os dois consultam a mesma fila, evitando lógicas duplicadas.
"""

import threading
from datetime import datetime

MAX_ALERTAS = 50

_lock = threading.Lock()
_alertas = []       # lista de dicts, mais recente no final
_proximo_id = 1


def adicionar_alerta(tipo: str, titulo: str, mensagem: str = '') -> dict:
    """
    tipo: 'ok' | 'alerta' | 'critico' | 'erro'
    Retorna o alerta criado (já com id e timestamp).
    """
    global _proximo_id
    with _lock:
        alerta = {
            'id':        _proximo_id,
            'tipo':      tipo,
            'titulo':    titulo,
            'mensagem':  mensagem,
            'timestamp': datetime.now().strftime('%H:%M:%S'),
        }
        _proximo_id += 1
        _alertas.append(alerta)
        if len(_alertas) > MAX_ALERTAS:
            _alertas.pop(0)
        return alerta


def get_alertas(limite: int = 30) -> list:
    with _lock:
        return list(_alertas[-limite:])


def limpar_alertas():
    with _lock:
        _alertas.clear()


# ── Teste isolado ─────────────────────────────────────────────
if __name__ == '__main__':
    adicionar_alerta('ok', 'Sessão iniciada em C-01', 'Wendel Pedro · BYD Seal 2024')
    adicionar_alerta('alerta', 'Balanceamento preventivo ativado', 'Demanda em 82%')
    adicionar_alerta('erro', 'Falha no conector C-06', 'Verifique a conexão RS-485.')

    for a in get_alertas():
        print(f'  [{a["timestamp"]}] ({a["tipo"]}) {a["titulo"]} — {a["mensagem"]}')

    limpar_alertas()
    print('Após limpar:', get_alertas())
    print('[OK] alerts.py funcionando.')
