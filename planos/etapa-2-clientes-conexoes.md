# Etapa 2 — Clientes e conexões

## Objetivo
Cada cliente do MSP tem a sua chave da UniFi. O MSP cadastra a chave no cliente, testa a conexão e escolhe quais consoles daquela conta entram no acompanhamento. Ao final:
- O admin da organização cadastra a chave Site Manager (unifi.ui.com) de um cliente. A chave fica criptografada no banco e, depois de salva, só aparecem os últimos 4 caracteres.
- O botão "Testar conexão" consulta a api.ui.com e mostra se a chave funciona e quantos consoles ela enxerga.
- Os consoles que a chave enxerga ficam ligados ao cliente dela. O MSP marca quais acompanhar.
- Tudo isolado por organização, com os mesmos testes de isolamento da etapa 1, e cada dado novo também marcado com o cliente, para o acesso do cliente no futuro.

Fora desta etapa: o login do cliente final (só a preparação, ver abaixo), coletas em segundo plano (etapa 3), relatórios (etapa 4), agendamentos e SMTP (etapa 5) e conexão por IP direto (depois da publicação, porque exige VPN entre o servidor e a rede do cliente).

## Como conduzir
1. O Gustavo aprova este plano antes de qualquer código.
2. Partes pequenas; cada parte termina com os testes rodando e um commit.
3. Branch etapa-2-clientes-conexoes. No fim, merge na main e push.
4. Não alterar o código do MVP (raiz do projeto). O sistema ganha o seu próprio cliente da api.ui.com, copiando as regras de coletor/api.py.

## Decisões (aprovadas pelo Gustavo em 21/11/2026)
1. A chave é cadastrada por cliente, não por organização. Cada cliente tem uma chave; os consoles que ela enxerga pertencem a esse cliente.
2. No futuro, o MSP poderá liberar um acesso só de leitura para o cliente ver os próprios dashboards. Por isso, toda tabela nova com dado de cliente leva também o ID do cliente, além do ID da organização.
3. Quem mexe em quê (dentro da organização):
   - Admin: cadastra, troca e apaga a chave de um cliente.
   - Admin e operador: testam a conexão e escolhem quais consoles acompanhar.
   - Leitura: só vê (nome da chave, 4 últimos caracteres, consoles).
4. "Testar conexão" roda na hora, com tempo limite de 30 s. Em segundo plano só a partir da etapa 3.
5. Conexão por IP direto fica para depois da publicação.

## Requisitos

### Cofre de credenciais
- Criptografia com Fernet (biblioteca cryptography, já instalada). A chave mestra vem da variável de ambiente UNIFI_CHAVE_MESTRA, gerada pelo scripts/gerar_env.py. Nunca no banco, nunca no Git.
- Suporte a troca da chave mestra (MultiFernet): aceita a chave nova e a antiga até recriptografar tudo, com um comando manage.py para isso.
- Na tabela: organização, cliente (uma chave por cliente), chave criptografada, últimos 4 caracteres, data do último teste e resultado.
- A chave nunca volta para a tela: o campo de edição fica vazio e só troca se o admin digitar uma nova.
- Nunca aparece em log, mensagem de erro, auditoria, página de erro do Django ou resposta HTML. Testes verificam isso.
- Sem a UNIFI_CHAVE_MESTRA o sistema não sobe (erro claro na inicialização).

### Cliente da api.ui.com no sistema
- Novo app sistema/unifi/, com a mesma lista de caminhos permitidos do MVP (GET_PERMITIDOS e POST_PERMITIDOS), certificado sempre verificado, Retry-After respeitado e mensagens de erro em português sem a chave.
- Recebe a chave como parâmetro (não lê do .env), porque cada cliente tem a sua.
- Nesta etapa só usa GET /v1/hosts (com paginação).
- Biblioteca nova: requests (a mesma do MVP), com versão fixada.

### Testar conexão
- Fica na tela do cliente.
- Resultados possíveis, em português: funcionou (N consoles, X conectados), chave recusada (401), sem permissão (403), limite de chamadas (429), falha de rede ou tempo esgotado.
- Limite de uso do botão: no máximo 5 testes por minuto por organização, para não estourar o limite da UniFi.
- O teste atualiza a lista de consoles do cliente (hostId, nome, modelo, conectado ou não, versão). Não guarda e-mail, coordenadas ou dados de usuários do /v1/hosts (LGPD).

### Consoles
- Tabela de consoles com organização, cliente, hostId, nome, modelo, situação, versão e "acompanhar" (sim/não).
- No primeiro teste, consoles conectados entram com "acompanhar" ligado; antigos ou desconectados entram desligados. O MSP pode mudar.
- Console que sumiu da conta numa atualização fica marcado como "não aparece mais na conta", sem ser apagado (o histórico das próximas etapas depende dele).
- O mesmo hostId não pode ser acompanhado por dois clientes da mesma organização (caso o MSP cadastre a mesma conta em dois clientes): o sistema recusa e diz em qual cliente ele já está.
- Trocar a chave do cliente por outra conta: os consoles que não aparecem na conta nova ficam marcados como "não aparece mais na conta".
- Apagar a chave: pede confirmação com o nome do cliente; os consoles ficam, marcados como sem chave.
- Apagar um cliente com chave ou consoles: pede confirmação com o nome do cliente e apaga a chave e os consoles dele.

### Preparação para o acesso do cliente (futuro)
- Chave e consoles levam o ID do cliente, e as consultas do sistema passam a aceitar o filtro por cliente na mesma camada de isolamento.
- Nesta etapa não há login de cliente nem RLS por cliente: só a estrutura, para que a etapa futura não precise refazer tabelas.
- Fica registrado no CLAUDE.md como decisão nova (o acesso do cliente com login muda a decisão de 15/11/2026 de "só o MSP tem login").

### Isolamento
- As tabelas novas (chaves e consoles) herdam de ModeloDaOrganizacao e ficam sob RLS com FORCE, como clientes_cliente.
- O banco garante que o cliente da chave e do console é da mesma organização (chave estrangeira composta organização + cliente).
- Acesso a chave ou console de outra organização responde 404.

### Auditoria
- Novos eventos: chave cadastrada, trocada, apagada; conexão testada (com o resultado); console passou a ser acompanhado ou deixou de ser.
- Nunca registrar a chave, nem parte dela além dos 4 últimos caracteres.

## Testes obrigatórios
Com pytest, no PostgreSQL, sem chamar a api.ui.com de verdade (respostas simuladas):
- Isolamento: o MSP A não vê, não testa, não troca e não apaga chave de cliente do MSP B; não vê nem altera console do B (404). No banco, consulta direta com a organização A não devolve linhas do B; sem organização, zero linhas.
- O banco recusa chave ou console apontando para cliente de outra organização.
- A chave fica criptografada no banco (o texto puro não aparece na coluna) e volta igual ao descriptografar.
- A chave não aparece no HTML de nenhuma tela, nem na auditoria, nem em mensagens de erro.
- Troca da chave mestra: o comando recriptografa e a chave continua funcionando.
- Papéis: operador não cadastra chave; leitura não testa nem muda console.
- Testar conexão: cada resultado (200, 401, 403, 429, rede) mostra a mensagem certa; o limite de 5 por minuto funciona.
- Consoles: primeiro teste liga só os conectados; console que sumiu fica marcado; mesmo hostId em dois clientes é recusado.
- O cliente da api.ui.com recusa caminho fora da lista e qualquer método além de GET e dos POST permitidos.
- Teste manual com a chave real do lab, rodado pelo Gustavo, que confirma o UDR no cliente.

## Partes
1. Cofre: chave mestra no .env, criptografia, troca da chave mestra e testes.
2. Cliente da api.ui.com no sistema (app unifi/) e testes com respostas simuladas.
3. Chave do cliente: modelo, RLS, telas de cadastro, troca e exclusão na tela do cliente, auditoria.
4. Testar conexão e lista de consoles do cliente.
5. Acompanhar ou não cada console, regras de console sumido e de hostId repetido.
6. Revisão de segurança da etapa (chave fora de logs e telas, check --deploy), README atualizado, validação manual do Gustavo com a chave do lab, merge e push, CLAUDE.md marcando a etapa 2 feita e a 3 como próxima.

## Pronto quando
- Todos os testes passam.
- O Gustavo cadastra a chave do lab num cliente de uma organização de teste, testa a conexão e vê o UDR no cliente; numa segunda organização, nada disso aparece.
- A branch foi para a main e para o GitHub, e o CLAUDE.md está atualizado.
