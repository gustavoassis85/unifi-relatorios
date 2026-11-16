# Dashboard UniFi — contexto do projeto

## O que é
SaaS de relatórios para MSPs que usam UniFi. Primeiro produto: relatório mensal de saúde da rede por cliente do MSP, em PDF com a marca do MSP. Os pontos de atenção são separados pela área afetada (Internet, Console, Equipamentos, Wi-Fi, Conta), sem notas nem metodologia própria (decisão de 15/11/2026: a análise DPS saiu do produto).

## Como trabalhar com o Gustavo
- Ele não é desenvolvedor. Guiar passo a passo, um passo por vez, com comandos prontos para PowerShell (Windows).
- Explicar o que cada comando faz em uma linha.
- Respostas curtas, sem negrito.

## Decisões (15/11/2026)
- Construção: Gustavo com IA. Um dev revisa a segurança antes do primeiro cliente pagante.
- MVP sem portal web: coletor + banco + PDF por e-mail. Cadastro de MSP feito à mão.
- Acesso só pela nuvem (api.ui.com) com a chave Site Manager do MSP. Sem agente, sem VPN. Validado em 15/11/2026.
- Linguagem: Python.
- Banco: SQLite local no desenvolvimento (zero instalação); Postgres gerenciado em produção. Escrever o acesso ao banco de forma que a troca seja simples.
- PDF: modelo HTML → PDF. Ferramenta a definir no passo 6 (WeasyPrint exige dependências extras no Windows; Playwright é mais simples de instalar).

## APIs validadas
Base: https://api.ui.com — header X-API-Key — certificado válido (não usar verify=False).

Site Manager:
- GET /v1/hosts — todos os consoles da conta, inclusive antigos/desconectados (filtrar).
  Campos usados: id (hostId), reportedState.name, reportedState.hardware.name, reportedState.state (connected/disconnected), reportedState.version, reportedState.firmwareUpdate.latestAvailableVersion, latestBackupTime, reportedState.wans[], reportedState.internetIssues5min.periods[] (index × 300 = timestamp Unix).
- GET /v1/isp-metrics/1h?duration=7d (ou 30d). Também existe 5m (duration=24h).
  Resposta: data[].hostId, data[].siteId, data[].periods[].metricTime, data[].periods[].data.wan.{avgLatency, maxLatency, packetLoss, uptime, downtime, download_kbps, upload_kbps, ispName, ispAsn}.
  Retenção: 1h por pelo menos 30 dias; 5m por pelo menos 24h. download_kbps/upload_kbps = velocidade do plano, não tráfego.
  Atenção: podem faltar horas (no lab, 26–27/10 teve 17 horas sem dado) e o campo uptime fica em 100 nas horas que chegam.
  Hora ausente deve ser tratada como possível indisponibilidade, nunca ignorada.
- /v1/hosts pagina com pageSize e nextToken (o coletor segue as páginas).

Connector (API Network de cada console, via nuvem):
- GET /v1/connector/consoles/{hostId}/network/integration/v1/<caminho>
  - sites → id (UUID), internalReference, name
  - sites/{siteId}/devices → id, name, model, macAddress, ipAddress, state, firmwareVersion, firmwareUpdatable
  - sites/{siteId}/devices/{deviceId} → interfaces.ports[] (idx, state, speedMbps, maxSpeedMbps, poe), interfaces.radios[] (wlanStandard, frequencyGHz, channelWidthMHz, channel), provisionedAt
  - sites/{siteId}/devices/{deviceId}/statistics/latest → uptimeSec, cpuUtilizationPct, memoryUtilizationPct, loadAverage1Min/5Min/15Min, uplink.txRateBps/rxRateBps, interfaces.radios[].txRetriesPct
  - sites/{siteId}/clients → type (WIRED/WIRELESS), name, ipAddress, macAddress, connectedAt, uplinkDeviceId
  - sites/{siteId}/wans → id, name
- Paginação: offset, limit (padrão 25), count, totalCount.
- Limites: 100 req/min por console (erro 429 com Retry-After), timeout de 25 s, resposta até 10 MB.
- IDs: o siteId da Site Manager (hex) é diferente do siteId da Network (UUID). Ligação pelo hostId.
- Dados por cliente e consumo: não existem na API oficial (nem na v11.0.97). Vêm das APIs internas do Network, que a chave da nuvem acessa pelo connector (validado em 15/11/2026):
  - GET {connector}/network/v2/api/site/{site}/clients/active → nome, type (WIRELESS/WIRED), oui (fabricante), model_name (tipo), fingerprint.os_name (código do SO), essid, signal, wifi_experience_score, wifi_tx_retries_percentage, sw_port, wired_rate_mbps, tx_bytes/rx_bytes desde a conexão.
  - GET {connector}/network/v2/api/site/{site}/traffic?start=ms&end=ms&includeUnidentified=true → total_usage_by_app (application, category, bytes_received = download, bytes_transmitted = upload, client_count) e client_usage_by_app (não usamos: LGPD). application 65535 / category 255 = não identificado.
  - GET {connector}/network/v2/api/fingerprint_devices/0 → os_name_ids, vendor_ids, family_ids, dev_type_ids (tradução).
  - POST {connector}/network/api/s/{site}/stat/report/daily.site e daily.user (consulta de leitura) → wan-rx_bytes = download e wan-tx_bytes = upload do site por dia; por cliente, tx_bytes = download e rx_bytes = upload (validado com a tela do UniFi).
  - POST {connector}/network/api/s/{site}/stat/report/hourly.site → consumo por hora (horário de pico). Se falhar, o coletor segue sem ele.
  - Não identificado por família de dispositivo: somado a partir de client_usage_by_app sem guardar quem é quem (tabela naoident_familia_dia).
  - O antigo stat/sitedpi volta vazio (aposentado).
  - Catálogo de DPI pela API oficial: /network/integration/v1/dpi/categories (35) e /dpi/applications (2.112), em inglês.
  - Tráfego por cliente inclui rede local + internet; consumo de internet de verdade só no total do site.
  - São rotas não documentadas: podem mudar numa atualização. O relatório tem que sair mesmo se elas falharem.

## Regras obrigatórias do código
- Só leitura. GET apenas nos caminhos de coletor/api.py (GET_PERMITIDOS). POST apenas nos relatórios daily.site e daily.user (POST_PERMITIDOS), que são consultas.
- LGPD: aplicativos só no total da rede; não coletamos nem mostramos uso de aplicativo por pessoa/dispositivo.
- Connector: no máximo ~85 chamadas/min por console (classe Ritmo em coletor/equipamentos.py).
- Detalhe de portas/rádios em toda coleta: uma foto só engana (PC em repouso negocia 10/100 Mbps). Regra de "porta abaixo da capacidade" só vira achado se persistir em várias amostras.
- Chave da API no arquivo .env. Nunca no código, nunca no Git. .env listado no .gitignore.
- Nunca imprimir a chave em log ou mensagem de erro.
- A chave nunca é colada no chat. Para conferir o .env sem expor a chave:
  python -c "from dotenv import dotenv_values; print({n: len(v or '') for n, v in dotenv_values('.env').items()})"
- Não guardar e-mail, coordenadas ou dados de usuários vindos de /v1/hosts (LGPD).
- Respeitar Retry-After; falha em uma coleta não derruba as outras; console offline é registrado como indisponível.

## Ordem de construção (fase 1)
1. Ambiente: pasta, ambiente virtual Python, Git, .env, .gitignore.  (feito)
2. Coletor de WAN (isp-metrics) gravando no banco.  (feito)
3. Coletor de consoles (hosts).  (feito)
4. Coletor de equipamentos (connector) com controle de ritmo.  (feito)
   4b. Agendamento: coletar.py de hora em hora pelo Agendador de Tarefas do Windows (log em dados/coleta.log).  (feito)
   4c. Clientes (de hora em hora), consumo diário e aplicativos (a cada 6h, 30 dias na primeira vez) e catálogos (1x por semana): coletor/clientes.py, coletor/consumo.py, coletor/catalogos.py. Controle de frequência na tabela controle_coleta.  (feito)
5. Motor de achados (regras com severidade, evidência e recomendação).  (feito)
   achados/regras.py: limites ajustáveis em LIMITES; cada achado tem área, severidade (alta, média, baixa, informativo), evidência e recomendação.
6. Relatório PDF do lab.  ← em andamento
   gerar_relatorio.py gera HTML por console em dados/relatorios/ (marca do MSP em relatorio/marca.json); PDF por Ctrl+P no navegador. PDF automático (Playwright) fica para depois.
   Visual: linguagem do Site Manager da UniFi, para quem já usa a plataforma (tema escuro padrão, claro opcional em marca.json "tema"). Tokens de cor no CSS de relatorio/gerar.py. Regras de UI: 60-30-10 (azul UniFi só em ação/link), bordas finas antes de sombra, no máximo 3 pesos de fonte (400/500/600), nada abaixo de 12px, espaçamento em múltiplos de 4/8px, sem gradientes, pílulas ou decoração. Peça principal: faixa de saúde do link por dia (estável/instável/crítico/poucos dados). Versão exibida = firmware que o Site Manager mostra (console_estado.firmware).
   Relatório executivo e reativo (decisão de 15/11/2026): sem "próximos passos" nem recomendações no relatório; pontos de atenção mostram só a evidência. Seções: linha do console, resumo, saúde do link, pontos de atenção, perda/latência, consumo da internet, horário de pico, aplicativos (com nota sobre não identificado), conexões por rede (SSID), clientes, equipamentos UniFi. Sem logotipos de aplicativos (marcas de terceiros): ícones genéricos por categoria em relatorio/icones.py.
   python coletar.py --forcar refaz consumo e catálogos na hora, buscando 30 dias.
   Pendências conhecidas: juntar achados relacionados num incidente (ex.: horas sem dado + perda alta no mesmo dia); registros antigos (network-server) vão para uma seção de higiene da conta, não para relatório de cliente.
7. Piloto com um MSP.

## Estrutura de pastas
```
unifi-relatorios/
  CLAUDE.md
  .env              (não vai para o Git)
  .gitignore
  requirements.txt
  coletar.py        (roda todas as coletas; uma falha não derruba as outras)
  resumo_wan.py     (resumo diário do link, com horas sem dado)
  resumo_consoles.py (situação atual de cada console)
  resumo_equipamentos.py (saúde, portas, Wi-Fi e clientes de cada site)
  ver_achados.py    (pontos de atenção do período por console; --dias N)
  gerar_relatorio.py (relatório HTML por console; --dias N, --mes AAAA-MM, --console nome)
  teste_conexao.py  (teste rápido da chave)
  coletor/          (cliente HTTP da api.ui.com e um módulo por coleta)
  banco/            (modelo e acesso ao banco)
  achados/          (regras)
  relatorio/        (modelos HTML e geração do PDF)
  dados/            (arquivo SQLite local, fora do Git)
```

## Lab de testes
- Console: UDR (Dream Router), Network 10.5.67, link V.tal.
- hostId: AC8BA9590D19000000000709CC8000000000075E7C0E00000000638880EA:1907547615
- Site "Default": siteId Network 88f7af54-98f8-306a-a1c7-c9349722b1f6; siteId Site Manager 6552cabbf0c08c7cf2ca70f2.

Detalhes completos nos docs do projeto Dashboard Unifi: "arquitetura-mvp" e "api-unifi-network-mapa".
