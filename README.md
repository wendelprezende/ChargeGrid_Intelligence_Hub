# ⚡ ChargeGrid Intelligence Hub

Plataforma web que transforma o carregador **GoodWe HCA G2** em um eletroposto comercial completo — tarifação dinâmica, controle de demanda, billing e assistente de suporte em tempo real, sem depender de nenhuma API externa.

Desenvolvido para o **FIAP EV Challenge 2026** — track ChargeGrid Intelligence, em parceria com a GoodWe.

---

## O problema

O SEMS+ da GoodWe atende muito bem o setor residencial, mas não possui: motor de tarifação por sessão, controle automático de demanda entre múltiplos conectores, nem uma tela dedicada ao usuário final durante a recarga. O ChargeGrid Intelligence Hub nasce para preencher exatamente essas lacunas no setor comercial.

## O que o sistema faz

- **Simula os registros MODBUS reais** do HCA G2 (potência, corrente, tensão, status) para 6 conectores simultâneos
- **Balanceia a carga automaticamente** quando a demanda ultrapassa 80%/95% do limite contratado, com histerese para evitar oscilação
- **Calcula tarifas dinâmicas** por faixa horária (madrugada, normal, pico, reduzido)
- **Gera comprovantes** e mantém histórico completo de sessões, com exportação em CSV
- **Responde dúvidas do usuário** com um motor de intenções por pontuação de relevância — sem IA generativa, só lógica de regras
- **Alerta o operador** em tempo real sobre falhas e eventos de balanceamento, com central de notificações e toasts

## Telas

| Rota | Descrição |
|---|---|
| `/` | Landing page com status ao vivo e QR Code para o painel do usuário |
| `/operador` | Painel de controle: conectores, gráfico de potência, faturamento, IA, configurações, notificações |
| `/usuario/<conector_id>` | Painel do motorista: progresso da carga, custo, assistente, wizard de auto-início de sessão |
| `/mapa` | Planta interativa dos conectores |
| `/comprovante/<sessao_id>` | Comprovante imprimível de uma sessão encerrada |

---

## Como rodar

```bash
pip install -r requirements.txt
python app.py
```

Acesse **http://localhost:5000**

Na primeira execução do dia, o sistema gera automaticamente um histórico de sessões simuladas (mais sessões quanto mais tarde no dia), então o faturamento já aparece populado desde a primeira abertura.

---

## Arquitetura

```
chargegrid/
├── app.py                  # Servidor Flask — todas as rotas
├── database.py             # Camada SQLite (sessões, config, eventos)
├── modbus_simulator.py     # Simulador dos registros MODBUS do HCA G2
├── load_balancer.py        # Balanceamento dinâmico com histerese
├── billing_engine.py       # Tarifação, comprovantes, cálculo de custo
├── assistant_engine.py     # Motor de assistente por pontuação de intenção
├── alerts.py                # Fila central de eventos do sistema
├── seed_data.py             # Gerador de histórico por horário do dia
├── requirements.txt
└── templates/
    ├── index.html
    ├── operador.html
    ├── usuario.html
    ├── mapa.html
    └── comprovante.html
```

Nenhum módulo Python depende de bibliotecas externas além do Flask — toda a lógica de negócio roda localmente.

## Stack técnica

- **Backend:** Python 3 + Flask
- **Banco de dados:** SQLite (local, sem servidor externo)
- **Frontend:** HTML5 + CSS3 + JavaScript vanilla (sem frameworks)
- **Gráficos:** Chart.js (via CDN, com fallback caso a rede falhe)
- **QR Code:** biblioteca embutida no código — funciona offline

## Testes

Veja o [`MANUAL_DE_TESTES.md`](./MANUAL_DE_TESTES.md) para o roteiro completo de validação de todos os módulos, endpoints e regras de negócio.

---

## Equipe 03 — FIAP EV Challenge 2026

Anna Karla · Arthur Araújo · Beatriz da Silva · Daniel Alejandro · Victor Hugo Lavaqui · Wendel Pedro
