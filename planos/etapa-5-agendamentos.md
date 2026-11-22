# Etapa 5 — Agendamentos, SMTP e o plano B para o PDF

## Objetivo
O relatório sai sozinho, na data marcada, e chega por e-mail ao cliente final. Ao final:
- Cada organização configura o próprio servidor de e-mail (SMTP) e confere com um "Enviar teste".
- Na página do cliente, o MSP cria agendamentos: frequência, dia, hora e destinatários.
- Na hora marcada, o trabalhador gera o relatório e manda o PDF anexado por e-mail.
- Sem SMTP configurado, o agendamento só gera o relatório e deixa no histórico (plano B).
- Falha de envio não perde o relatório: ele fica no histórico, com o motivo e a opção de reenviar.

Fora desta etapa: servidor de produção (etapa 6), acesso do cliente final com login (futuro).

## Como conduzir
1. O Gustavo aprova este plano antes de qualquer código.
2. Partes pequenas; cada parte termina com os testes rodando e um commit.
3. Branch etapa-5-agendamentos. No fim, merge na main e push.
4. Nada novo para instalar: o envio usa o próprio Django (smtplib), e o disparo usa as periódicas do trabalhador (tarefas/periodicas.py), sem o Agendador do Windows.

## Decisões propostas (para o Gustavo confirmar)
1. Frequências: mensal (dia 1 a 28, para existir em todos os meses) ou semanal (dia da semana), sempre em hora cheia, no fuso de São Paulo. O mensal cobre o mês anterior fechado; o semanal, os últimos 7 dias. Padrão: mensal, dia 1, 8h.
2. Um cliente pode ter até 5 agendamentos (por exemplo, semanal para o técnico e mensal para a diretoria), cada um com até 10 destinatários. Dá para pausar sem apagar.
3. SMTP por organização (só o admin configura): servidor, porta, segurança (STARTTLS ou SSL; sem criptografia não é aceito), usuário, senha e remetente. A senha fica cifrada no cofre, como a chave da UniFi, e depois de salva só aparecem os últimos 4 caracteres. O nome do remetente é o nome da empresa da marca.
4. "Enviar teste" manda um e-mail curto para quem clicou, pelo trabalhador; a tela se atualiza sozinha com o resultado ("enviado" ou o erro em português). Assim a página nunca fica presa esperando o servidor de e-mail.
5. Proteção do servidor: o endereço do SMTP não pode apontar para a rede interna (localhost, IPs privados, link-local), as portas aceitas são 25, 465, 587 e 2525, o certificado é conferido e cada conexão tem tempo limite de 20 s. Motivo: quando o sistema estiver num servidor, um MSP não pode usar o campo do SMTP para sondar a rede de lá.
6. O e-mail leva o PDF anexado e um texto curto com a marca do MSP (cliente, período, contato). O relatório não vai no corpo do e-mail, porque cada leitor de e-mail mostra HTML de um jeito.
7. Plano B e falhas:
   - Sem SMTP (ou com o SMTP desligado): o relatório agendado é gerado e fica no histórico com "não enviado: SMTP não configurado".
   - Falha de envio: até 3 tentativas (na hora, depois de 10 min e de 1 h). Esgotadas, o histórico mostra "envio falhou" com o motivo e um botão "Reenviar".
   - Falha ao gerar o PDF: nada é enviado e o histórico mostra o erro, como já acontece hoje.
   - Se o trabalhador ficou desligado na hora marcada, o agendamento roda uma vez assim que ele volta (não repete as datas perdidas).
8. Cada envio fica registrado (relatório, destinatários, situação, motivo, quando), sob RLS, e é apagado junto com o relatório (13 meses). Auditoria: SMTP alterado, teste enviado, agendamento criado, alterado, pausado ou excluído, relatório reenviado. Os e-mails dos destinatários são dados pessoais informados pelo MSP: só ficam no agendamento e no registro do envio, e nunca aparecem no log.
9. Pendência da etapa 2: o "Testar conexão" deixa de segurar a transação por até 30 s. A consulta à UniFi passa a ser feita fora da transação, e o resultado é gravado numa transação curta.

## Requisitos

### SMTP
- Tela "E-mail (SMTP)" nas configurações da organização: só admin edita; operador e leitura não veem a senha nem os últimos 4.
- Validação ao salvar: porta da lista, endereço que não aponta para a rede interna, remetente com e-mail válido.
- Botão "Enviar teste" e a situação do último teste (quando, resultado).

### Agendamentos
- Seção "Agendamentos" na página do cliente: lista com frequência, próxima execução, destinatários e situação (ativo ou pausado).
- Criar e editar: admin e operador. Ver: todos os papéis.
- A próxima execução é calculada e guardada; a periódica procura os agendamentos vencidos a cada hora.

### Disparo e envio
- Periódica "disparar_agendamentos": para cada agendamento vencido, cria o relatório (origem: agendamento) e enfileira a geração; não cria um segundo se o anterior do mesmo agendamento ainda estiver gerando.
- Quando o relatório fica pronto e veio de um agendamento com SMTP, enfileira a tarefa "enviar_relatorio".
- Histórico do cliente mostra a origem (manual ou agendado) e a situação do envio.
- Reenviar: admin e operador, para os destinatários do agendamento.

## Testes obrigatórios
Com pytest, no PostgreSQL, com o e-mail em memória do Django (nada sai de verdade nos testes):
- Isolamento: MSP A não vê, não edita e não dispara SMTP, agendamento, envio ou reenvio do MSP B (404); consulta direta com a organização A não devolve linhas do B; sem organização, zero linhas.
- Cálculo da próxima execução: mensal, semanal, virada de mês e de ano, trabalhador parado por dias (roda uma vez só).
- Disparo: agendamento vencido gera um relatório; pausado não gera; não duplica.
- Envio: PDF anexado, remetente e destinatários certos; sem SMTP vira "não enviado"; falha tenta de novo e, esgotada, aparece no histórico; reenviar funciona.
- SMTP: senha cifrada e nunca devolvida na tela; endereço interno, porta fora da lista e conexão sem criptografia recusados.
- Papéis: leitura não cria agendamento nem mexe no SMTP; operador não mexe no SMTP.
- "Testar conexão" sem transação aberta durante a consulta à UniFi.

## Partes
1. SMTP: modelo cifrado, tela, validações e envio de teste pelo trabalhador.
2. Agendamentos: modelo, cálculo da próxima execução e tela no cliente.
3. Disparo: periódica que cria e enfileira os relatórios agendados.
4. Envio: tarefa com tentativas, registro dos envios, histórico com a situação e o "Reenviar".
5. Pendência do "Testar conexão".
6. Revisão de segurança, README e teste ponta a ponta com um SMTP de verdade.

## Para o teste real (parte 6)
Para ver o e-mail chegando de verdade, é preciso um SMTP. Opções: uma conta do Gmail com senha de app (o Gmail pede verificação em duas etapas) ou o SMTP do provedor de e-mail da empresa. A senha é digitada pelo Gustavo na tela do sistema, nunca na conversa.
