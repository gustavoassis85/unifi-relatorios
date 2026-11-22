# Visual 1: identidade do painel (antes da etapa 6)

## Objetivo
Trocar o visual provisório da etapa 1 por uma identidade única em todas as telas, sem mudar o que cada tela faz. Pedido do Gustavo (22/11/2026):
- Visual geral: cores, tipografia, espaçamento, menu, tabelas, botões e formulários.
- Tema claro e escuro, seguindo a preferência do sistema operacional de quem usa.
- Estrutura parecida com a do Site Manager da UniFi, para ser familiar a quem já usa: faixa de ícones na lateral, painel com a lista de clientes ao lado e a área principal com um quadro por cliente. Sem copiar a UniFi: nada de logo, ícones, nomes de tela ou cores dela.

Fora daqui: o relatório do cliente (tem modelo e temas próprios), reorganizar a página do cliente em abas.

## Para quem e para quê
Técnicos e admins de MSP que cuidam de várias redes UniFi de pequenos clientes e já conhecem o Site Manager. Abrem o painel para saber, em segundos, se cada cliente está sendo coletado, se a conexão funciona e se o relatório saiu, e para agir quando algo falhou.

## Decisões propostas (para o Gustavo confirmar)

1. Três colunas, como no Site Manager:
   - Faixa de ícones (56 px) na extrema esquerda: Clientes, Usuários, Marca e E-mail, conforme o papel; embaixo, Segurança da conta e Sair. Cada ícone tem nome ao passar o mouse e para leitor de tela; o da tela atual fica marcado. Ícones de traço simples de um conjunto de licença livre (Lucide, ISC), guardados no próprio sistema.
   - Barra fina no topo: nome do sistema à esquerda, título da tela no centro, nome da organização à direita.
   - Painel lateral (260 px) com a lista de clientes, em todas as telas de cliente: campo "Buscar cliente", filtro de situação (todos, com problema, sem coleta) e um item por cliente com o ponto de situação. O cliente aberto fica marcado. Um botão recolhe o painel (a escolha fica guardada no navegador).

2. Tela de clientes: um quadro por cliente, em grade, com botão para trocar para lista (tabela), como no Site Manager. Cada quadro:
   - nome do cliente e, embaixo, ponto de situação com o resumo ("2 consoles acompanhados" ou "Sem chave da UniFi");
   - faixa das coletas das últimas 24 h: 24 marcas, uma por hora, na cor do resultado (ok, parte falhou, falhou, sem coleta), com a régua "há 24 h, há 12 h, agora" embaixo e o texto "23 de 24 ok". A cor nunca é a única informação (texto e descrição para leitor de tela);
   - rodapé com o último relatório (data e envio) e o próximo agendamento.
   O quadro inteiro leva à página do cliente. Tudo calculado em poucas consultas (sem uma consulta por cliente).

3. Cores. Uma cor de ação (petróleo, para não usar o azul da UniFi) e três cores de estado, separadas da cor de ação para "ok" não parecer botão. Sem gradiente; quadros com borda fina e fundo um tom acima da página, sem sombra.

   | Papel            | Claro     | Escuro    |
   |------------------|-----------|-----------|
   | Fundo da página  | #F4F6F5   | #111716   |
   | Superfície       | #FFFFFF   | #182120   |
   | Texto            | #16201E   | #E4EAE8   |
   | Texto suave      | #56625F   | #9AA8A4   |
   | Borda            | #D6DDDA   | #2A3532   |
   | Ação (petróleo)  | #0A6870   | #5BB8B4   |
   | Ok               | #1F7A4D   | #4CC38A   |
   | Atenção          | #9A5B00   | #E2A63F   |
   | Falha            | #B42318   | #F2756A   |
   | Sem coleta       | #C9D1CE   | #33403C   |

   Contraste de texto e de estado conferido (mínimo 4,5:1 para texto). O tema segue o sistema operacional.

4. Tipografia: Atkinson Hyperlegible Next (licença livre OFL), hospedada junto com o sistema (a CSP só aceita fontes do próprio site). Desenhada para distinguir 0 e O, 1, l e I, o que importa num painel de nomes de console e horários. Pesos 400 e 600, números tabulares. Escala: 14 px de texto (densidade de painel), 12 px para notas e régua, 16 px para títulos de quadro e seção, 20 px para o título da página.

5. Layout:
```
Desktop
+----+---------------------------------------------------------------+
|    | Dashboard UniFi            Clientes                    MSP Lab |
+----+--------------+------------------------------------------------+
| ▦  | Buscar…      |  Clientes                     [▦][≣] [Cadastrar]|
| 👤 | Situação  v  | +----------------+ +----------------+          |
| ✎  | ● Lab        | | Lab            | | Padaria        |          |
| ✉  | ● Padaria    | | ● 2 consoles   | | ● Sem chave    |          |
|    | ○ Escola     | | ▮▮▮▮▮▮▮▮▮▮▮▮▮▮ | | ▯▯▯▯▯▯▯▯▯▯▯▯▯▯ |          |
|    |              | | há 24h  12h agora| …                         |
| ⚙  |              | | 23 de 24 ok    | |                |          |
| ⎋  |       [«]    | | Rel. 01/12 env.| |                |          |
+----+--------------+------------------------------------------------+
Celular: faixa de ícones vira barra no rodapé; o painel de clientes abre
pelo botão "Clientes"; quadros em uma coluna.
```
   Página do cliente: o painel lateral continua (troca rápida entre clientes); a área principal mostra o cabeçalho do cliente e as seções atuais (conexão, coletas, relatórios, agendamentos, higiene, consoles), cada uma num quadro.
   Formulários com largura máxima de 640 px. Espaçamento em múltiplos de 4 px.

6. Componentes únicos para todas as telas: botão principal (preenchido, cor de ação), secundário (contorno), perigo (só nas confirmações de apagar), botão de ícone com nome ao passar o mouse; campos com rótulo visível em cima e ajuda embaixo; mensagens de sucesso e erro com faixa lateral na cor do estado; foco do teclado sempre visível. Botões dizem o que fazem.

7. Movimento: nenhuma animação decorativa. Só o que a pessoa causou (recolher o painel, abrir o menu no celular). Quem pede movimento reduzido não vê nem isso.

## Como conduzir
1. O Gustavo aprova este plano antes de qualquer código.
2. Branch visual-1. Partes: (1) base: fonte, ícones, cores, temas, componentes; (2) estrutura de três colunas e painel de clientes com busca e filtro; (3) tela de clientes em quadros e lista; (4) passada em todas as telas (página do cliente, formulários, usuários, login e MFA). Commit e testes a cada parte.
3. Conferência por imagem: o Playwright que já gera o PDF tira capturas das telas em claro, escuro e celular para eu revisar antes de mostrar.
4. Nenhuma mudança em permissão, isolamento ou regra: os testes atuais continuam passando; painel e quadros ganham testes de isolamento (MSP A não vê cliente nem situação do MSP B).
