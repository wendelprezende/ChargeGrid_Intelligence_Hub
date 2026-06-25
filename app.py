"""
app.py — ChargeGrid Intelligence Hub
Servidor Flask: rotas de interface e API JSON.

Rotas de interface:
    /              → index (links para os painéis)
    /operador      → painel do operador
    /usuario/<id>  → painel do usuário para o conector <id>

API JSON (consultada pelo frontend a cada 3s):
    GET  /api/conectores          → todos os conectores + estado da demanda
    GET  /api/conector/<id>       → dados de um conector + configurações
    GET  /api/config              → todas as configurações
    GET  /api/financeiro          → sessões do dia + receita
    GET  /api/recomendacoes       → recomendações do motor de IA
    POST /api/assistente          → assistente do usuário (motor de regras)
"""

import threading
import time
from datetime import datetime

from flask import Flask, jsonify, render_template, request

from database import (
    init_db, get_all_config, get_sessoes_do_dia, get_config
)
from modbus_simulator import simulator
from load_balancer import verificar_e_balancear

app = Flask(__name__)

# ── Inicialização ─────────────────────────────────────────────
init_db()

def _loop_balanceamento():
    """Thread em background: verifica demanda a cada 3 segundos."""
    while True:
        verificar_e_balancear()
        time.sleep(3)

threading.Thread(target=_loop_balanceamento, daemon=True).start()
print('[APP] Loop de balanceamento iniciado.')


# ─────────────────────────────────────────────────────────────
# Rotas de interface
# ─────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return (
        '<h2 style="font-family:sans-serif">ChargeGrid Intelligence Hub</h2>'
        '<p><a href="/operador">🖥 Painel do Operador</a></p>'
        '<p><a href="/usuario/C-01">👤 Painel do Usuário — C-01</a></p>'
        '<p><a href="/usuario/C-02">👤 Painel do Usuário — C-02</a></p>'
        '<hr><p style="font-size:12px;color:#999">API: '
        '<a href="/api/conectores">/api/conectores</a> · '
        '<a href="/api/config">/api/config</a> · '
        '<a href="/api/financeiro">/api/financeiro</a></p>'
    )

@app.route('/operador')
def operador():
    return render_template('operador.html')

@app.route('/usuario/<conector_id>')
def usuario(conector_id):
    return render_template('usuario.html', conector_id=conector_id.upper())


# ─────────────────────────────────────────────────────────────
# API JSON
# ─────────────────────────────────────────────────────────────

@app.route('/api/conectores')
def api_conectores():
    """Retorna todos os conectores + estado da demanda elétrica."""
    conectores = simulator.get_all()
    estado     = verificar_e_balancear()
    return jsonify({
        'conectores': conectores,
        'demanda': {
            'potencia_total_kw': estado['potencia_total_kw'],
            'limite_kw':         estado['limite_kw'],
            'percentual':        estado['percentual'],
            'nivel':             estado['nivel'],
            'acao':              estado['acao'],
            'mensagem':          estado['mensagem'],
        },
        'timestamp': datetime.now().strftime('%H:%M:%S'),
    })


@app.route('/api/conector/<conector_id>')
def api_conector(conector_id):
    """Retorna dados de um conector específico + configurações atuais."""
    c = simulator.get_conector(conector_id.upper())
    if not c:
        return jsonify({'erro': f'Conector {conector_id} não encontrado.'}), 404
    return jsonify({
        'conector': c,
        'config':   get_all_config(),
        'timestamp': datetime.now().strftime('%H:%M:%S'),
    })


@app.route('/api/config')
def api_config():
    """Retorna todas as configurações do sistema."""
    return jsonify(get_all_config())


@app.route('/api/financeiro')
def api_financeiro():
    """Retorna resumo financeiro do dia."""
    sessoes  = get_sessoes_do_dia()
    encerradas = [s for s in sessoes if s['status'] == 'encerrada']
    receita  = sum(s['valor_total'] for s in encerradas)
    ticket_medio = round(receita / len(encerradas), 2) if encerradas else 0
    return jsonify({
        'receita_dia':    round(receita, 2),
        'total_sessoes':  len(sessoes),
        'sessoes_encerradas': len(encerradas),
        'ticket_medio':   ticket_medio,
        'sessoes':        sessoes,
    })


@app.route('/api/recomendacoes')
def api_recomendacoes():
    """Motor de IA por regras: gera recomendações para o operador."""
    hora = datetime.now().hour
    recomendacoes = []

    conectores  = simulator.get_all()
    ativos      = [c for c in conectores if c['status_cod'] == 3]
    pct_demanda = simulator.get_percentual_demanda()

    # Regra 1 — demanda elevada no horário de pico
    if pct_demanda > 75 and 17 <= hora < 21:
        recomendacoes.append({
            'nivel':   'alerta',
            'titulo':  'Demanda elevada no horário de pico',
            'texto':   f'Uso atual em {pct_demanda}% com {len(ativos)} conectores ativos. '
                       f'Considere aumentar a tarifa de pico para R$1,40/kWh para redistribuir a demanda.',
        })

    # Regra 2 — conector em falha
    falhas = [c for c in conectores if c['status_cod'] == 5]
    if falhas:
        ids = ', '.join(c['id'] for c in falhas)
        recomendacoes.append({
            'nivel':   'critico',
            'titulo':  f'Conector(es) em falha: {ids}',
            'texto':   f'{len(falhas)} conector(es) com alarme ativo. '
                       f'Verifique a conexão RS-485 e os logs de erro no registro MODBUS 10001–10008.',
        })

    # Regra 3 — alta ocupação (todos os conectores em uso)
    disponiveis = [c for c in conectores if c['status_cod'] == 1]
    if not disponiveis and len(ativos) >= 4:
        recomendacoes.append({
            'nivel':   'info',
            'titulo':  'Todos os conectores ocupados',
            'texto':   'Nenhum conector disponível no momento. Se isso for recorrente, '
                       'considere expandir a frota de carregadores.',
        })

    # Regra 4 — horário fora de ponta com baixa ocupação
    if hora < 6 and len(ativos) <= 1:
        recomendacoes.append({
            'nivel':   'ok',
            'titulo':  'Baixa demanda fora de ponta',
            'texto':   'Tarifa reduzida (R$0,62/kWh) ativa com poucos usuários. '
                       'Promoção de recarga noturna pode aumentar a utilização.',
        })

    # Regra padrão se não houver nenhuma
    if not recomendacoes:
        recomendacoes.append({
            'nivel':   'ok',
            'titulo':  'Sistema operando normalmente',
            'texto':   f'Demanda em {pct_demanda}%. Nenhuma ação necessária no momento.',
        })

    return jsonify({'recomendacoes': recomendacoes, 'timestamp': datetime.now().strftime('%H:%M:%S')})


@app.route('/api/assistente', methods=['POST'])
def api_assistente():
    """
    Assistente do usuário — motor de regras por palavras-chave.
    Body JSON: { "pergunta": "...", "conector_id": "C-01" }
    """
    dados       = request.get_json(silent=True) or {}
    pergunta    = dados.get('pergunta', '').lower().strip()
    conector_id = dados.get('conector_id', 'C-01').upper()

    c      = simulator.get_conector(conector_id)
    config = get_all_config()
    hora   = datetime.now().hour

    # Tarifa vigente
    if   0  <= hora <  6: tarifa, faixa = config['tarifa_00_06'], 'fora de ponta (00h–06h)'
    elif 6  <= hora < 17: tarifa, faixa = config['tarifa_06_17'], 'normal (06h–17h)'
    elif 17 <= hora < 21: tarifa, faixa = config['tarifa_17_21'], 'pico (17h–21h)'
    else:                 tarifa, faixa = config['tarifa_21_00'], 'reduzido (21h–00h)'

    custo_atual = round(c['kwh_sessao'] * float(tarifa), 2) if c else 0

    # Tabela de intenções
    intencoes = [
        (
            ['lento', 'devagar', 'reduzido', 'diminuiu', 'baixo', 'potência'],
            f'A velocidade de carregamento foi reduzida para {c["potencia_kw"] if c else "—"} kW '
            f'pelo balanceamento dinâmico de carga. Isso acontece quando a demanda total do '
            f'estabelecimento se aproxima do limite contratado. É temporário e automático.'
        ),
        (
            ['custo', 'preço', 'valor', 'quanto', 'pagar', 'cobrança', 'total'],
            f'Você consumiu {c["kwh_sessao"] if c else 0} kWh até agora. '
            f'Com a tarifa {faixa} (R${tarifa}/kWh), '
            f'o custo acumulado é de R${custo_atual:.2f}.'
        ),
        (
            ['tarifa', 'pico', 'horário', 'faixa', 'kWh'],
            f'Tarifa atual: {faixa} — R${tarifa}/kWh. '
            f'Para economizar, prefira recarregar entre 00h e 06h (R$0,62/kWh).'
        ),
        (
            ['tempo', 'termina', 'quando', 'restante', 'falta', 'demora'],
            f'Sua sessão está ativa há {c["duracao_str"] if c else "—"}. '
            f'O tempo restante depende da capacidade restante da bateria do seu veículo.'
        ),
        (
            ['problema', 'erro', 'parou', 'falhou', 'não funciona', 'travou'],
            'Tente desconectar e reconectar o cabo. Se o problema persistir, '
            'acione o suporte do estabelecimento ou verifique se o conector indicado é o correto.'
        ),
        (
            ['obrigado', 'valeu', 'ok', 'certo', 'entendi'],
            'Fico feliz em ajudar! Qualquer outra dúvida é só perguntar. 😊'
        ),
    ]

    for palavras, resposta in intencoes:
        if any(p in pergunta for p in palavras):
            return jsonify({'resposta': resposta})

    return jsonify({
        'resposta': (
            f'Posso ajudar com: custo da recarga, tarifa vigente, '
            f'velocidade de carregamento, tempo de sessão ou problemas técnicos. '
            f'Sessão atual: {c["kwh_sessao"] if c else 0} kWh · {c["duracao_str"] if c else "—"}.'
        )
    })


# ─────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app.run(debug=True, port=5000, use_reloader=False)