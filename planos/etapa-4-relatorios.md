# Etapa 4 — Relatórios e PDF

## Objetivo
O MSP gera, na página do cliente, o relatório de saúde da rede (o mesmo modelo do MVP, com a marca dele) e baixa o PDF. Ao final:
- Botão "Gerar relatório" com a escolha do período; o relatório fica pronto em segundo plano e entra no histórico do cliente.
- O relatório abre na tela e sai em PDF gerado no servidor, sem Ctrl+P.
- Cada organização configura a própria marca (nome, contato, logo, tema).
- Os pontos de atenção do MVP rodam sobre os dados do sistema, com as duas pendências do relatório resolvidas.
- A coleta do MVP no Agendador de Tarefas é desligada.

Fora desta etapa: agendamentos e envio por e-mail (etapa 5), servidor de produção (etapa 6).

## Como conduzir
1. O Gustavo aprova este plano antes de qualquer código e antes de instalar o Playwright.
2. Partes pequenas; cada parte termina com os testes rodando e um commit.
3. Branch etapa-4-relatorios. No fim, merge na main e push.
4. O MVP não é alterado. A lógica de achados/regras.py e relatorio/ é copiada para o sistema e passa a ler as tabelas do PostgreSQL (coletas/models.py) em vez do SQLite.

## Decisões propostas (para o Gustavo confirmar)
1. Um relatório por cliente. Se o cliente tem mais de um console acompanhado, cada console vira uma seção do mesmo PDF, no layout do MVP.
2. Períodos: últimos 7 dias, últimos 30 dias ou um mês fechado (escolhido numa lista). Padrão: mês anterior fechado.
3. Marca por organização, editada pelo admin: nome da empresa, contato, logo (PNG ou JPG, até 500 KB; SVG não, porque pode carregar código) e tema escuro ou claro. Guardada no banco, sob RLS.
4. O HTML e o PDF de cada relatório ficam guardados no banco, sob RLS (um MSP nunca baixa o relatório de outro), por 13 meses, como os dados agregados.
5. PDF com o Playwright (Chromium sem tela), instalado dentro da pasta do projeto (sistema/.navegadores, fora do Git, cerca de 150 MB). Na geração: JavaScript desligado, nenhum acesso à rede (só o próprio HTML e imagens embutidas) e tempo limite de 60 s.
6. O relatório é gerado pelo trabalhador; a página mostra "gerando" e se atualiza sozinha até ficar pronto.
7. Pendências do relatório (do CLAUDE.md):
   - Achados relacionados viram um incidente: na mesma área e no mesmo dia (por exemplo, horas sem dado e perda alta na Internet), aparecem como um só ponto de atenção com as evidências juntas.
   - Registros antigos da conta (network-server desconectado há tempos) saem do relatório do cliente e vão para uma seção "Higiene da conta", que só o MSP vê na tela.
8. Coleta do MVP: depois que o Gustavo comparar o relatório do sistema com o do MVP para o lab, a tarefa "UniFi Relatorios - Coleta" é desativada no Agendador de Tarefas (desativada, não apagada: dá para religar). No lugar, uma tarefa nova no Agendador liga o trabalhador do sistema quando o Windows inicia, para as coletas não pararem quando a janela fecha. São mudanças fora da pasta do projeto: peço confirmação na hora.

## Requisitos

### Marca da organização
- Tela "Marca" (só admin): nome da empresa, contato, tema, logo com prévia.
- O logo é conferido pelo conteúdo do arquivo (não só pela extensão), reduzido se for grande e guardado como imagem embutida no relatório.

### Pontos de atenção
- Todas as regras do MVP (WAN sem dado, perda, latência, console offline e disponibilidade, backup, atualização, equipamentos, portas, rádios, Wi-Fi dos clientes), com os mesmos limites (LIMITES).
- Hora ausente continua sendo possível indisponibilidade, nunca 100%.
- Regra de porta abaixo da capacidade só com várias amostras, como no MVP.
- Agrupamento em incidentes e separação da higiene da conta (decisão 7).

### Relatório
- Mesmo conteúdo e visual do MVP (seções, faixa de saúde do link, gráficos em SVG, ícones genéricos por categoria, regras de UI do CLAUDE.md), com a marca da organização.
- Nomes de aplicativos e categorias com coletas.catalogo.Nomes.
- O HTML do relatório é aberto na tela numa resposta própria, com CSP que permite só os estilos dele, sem nenhum script.

### Geração e histórico
- Tarefa "gerar_relatorio" no trabalhador: monta o HTML, gera o PDF e guarda os dois. Falha vira mensagem em português no histórico.
- Histórico na página do cliente: período, quem pediu, quando, situação (gerando, pronto, falhou), botões "Ver" e "Baixar PDF".
- Gerar: admin e operador. Ver e baixar: todos os papéis. Limite: um relatório gerando por cliente de cada vez.
- Auditoria: relatório pedido e PDF baixado.

## Testes obrigatórios
Com pytest, no PostgreSQL:
- Isolamento: MSP A não vê, não abre e não baixa relatório nem marca do MSP B (404); consulta direta com a organização A não devolve linhas do B; sem organização, zero linhas.
- Cada regra de ponto de atenção com dados montados no teste, incluindo hora ausente, porta com uma amostra só e incidente agrupado.
- Higiene da conta fora do relatório do cliente.
- Relatório com dois consoles; relatório sem dados no período (sai com aviso, não quebra).
- Logo: PNG e JPG aceitos; SVG, arquivo disfarçado e arquivo grande recusados.
- PDF: gerado de verdade num teste (com o Chromium instalado), com JavaScript desligado e sem acesso à rede (uma imagem externa no HTML não é baixada).
- Papéis: leitura vê e baixa, não gera; só admin edita a marca.
- Retenção apaga relatórios com mais de 13 meses.

## Partes
1. Marca da organização (modelo, tela, validação do logo).
2. Pontos de atenção portados, com incidentes e higiene da conta.
3. Relatório HTML portado (um por cliente, uma seção por console).
4. PDF com o Playwright (instalação aprovada pelo Gustavo) e a tarefa de geração.
5. Telas: gerar, histórico, ver, baixar; auditoria; retenção.
6. Revisão de segurança, README, validação do Gustavo (comparar com o relatório do MVP para o lab), desligar a coleta do MVP com confirmação, merge e push, CLAUDE.md marcando a etapa 4 feita e a 5 como próxima.

## Pronto quando
- Todos os testes passam.
- O Gustavo gera o relatório do lab no sistema, abre na tela, baixa o PDF e confere que bate com o do MVP para o mesmo período.
- A coleta do MVP está desativada e o trabalhador do sistema é a única coleta.
- A branch foi para a main e para o GitHub, e o CLAUDE.md está atualizado.
