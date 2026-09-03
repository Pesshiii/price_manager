<#
.SYNOPSIS
    Launch the price_manager Telegram group bot.

.DESCRIPTION
    Starts a long-running Claude Code session wired to the Telegram channel.
    This session IS the bot: one bot token allows exactly one getUpdates poller,
    so exactly one of these may run at a time. Starting a second one does not
    fail politely -- the new server.ts finds the old PID and SIGTERMs it.

    Preflight checks run first because each failure mode is silent otherwise:
    a missing bun means the MCP server never connects and the bot is simply
    deaf, with nothing in the group to indicate it.

.EXAMPLE
    .\.claude\telegram-bot\start-bot.ps1
#>
[CmdletBinding()]
param(
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
Write-Host "Starting bot session. Ctrl+C stops the bot and releases the token." -ForegroundColor Cyan
Write-Host ''

Set-Location $repo
& claude `
    --channels $plugin `
    --append-system-prompt-file '.claude/telegram-bot/BOT.md' `
    --settings '.claude/telegram-bot/settings.json'
