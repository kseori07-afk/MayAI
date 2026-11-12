# Run on the MayAI PC with PowerShell 7.
param(
    [Parameter(Mandatory)] [ValidateSet('Configure', 'EnableFileTools', 'Files')] [string]$Action,
    [string]$LaptopIp
)

$ErrorActionPreference = 'Stop'
$api = 'http://127.0.0.1:8000/api'
if ($Action -ne 'EnableFileTools' -and -not $env:MAYAI_BOOTH_FILE_TOKEN) {
    throw 'Set MAYAI_BOOTH_FILE_TOKEN in this terminal.'
}

if ($Action -in @('Configure', 'EnableFileTools')) {
    if (-not $env:MAYAI_ADMIN_KEY) { throw 'Set MAYAI_ADMIN_KEY in this terminal.' }
    $headers = @{ 'X-Admin-Key' = $env:MAYAI_ADMIN_KEY }
}

function Add-Record($Path, $Body) {
    Invoke-RestMethod "$api/$Path" -Method Post -Headers $headers `
        -ContentType 'application/json; charset=utf-8' -Body ($Body | ConvertTo-Json -Compress) | Out-Null
}

function Enable-FileToolPolicies {
    $destination = 'http://127.0.0.1:9100/mcp'
    $existing = Invoke-RestMethod "$api/policies"
    foreach ($tool in @(
        @{ name='신입 요원 메모 읽기 시연'; id='read_notes_as_rookie' },
        @{ name='신입 요원 급여 파일 읽기 시연'; id='read_payroll_as_rookie' },
        @{ name='보안 책임자 급여 파일 읽기 시연'; id='read_payroll_as_chief' }
    )) {
        $matching = $existing | Where-Object {
            $_.agent_id -eq 'booth-villain' -and $_.target -eq $destination -and
            $_.mcp_method -eq 'tools/call' -and $_.tool -eq $tool.id -and $_.action -eq 'ALLOW'
        }
        if ($matching | Where-Object enabled) { continue }

        $body = @{ name=$tool.name; agent_id='booth-villain'; destination_url=$destination;
            mcp_method='tools/call'; tool=$tool.id; action='ALLOW' }
        if ($matching) {
            $policy = $matching | Select-Object -First 1
            $body.name = $policy.name
            $body.description = $policy.description
            Invoke-RestMethod "$api/policies/$($policy.policy_id)" -Method Put -Headers $headers `
                -ContentType 'application/json; charset=utf-8' -Body ($body | ConvertTo-Json -Compress) | Out-Null
        } else {
            Add-Record 'policies' $body
        }
    }
    Write-Host '파일 읽기 MCP 도구의 요청 허용 정책 준비 완료'
}

if ($Action -eq 'EnableFileTools') {
    Enable-FileToolPolicies
    return
}

if ($Action -eq 'Configure') {
    if (-not ($LaptopIp -and $env:MAYAI_BOOTH_TOKEN)) {
        throw 'Set -LaptopIp and MAYAI_BOOTH_TOKEN.'
    }
    $agents = Invoke-RestMethod "$api/agents"
    $policies = Invoke-RestMethod "$api/policies"
    $files = Invoke-RestMethod "$api/mac/files"
    $servers = Invoke-RestMethod "$api/mcp/servers"
    if ($agents.Count -or $policies.Count -or $files.files.Count -or $servers.Count -or -not $files.configured) {
        throw 'Use a new empty booth database and set MAYAI_PROTECTED_DIR on the API process.'
    }

    Add-Record 'agents' @{ agent_id='booth-villain'; agent_name='악당 에이전트'; token=$env:MAYAI_BOOTH_TOKEN; source_ip=$LaptopIp; clearance=2 }
    Add-Record 'agents' @{ agent_id='booth-rookie'; agent_name='신입 요원 · L2'; token=$env:MAYAI_BOOTH_FILE_TOKEN; source_ip='127.0.0.1'; clearance=2 }
    Add-Record 'agents' @{ agent_id='booth-chief'; agent_name='보안 책임자 · L3'; token=$env:MAYAI_BOOTH_FILE_TOKEN; source_ip='127.0.0.1'; clearance=3 }
    Add-Record 'mcp/servers' @{ name='사내 보고 서버'; http_url='http://127.0.0.1:9100/mcp' }
    Add-Record 'mcp/servers' @{ name='외부 수집 서버 (모의)'; http_url='http://127.0.0.1:9101/mcp' }

    foreach ($rule in @(
        @{ name='사내 보고 허용'; port=9100; tool='echo'; action='ALLOW' },
        @{ name='외부 수집 차단'; port=9101; tool='echo'; action='DENY' },
        @{ name='삭제 시연 기본 허용'; port=9100; tool='delete_file'; action='ALLOW' },
        @{ name='삭제 시연 차단'; port=9100; tool='delete_file'; action='DENY' }
    )) {
        Add-Record 'policies' @{ name=$rule.name; agent_id='booth-villain'; destination_url="http://127.0.0.1:$($rule.port)/mcp";
            mcp_method='tools/call'; tool=$rule.tool; action=$rule.action }
    }
    Add-Record 'mac/files' @{ filename='notes.txt'; level=2 }
    Add-Record 'mac/files' @{ filename='payroll.txt'; level=3 }
    Enable-FileToolPolicies
    Write-Host '시연용 에이전트, 정책, 파일 등록 완료'
    return
}

$registered = (Invoke-RestMethod "$api/mac/files").files
foreach ($step in @(
    @{ name='신입 요원 · L2'; agent='booth-rookie'; file='notes.txt'; status=200 },
    @{ name='신입 요원 · L2'; agent='booth-rookie'; file='payroll.txt'; status=403 },
    @{ name='보안 책임자 · L3'; agent='booth-chief'; file='payroll.txt'; status=200 }
)) {
    $file = $registered | Where-Object filename -eq $step.file
    if (-not $file) { throw "등록된 파일을 찾을 수 없습니다. $($step.file)" }
    $headers = @{ 'X-Agent-ID' = $step.agent; 'X-Agent-Token' = $env:MAYAI_BOOTH_FILE_TOKEN }
    $result = Invoke-RestMethod "$api/file-access/$($file.file_id)/read" -Method Post -Headers $headers `
        -SkipHttpErrorCheck -StatusCodeVariable status
    $detail = if ($status -eq 200) { $result.content } else { $result.detail }
    Write-Host "$($step.name) → $($step.file) → HTTP $status · $detail"
    if ($status -ne $step.status -or ($status -eq 403 -and $detail -notlike 'MAC_READ_UP_DENY*')) {
        throw '예상한 파일 접근 판정과 다릅니다.'
    }
}
