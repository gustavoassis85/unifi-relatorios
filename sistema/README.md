# Dashboard UniFi — sistema (fase 2)

Aplicação web multi-tenant: cada MSP (organização) tem seus usuários e clientes e nunca enxerga outro MSP.
Pronto até aqui:
- Etapa 1 (fundação): login com MFA, organizações, papéis, cadastro de clientes, isolamento entre MSPs e auditoria.
- Etapa 2 (clientes e conexões): chave da UniFi de cada cliente guardada cifrada, "Testar conexão" e escolha de quais consoles acompanhar.
- Etapa 3 (coletores): o trabalhador coleta sozinho, de hora em hora, os consoles acompanhados de todos os clientes.
- Etapa 4 (relatórios): relatório de saúde da rede por cliente, com a marca do MSP, gerado pelo trabalhador em HTML e PDF, com histórico na página do cliente.

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

Baixar o Chromium sem tela que gera os PDFs (cerca de 290 MB, fica na pasta `sistema\.navegadores`, fora do Git; não instala nada no Windows):

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = ".navegadores"; .\.venv\Scripts\python.exe -m playwright install chromium-headless-shell
```

Criar o arquivo `.env` com chave e senhas aleatórias (não aparecem na tela; o `.env` nunca vai para o Git):

```powershell
.\.venv\Scripts\python.exe scripts\gerar_env.py
```

Se o `.env` já existe (de uma versão anterior), acrescente só as linhas novas, sem mexer nas que já estão lá:

```powershell
.\.venv\Scripts\python.exe scripts\gerar_env.py --completar
```

Faça uma cópia do `.env` num lugar seguro fora do computador (um cofre de senhas, por exemplo). Ele guarda a `UNIFI_CHAVE_MESTRA`, que cifra as chaves da UniFi salvas no banco: se ela se perder, essas chaves não abrem mais e precisam ser cadastradas de novo em cada cliente.

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

### O trabalhador (coletas em segundo plano)

As coletas rodam num segundo processo, o trabalhador. Abra outro PowerShell (ou outro terminal no VS Code), entre na pasta `sistema` e rode:

```powershell
.\.venv\Scripts\python.exe manage.py trabalhador
```

Deixe as duas janelas abertas: uma com o site, outra com o trabalhador. Ele coleta todos os clientes no minuto 30 de cada hora, dispara os relatórios agendados no minuto 1 de cada hora e manda os e-mails, roda os pedidos de "Coletar agora", "Testar conexão", "Enviar teste" e de relatório e, às 3h15 e às 4h, limpa tarefas antigas e dados que passaram do prazo. Se ficar desligado, a coleta roda uma vez assim que ele voltar. Para parar: `Ctrl+C` (ele termina a coleta em andamento antes de sair).

Para ver os números coletados de um cliente (o número é o que aparece no endereço da página dele, por exemplo `/clientes/3/`):

```powershell
.\.venv\Scripts\python.exe manage.py resumo_cliente 3
.\.venv\Scripts\python.exe manage.py resumo_cliente 3 --dias 30
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

### Validação da etapa 2 (com a chave real do lab)

Precisa de uma chave Site Manager: em unifi.ui.com, menu API, gere uma chave (ou use a do lab). A chave é colada só na tela do sistema, nunca no chat.

1. Entre como o admin do MSP A e abra um cliente (clique no nome na lista).
2. Em "Conexão com a UniFi", clique em "Cadastrar chave", cole a chave e salve. A página mostra só os 4 últimos caracteres.
3. Clique em "Testar conexão". Deve aparecer "Conexão funcionou" e o UDR na tabela de consoles, com "Acompanhar: Sim". Consoles antigos ou desconectados da conta aparecem com "Não".
4. Clique em "Deixar de acompanhar" no UDR e depois em "Acompanhar" de novo.
5. Cadastre a mesma chave em outro cliente do MSP A e teste: o UDR aparece com "Não". Clicar em "Acompanhar" mostra em qual cliente ele já é acompanhado.
6. Entre como o operador do A: testa a conexão e muda o acompanhamento, mas não vê "Trocar chave" nem "Apagar chave". Como leitura: vê tudo, sem nenhum botão.
7. Entre como o admin do MSP B: nada do MSP A aparece (clientes, chaves, consoles).
8. Volte ao admin do A, clique em "Trocar chave" e salve uma chave inventada, por exemplo `abcdefghij0123456789`. "Testar conexão" deve mostrar "A UniFi recusou a chave (401)". Depois volte a chave certa.
9. Clique em "Testar conexão" 6 vezes seguidas: a sexta mostra "Muitos testes seguidos".

### Validação da etapa 3 (coletas)

1. Suba o site e, em outra janela, o trabalhador (seção 3).
2. Na página do cliente com a chave do lab, clique em "Coletar agora". Em até 1 minuto, recarregue a página: o bloco "Coletas" mostra a coleta com cada parte em OK, e a tabela de consoles mostra a hora da última coleta.
3. Deixe os dois rodando até passar do minuto 30 de alguma hora: aparece uma nova coleta, marcada como automática.
4. Rode `manage.py resumo_cliente <número do cliente>` e compare com o MVP (`python resumo_wan.py` e `python resumo_equipamentos.py` na raiz do projeto): horas de WAN por dia, perda, equipamentos e dispositivos devem bater. Diferenças esperadas: dias em que o computador estava desligado aparecem no sistema (ele busca 30 dias na primeira vez) e o consumo de aplicativos do sistema é mais completo (ele busca os aplicativos de hora em hora).
5. Na janela do trabalhador, aperte `Ctrl+C`: ele mostra "Parando" e depois "Trabalhador parado".
6. Entre como admin do outro MSP: nenhuma coleta do cliente do lab aparece.

### Validação da etapa 4 (relatórios)

1. Suba o site e o trabalhador (seção 3).
2. Como admin do MSP do lab, abra o menu Marca: preencha empresa e contato, escolha o tema e envie um logo PNG ou JPG. Tente enviar um arquivo que não é imagem (um .txt renomeado para .png): deve ser recusado.
3. Na página do cliente do lab, em Relatórios, escolha "Últimos 7 dias" e clique em "Gerar relatório". A linha aparece como "Gerando…" e vira "Pronto" sozinha em poucos segundos.
4. Clique em "Ver": o relatório abre numa aba nova, com a marca. Clique em "Baixar PDF" e abra o arquivo.
5. Compare com o relatório do MVP do mesmo período (`python gerar_relatorio.py --dias 7` na raiz do projeto, arquivo em `dados\relatorios\`): mesmas seções, mesmos números de link, equipamentos e dispositivos. Diferenças esperadas: o do sistema tem uma seção por console do cliente, não traz os registros antigos (eles ficam no bloco "Higiene da conta", só na tela do MSP) e pode ter mais dados onde o MVP ficou com buracos (computador desligado) e no consumo de aplicativos.
6. Entre como o usuário de leitura: vê e baixa os relatórios, mas não tem o botão "Gerar relatório" nem o menu Marca.
7. Entre como admin do outro MSP: nenhum relatório do cliente do lab aparece.

### Validação da etapa 5 (agendamentos e e-mail)

Precisa de uma conta de e-mail com SMTP. No Gmail: ative a verificação em duas etapas e crie uma "senha de app" (Conta Google > Segurança > Senhas de app). Servidor `smtp.gmail.com`, porta 587, STARTTLS, usuário = o e-mail, senha = a senha de app, remetente = o mesmo e-mail.

1. Suba o site e o trabalhador (seção 3). Se o trabalhador roda pelo Agendador de Tarefas, reinicie a tarefa "Dashboard UniFi - Trabalhador" depois de atualizar o código.
2. Como admin, abra o menu E-mail, preencha e salve. A senha some da tela; fica só "termina em" com os 4 últimos caracteres.
3. Clique em "Enviar teste": aparece "Enviando o e-mail de teste…" e, em segundos, o resultado. Confira a caixa de entrada do seu usuário. Troque a senha por uma errada e teste de novo: deve aparecer "O servidor de e-mail recusou o usuário ou a senha." Volte a senha certa.
4. Tente salvar `localhost` ou `192.168.1.1` como servidor: deve ser recusado.
5. Na página do cliente do lab, em Agendamentos, crie um agendamento semanal para hoje, na próxima hora cheia, com o seu e-mail como destinatário. Depois da hora cheia (no minuto 1), o relatório aparece no histórico com "Agendamento" e, quando fica pronto, "Enviado em … para 1 destinatário". O e-mail chega com o PDF anexado.
6. Clique em "Reenviar" no relatório: chega outro e-mail.
7. No menu E-mail, desmarque "enviar e-mails por este servidor" e clique em "Reenviar": aparece "Não enviado: o servidor de e-mail está desligado". Marque de novo.
8. Clique em "Testar conexão" na página do cliente: aparece "Testando a conexão com a UniFi…" e a página recarrega sozinha com o resultado.
9. Entre como o usuário de leitura: vê os agendamentos, mas não cria, não edita, não pausa e não reenvia; não tem o menu E-mail. Entre como admin do outro MSP: nenhum agendamento ou envio do lab aparece.
10. Pause o agendamento criado no passo 5 (ou exclua) para não receber e-mails toda semana.

## 6. Troca da chave mestra

Para trocar a `UNIFI_CHAVE_MESTRA` (por exemplo, se o `.env` vazou), com o sistema parado:

```powershell
.\.venv\Scripts\python.exe scripts\gerar_env.py --trocar-chave-mestra
.\.venv\Scripts\python.exe manage.py recriptografar
```

Depois apague a linha `UNIFI_CHAVE_MESTRA_ANTERIOR` do `.env` e suba o sistema de novo. Se a chave mestra vazou, troque também as chaves da UniFi dos clientes em unifi.ui.com.

## 7. Como o sistema está organizado

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
  cofre/              criptografia das credenciais e troca da chave mestra
  unifi/              cliente da api.ui.com (só leitura)
  conexoes/           chave da UniFi de cada cliente, testar conexão e consoles
  tarefas/            fila de tarefas no PostgreSQL, tarefas periódicas e o comando trabalhador
  coletas/            coletas portadas do MVP, dados coletados, retenção e resumo_cliente
  relatorios/         marca da organização, pontos de atenção, relatório HTML (portado do MVP), PDF e telas
  envios/             SMTP da organização, agendamentos, disparo e envio dos relatórios por e-mail
  .navegadores/       Chromium sem tela do Playwright (fora do Git)
  templates/, static/ telas e CSS/HTMX
```

## 8. Regras de segurança implementadas

- Isolamento entre MSPs em duas travas:
  - Camada única no Django (`organizacoes/isolamento.py`): os modelos de dado de MSP filtram pela organização atual e recusam gravar em outra.
  - Row-Level Security do PostgreSQL com FORCE em clientes, vínculos, eventos da organização, chaves da UniFi e consoles. A organização e o usuário da requisição são definidos com `set_config(..., true)`, com valores passados como parâmetro, e valem só dentro da transação. Sem organização definida, nenhuma linha aparece.
- Dois usuários do banco: `unifi_dono` (dono das tabelas, só para migrações e para criar o banco dos testes) e `unifi_app` (usado pelo sistema: não é dono, não é superusuário, sem BYPASSRLS). O superusuário `postgres` só é usado na instalação.
- A organização da requisição vem só do vínculo do usuário logado. Registro de outra organização responde 404.
- Login por e-mail e senha (mínimo de 12 caracteres), sem cadastro aberto. MFA por app autenticador obrigatório para admins e para o dono, com códigos de recuperação. Bloqueio após 5 senhas erradas (cache no banco, vale para vários processos). Sessão expira após 2 horas sem uso.
- O admin do Django não tem login próprio: sempre passa pelo login do sistema, com MFA.
- Auditoria só de acréscimo: o `unifi_app` só pode incluir e ler eventos. Senhas, códigos de MFA e chaves nunca são registrados.
- Cookies Secure, HttpOnly e SameSite; CSRF; CSP sem nada embutido; X-Frame-Options DENY. Na publicação, `DJANGO_HTTPS=1` liga o redirecionamento para HTTPS e o HSTS.
- Chaves da UniFi cifradas no banco (Fernet) com a `UNIFI_CHAVE_MESTRA`, que fica só no ambiente. Depois de salva, a chave nunca volta para a tela: só os 4 últimos caracteres. Páginas de erro escondem qualquer configuração ou campo com CHAVE, SENHA, KEY ou PASS no nome.
- Chaves e consoles levam a organização e o cliente; o banco recusa ligar uma chave ou console a cliente de outra organização (chave estrangeira composta).
- Conversa com a UniFi só de leitura (`unifi/api.py`): lista fechada de caminhos, certificado sempre verificado, sem seguir redirecionamento, prazo por chamada e limite de tamanho da resposta. Do `/v1/hosts`, nada de e-mail, localização ou usuários é guardado.
- "Testar conexão": no máximo 5 por minuto por organização. Só admin cadastra, troca ou apaga chaves; admin e operador testam e escolhem os consoles.
- Trabalhador: conecta como o usuário da aplicação (o mesmo do site) e roda cada tarefa no contexto da organização dela; a RLS vale como no site. A fila não guarda chave nem dado coletado. Erros inesperados ficam só com o tipo do erro na tela; o detalhe vai para o log do servidor.
- Dados coletados: toda tabela tem organização, cliente e console, sob RLS, e o banco garante que os três batem. Do `/v1/hosts`, nada de e-mail, localização ou usuários; aplicativos só no total da rede.
- Retenção: amostras de equipamentos e dispositivos e tráfego por dispositivo por 90 dias; agregados do site por 13 meses.
- Catálogos (nomes de aplicativos e sistemas da UniFi) ficam numa tabela da plataforma, compartilhada por todas as organizações. Para a revisão de segurança antes do primeiro MSP pagante: um console adulterado poderia trocar esses nomes para todos (o texto é sempre escapado na tela, então não vira código).
- Relatórios: guardados no banco (HTML e PDF) com organização e cliente, sob RLS, por 13 meses. Admin e operador geram; todos os papéis veem e baixam; cada pedido e cada download vão para a auditoria. Um relatório gerando por cliente de cada vez; um que fique "gerando" por mais de 15 minutos (trabalhador caiu) vira falha e libera novo pedido.
- PDF: o Chromium abre o HTML com JavaScript desligado, sem rede (toda requisição é abortada; só imagens embutidas funcionam) e com tempo limite de 60 s. O erro do Chromium vai para o log; a tela mostra só o resumo.
- Página do relatório com CSP própria: só estilos e imagens embutidos, nenhum script; sem cache no navegador (também no PDF). Todo texto vindo da UniFi ou do MSP é escapado. O nome do arquivo baixado só tem letras sem acento, números e hífen.
- Logo da marca: só admin envia; PNG ou JPG conferido pelo conteúdo, até 500 KB, limite de pixels contra imagem "bomba", e regravado como PNG novo (descarta metadados e conteúdo escondido). SVG não é aceito.
- Higiene da conta (registros antigos e consoles fora do acompanhamento) aparece só na tela do MSP, nunca no relatório do cliente.
- SMTP por organização: só o admin configura. Senha cifrada no cofre (como as chaves da UniFi), nunca volta para a tela (só os 4 últimos caracteres) e fica fora da auditoria e das páginas de erro. Sem criptografia não é aceito (STARTTLS ou SSL), o certificado é conferido pelo nome do servidor e cada conexão tem 20 s de limite. Portas aceitas: 25, 465, 587 e 2525.
- O servidor de e-mail não pode apontar para a rede interna (`envios/rede.py`): o nome é resolvido, todos os IPs têm de ser da Internet e a conexão vai para o IP conferido (uma segunda consulta ao DNS não consegue trocar o destino). Assim, no servidor, o campo do SMTP não serve para sondar a rede de lá.
- Agendamentos e envios: organização e cliente sob RLS, e o banco garante que batem. Admin e operador criam, editam, pausam, excluem e reenviam; leitura só vê. No máximo 5 agendamentos por cliente, 10 destinatários e 5 envios por relatório a cada 24 horas.
- Os e-mails dos destinatários são dados pessoais informados pelo MSP: ficam só no agendamento e no registro do envio (apagado com o relatório, em 13 meses). Não vão para o log, para a fila de tarefas nem para a auditoria (lá só a quantidade).
- Envio: falha passageira tenta de novo (10 min e 1 h depois); falha que pede correção (senha, remetente, certificado) para na hora. Envio que não termina em 3 horas vira falha e libera o "Reenviar". Sem SMTP, o agendamento só gera o relatório (plano B).
- "Testar conexão" e "Enviar teste" rodam no trabalhador: a consulta à UniFi e a conversa com o servidor de e-mail nunca seguram uma transação do banco. Se o trabalhador estiver desligado, a tela para de esperar depois de 10 minutos.
