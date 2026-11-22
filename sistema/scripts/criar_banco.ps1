# Cria o banco unifi_sistema e os usuários unifi_dono e unifi_app.
# Uso (dentro de sistema/):  powershell -ExecutionPolicy Bypass -File scripts\criar_banco.ps1
# Se o PostgreSQL não estiver na pasta padrão:  ... -File scripts\criar_banco.ps1 -Psql "D:\DB\bin\psql.exe"
# Pede a senha do superusuário postgres na própria janela. Nenhuma senha aparece na tela.
param(
    [string]$Psql = "C:\Program Files\PostgreSQL\18\bin\psql.exe"
)
$ErrorActionPreference = 'Stop'
$pasta = Split-Path -Parent $MyInvocation.MyCommand.Path
$envArq = Join-Path (Split-Path -Parent $pasta) '.env'

if (-not (Test-Path $envArq)) { throw "Crie o sistema/.env antes (python scripts\gerar_env.py)." }
if (-not (Test-Path $Psql)) { throw "psql não encontrado em $Psql. Use o parâmetro -Psql." }

# Carrega só as duas senhas, apenas para este processo.
foreach ($linha in Get-Content $envArq) {
    if ($linha -match '^(DB_DONO_SENHA|DB_APP_SENHA)=(.+)$') {
        Set-Item -Path ("env:" + $Matches[1]) -Value $Matches[2]
    }
}

try {
    Write-Host "Digite a senha do superusuario postgres quando pedir." -ForegroundColor Cyan
    & $Psql -h localhost -p 5432 -U postgres -d postgres -X -f (Join-Path $pasta 'criar_banco.sql')
    if ($LASTEXITCODE -ne 0) { throw "O psql terminou com erro ($LASTEXITCODE)." }
} finally {
    Remove-Item env:DB_DONO_SENHA, env:DB_APP_SENHA -ErrorAction SilentlyContinue
}
