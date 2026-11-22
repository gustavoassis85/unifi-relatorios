# Dashboard UniFi — sistema (fase 2)

Aplicação web multi-tenant: cada MSP (organização) tem seus usuários e clientes e nunca enxerga outro MSP.
Esta é a etapa 1 (fundação): login com MFA, organizações, papéis, cadastro de clientes, isolamento entre MSPs e auditoria.

Todos os comandos abaixo são para o PowerShell do Windows e rodam dentro da pasta `sistema`.

## 1. Programas necessários

- Python 3.13
- Git
- PostgreSQL 18, pelo instalador oficial (https://www.postgresql.org/download/windows/), com o servidor e as ferramentas de linha de comando. Guarde a senha do superusuário `postgres`.

Depois de instalar, deixe o PostgreSQL escutando só no próprio computador: no arquivo `postgresql.conf` (fica na pasta `data` da instalação), a linha `listen_addresses` deve ser `'localhost'`. Reinicie o serviço `postgresql-x64-18` depois de mudar.

## 2. Primeira vez: preparar o ambiente

Entrar na pasta do sistema:

```powershell
cd C:\Users\<voce>\Projetos\unifi-relatorios\sistema
```

Criar o ambiente virtual do Python (fica em `.venv`, fora do Git) e instalar as bibliotecas com as versões fixadas:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Criar o arquivo `.env` com chave e senhas aleatórias (não aparecem na tela; o `.env` nunca vai para o Git):

```powershell
.\.venv\Scripts\python.exe scripts\gerar_env.py
```

Criar o banco `unifi_sistema` e os dois usuários do banco. Abre o `psql`, que pede a senha do `postgres`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\criar_banco.ps1
```

Se o PostgreSQL foi instalado fora da pasta padrão, informe onde está o `psql`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\criar_banco.ps1 -Psql "D:\DB\bin\psql.exe"
```

Criar as tabelas (o `manage.py` usa sozinho o usuário dono para as migrações):

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

Criar o dono da plataforma (você). Pede e-mail e senha (mínimo de 12 caracteres):

```powershell
.\.venv\Scripts\python.exe manage.py createsuperuser
```

## 3. Subir o sistema

```powershell
.\.venv\Scripts\python.exe manage.py runserver --insecure
```

Abra http://localhost:8000 no navegador. Use `localhost`, não `127.0.0.1`: os cookies são do tipo seguro e os navegadores só aceitam isso por http no endereço `localhost`.

O `--insecure` só serve para o servidor de desenvolvimento entregar o CSS e o HTMX com o DEBUG desligado. Não é usado em produção. Para parar o servidor: `Ctrl+C`.

O admin do Django (onde o dono cria organizações) fica no endereço da linha `DJANGO_ADMIN_URL` do `.env`, por exemplo http://localhost:8000/plataforma-xxxxxxxxxxxx/. Para ver só esse valor:

```powershell
Select-String -Path .env -Pattern '^DJANGO_ADMIN_URL='
```

## 4. Rodar os testes

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Os testes criam um banco temporário no PostgreSQL (nunca no SQLite), rodam conectados como o usuário da aplicação e apagam o banco no fim.

## 5. Roteiro de validação na tela

Precisa de um app autenticador no celular (Google Authenticator, Microsoft Authenticator ou similar).

1. Entre em http://localhost:8000 com o e-mail e a senha do dono. O sistema pede para configurar o MFA: confirme a senha, leia o QR code com o app, digite o código e guarde os códigos de recuperação.
2. Abra o admin do Django (endereço do `DJANGO_ADMIN_URL`). Em Organizações, crie "MSP Teste A" com o primeiro admin (e-mail e senha inicial). Depois crie "MSP Teste B" com outro admin.
3. Saia. Entre como o admin do MSP A: configure o MFA dele (outra conta no app autenticador), cadastre dois clientes e, em Usuários, cadastre um operador e um usuário de leitura.
4. Saia e entre como o admin do MSP B: configure o MFA e cadastre um cliente. Confira que os clientes e usuários do MSP A não aparecem.
5. Ainda como admin do B, tente cadastrar um usuário com o e-mail do admin do A: deve aparecer a mensagem genérica, sem dizer que o e-mail existe.
6. Entre como o usuário de leitura do A: vê a lista de clientes, mas sem botões de cadastrar, editar ou apagar, e sem o menu Usuários.
7. Entre como o operador do A: cadastra e edita clientes, mas não vê o menu Usuários.
8. Erre a senha de um usuário 5 vezes: o login fica bloqueado por 15 minutos, mesmo com a senha certa.

## 6. Como o sistema está organizado

```
sistema/
  manage.py           comando principal do Django
  requirements.txt    bibliotecas com versão fixada
  .env.example        nomes das configurações, sem valores (o .env real fica fora do Git)
  conftest.py         preparação dos testes (banco temporário, cenário com dois MSPs)
  apoio_testes.py     funções usadas pelos testes (MFA)
  scripts/            gerar o .env e criar o banco
  config/             configurações, endereços e permissões do banco
  contas/             usuário com login por e-mail, MFA obrigatório, login do admin
  organizacoes/       organização, vínculo com papel, isolamento (RLS), telas de usuários
  clientes/           cadastro de clientes
  auditoria/          registro de eventos (só de acréscimo)
  templates/, static/ telas e CSS/HTMX
```

## 7. Regras de segurança implementadas

- Isolamento entre MSPs em duas travas:
  - Camada única no Django (`organizacoes/isolamento.py`): os modelos de dado de MSP filtram pela organização atual e recusam gravar em outra.
  - Row-Level Security do PostgreSQL com FORCE em clientes, vínculos e eventos da organização. A organização e o usuário da requisição são definidos com `set_config(..., true)`, com valores passados como parâmetro, e valem só dentro da transação. Sem organização definida, nenhuma linha aparece.
- Dois usuários do banco: `unifi_dono` (dono das tabelas, só para migrações e para criar o banco dos testes) e `unifi_app` (usado pelo sistema: não é dono, não é superusuário, sem BYPASSRLS). O superusuário `postgres` só é usado na instalação.
- A organização da requisição vem só do vínculo do usuário logado. Registro de outra organização responde 404.
- Login por e-mail e senha (mínimo de 12 caracteres), sem cadastro aberto. MFA por app autenticador obrigatório para admins e para o dono, com códigos de recuperação. Bloqueio após 5 senhas erradas (cache no banco, vale para vários processos). Sessão expira após 2 horas sem uso.
- O admin do Django não tem login próprio: sempre passa pelo login do sistema, com MFA.
- Auditoria só de acréscimo: o `unifi_app` só pode incluir e ler eventos. Senhas, códigos de MFA e chaves nunca são registrados.
- Cookies Secure, HttpOnly e SameSite; CSRF; CSP sem nada embutido; X-Frame-Options DENY. Na publicação, `DJANGO_HTTPS=1` liga o redirecionamento para HTTPS e o HSTS.
