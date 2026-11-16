# Dashboard UniFi — contexto do projeto

## O que é
SaaS de relatórios para MSPs que usam UniFi. Primeiro produto: relatório mensal de saúde da rede por cliente do MSP, em PDF com a marca do MSP, estruturado na tríade DPS (Disponibilidade, Produtividade, Segurança).

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

## Regras obrigatórias do código
- Só requisições GET, com lista fixa de caminhos permitidos.
- Chave da API no arquivo .env. Nunca no código, nunca no Git. .env listado no .gitignore.
- Nunca imprimir a chave em log ou mensagem de erro.
- Não guardar e-mail, coordenadas ou dados de usuários vindos de /v1/hosts (LGPD).
- Respeitar Retry-After; falha em uma coleta não derruba as outras; console offline é registrado como indisponível.

## Ordem de construção (fase 1)
1. Ambiente: pasta, ambiente virtual Python, Git, .env, .gitignore.  ← próximo passo
2. Coletor de WAN (isp-metrics) gravando no banco.
3. Coletor de consoles (hosts).
4. Coletor de equipamentos (connector) com controle de ritmo.
5. Motor de achados (regras com severidade, evidência e recomendação).
6. Relatório PDF do lab.
7. Piloto com um MSP.

## Estrutura de pastas proposta
```
unifi-relatorios/
  CLAUDE.md
  .env              (não vai para o Git)
  .gitignore
  requirements.txt
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
