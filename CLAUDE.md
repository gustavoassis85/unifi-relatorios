# Dashboard UniFi — contexto do projeto

## O que é
SaaS de relatórios para MSPs que usam UniFi. Produto: relatório de saúde da rede por cliente do MSP, em PDF com a marca do MSP. Os pontos de atenção são separados pela área afetada (Internet, Console, Equipamentos, Wi-Fi, Conta), sem notas nem metodologia própria (decisão de 15/11/2026: a análise DPS saiu do produto).

Duas fases:
- Fase 1, MVP do lab (concluída): scripts Python na raiz do projeto que coletam, geram os pontos de atenção e montam o relatório HTML de um ambiente.
- Fase 2, sistema (em construção, etapas 1 a 4 concluídas): aplicação web multi-tenant em sistema/, que reaproveita os coletores, as regras e o relatório do MVP.

## Como trabalhar com o Gustavo
- Ele não é desenvolvedor. Guiar passo a passo, um passo por vez.
- Ambiente: Windows, PowerShell, VS Code com o Claude Code.
- Antes de rodar um comando, explicar em uma linha o que ele faz.
- Pedir aprovação antes de instalar programas no Windows ou mudar algo fora da pasta do projeto.
- Em etapas grandes, apresentar o plano antes de escrever código.
- Ao fim de cada etapa que funcionar: rodar os testes e fazer o commit.
- Respostas curtas, sem negrito.

## Decisões
MVP (15/11/2026):
- Construção: Gustavo com IA. Um dev revisa a segurança antes do primeiro cliente pagante.
- Acesso só pela nuvem (api.ui.com) com a chave Site Manager do MSP. Sem agente, sem VPN. Validado em 15/11/2026.
- Linguagem: Python. Banco do MVP: SQLite local (dados/).

Sistema (15/11/2026):
- Aplicação web multi-tenant, no modelo do multi-site da UniFi: Organização (MSP) → Clientes → Consoles/Sites. Um MSP nunca enxerga outro.
- Hospedagem: SaaS na nuvem, hospedado pelo Gustavo para todos os MSPs.
- Acesso: só o MSP tem login. O cliente final recebe o relatório por e-mail ou PDF, sem login. Papéis dentro da organização: admin, operador, leitura. (Acesso de leitura para o cliente final previsto no futuro: ver 21/11/2026.)
- O dono da plataforma cria as organizações e o primeiro admin de cada uma, mas não vê os dados dos clientes dos MSPs pela aplicação.
- Stack: Python + Django 5.2 LTS + HTMX + PostgreSQL. Processo em segundo plano para coletas, relatórios e agendamentos. PDF no servidor com Playwright (Chromium sem tela).
- Conexão com a UniFi: pela nuvem (chave unifi.ui.com) primeiro; IP direto depois, e vai exigir VPN entre o servidor e a rede do cliente.
- Funcionalidades: clientes e conexões (com "Testar conexão"), relatórios sob demanda com histórico, agendamentos (frequência, dia, hora, destinatários), SMTP por organização com envio de teste. Sem SMTP, o agendamento só gera o PDF e deixa na tela.
- Um único modelo de relatório: o do MVP.
- Cobrança: a definir depois.
- Plano completo: Claude Doc "Plano do sistema Dashboard UniFi" (https://claude.ai/artifact/Cpr1bsN4jYhU9PMkyEvTx3).

Sistema (21/11/2026):
- A chave da UniFi é cadastrada por cliente, não por organização. Os consoles que a chave enxerga pertencem a esse cliente.
- Futuro: o MSP poderá liberar acesso só de leitura para o cliente ver os próprios dashboards (muda o "só o MSP tem login"). Por isso toda tabela com dado de cliente leva o ID do cliente, além do da organização.

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
- O connector aceita todos os métodos HTTP: a chave consegue alterar configuração. Só o nosso código garante a leitura.
- IDs: o siteId da Site Manager (hex) é diferente do siteId da Network (UUID). Ligação pelo hostId.
- Dados por cliente e consumo: não existem na API oficial (nem na v11.0.97). Vêm das APIs internas do Network, que a chave da nuvem acessa pelo connector (validado em 15/11/2026):
  - GET {connector}/network/v2/api/site/{site}/clients/active → nome, type (WIRELESS/WIRED), oui (fabricante), model_name (tipo), fingerprint.os_name (código do SO), essid, signal, wifi_experience_score, wifi_tx_retries_percentage, sw_port, wired_rate_mbps, tx_bytes/rx_bytes desde a conexão.
  - GET {connector}/network/v2/api/site/{site}/traffic?start=ms&end=ms&includeUnidentified=true → total_usage_by_app (application, category, bytes_received = download, bytes_transmitted = upload, client_count) e client_usage_by_app (não usamos: LGPD). application 65535 / category 255 = não identificado.
    O console só guarda o tráfego por aplicativo do dia corrente (desde a meia-noite): dias passados voltam vazios e "últimas 24h" = hoje (conferido em 21/11/2026). O sistema busca o dia de hoje em toda coleta de hora em hora.
  - GET {connector}/network/v2/api/fingerprint_devices/0 → os_name_ids, vendor_ids, family_ids, dev_type_ids (tradução).
  - POST {connector}/network/api/s/{site}/stat/report/daily.site e daily.user (consulta de leitura) → wan-rx_bytes = download e wan-tx_bytes = upload do site por dia; por cliente, tx_bytes = download e rx_bytes = upload (validado com a tela do UniFi).
  - POST {connector}/network/api/s/{site}/stat/report/hourly.site → consumo por hora (horário de pico). Se falhar, o coletor segue sem ele.
  - Não identificado por família de dispositivo: somado a partir de client_usage_by_app sem guardar quem é quem (tabela naoident_familia_dia).
  - O antigo stat/sitedpi volta vazio (aposentado).
  - Catálogo de DPI pela API oficial: /network/integration/v1/dpi/categories (35) e /dpi/applications (2.112), em inglês.
  - Tráfego por cliente inclui rede local + internet; consumo de internet de verdade só no total do site.
  - São rotas não documentadas: podem mudar numa atualização. O relatório tem que sair mesmo se elas falharem.

## Regras obrigatórias do código
Coleta (MVP e sistema):
- Só leitura. GET apenas nos caminhos de coletor/api.py e, no sistema, de sistema/unifi/api.py (GET_PERMITIDOS). POST apenas nos relatórios daily.site, daily.user e hourly.site (POST_PERMITIDOS), que são consultas.
- LGPD: aplicativos só no total da rede; não coletamos nem mostramos uso de aplicativo por pessoa/dispositivo.
- Connector: no máximo ~85 chamadas/min por console (classe Ritmo em coletor/equipamentos.py).
- Detalhe de portas/rádios em toda coleta: uma foto só engana (PC em repouso negocia 10/100 Mbps). Regra de "porta abaixo da capacidade" só vira achado se persistir em várias amostras.
- Não guardar e-mail, coordenadas ou dados de usuários vindos de /v1/hosts (LGPD).
- Respeitar Retry-After; falha em uma coleta não derruba as outras; console offline é registrado como indisponível.

Segredos:
- Chaves e senhas no arquivo .env no desenvolvimento. Nunca no código, nunca no Git. .env listado no .gitignore; .env.example (sem valores) vai para o Git.
- Nunca imprimir chave ou senha em log ou mensagem de erro.
- A chave nunca é colada no chat. Para conferir o .env sem expor valores:
  python -c "from dotenv import dotenv_values; print({n: len(v or '') for n, v in dotenv_values('.env').items()})"
- No sistema: chaves da UniFi e senhas de SMTP criptografadas no banco, com a chave mestra em variável de ambiente. Depois de salvas, só aparecem os últimos 4 caracteres.

Isolamento entre MSPs (sistema):
- Toda tabela com dado de MSP tem o ID da organização, e todo acesso passa por uma camada única que filtra por ela.
- Segunda trava no banco: Row-Level Security do PostgreSQL com FORCE ROW LEVEL SECURITY. A aplicação conecta com um usuário do banco que não é dono das tabelas, não é superusuário e não tem BYPASSRLS. Migrações rodam com outro usuário.
- Sem organização definida na conexão, as tabelas de MSP não devolvem nenhuma linha.
- Testes de isolamento obrigatórios, sempre no PostgreSQL (nunca SQLite): usuário do MSP A tentando ver, editar ou apagar dado do MSP B pela tela e direto no banco. Nenhuma mudança entra se esses testes falharem.
- O admin do Django só gerencia organizações e usuários. Dados dos clientes dos MSPs ficam fora do admin.

Segurança da aplicação (sistema):
- MFA obrigatório para admins, bloqueio após tentativas de login, cookies seguros, CSRF, cabeçalhos de segurança (CSP, HSTS em produção).
- DEBUG e SECRET_KEY vêm do ambiente; DEBUG desligado por padrão.
- Log de auditoria: quem cadastrou, gerou, enviou ou apagou o quê.
- LGPD: coleta mínima, retenção definida e exclusão de todos os dados de um MSP quando ele sair.
- IP direto (quando chegar): nunca desligar a verificação de certificado; gravar a impressão digital do certificado do console e recusar a conexão se ela mudar.

Git:
- main sempre funcionando; uma branch por etapa ou funcionalidade; tag a cada versão que for para produção.
- .env e dados/ nunca vão para o Git.

## Ordem de construção
Fase 1, MVP do lab (concluída):
1. Ambiente: pasta, ambiente virtual Python, Git, .env, .gitignore.
2. Coletor de WAN (isp-metrics) gravando no banco.
3. Coletor de consoles (hosts).
4. Coletor de equipamentos (connector) com controle de ritmo.
   4b. Agendamento: coletar.py de hora em hora pelo Agendador de Tarefas do Windows (log em dados/coleta.log).
   4c. Clientes (de hora em hora), consumo diário e aplicativos (a cada 6h, 30 dias na primeira vez) e catálogos (1x por semana): coletor/clientes.py, coletor/consumo.py, coletor/catalogos.py. Controle de frequência na tabela controle_coleta.
5. Motor de achados: achados/regras.py, limites ajustáveis em LIMITES; cada achado tem área, severidade (alta, média, baixa, informativo), evidência e recomendação.
6. Relatório do lab: gerar_relatorio.py gera HTML por console em dados/relatorios/ (marca do MSP em relatorio/marca.json); PDF por Ctrl+P no navegador.
   python coletar.py --forcar refaz consumo e catálogos na hora, buscando 30 dias.

Fase 2, sistema (em sistema/):
1. Fundação (concluída em 21/11/2026): projeto Django, PostgreSQL, login com MFA, organizações, papéis, isolamento com RLS, auditoria e testes de isolamento. Detalhe em planos/etapa-1-fundacao.md; como subir em sistema/README.md.
2. Clientes e conexões (concluída em 21/11/2026): chave da UniFi por cliente cifrada no cofre (cofre/, UNIFI_CHAVE_MESTRA), cliente da api.ui.com só leitura (unifi/api.py), "Testar conexão" e consoles por cliente com "acompanhar" (conexoes/). IP direto fica para depois da publicação. Detalhe em planos/etapa-2-clientes-conexoes.md.
3. Coletores (concluída em 21/11/2026): fila no PostgreSQL e `manage.py trabalhador` (tarefas/), coletas portadas do MVP em coletas/coletores/ (só consoles acompanhados; no minuto 30 de cada hora; o MVP roda no minuto 3), dados por organização/cliente/console sob RLS, retenção (90 dias amostras e tráfego por dispositivo, 13 meses agregados), "Coletar agora" e `manage.py resumo_cliente`. Detalhe em planos/etapa-3-coletores.md.
4. Relatórios sob demanda e PDF automático (concluída em 22/11/2026): app relatorios/ com marca por organização no banco, relatório por cliente e período lido das tabelas de coletas/models.py, incidentes e seção de higiene da conta, HTML+PDF guardados no banco por 13 meses, PDF pelo Playwright (Chromium em sistema/.navegadores, JS e rede desligados) gerado no trabalhador. A coleta do MVP ("UniFi Relatorios - Coleta") foi desativada, não apagada; o trabalhador sobe no logon pela tarefa "Dashboard UniFi - Trabalhador" (scripts/trabalhador_sem_janela.py, log em sistema/logs/trabalhador.log). Detalhe em planos/etapa-4-relatorios.md.
5. Agendamentos, SMTP e o fallback para PDF.  ← próxima
   Pendente da etapa 2: o "Testar conexão" segura a transação da requisição por até 30 s.
6. Publicação num servidor, com backup e monitoramento, e revisão de segurança por um dev antes do primeiro MSP pagante.

O código do MVP continua na raiz; a coleta agendada do lab foi desativada em 22/11/2026, já substituída pelo sistema. Não alterar o MVP sem pedido explícito.

## Relatório (vale para o MVP e para o sistema)
- Visual: linguagem do Site Manager da UniFi, para quem já usa a plataforma (tema escuro padrão, claro opcional em marca.json "tema"). Tokens de cor no CSS de relatorio/gerar.py.
- Regras de UI: 60-30-10 (azul UniFi só em ação/link), bordas finas antes de sombra, no máximo 3 pesos de fonte (400/500/600), nada abaixo de 12px, espaçamento em múltiplos de 4/8px, sem gradientes, pílulas ou decoração.
- Peça principal: faixa de saúde do link por dia (estável/instável/crítico/poucos dados). Versão exibida = firmware que o Site Manager mostra (console_estado.firmware).
- Executivo e reativo (decisão de 15/11/2026): sem "próximos passos" nem recomendações; pontos de atenção mostram só a evidência.
- Seções: linha do console, resumo, saúde do link, pontos de atenção, perda/latência, consumo da internet, horário de pico, aplicativos (com nota sobre não identificado), conexões por rede (SSID), clientes, equipamentos UniFi.
- Sem logotipos de aplicativos (marcas de terceiros): ícones genéricos por categoria em relatorio/icones.py.

## Estrutura de pastas
```
unifi-relatorios/
  CLAUDE.md
  .env              (não vai para o Git)
  .gitignore
  requirements.txt
  planos/           (detalhe de cada etapa do sistema)
  sistema/          (fase 2: projeto Django; apps contas, organizacoes, clientes, auditoria, cofre, unifi, conexoes, tarefas, coletas)

  MVP (fase 1):
  coletar.py        (roda todas as coletas; uma falha não derruba as outras)
  resumo_wan.py     (resumo diário do link, com horas sem dado)
  resumo_consoles.py (situação atual de cada console)
  resumo_equipamentos.py (saúde, portas, Wi-Fi e clientes de cada site)
  ver_achados.py    (pontos de atenção do período por console; --dias N)
  gerar_relatorio.py (relatório HTML por console; --dias N, --mes AAAA-MM, --console nome)
  teste_conexao.py  (teste rápido da chave)
  coletor/          (cliente HTTP da api.ui.com e um módulo por coleta)
  banco/            (modelo e acesso ao banco SQLite)
  achados/          (regras)
  relatorio/        (modelo HTML do relatório)
  dados/            (SQLite local e relatórios gerados, fora do Git)
```

## Lab de testes
- Console: UDR (Dream Router), Network 10.5.67, link V.tal.
- hostId: AC8BA9590D19000000000709CC8000000000075E7C0E00000000638880EA:1907547615
- Site "Default": siteId Network 88f7af54-98f8-306a-a1c7-c9349722b1f6; siteId Site Manager 6552cabbf0c08c7cf2ca70f2.

Detalhes completos nos docs do projeto Dashboard Unifi: "arquitetura-mvp" e "api-unifi-network-mapa".
