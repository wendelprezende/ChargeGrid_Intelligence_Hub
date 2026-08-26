"""
app.py — ChargeGrid Intelligence Hub
Servidor Flask: rotas de interface e API JSON.

Rotas de interface:
    /              → index (links para os painéis)
    /operador      → painel do operador
    /usuario/<id>  → painel do usuário para o conector <id>

API JSON (consultada pelo frontend a cada 3s):
    GET  /api/conectores                   → todos os conectores + estado da demanda
    GET  /api/conector/<id>                → dados de um conector + configurações
    GET  /api/config                       → todas as configurações
    GET  /api/financeiro                   → sessões do dia + receita
    GET  /api/recomendacoes                → recomendações do motor de IA
    POST /api/assistente                   → assistente do usuário (motor de regras)
    POST /api/sessao/iniciar/<id>          → inicia sessão manualmente
    POST /api/sessao/encerrar/<id>         → encerra sessão manualmente
    POST /api/config/salvar                → salva configurações do operador
    POST /api/simulador/reset              → reinicia o simulador ao estado inicial
"""

import threading
import time
import csv
import io
from datetime import datetime

from flask import Flask, jsonify, render_template, request, Response

from database import (
    init_db, get_all_config, get_sessoes_do_dia, get_config, atualizar_config,
    get_historico_por_usuario, criar_sessao_ativa, get_sessao_por_id
)
from modbus_simulator import simulator
from load_balancer import verificar_e_balancear
from billing_engine import get_dados_sessao, encerrar_e_gerar_comprovante, get_bateria_pct
from assistant_engine import gerar_resposta
from alerts import adicionar_alerta, get_alertas, limpar_alertas
from seed_data import seed_historico_do_dia_se_necessario

app = Flask(__name__)

# ── Inicialização ─────────────────────────────────────────────
init_db()
seed_historico_do_dia_se_necessario()

def _loop_balanceamento():
    """Thread em background: verifica demanda a cada 3 segundos."""
    while True:
        verificar_e_balancear()
        time.sleep(3)

threading.Thread(target=_loop_balanceamento, daemon=True).start()
print('[APP] Loop de balanceamento iniciado.')

# Rastreamento de estado — evita disparar o mesmo alerta a cada poll de 3s.
_ultimo_nivel_demanda      = 'ok'   # último nível efetivamente alertado
_ultimo_alerta_demanda_ts  = 0.0    # timestamp (time.time()) do último alerta de demanda
COOLDOWN_ALERTA_DEMANDA_S  = 35     # intervalo mínimo entre notificações de balanceamento
_falhas_ja_alertadas        = set()
_alerts_lock                = threading.Lock()


def _checar_alertas_sistema(estado_demanda: dict, conectores: list):
    """
    Compara o estado atual com o último alertado e dispara alertas só em mudança
    real de nível — com um cooldown mínimo entre notificações de balanceamento,
    evitando flood quando a demanda oscila perto do limiar (80%/95%).
    Falhas de conector não têm cooldown: cada nova falha é sempre notificada.
    """
    global _ultimo_nivel_demanda, _ultimo_alerta_demanda_ts, _falhas_ja_alertadas
    with _alerts_lock:
        nivel = estado_demanda['nivel']
        agora = time.time()

        if nivel != _ultimo_nivel_demanda:
            if (agora - _ultimo_alerta_demanda_ts) >= COOLDOWN_ALERTA_DEMANDA_S:
                if nivel == 'critico':
                    adicionar_alerta('critico', 'Balanceamento crítico ativado', estado_demanda['mensagem'])
                elif nivel == 'alerta':
                    adicionar_alerta('alerta', 'Balanceamento preventivo ativado', estado_demanda['mensagem'])
                elif nivel == 'ok' and _ultimo_nivel_demanda in ('alerta', 'critico'):
                    adicionar_alerta('ok', 'Demanda normalizada', 'Balanceamento desativado — operação normal.')
                _ultimo_nivel_demanda     = nivel
                _ultimo_alerta_demanda_ts = agora
            # Se ainda dentro do cooldown, a mudança de nível é ignorada por ora —
            # na próxima verificação após os 35s, o nível mais recente é que conta.

        falhas_atuais = {c['id'] for c in conectores if c['status_cod'] == 5}
        novas = falhas_atuais - _falhas_ja_alertadas
        for fid in novas:
            adicionar_alerta('erro', f'Falha no conector {fid}', 'Verifique a conexão RS-485.')
        _falhas_ja_alertadas |= novas
        _falhas_ja_alertadas -= (_falhas_ja_alertadas - falhas_atuais)




# ─────────────────────────────────────────────────────────────
# Rotas de interface
# ─────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/operador')
def operador():
    return render_template('operador.html')

@app.route('/mapa')
def mapa():
    return render_template('mapa.html')


@app.route('/comprovante/<int:sessao_id>')
def comprovante(sessao_id):
    """Página dedicada e imprimível do comprovante de uma sessão encerrada."""
    s = get_sessao_por_id(sessao_id)
    if not s:
        return "Comprovante não encontrado.", 404

    duracao_str = '--'
    if s.get('inicio') and s.get('fim'):
        try:
            t_inicio = datetime.strptime(s['inicio'], '%Y-%m-%d %H:%M:%S')
            t_fim    = datetime.strptime(s['fim'], '%Y-%m-%d %H:%M:%S')
            segundos = int((t_fim - t_inicio).total_seconds())
            h, m = divmod(max(0, segundos) // 60, 60)
            duracao_str = f'{h}h {m:02d}min' if h > 0 else f'{m}min'
        except ValueError:
            pass

    return render_template('comprovante.html', s=s, duracao_str=duracao_str)

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
    _checar_alertas_sistema(estado, conectores)
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


@app.route('/api/exportar/csv')
def api_exportar_csv():
    """Exporta as sessões do dia como arquivo CSV para download."""
    sessoes = get_sessoes_do_dia()

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=';')
    writer.writerow([
        'ID', 'Conector', 'Usuário', 'Veículo', 'Placa',
        'Início', 'Fim', 'kWh', 'Valor (R$)', 'Tarifa', 'Status'
    ])
    for s in sessoes:
        writer.writerow([
            s['id'], s['conector_id'], s['usuario'], s['veiculo'], s['placa'],
            s['inicio'], s.get('fim') or '',
            f"{s['kwh_total']:.2f}".replace('.', ','),
            f"{s['valor_total']:.2f}".replace('.', ','),
            s.get('tarifa_aplicada') or '', s['status'],
        ])

    # BOM UTF-8 para o Excel reconhecer acentuação corretamente
    csv_data = '\ufeff' + buffer.getvalue()
    nome_arquivo = f"chargegrid_sessoes_{datetime.now().strftime('%Y-%m-%d')}.csv"

    return Response(
        csv_data,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={nome_arquivo}'}
    )


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




@app.route('/api/sessao/iniciar/<conector_id>', methods=['POST'])
def api_iniciar(conector_id):
    """Inicia uma sessão manualmente — chamado pelo painel do operador."""
    dados = request.get_json(silent=True) or {}
    usuario = {
        'nome':    dados.get('nome', 'Usuário').strip(),
        'veiculo': dados.get('veiculo', 'Veículo').strip(),
        'placa':   dados.get('placa', '---').strip().upper(),
    }
    ok = simulator.iniciar_sessao(conector_id.upper(), usuario)
    if not ok:
        return jsonify({'ok': False, 'erro': f'{conector_id} não está disponível para iniciar.'}), 400
    criar_sessao_ativa(conector_id.upper(), usuario['nome'], usuario['veiculo'], usuario['placa'])
    adicionar_alerta('ok', f'Sessão iniciada em {conector_id.upper()}', f'{usuario["nome"]} · {usuario["veiculo"]}')
    return jsonify({'ok': True, 'conector_id': conector_id.upper(), 'usuario': usuario})


@app.route('/api/sessao/<conector_id>')
def api_sessao(conector_id):
    dados = get_dados_sessao(conector_id.upper())
    if not dados:
        return jsonify({'erro': f'Sem sessao ativa em {conector_id}.'}), 404
    return jsonify(dados)

@app.route('/api/historico/<nome_usuario>')
def api_historico(nome_usuario):
    """Retorna as últimas sessões encerradas de um usuário — alimenta o carrossel."""
    historico = get_historico_por_usuario(nome_usuario, limite=5)
    return jsonify({'historico': historico, 'total': len(historico)})

@app.route('/api/sessao/encerrar/<conector_id>', methods=['POST'])
def api_encerrar(conector_id):
    try:
        comprovante = encerrar_e_gerar_comprovante(conector_id.upper())
        adicionar_alerta(
            'ok', f'Sessão encerrada em {conector_id.upper()}',
            f'R${comprovante["valor_total"]:.2f} · {comprovante["kwh_total"]} kWh'
        )
        return jsonify({'ok': True, 'comprovante': comprovante})
    except Exception as e:
        return jsonify({'ok': False, 'erro': str(e)}), 500

@app.route('/api/alertas')
def api_alertas():
    """Retorna a fila de eventos — alimenta a central e os toasts."""
    return jsonify({'alertas': get_alertas(30)})


@app.route('/api/alertas/limpar', methods=['POST'])
def api_alertas_limpar():
    limpar_alertas()
    return jsonify({'ok': True})


@app.route('/api/config/salvar', methods=['POST'])
def api_config_salvar():
    """
    Salva alterações de configuração vindas da aba Configurações.
    Body JSON pode conter qualquer subconjunto de:
    limite_contratado_kw, nome_estabelecimento,
    tarifa_00_06, tarifa_06_17, tarifa_17_21, tarifa_21_00
    """
    dados = request.get_json(silent=True) or {}
    chaves_validas = {
        'limite_contratado_kw', 'nome_estabelecimento',
        'tarifa_00_06', 'tarifa_06_17', 'tarifa_17_21', 'tarifa_21_00',
    }
    salvas = []
    for chave, valor in dados.items():
        if chave in chaves_validas and str(valor).strip() != '':
            atualizar_config(chave, str(valor).strip())
            salvas.append(chave)

    if not salvas:
        return jsonify({'ok': False, 'erro': 'Nenhum campo válido enviado.'}), 400

    return jsonify({'ok': True, 'salvas': salvas, 'config': get_all_config()})


@app.route('/api/simulador/reset', methods=['POST'])
def api_simulador_reset():
    """Reinicia o simulador MODBUS ao estado inicial de demonstração."""
    simulator.resetar()
    return jsonify({'ok': True, 'mensagem': 'Simulador reiniciado ao estado inicial.'})


@app.route('/api/assistente', methods=['POST'])
def api_assistente():
    """
    Assistente do usuário — motor de intenções com pontuação de relevância
    (ver assistant_engine.py).
    Body JSON: { "pergunta": "...", "conector_id": "C-01" }
    """
    dados       = request.get_json(silent=True) or {}
    pergunta    = dados.get('pergunta', '')
    conector_id = dados.get('conector_id', 'C-01').upper()

    c      = simulator.get_conector(conector_id)
    config = get_all_config()
    hora   = datetime.now().hour

    if   0  <= hora <  6: tarifa, faixa = float(config['tarifa_00_06']), 'fora de ponta (00h–06h)'
    elif 6  <= hora < 17: tarifa, faixa = float(config['tarifa_06_17']), 'normal (06h–17h)'
    elif 17 <= hora < 21: tarifa, faixa = float(config['tarifa_17_21']), 'pico (17h–21h)'
    else:                 tarifa, faixa = float(config['tarifa_21_00']), 'reduzido (21h–00h)'

    tem_sessao = c is not None and c['status_cod'] in (2, 3)
    contexto = {
        'tem_sessao':  tem_sessao,
        'potencia_kw': c['potencia_kw']  if tem_sessao else 0,
        'kwh_sessao':  c['kwh_sessao']   if tem_sessao else 0,
        'duracao_str': c['duracao_str']  if tem_sessao else '--',
        'bateria_pct': get_bateria_pct(conector_id, c['kwh_sessao']) if tem_sessao else 0,
        'faixa':       faixa,
        'tarifa':      tarifa,
        'custo_atual': round(c['kwh_sessao'] * tarifa, 2) if tem_sessao else 0,
    }

    resposta = gerar_resposta(pergunta, contexto)
    return jsonify({'resposta': resposta})


# ─────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app.run(debug=True, port=5000, use_reloader=False)
