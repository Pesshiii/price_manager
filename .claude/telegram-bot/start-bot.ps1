<#
.SYNOPSIS
    Launch the price_manager Telegram group bot.

.DESCRIPTION
    Starts a long-running Claude Code session wired to the Telegram channel.
    This session IS the bot: one bot token allows exactly one getUpdates poller,
    so exactly one of these may run at a time. Starting a second one does not
    fail politely -- the new server.ts finds the old PID and SIGTERMs it.

    The session runs unattended in auto permission mode. The bot answers the
    group itself and delegates the slow work -- code questions, GitHub issue
    mutations, digests -- to the tg-analyst / tg-tracker / tg-digest subagents.

    Preflight checks run first because each failure mode is silent otherwise:
    a missing bun means the MCP server never connects and the bot is simply
    deaf, with nothing in the group to indicate it.

.EXAMPLE
    .\.claude\telegram-bot\start-bot.ps1

.EXAMPLE
    .\.claude\telegram-bot\start-bot.ps1 -Model sonnet
    Run the conversational half on a faster model. The subagents keep the models
    pinned in their own frontmatter, so this trades only the bot's own
    routing-and-relay quality -- including its untrusted-input judgement -- for
    time to first word. Left unset, the session uses your configured default.
#>
[CmdletBinding()]
param(
    # Model for the bot session itself. Unset means your configured default.
    [string]$Model,

    # Permission mode. 'auto' is what makes the bot unattended: a prompt raised
    # while handling a group message can only be answered from the operator's
    # DM, so anything that would prompt is a silent stall in the group. The deny
    # list in settings.json still applies on top of this.
    [ValidateSet('auto', 'acceptEdits', 'bypassPermissions', 'dontAsk', 'manual', 'plan')]
    [string]$PermissionMode = 'auto',

    # Skip preflight and launch anyway.
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$plugin = 'plugin:telegram@claude-plugins-official'
$problems = @()

Write-Host "price_manager Telegram bot" -ForegroundColor Cyan
Write-Host "repo: $repo"
Write-Host ''

# --- bun: the MCP server's runtime. Without it the channel never connects. ---
$bun = Get-Command bun -ErrorAction SilentlyContinue
if ($null -eq $bun) {
    $problems += "bun is not on PATH. The telegram MCP server runs on bun and cannot start without it.`n     Install:  npm install -g bun`n     Or:       powershell -c ""irm bun.sh/install.ps1 | iex"""
} else {
    Write-Host "[ok] bun $(& bun --version)" -ForegroundColor Green
}

# --- gh: every issue operation goes through it. ---
$gh = Get-Command gh -ErrorAction SilentlyContinue
if ($null -eq $gh) {
    $problems += "gh (GitHub CLI) is not on PATH. The bot cannot create or close issues without it."
} else {
    & gh auth status 2>&1 | Out-Null
    if ($?) {
        Write-Host "[ok] gh authenticated" -ForegroundColor Green
    } else {
        $problems += "gh is installed but not authenticated. Run: gh auth login"
    }
}

# --- bot token ---
$envFile = Join-Path $env:USERPROFILE '.claude\channels\telegram\.env'
if (Test-Path $envFile) {
    Write-Host "[ok] bot token present" -ForegroundColor Green
} else {
    $problems += "No bot token at $envFile. Run /telegram:configure <token> in a Claude Code session."
}

# --- group allowlist: absent access.json means DM-only, groups silently dropped ---
$accessFile = Join-Path $env:USERPROFILE '.claude\channels\telegram\access.json'
if (Test-Path $accessFile) {
    $access = Get-Content $accessFile -Raw | ConvertFrom-Json
    $groups = @()
    if ($access.PSObject.Properties.Name -contains 'groups') {
        $groups = @($access.groups.PSObject.Properties.Name)
    }
    if ($groups.Count -eq 0) {
        $problems += "access.json has no groups enabled -- every group message will be dropped.`n     Run:  /telegram:access group add <-100...> --no-mention"
    } else {
        Write-Host "[ok] groups enabled: $($groups -join ', ')" -ForegroundColor Green
        foreach ($g in $groups) {
            if ($access.groups.$g.requireMention -ne $false) {
                Write-Host "[warn] group $g has requireMention=true -- ambient capture is OFF, the bot will only see @mentions and replies." -ForegroundColor Yellow
            }
        }
    }
} else {
    $problems += "No access.json yet -- policy is 'pairing' and no group is enabled.`n     Pair your DM first, then:  /telegram:access group add <-100...> --no-mention"
}

# --- the subagents the bot delegates to ---
$agents = 'tg-analyst', 'tg-tracker', 'tg-digest'
$missingAgents = @($agents | Where-Object { -not (Test-Path (Join-Path $repo ".claude\agents\$_.md")) })
if ($missingAgents.Count -gt 0) {
    $problems += "Missing subagent definitions: $($missingAgents -join ', '). The bot delegates every slow job to these; without them it has nothing to hand work to."
} else {
    Write-Host "[ok] subagents present: $($agents -join ', ')" -ForegroundColor Green
}

# --- exclusive poller. Telegram allows exactly one getUpdates consumer per
#     token, and on Windows the plugin CANNOT enforce that itself: server.ts
#     verifies a stale holder with `ps -p <pid> -o args=` before SIGTERM, `ps`
#     does not exist here, execFileSync throws, and the bare catch swallows it.
#     The new server then overwrites bot.pid and starts polling anyway -- so two
#     pollers thrash on 409 Conflict and the bot receives nothing at all. Any
#     other Claude session with the telegram plugin loaded (the desktop app
#     counts, and does not announce itself) is that second poller. ---
$rivals = @(Get-CimInstance Win32_Process -Filter "Name='bun.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match 'telegram' -and $_.CommandLine -match 'server\.ts|--cwd' })
if ($rivals.Count -gt 0) {
    $owners = foreach ($r in $rivals) {
        $id = $r.ParentProcessId; $owner = $null; $hops = 0
        while ($id -and $hops -lt 6) {
            $anc = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
            if (-not $anc) { break }
            if ($anc.Name -eq 'claude.exe') { $owner = $anc.ProcessId; break }
            $id = $anc.ParentProcessId; $hops++
        }
        if ($owner) { "bun pid $($r.ProcessId) owned by claude pid $owner" } else { "bun pid $($r.ProcessId)" }
    }
    $problems += "A telegram MCP server is already polling: $($owners -join '; ').`n     Telegram allows one consumer per token, and the plugin's stale-poller kill is broken on Windows (it shells out to ``ps``), so launching now gives you two pollers fighting over 409 Conflict -- the bot starts, receives nothing, and looks broken.`n     Close the Claude session that owns it (the desktop app counts), or kill the process, then re-run."
} else {
    Write-Host "[ok] no rival telegram poller" -ForegroundColor Green
}

# --- capture round trip: the log is the bot's only memory, and a broken
#     capture.py fails silently (the hook swallows its own exceptions). ---
$probe = Join-Path ([System.IO.Path]::GetTempPath()) ("tgcapture_" + [guid]::NewGuid().ToString('N'))
try {
    $payload = '{"prompt":"<channel source=\"telegram\" chat_id=\"-1\" message_id=\"1\" user=\"probe\" ts=\"2026-01-01T00:00:00+00:00\">проверка</channel>"}'
    $env:TG_BOT_STATE = $probe
    $payload | & python (Join-Path $repo '.claude\telegram-bot\capture.py') hook | Out-Null
    $stats = & python (Join-Path $repo '.claude\telegram-bot\capture.py') stats | ConvertFrom-Json
    if ($stats.messages -ge 1) {
        Write-Host "[ok] capture.py round trip (unicode + jsonl write)" -ForegroundColor Green
    } else {
        $problems += "capture.py ran but wrote nothing. Every message the group sends would be lost, and no digest would ever be correct."
    }
} catch {
    $problems += "capture.py failed to run: $($_.Exception.Message)"
} finally {
    Remove-Item env:TG_BOT_STATE -ErrorAction SilentlyContinue
    Remove-Item $probe -Recurse -Force -ErrorAction SilentlyContinue
}

if ($problems.Count -gt 0) {
    Write-Host ''
    Write-Host "Preflight found $($problems.Count) problem(s):" -ForegroundColor Yellow
    foreach ($p in $problems) { Write-Host "  - $p" -ForegroundColor Yellow }
    Write-Host ''
    if (-not $Force) {
        Write-Host "Fix these, or re-run with -Force to launch anyway." -ForegroundColor Yellow
        exit 1
    }
    Write-Host "-Force given, launching regardless." -ForegroundColor Yellow
}

Write-Host ''
Write-Host "Starting bot session (permission mode: $PermissionMode). Ctrl+C stops the bot and releases the token." -ForegroundColor Cyan
Write-Host ''

$claudeArgs = @(
    '--channels', $plugin,
    '--append-system-prompt-file', '.claude/telegram-bot/BOT.md',
    '--settings', '.claude/telegram-bot/settings.json',
    '--permission-mode', $PermissionMode
)
if ($Model) { $claudeArgs += @('--model', $Model) }

# The project Stop hook (suggest_record.py) fires after every turn, including
# the silent capture-only ones that are most of a busy group. It shells out to
# git twice and can never fire usefully here -- the bot does not edit code -- so
# it short-circuits on this flag rather than costing a process per message.
$env:TG_BOT_SESSION = '1'

Set-Location $repo
& claude @claudeArgs
