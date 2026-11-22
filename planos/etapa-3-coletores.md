# Etapa 3 — Coletores em segundo plano

## Objetivo
O sistema passa a coletar sozinho, de hora em hora, os dados de todos os consoles acompanhados de todos os clientes de todas as organizações, como o MVP faz hoje para o lab. Ao final:
- Um processo "trabalhador" roda junto com o site e faz as coletas sem ninguém clicar.
- Os dados ficam no PostgreSQL, por organização e por cliente, sob RLS.
- A página do cliente mostra a última coleta de cada console (quando, se deu certo, o que falhou) e tem o botão "Coletar agora".
- Os números coletados batem com os do MVP para o lab.

Fora desta etapa: relatório e PDF (etapa 4), agendamentos e SMTP (etapa 5), servidor de produção (etapa 6).

## Como conduzir
1. O Gustavo aprova este plano antes de qualquer código.
2. Partes pequenas; cada parte termina com os testes rodando e um commit.
3. Branch etapa-3-coletores. No fim, merge na main e push.
4. O MVP não é alterado. A lógica dos coletores do MVP é copiada para o sistema e adaptada (chave por cliente, banco PostgreSQL, organização e cliente em cada linha).

## Decisões propostas (para o Gustavo confirmar)
1. Fila de tarefas no próprio PostgreSQL, sem instalar nada novo (sem Redis, sem Celery). Uma tabela de tarefas e um comando `manage.py trabalhador` que pega as tarefas e executa. O mesmo trabalhador serve depois para gerar PDFs (etapa 4) e enviar e-mails (etapa 5). Motivo: no volume esperado (dezenas de MSPs, coletas de hora em hora) o PostgreSQL dá conta, e é um programa a menos para instalar, proteger e monitorar.
2. Frequências iguais às do MVP: consoles, WAN, equipamentos e clientes conectados de hora em hora; consumo e aplicativos a cada 6 horas (30 dias na primeira vez); catálogos uma vez por semana.
3. Retenção (LGPD, coleta mínima): amostras de hora em hora (equipamentos, portas, rádios, clientes conectados) por 90 dias; dados por hora e por dia (WAN, consumo, aplicativos) por 13 meses, para permitir comparar com o mesmo mês do ano anterior. Uma tarefa diária apaga o que passou do prazo.
4. Convivência com o MVP: enquanto os dois rodam, o sistema coleta no minuto 30 de cada hora e o MVP continua no horário dele no Agendador de Tarefas (conferir que não é no minuto 30), para não somar chamadas no mesmo console ao mesmo tempo (limite de 100 por minuto por console). Quando a etapa 4 trouxer o relatório para o sistema, a coleta do MVP é desligada.
5. Catálogos (nomes de aplicativos e de sistemas operacionais) são dados da UniFi, iguais para todos: ficam numa tabela da plataforma, sem organização.

## Requisitos

### Fila e trabalhador
- Tabela de tarefas com tipo, organização, cliente, situação (na fila, rodando, feita, falhou), tentativas, horários e mensagem de erro. Não guarda chave nem dado coletado.
- O trabalhador pega uma tarefa por vez com `select ... for update skip locked` (dá para rodar mais de um trabalhador sem pegar a mesma tarefa).
- Cada tarefa roda dentro de `contexto(organizacao_id=...)`: a RLS vale no trabalhador como vale no site. O trabalhador conecta com o usuário da aplicação (unifi_app), nunca com o dono.
- Agendador dentro do trabalhador: a cada hora, no minuto 30, cria uma tarefa de coleta para cada cliente com chave e pelo menos um console acompanhado. Não cria outra se a do mesmo cliente ainda estiver na fila ou rodando.
- Tarefa travada (trabalhador caiu no meio) volta para a fila depois de 30 minutos. Falha de rede ou 429 tenta de novo até 3 vezes, com espera crescente. Chave recusada (401) não tenta de novo e aparece na página do cliente.
- Tarefas feitas há mais de 30 dias são apagadas.
- Parar com Ctrl+C termina a tarefa atual antes de sair.

### Coletas (portadas do MVP)
- Uma coleta por cliente: busca a chave no cofre, abre um ClienteUniFi e roda as coletas na ordem do MVP (consoles, WAN, equipamentos, clientes conectados, consumo, catálogos).
- Só consoles com "acompanhar" ligado. A coleta de consoles também atualiza a situação na tabela de consoles da etapa 2.
- Uma falha numa coleta (ou num console) não derruba as outras. Console offline é registrado como indisponível.
- Ritmo de no máximo ~85 chamadas por minuto por console no connector (classe Ritmo do MVP).
- Todas as regras de "Coleta" do CLAUDE.md continuam valendo: só leitura pela lista de caminhos de unifi/api.py, LGPD (aplicativos só no total da rede; nada de e-mail, localização ou usuários do /v1/hosts; não identificado por família somado sem guardar quem é quem), hora sem dado nunca vira 100% de disponibilidade.
- Gravação idempotente: rodar a mesma coleta duas vezes não duplica linhas (restrições únicas e atualização da linha existente).

### Tabelas de dados
- As mesmas tabelas do banco do MVP (banco/banco.py), no PostgreSQL, cada uma com organização, cliente e console: WAN por hora, situação do console, sites, amostras de equipamentos, rádios e portas, detalhe de equipamentos, clientes conectados, consumo por dia e por hora, aplicativos por dia, não identificado por família, controle de frequência.
- Todas sob RLS com FORCE e com a chave estrangeira composta organização + cliente.
- Registro de execução por cliente (início, fim, resultado de cada coleta, mensagens), mostrado na página do cliente.

### Telas
- Página do cliente: por console, data da última coleta que deu certo e a situação; bloco "Última coleta" com o resultado de cada parte (ok ou o erro em português).
- Botão "Coletar agora" (admin e operador): enfileira uma coleta do cliente. No máximo uma por cliente a cada 10 minutos.
- Nesta etapa não há telas com os dados coletados (gráficos e relatório são da etapa 4). Para conferir, um comando `manage.py resumo_cliente <id>` mostra no terminal os números principais, no formato dos resumos do MVP.

### Auditoria
- "Coletar agora" registra quem pediu. As coletas automáticas não geram evento de auditoria (ficam no registro de execução).

## Testes obrigatórios
Com pytest, no PostgreSQL, com a UniFi simulada:
- Isolamento: tarefa da organização A só lê e grava dados da A; nas tabelas novas, consulta direta com a organização A não devolve linhas da B; sem organização, zero linhas; o banco recusa linha com cliente de outra organização.
- Trabalhador: pega a tarefa, roda no contexto certo, marca feita ou falhou; dois trabalhadores não pegam a mesma tarefa; tarefa travada volta para a fila; 401 não tenta de novo; falha de rede tenta de novo.
- Agendador: cria uma tarefa por cliente elegível, nenhuma para cliente sem chave ou sem console acompanhado, nenhuma duplicada.
- Cada coleta, com respostas simuladas tiradas do lab: grava o esperado, é idempotente, não guarda dados pessoais, uma falha não derruba as outras, console não acompanhado não é chamado.
- Hora ausente na WAN não vira disponibilidade de 100%.
- Retenção apaga só o que passou do prazo.
- "Coletar agora": papéis, limite de 10 minutos, 404 para cliente de outra organização.

## Partes
1. Fila, trabalhador e agendador (com uma tarefa de teste), e registro de execução.
2. Tabelas de dados com RLS, e coletas de consoles e WAN.
3. Coleta de equipamentos (sites, amostras, portas, rádios) com o Ritmo.
4. Coletas de clientes conectados, consumo, aplicativos e catálogos.
5. Página do cliente (última coleta, "Coletar agora"), retenção e o comando resumo_cliente.
6. Revisão de segurança, README (como rodar o trabalhador no Windows), validação do Gustavo comparando o resumo do sistema com o do MVP para o lab, merge e push, CLAUDE.md marcando a etapa 3 feita e a 4 como próxima.

## Pronto quando
- Todos os testes passam.
- Com o site e o trabalhador rodando, o cliente do lab é coletado sozinho no minuto 30, e o resumo_cliente mostra os mesmos números do MVP (WAN, equipamentos, clientes, consumo) para o mesmo período.
- A branch foi para a main e para o GitHub, e o CLAUDE.md está atualizado.
