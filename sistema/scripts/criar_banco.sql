-- Roda uma vez, como o superusuário postgres (ver criar_banco.ps1).
-- As senhas vêm de variáveis de ambiente (\getenv), não ficam neste arquivo,
-- e entram como texto entre aspas (:'var'), nunca montadas no SQL.
\set ON_ERROR_STOP on
\getenv dono_senha DB_DONO_SENHA
\getenv app_senha DB_APP_SENHA

-- Dono: cria as tabelas e roda as migrações. CREATEDB só para os testes criarem o banco temporário.
CREATE ROLE unifi_dono LOGIN NOSUPERUSER NOCREATEROLE CREATEDB NOREPLICATION NOBYPASSRLS PASSWORD :'dono_senha';

-- App: usado pelo sistema no dia a dia. Sem nenhum poder extra.
CREATE ROLE unifi_app LOGIN NOSUPERUSER NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS PASSWORD :'app_senha';

CREATE DATABASE unifi_sistema OWNER unifi_dono ENCODING 'UTF8' TEMPLATE template0;
REVOKE ALL ON DATABASE unifi_sistema FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE unifi_sistema TO unifi_app;

-- Conferência (sem senhas): todas as colunas devem ser f, menos rolcreatedb do dono.
SELECT rolname, rolsuper, rolcreaterole, rolcreatedb, rolbypassrls
  FROM pg_roles WHERE rolname IN ('unifi_dono', 'unifi_app') ORDER BY rolname;
