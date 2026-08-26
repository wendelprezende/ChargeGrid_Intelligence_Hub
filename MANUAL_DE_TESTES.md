# ChargeGrid Intelligence Hub
## Manual de Testes — Validação Completa Antes da Gravação do Pitch

Este documento cobre **todos os artefatos do sistema**: cada módulo de backend, cada motor de regras, cada página e cada regra de negócio. Siga na ordem — cada bloco testa uma camada diferente, do mais interno (lógica pura) ao mais externo (interface visível pela banca).

**Antes de começar:** apague `chargegrid.db`, garanta que `static/goodwe_logo.png` e `static/ev_charger_g2.png` existem, e suba o servidor com `python app.py`. Deixe o terminal aberto — os avisos `[DB]`, `[SEED]` e `[APP]` confirmam que tudo inicializou.

---

## Parte 1 — Motores de regras (lógica pura, sem interface)

Estes testes rodam módulos isolados no terminal, sem depender do navegador. Provam que a lógica de negócio funciona independentemente da interface.

### 1.1 — Simulador MODBUS
```bash
python modbus_simulator.py
```
**Esperado:** imprime leituras de 4 conectores ativos a cada 3 segundos, com potência oscilando levemente e kWh subindo de forma consistente. Termina com `[OK] modbus_simulator.py funcionando.`

### 1.2 — Motor de balanceamento (com histerese)
```bash
python load_balancer.py
```
**Esperado:** imprime o estado inicial de demanda (percentual e nível). Para validar a histerese de verdade, use o teste prático da Parte 3.4 abaixo.

### 1.3 — Motor de tarifação
```bash
python billing_engine.py
```
**Esperado:** imprime a tarifa vigente conforme o horário atual do seu computador, e os dados de uma sessão ativa (se houver).

### 1.4 — Motor de assistente (pontuação de relevância)
```bash
python assistant_engine.py
```
**Esperado:** lista ~13 perguntas de teste, cada uma com a intenção identificada e a resposta gerada. Confirme que perguntas diferentes caem em intenções diferentes (ex: "aceita pix?" → `pagamento`, não `custo`).

### 1.5 — Fila de alertas
```bash
python alerts.py
```
**Esperado:** cria 3 alertas de teste, lista todos, depois limpa e confirma lista vazia.

### 1.6 — Gerador de histórico por horário
```bash
python seed_data.py
```
**Esperado:** imprime quantas sessões históricas foram geradas e a receita simulada total — o número deve ser proporcional à hora atual do seu relógio (poucas sessões de madrugada, muitas à noite). Se já existir `chargegrid.db` com sessões de hoje, vai imprimir que nada foi gerado (comportamento correto — evita duplicar).

---

## Parte 2 — API (backend completo, via Postman ou navegador)

Com o servidor rodando, teste cada endpoint. Os `GET` abrem direto no navegador; os `POST` precisam do Postman.

| Rota | Método | O que confirmar |
|---|---|---|
| `/api/conectores` | GET | 6 conectores com status, potência e o bloco `demanda` com percentual e nível |
| `/api/conector/C-01` | GET | Dados de um conector específico + configurações |
| `/api/config` | GET | As 4 tarifas, limite contratado e nome do estabelecimento |
| `/api/financeiro` | GET | Receita, total de sessões e ticket médio **já preenchidos** desde a primeira abertura (graças ao seed) |
| `/api/recomendacoes` | GET | Pelo menos uma recomendação do motor de IA |
| `/api/alertas` | GET | Lista de eventos do sistema |
| `/api/exportar/csv` | GET | Baixa um arquivo `.csv` com as sessões do dia |
| `/api/sessao/iniciar/C-05` | POST | Body `{"nome":"Teste","veiculo":"Teste","placa":"TST-0001"}` → `{"ok": true}` |
| `/api/sessao/C-05` | GET | Dados da sessão recém-criada, com `custo_atual` e `bateria_pct` |
| `/api/sessao/encerrar/C-05` | POST | Retorna o comprovante completo |
| `/api/assistente` | POST | Body `{"pergunta":"quanto vou pagar?","conector_id":"C-01"}` → resposta coerente |
| `/api/config/salvar` | POST | Body `{"nome_estabelecimento":"Teste"}` → `{"ok": true}` |
| `/api/simulador/reset` | POST | Reinicia todos os conectores ao estado inicial |
| `/api/alertas/limpar` | POST | Esvazia a fila de alertas |

---

## Parte 3 — Regras de negócio (comportamento ao longo do tempo)

Estes testes provam que a **lógica**, não só a tela, está correta.

### 3.1 — Tarifação dinâmica por horário
Abra `/api/config` e confirme as 4 faixas. Inicie uma sessão e observe no painel do usuário se a tarifa exibida bate com o horário atual do seu computador (madrugada = fora de ponta, 17h-21h = pico, etc).

### 3.2 — Acúmulo real de energia
Inicie uma sessão pelo operador, **espere pelo menos 60 segundos reais**, e encerre. Confirme que o comprovante mostra kWh e valor **diferentes de zero** — essa é a correção do bug de truncamento que resolvemos.

### 3.3 — Balanceamento automático
No painel do operador, deixe vários conectores ativos simultaneamente até a demanda passar de 80%. Observe o gauge mudando para laranja e a mensagem "balanceamento preventivo ativo".

### 3.4 — Histerese (sem oscilação)
Com a demanda perto de 80%, **deixe a página aberta por 30-40 segundos sem interagir**. O nível não deve alternar rapidamente entre "normal" e "alerta" — deve permanecer estável em um dos dois estados por um tempo, só mudando quando a demanda realmente cruzar a zona de saída (65% para baixo, ou 95%/85% para o crítico).

### 3.5 — Liberação de conector após encerramento
Encerre uma sessão pelo painel do usuário ou operador. Confirme que o conector fica "Disponível" (não trava em "Carregando") e que uma nova sessão pode começar ali.

### 3.6 — Cooldown de notificações
Deixe o painel do operador aberto por 2 minutos observando o canto da tela. Toasts de balanceamento não devem aparecer com menos de 35 segundos de intervalo entre si, mesmo que a demanda oscile.

### 3.7 — Motor de assistente por contexto
No painel do usuário, teste as mesmas perguntas do teste 1.4 diretamente no chat. Confirme que a resposta usa dados **reais** da sessão ativa (kWh, tarifa, tempo), não texto genérico.

### 3.8 — Geração de histórico por horário do dia
Se possível, teste em dois horários diferentes (ex: de manhã e à noite, ou ajustando o relógio do sistema) e confirme que o volume de sessões simuladas e a receita acompanham a regra: mais tarde no dia = mais dados.

---

## Parte 4 — Interface, tela por tela

### 4.1 — Tela inicial (`/`)
- Logo GoodWe visível, sem fundo branco
- Números de "Ativos", "Potência" e "Receita hoje" piscando ao atualizar a cada 5s
- QR Code real — escaneie com o celular e confirme que abre o painel do usuário
- Clique em cada um dos 3 cards e confirme a transição suave antes de navegar

### 4.2 — Painel do operador (`/operador`)
- Gauge de demanda, gráfico de potência (20 minutos já preenchidos ao abrir)
- Cards de conectores com botões **Iniciar** (nos disponíveis) e **Encerrar** (nos ativos)
- Aba Faturamento com dados já preenchidos, botão **Exportar CSV** funcional, ícone de comprovante em cada linha
- Aba Configurações — altere uma tarifa, salve, confirme reflexo imediato
- Sino de notificações — abra, confira o histórico, teste "Limpar tudo"
- Redimensione a janela para simular mobile/tablet — confirme que nada corta ou soma barra de rolagem horizontal

### 4.3 — Painel do usuário (`/usuario/C-01`)
- Anel de progresso, custo em tempo real, indicador de velocidade de carregamento
- Carrossel de histórico (arraste lateralmente)
- Chat do assistente
- Encerre a sessão → confirme comprovante → feche → confirme a tela de **wizard de nova sessão** aparecendo
- No wizard: avance do passo 1 para o 2, preencha o formulário, confirme início de nova sessão sem reload
- Confirme o botão **Home** no topo levando para `/`

### 4.4 — Mapa de conectores (`/mapa`)
- 6 vagas com cores dinâmicas de status
- Clique em uma vaga disponível → inicia sessão pelo modal
- Clique em uma vaga ativa → vai para o painel do usuário daquele conector

### 4.5 — Comprovante (`/comprovante/<id>`)
- Abra pelo ícone na tabela de faturamento
- Confirme todos os dados da sessão
- Teste o botão Imprimir (`Ctrl+P`) — o preview deve vir em fundo branco, sem botões

---

## Checklist final antes de gravar

- [ ] Todos os 6 testes da Parte 1 rodaram sem erro
- [ ] Todos os endpoints da Parte 2 responderam corretamente
- [ ] Histerese confirmada (Parte 3.4) — sem oscilação visível
- [ ] Faturamento com dados reais desde a abertura (Parte 3.8 / 4.2)
- [ ] Fluxo completo testado: iniciar → acompanhar → encerrar → novo usuário inicia (Parte 4.3)
- [ ] Responsividade conferida em pelo menos 2 tamanhos de tela

---

*ChargeGrid Intelligence Hub · Equipe 03 · FIAP EV Challenge 2026*
