"""
modbus_simulator.py — ChargeGrid Intelligence Hub
Simula os registros MODBUS do GoodWe HCA G2.

Registros referenciados (Mapa_MODBUS_HCA_G2.pdf):
    10009 — A Phase Charging Volt      (U16, gain 10, V)
    10012 — A Phase Charging Current   (U16, gain 10, A)
    10015 — Charging power             (U16, gain 10, kW)
    10017 — Charging Station Status    (U16, 0-10)
    10063 — Charge duration            (U32, s)
    10065 — Accumulated electricity    (U32, gain 10, kWh)
    10029 — Maximum Charging Power     (RW, U16, gain 10, kW)

Status possíveis (reg 10017):
    0 = Ocioso (sem conector)
    1 = Disponível (conector plugado)
    2 = Handshake com veículo
    3 = Carregando
    4 = Carregamento concluído
    5 = Alarme
"""

import random
import time
import threading
from datetime import datetime


class MODBUSSimulator:

    STATUS_MAP = {
        0: 'Ocioso',
        1: 'Disponível',
        2: 'Handshake',
        3: 'Carregando',
        4: 'Concluído',
        5: 'Alarme',
    }

    USUARIOS = [
        {'nome': 'Wendel Pedro',   'veiculo': 'BYD Seal 2024',    'placa': 'ABC-1D23'},
        {'nome': 'Ana Carolina',   'veiculo': 'Tesla Model 3',     'placa': 'DEF-4E56'},
        {'nome': 'Carlos Mendes',  'veiculo': 'Volvo XC40',        'placa': 'GHI-7F89'},
        {'nome': 'Marcos Reis',    'veiculo': 'Chery Tiggo 8',     'placa': 'JKL-0G12'},
    ]

    def __init__(self, num_conectores=6, limite_kw=55.0):
        self.num_conectores = num_conectores
        self.limite_kw = limite_kw
        self._lock = threading.Lock()
        self._conectores = {}
        self._inicializar()
        self._iniciar_loop()

    # ── Setup ─────────────────────────────────────────────────

    def _inicializar(self):
        # Estado inicial: 4 carregando, 1 disponível, 1 em alarme
        estados = [3, 3, 3, 3, 1, 5]

        for i in range(self.num_conectores):
            cid = f'C-0{i + 1}'
            st  = estados[i] if i < len(estados) else 1
            usr = self.USUARIOS[i] if (st == 3 and i < len(self.USUARIOS)) else None
            pmax = [7.0, 11.0, 22.0, 11.0, 7.0, 7.0][i]

            self._conectores[cid] = {
                'id':            cid,
                'usuario':       usr,

                # Registros MODBUS (armazenados com gain, igual ao hardware)
                'reg_10009': random.randint(2190, 2310),          # tensão   V * 10
                'reg_10012': random.randint(120, 320),            # corrente A * 10
                'reg_10015': int(pmax * 10) if st == 3 else 0,   # potência kW * 10
                'reg_10017': st,
                'reg_10063': random.randint(300, 3600) if st == 3 else 0,  # duração s
                'reg_10065': round(random.uniform(3.0, 25.0) * 10) if st == 3 else 0,  # kWh * 10

                # Controle interno do simulador
                '_pmax_kw':      pmax,
                '_palvo_kw':     pmax,
                '_balanceado':   False,
                '_falha_cod':    '0x0001' if st == 5 else None,
            }

    # ── Loop de atualização ───────────────────────────────────

    def _tick(self):
        """Chamado a cada 3 segundos: avança sessões ativas."""
        with self._lock:
            for c in self._conectores.values():
                if c['reg_10017'] != 3:
                    continue

                # Avança tempo e energia
                c['reg_10063'] += 3
                palvo = c['_palvo_kw']
                oscila = random.uniform(-0.08, 0.08)
                p_real = max(1.4, palvo + oscila)
                c['reg_10015'] = int(p_real * 10)

                # kWh = potência (kW) × tempo (h)
                # kWh = potência (kW) × tempo (h) — acumula em ponto flutuante,
                # sem truncar a cada tick (truncar aqui descartava incrementos
                # pequenos e o registrador nunca progredia).
                kwh_tick = p_real * (3 / 3600)
                c['reg_10065'] += kwh_tick * 10

                # Tensão oscila levemente
                c['reg_10009'] = max(2150, min(2400, c['reg_10009'] + random.randint(-5, 5)))

    def _iniciar_loop(self):
        def _run():
            while True:
                self._tick()
                time.sleep(3)
        threading.Thread(target=_run, daemon=True).start()

    # ── API pública ───────────────────────────────────────────

    def get_all(self):
        with self._lock:
            return [self._serial(cid, c) for cid, c in self._conectores.items()]

    def get_conector(self, cid):
        with self._lock:
            c = self._conectores.get(cid)
            return self._serial(cid, c) if c else None

    def get_potencia_total_kw(self):
        with self._lock:
            return round(sum(c['reg_10015'] / 10 for c in self._conectores.values()), 2)

    def get_percentual_demanda(self):
        return round((self.get_potencia_total_kw() / self.limite_kw) * 100, 1)

    def set_potencia_alvo(self, cid, kw):
        with self._lock:
            if cid in self._conectores:
                self._conectores[cid]['_palvo_kw']   = max(1.4, kw)
                self._conectores[cid]['_balanceado'] = True

    def restaurar_potencia(self, cid):
        with self._lock:
            if cid in self._conectores:
                c = self._conectores[cid]
                c['_palvo_kw']   = c['_pmax_kw']
                c['_balanceado'] = False

    def iniciar_sessao(self, cid, usuario: dict) -> bool:
        """
        Inicia uma sessão manualmente em um conector disponível (status 1).
        usuario = {'nome': str, 'veiculo': str, 'placa': str}
        Retorna True se iniciou com sucesso, False caso contrário.
        """
        with self._lock:
            c = self._conectores.get(cid)
            if not c or c['reg_10017'] not in (0, 1):
                return False
            c['reg_10017'] = 3
            c['reg_10063'] = 0
            c['reg_10065'] = 0
            c['reg_10015'] = int(c['_pmax_kw'] * 10)
            c['usuario']   = usuario
            c['_balanceado'] = False
            return True

    def encerrar_sessao_manual(self, cid) -> bool:
        """
        Encerra uma sessão ativa manualmente pelo operador.
        Retorna True se encerrou com sucesso, False caso contrário.
        """
        with self._lock:
            c = self._conectores.get(cid)
            if not c or c['reg_10017'] != 3:
                return False
            c['reg_10017'] = 1
            c['reg_10015'] = 0
            c['usuario']   = None
            c['_balanceado'] = False
            return True

    def resetar(self):
        """Reinicia todos os conectores ao estado inicial de demonstração."""
        with self._lock:
            self._inicializar()

    # ── Serialização ──────────────────────────────────────────

    def _serial(self, cid, c):
        dur_s = c['reg_10063']
        h, m  = divmod(dur_s // 60, 60)
        dur_str = f'{h}h {m:02d}min' if h > 0 else f'{m}min'

        kwh = round(c['reg_10065'] / 10, 2)

        return {
            'id':            cid,
            'status_cod':    c['reg_10017'],
            'status':        self.STATUS_MAP.get(c['reg_10017'], '?'),
            'tensao_v':      round(c['reg_10009'] / 10, 1),
            'corrente_a':    round(c['reg_10012'] / 10, 1),
            'potencia_kw':   round(c['reg_10015'] / 10, 1),
            'pmax_kw':       c['_pmax_kw'],
            'kwh_sessao':    kwh,
            'duracao_s':     dur_s,
            'duracao_str':   dur_str,
            'balanceado':    c['_balanceado'],
            'falha_cod':     c['_falha_cod'],
            'usuario':       c['usuario'],
        }


# ── Instância global ──────────────────────────────────────────
simulator = MODBUSSimulator(num_conectores=6, limite_kw=55.0)


# ── Teste isolado ─────────────────────────────────────────────
if __name__ == '__main__':
    print('[MODBUS] Iniciando simulador — aguarde 6 segundos para ver evolução...\n')
    for _ in range(3):
        time.sleep(3)
        all_c = simulator.get_all()
        pt = simulator.get_potencia_total_kw()
        print(f'  Potência total: {pt} kW  |  {simulator.get_percentual_demanda()}% do limite')
        for c in all_c:
            if c['status_cod'] == 3:
                print(f'    {c["id"]} | {c["potencia_kw"]} kW | {c["kwh_sessao"]} kWh | {c["duracao_str"]}')
    print('\n[OK] modbus_simulator.py funcionando.')
