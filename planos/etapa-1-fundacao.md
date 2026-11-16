# Etapa 1 — Fundação do sistema

## Objetivo
Montar a base segura do sistema, antes de qualquer tela de relatório. Ao final:
- O Gustavo (dono da plataforma) cria uma organização (MSP) e o primeiro admin dela.
- O admin entra com e-mail, senha e MFA, cria usuários da organização com um papel e cadastra clientes (por enquanto, só o nome).
- Dois MSPs de teste não se enxergam, e os testes automáticos provam isso.

Fora desta etapa: conexão com a UniFi, coletores, relatórios, agendamentos, SMTP, publicação em servidor e visual final das telas.

## Como conduzir
1. Antes de qualquer código, apresentar um plano por escrito para o Gustavo aprovar: o que será instalado no Windows, bibliotecas com o motivo de cada uma, estrutura de pastas e ordem das partes.
2. Depois, construir em partes pequenas. Cada parte termina com os testes rodando e um commit.
3. Trabalhar na branch etapa-1-fundacao. No fim, merge na main e push.
4. Não alterar o código do MVP (raiz do projeto). A coleta agendada do lab continua rodando.

## Requisitos

### Projeto
- Django 5.2 LTS em sistema/, com o manage.py dentro de sistema/.
- Dependências em sistema/requirements.txt, com versões fixadas.
- Configurações pelo ambiente (.env fora do Git, .env.example sem valores no Git).
- Modelo de usuário próprio desde a primeira migração, com login por e-mail.
- Idioma pt-BR e fuso America/Sao_Paulo.

### PostgreSQL
- Instalar o PostgreSQL no Windows pelo instalador oficial, com aprovação do Gustavo antes.
- Dois usuários do banco: um dono das tabelas, que roda as migrações, e um da aplicação, que não é dono, não é superusuário e não tem BYPASSRLS.
- Os testes rodam no PostgreSQL, nunca no SQLite.

### Organizações, papéis e clientes
- Organização (MSP): criada pelo dono da plataforma no admin do Django.
- Vínculo usuário-organização com papel: admin, operador ou leitura. No começo, cada usuário pertence a uma organização.
- Admin da organização: cria, desativa e muda o papel dos usuários da própria organização.
- Operador: cria e edita clientes. Leitura: só vê.
- Cliente: por enquanto só o nome. É a primeira tabela com dado de MSP e serve para provar o isolamento.
- O admin do Django só gerencia organizações e usuários. Clientes ficam fora do admin.

### Login
- E-mail e senha, com os validadores de senha do Django (mínimo de 12 caracteres).
- MFA por app autenticador (TOTP) obrigatório para admins da organização e para o dono da plataforma, com códigos de recuperação. Sugestão: django-allauth com o módulo de MFA. Se propor outra opção, explicar o motivo no plano.
- Admin sem MFA configurado só acessa a tela de configurar o MFA.
- Bloqueio temporário após tentativas erradas, sessão com expiração e logout.

### Isolamento
- Seguir as regras de "Isolamento entre MSPs" do CLAUDE.md: camada única que filtra pela organização, Row-Level Security com FORCE, nenhuma linha sem organização definida.
- A organização da requisição é definida na conexão do banco dentro da transação da requisição (SET LOCAL), a partir do usuário logado.
- Explicar no plano quais tabelas ficam sob RLS e como o login descobre a organização do usuário sem abrir brecha.
- Acesso a um registro de outra organização responde 404, não 403, para não revelar que ele existe.

### Auditoria
- Tabela de eventos com organização, usuário, data, IP e o que aconteceu: login, falha de login, usuário criado ou alterado, cliente criado, alterado ou apagado.
- Nunca registrar senhas, códigos de MFA ou chaves.

### Segurança da aplicação
- DEBUG desligado por padrão e SECRET_KEY vinda do ambiente.
- Cookies Secure, HttpOnly e SameSite; CSRF ativo; CSP básica; X-Frame-Options DENY.
- Admin do Django numa URL que não seja /admin/.
- python manage.py check --deploy sem alertas, exceto os de HTTPS no ambiente local.

### Telas mínimas
- Login, configuração do MFA, lista e cadastro de clientes, lista e cadastro de usuários da organização.
- Django + HTMX, em português, simples. O visual final vem depois.

## Testes obrigatórios
Com pytest e pytest-django, no PostgreSQL:
- O usuário do MSP A não vê na lista, não abre, não edita e não apaga cliente do MSP B (404).
- No banco, com o usuário da aplicação e a organização A definida, uma consulta direta não devolve linhas de B.
- Sem organização definida, a consulta devolve zero linhas.
- Gravar um cliente com o ID de outra organização é recusado pelo banco.
- O papel leitura não cria nem edita; o operador não gerencia usuários.
- Admin sem MFA não acessa nada além da configuração do MFA.
- Bloqueio após tentativas de login erradas.
- Cada evento auditado gera registro, sem dado sensível.

## Pronto quando
- Todos os testes passam.
- O Gustavo cria duas organizações de teste, entra como admin de cada uma com MFA, cadastra clientes e confirma na tela que uma não vê a outra.
- sistema/README.md explica, passo a passo para Windows, como subir o sistema e rodar os testes.
- A branch etapa-1-fundacao foi para a main e para o GitHub.
- O CLAUDE.md marca a etapa 1 como feita e a etapa 2 como a próxima.
