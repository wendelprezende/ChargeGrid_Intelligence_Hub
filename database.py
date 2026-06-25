"""
database.py — ChargeGrid Intelligence Hub
Gerencia o banco SQLite local: sessões, configurações e eventos.
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'chargegrid.db')


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Cria tabelas e insere configurações padrão na primeira execução."""
    conn = get_conn()
    cur = conn.cursor()

    cur.executescript('''
        CREATE TABLE IF NOT EXISTS sessoes (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            conector_id      TEXT    NOT NULL,
            usuario          TEXT    NOT NULL,
            veiculo          TEXT    NOT NULL,
            placa            TEXT    NOT NULL,
            inicio           TEXT    NOT NULL,
            fim              TEXT,
            kwh_total        REAL    DEFAULT 0,
            valor_total      REAL    DEFAULT 0,
            tarifa_aplicada  TEXT,
            status           TEXT    DEFAULT 'ativa'
        );

        CREATE TABLE IF NOT EXISTS configuracoes (
            chave  TEXT PRIMARY KEY,
            valor  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS eventos_balanceamento (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp      TEXT    NOT NULL,
            potencia_total REAL,
            acao           TEXT,
            detalhes       TEXT
        );
    ''')

    # Configurações padrão — só inseridas se ainda não existirem
    defaults = {
        'limite_contratado_kw':  '55',
        'threshold_alerta':      '0.80',
        'nome_estabelecimento':  'Estacionamento Central',
        'tarifa_00_06':          '0.62',
        'tarifa_06_17':          '0.78',
        'tarifa_17_21':          '1.25',
        'tarifa_21_00':          '0.70',
    }
    for chave, valor in defaults.items():
        cur.execute(
            'INSERT OR IGNORE INTO configuracoes (chave, valor) VALUES (?, ?)',
            (chave, valor)
        )

    conn.commit()
    conn.close()
    print('[DB] Banco inicializado em', DB_PATH)


# ── Leitura ───────────────────────────────────────────────────

def get_config(chave):
    conn = get_conn()
    row = conn.execute('SELECT valor FROM configuracoes WHERE chave = ?', (chave,)).fetchone()
    conn.close()
    return row['valor'] if row else None


def get_all_config():
    conn = get_conn()
    rows = conn.execute('SELECT chave, valor FROM configuracoes').fetchall()
    conn.close()
    return {r['chave']: r['valor'] for r in rows}


def get_sessoes_do_dia():
    conn = get_conn()
    hoje = datetime.now().strftime('%Y-%m-%d')
    rows = conn.execute(
        "SELECT * FROM sessoes WHERE inicio LIKE ? ORDER BY inicio DESC",
        (f'{hoje}%',)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_sessao_ativa(conector_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM sessoes WHERE conector_id = ? AND status = 'ativa' LIMIT 1",
        (conector_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ── Escrita ───────────────────────────────────────────────────

def encerrar_sessao(conector_id, kwh_total, valor_total, tarifa_aplicada):
    conn = get_conn()
    fim = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn.execute(
        '''UPDATE sessoes
           SET fim = ?, kwh_total = ?, valor_total = ?, tarifa_aplicada = ?, status = "encerrada"
           WHERE conector_id = ? AND status = "ativa"''',
        (fim, kwh_total, valor_total, tarifa_aplicada, conector_id)
    )
    conn.commit()
    conn.close()


def registrar_balanceamento(potencia_total, acao, detalhes):
    conn = get_conn()
    conn.execute(
        'INSERT INTO eventos_balanceamento (timestamp, potencia_total, acao, detalhes) VALUES (?, ?, ?, ?)',
        (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), potencia_total, acao, detalhes)
    )
    conn.commit()
    conn.close()


def atualizar_config(chave, valor):
    conn = get_conn()
    conn.execute('UPDATE configuracoes SET valor = ? WHERE chave = ?', (valor, chave))
    conn.commit()
    conn.close()


# ── Teste isolado ─────────────────────────────────────────────
if __name__ == '__main__':
    init_db()
    print('[TESTE] Config carregada:', get_all_config())
    print('[TESTE] Sessões de hoje:', get_sessoes_do_dia())
    print('[OK] database.py funcionando.')