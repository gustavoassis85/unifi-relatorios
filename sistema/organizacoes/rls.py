"""SQL das políticas de Row-Level Security, usado nas migrações.

A organização e o usuário da requisição ficam em duas configurações da conexão
(app.organizacao_id e app.user_id), definidas com set_config(..., true): valem só
dentro da transação. Sem elas definidas, as expressões dão nulo e nenhuma linha passa.
"""
from django.db import migrations

ORG_DEFINIDA = "organizacao_id = nullif(current_setting('app.organizacao_id', true), '')::bigint"
USUARIO_LOGADO = "usuario_id = nullif(current_setting('app.user_id', true), '')::bigint"


def _ativar(tabela):
    return [
        f"alter table {tabela} enable row level security",
        f"alter table {tabela} force row level security",
    ]


def _desativar(tabela, politicas):
    return [f"drop policy if exists {p} on {tabela}" for p in politicas] + [
        f"alter table {tabela} no force row level security",
        f"alter table {tabela} disable row level security",
    ]


def rls_por_organizacao(tabela):
    """Tabela de dado de MSP: só a organização definida lê e grava."""
    return migrations.RunSQL(
        sql=_ativar(tabela)
        + [
            f"create policy isolamento on {tabela} for all "
            f"using ({ORG_DEFINIDA}) with check ({ORG_DEFINIDA})"
        ],
        reverse_sql=_desativar(tabela, ["isolamento"]),
    )


def rls_vinculo(tabela):
    """Vínculo: lê a linha da organização definida ou a do próprio usuário logado
    (é assim que o login descobre a organização). Gravar, só na organização definida."""
    return migrations.RunSQL(
        sql=_ativar(tabela)
        + [
            f"create policy ver on {tabela} for select "
            f"using ({ORG_DEFINIDA} or {USUARIO_LOGADO})",
            f"create policy incluir on {tabela} for insert with check ({ORG_DEFINIDA})",
            f"create policy alterar on {tabela} for update "
            f"using ({ORG_DEFINIDA}) with check ({ORG_DEFINIDA})",
            f"create policy apagar on {tabela} for delete using ({ORG_DEFINIDA})",
        ],
        reverse_sql=_desativar(tabela, ["ver", "incluir", "alterar", "apagar"]),
    )


def cliente_da_mesma_organizacao(tabela):
    """Tabela que pertence a um cliente: chave estrangeira composta (organização, cliente)
    para clientes_cliente. O banco recusa apontar para cliente de outra organização."""
    restricao = f"{tabela}_cliente_mesma_org"
    return migrations.RunSQL(
        sql=[
            f"alter table {tabela} add constraint {restricao} "
            f"foreign key (organizacao_id, cliente_id) "
            f"references clientes_cliente (organizacao_id, id) "
            f"deferrable initially deferred"
        ],
        reverse_sql=[f"alter table {tabela} drop constraint if exists {restricao}"],
    )
