param([switch]$Setup, [string]$Distro = 'Ubuntu', [switch]$TestMode)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
[Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)
$script:Root = Join-Path $env:LOCALAPPDATA 'Viralogix'
$script:Utf8 = New-Object System.Text.UTF8Encoding($false)

function Quote-Argument([string]$Value) {
    # WSL's option parser does not treat quoted switches like CRT argv.
    # Keep simple options/names bare; quote values that need escaping.
    if ($Value -match '\A[A-Za-z0-9_./:\\=-]+\z') { return $Value }
    $result = '"'; $slashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') { $slashes++; continue }
        if ($character -eq '"') { $result += ('\' * (2 * $slashes + 1)) + '"' }
        else { $result += ('\' * $slashes) + $character }
        $slashes = 0
    }
    return $result + ('\' * (2 * $slashes)) + '"'
}
function Start-Owned([string]$Executable, [string[]]$Arguments, [switch]$Unicode, [switch]$Visible) {
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $Executable
    $info.Arguments = (($Arguments | ForEach-Object { Quote-Argument $_ }) -join ' ')
    $info.UseShellExecute = $false
    $info.CreateNoWindow = -not $Visible
    $info.RedirectStandardOutput = -not $Visible
    $info.RedirectStandardError = -not $Visible
    if (-not $Visible) {
        $info.StandardOutputEncoding = $(if ($Unicode) { [Text.Encoding]::Unicode } else { [Text.Encoding]::UTF8 })
        $info.StandardErrorEncoding = [Text.Encoding]::UTF8
    }
    $process = [Diagnostics.Process]::Start($info)
    $bytes = $null; $copy = $null; $output = $null
    if ($Unicode -and -not $Visible) {
        $bytes = New-Object IO.MemoryStream
        $copy = $process.StandardOutput.BaseStream.CopyToAsync($bytes)
    } elseif (-not $Visible) { $output = $process.StandardOutput.ReadToEndAsync() }
    return [pscustomobject]@{ Process = $process; Out = $output; Bytes = $bytes; Copy = $copy; Err = $(if (-not $Visible) { $process.StandardError.ReadToEndAsync() }) }
}
function Decode-WslOutput([byte[]]$Bytes) {
    # WSL versions/settings emit either UTF-8 or UTF-16, with or without BOM.
    if ($Bytes.Length -ge 2 -and $Bytes[0] -eq 254 -and $Bytes[1] -eq 255) { $encoding = [Text.Encoding]::BigEndianUnicode }
    elseif (($Bytes.Length -ge 2 -and $Bytes[0] -eq 255 -and $Bytes[1] -eq 254) -or $Bytes -contains 0) { $encoding = [Text.Encoding]::Unicode }
    else { $encoding = [Text.Encoding]::UTF8 }
    return $encoding.GetString($Bytes).Trim([char]0xFEFF).Trim()
}
function Get-InstalledDistributions {
    try { $output = Capture @('--list','--quiet') -Unicode }
    catch { throw ('Could not read installed WSL distributions. No Ubuntu installation was requested. Run wsl --list --verbose in Windows to check WSL, then retry Setup. Details: ' + $_.Exception.Message) }
    return @($output -split "`r?`n" | ForEach-Object { $_.Trim().Trim([char]0xFEFF) } | Where-Object { $_ })
}
function Capture([string[]]$Arguments, [switch]$Unicode) {
    $task = Start-Owned 'wsl.exe' $Arguments -Unicode:$Unicode
    $deadline = [Diagnostics.Stopwatch]::StartNew()
    while (-not $task.Process.WaitForExit(100)) {
        [Windows.Forms.Application]::DoEvents()
        if ($deadline.Elapsed.TotalSeconds -gt 45) { $task.Process.Kill(); throw 'Ubuntu did not respond. Open Ubuntu to finish initialization, then retry.' }
    }
    if ($task.Process.ExitCode -ne 0) { throw $task.Err.Result }
    if ($Unicode) {
        $null = $task.Copy.GetAwaiter().GetResult()
        try { return Decode-WslOutput $task.Bytes.ToArray() } finally { $task.Bytes.Dispose() }
    }
    return $task.Out.Result.Trim().Replace([string][char]0, '')
}
function Write-Json([string]$Path, $Value) {
    $temporary = $Path + '.' + [Guid]::NewGuid().ToString('N') + '.writing'
    try {
        [IO.File]::WriteAllText($temporary, ($Value | ConvertTo-Json -Depth 8 -Compress), $script:Utf8)
        $deadline = [Diagnostics.Stopwatch]::StartNew()
        while (-not [ViraFiles]::MoveFileEx($temporary, $Path, 1)) {
            $code = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
            # WSL readers and scanners can briefly deny replacement on NTFS.
            # Keep the old complete JSON while retrying only sharing/access errors.
            if ($code -notin @(5,32,33) -or $deadline.Elapsed.TotalSeconds -ge 2) {
                throw "Could not update desktop control file '$Path' (Windows error $code)."
            }
            # No DoEvents here: a heartbeat callback must not reenter this write.
            Start-Sleep -Milliseconds 25
        }
    } finally { if ([IO.File]::Exists($temporary)) { Remove-Item -LiteralPath $temporary -ErrorAction SilentlyContinue } }
}
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ViraFiles {
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
 public static extern bool MoveFileEx(string from, string to, int flags);
}
'@
function Read-SharedText([string]$Path) {
    $stream = [IO.FileStream]::new($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
    try {
        $reader = [IO.StreamReader]::new($stream, [Text.Encoding]::UTF8, $true)
        try { return $reader.ReadToEnd() } finally { $reader.Dispose() }
    } finally { $stream.Dispose() }
}
function Read-Json([string]$Path) {
    try { return ((Read-SharedText $Path) | ConvertFrom-Json) }
    catch { return $null }
}
function New-Progress([string]$Title) {
    $form = New-Object Windows.Forms.Form
    $form.Text = $Title; $form.ClientSize = New-Object Drawing.Size(680, 450)
    $form.StartPosition = 'CenterScreen'; $form.BackColor = [Drawing.ColorTranslator]::FromHtml('#F5F8FF')
    $form.Font = New-Object Drawing.Font('Segoe UI', 10)
    $form.FormBorderStyle = 'FixedDialog'; $form.MaximizeBox = $false
    $icon = Join-Path $PSScriptRoot 'brand.ico'
    if (Test-Path $icon) { $form.Icon = New-Object Drawing.Icon($icon) }
    $banner = New-Object Windows.Forms.Panel
    $banner.SetBounds(0,0,680,100); $banner.BackColor = [Drawing.ColorTranslator]::FromHtml('#102D56')
    $picture = New-Object Windows.Forms.PictureBox
    $picture.SetBounds(30,22,49,56); $picture.SizeMode = 'Zoom'
    $png = Join-Path $PSScriptRoot 'brand.png'
    if (Test-Path $png) { $picture.Image = [Drawing.Image]::FromFile($png) }
    $brand = New-Object Windows.Forms.Label
    $brand.Text = 'Virologix'; $brand.SetBounds(96,19,500,39)
    $brand.Font = New-Object Drawing.Font('Segoe UI',25,[Drawing.FontStyle]::Bold); $brand.ForeColor = [Drawing.Color]::White
    $tag = New-Object Windows.Forms.Label
    $tag.Text = 'HUMAN LINK GenoMix'; $tag.SetBounds(100,63,470,24)
    $tag.Font = New-Object Drawing.Font('Segoe UI',9); $tag.ForeColor = [Drawing.ColorTranslator]::FromHtml('#93C5FD')
    $banner.Controls.AddRange(@($picture,$brand,$tag)); $form.Controls.Add($banner)
    $heading = New-Object Windows.Forms.Label
    $heading.SetBounds(30,124,620,38); $heading.Font = New-Object Drawing.Font('Segoe UI',17,[Drawing.FontStyle]::Bold)
    $detail = New-Object Windows.Forms.Label
    $detail.SetBounds(32,172,610,66); $detail.ForeColor = [Drawing.ColorTranslator]::FromHtml('#52676B')
    $bar = New-Object Windows.Forms.ProgressBar
    $bar.SetBounds(32,254,610,12); $bar.Style = 'Marquee'; $bar.MarqueeAnimationSpeed = 28
    $steps = New-Object Windows.Forms.Label
    $steps.SetBounds(32,290,610,75); $steps.ForeColor = [Drawing.ColorTranslator]::FromHtml('#2563EB')
    $steps.Text = 'Ubuntu  >  Conda  >  viromics  >  Virologix  >  Shortcut'
    $footer = New-Object Windows.Forms.Label
    $footer.SetBounds(32,388,610,32); $footer.Text = 'Your pipelines, databases and completed work stay in place.'
    $footer.ForeColor = [Drawing.ColorTranslator]::FromHtml('#52676B')
    $form.Controls.AddRange(@($heading,$detail,$bar,$steps,$footer))
    $form.Add_FormClosing({ if (-not $script:AllowClose) { $_.Cancel = $true } })
    return [pscustomobject]@{ Form=$form; Heading=$heading; Detail=$detail; Bar=$bar; Steps=$steps; Footer=$footer }
}
function Show-Stage($View, [string]$Title, [string]$Detail) {
    $View.Heading.Text = $Title; $View.Detail.Text = $Detail
    if (-not $View.Form.Visible) { $View.Form.Show() }
    [Windows.Forms.Application]::DoEvents()
}
function New-Shortcut([string]$Directory, [string]$Destination) {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($Destination)
    $shortcut.TargetPath = Join-Path $env:WINDIR 'System32\wscript.exe'
    $shortcut.Arguments = Quote-Argument (Join-Path $Directory 'Viralogix.vbs')
    $shortcut.WorkingDirectory = $Directory
    $shortcut.IconLocation = (Join-Path $Directory 'brand.ico') + ',0'
    $shortcut.Description = 'Virologix - Human Link GenoMix virology workspace'
    $shortcut.Save()
}
function Find-Browser {
    foreach ($name in @('Microsoft\Edge\Application\msedge.exe','Google\Chrome\Application\chrome.exe')) {
        foreach ($base in @($env:ProgramFiles,${env:ProgramFiles(x86)},$env:LOCALAPPDATA)) {
            if ($base) { $path = Join-Path $base $name; if (Test-Path -LiteralPath $path) { return $path } }
        }
    }
    throw 'Install Microsoft Edge or Google Chrome before using the desktop launcher.'
}
function Browser-Endpoint([string]$Profile) {
    $file = Join-Path $Profile 'DevToolsActivePort'
    if (-not (Test-Path -LiteralPath $file)) { return $null }
    try { $lines = (Read-SharedText $file) -split "`r?`n" } catch { return $null }
    if ($lines.Length -lt 2 -or $lines[0] -notmatch '^\d{1,5}$' -or [int]$lines[0] -gt 65535 -or $lines[1] -notmatch '^/devtools/browser/[a-zA-Z0-9-]+$') { return $null }
    return @{ port=$lines[0]; socket=$lines[1] }
}
function Browser-State([string]$Profile) {
    $endpoint = Browser-Endpoint $Profile
    if (-not $endpoint) { return @{ reachable=$false; pages=0 } }
    try {
        $request = [Net.HttpWebRequest]::Create("http://127.0.0.1:$($endpoint.port)/json/list")
        $request.CachePolicy = [Net.Cache.RequestCachePolicy]::new([Net.Cache.RequestCacheLevel]::NoCacheNoStore)
        $request.Proxy = $null; $request.Timeout = 1000
        $response = $request.GetResponse()
        try {
            $reader = New-Object IO.StreamReader($response.GetResponseStream())
            $rows = $reader.ReadToEnd() | ConvertFrom-Json
        } finally { $response.Dispose() }
        return @{ reachable=$true; pages=@($rows | Where-Object { $_.type -eq 'page' }).Count }
    } catch { return @{ reachable=$false; pages=0 } }
}
function Update-BrowserPresence($Presence, $Observed, [double]$Seconds) {
    if ($Observed.reachable -and $Observed.pages -gt 0) {
        $Presence.ready = $true; $Presence.missing_since = $null
        return $false
    }
    if (-not $Presence.ready) { return $false }
    if ($null -eq $Presence.missing_since) { $Presence.missing_since = $Seconds }
    # A resize, minimization or busy browser is not a close event. Require a
    # sustained absence; the heartbeat continues during this grace period.
    return ($Seconds - $Presence.missing_since -ge 10)
}
function Close-OwnedBrowser([string]$Profile) {
    $endpoint = Browser-Endpoint $Profile
    if (-not $endpoint) { return }
    $socket = New-Object Net.WebSockets.ClientWebSocket
    $cancel = New-Object Threading.CancellationTokenSource
    $cancel.CancelAfter(2000)
    try {
        $socket.Options.Proxy = $null
        $null = $socket.ConnectAsync([Uri]"ws://127.0.0.1:$($endpoint.port)$($endpoint.socket)", $cancel.Token).GetAwaiter().GetResult()
        $bytes = [Text.Encoding]::UTF8.GetBytes('{"id":1,"method":"Browser.close"}')
        $segment = [ArraySegment[byte]]::new($bytes)
        $null = $socket.SendAsync($segment, [Net.WebSockets.WebSocketMessageType]::Text, $true, $cancel.Token).GetAwaiter().GetResult()
        # Do not abort the connection immediately after sending: wait for the
        # browser to consume the request and acknowledge or close the socket.
        $buffer = New-Object byte[] 4096
        $reply = [ArraySegment[byte]]::new($buffer)
        $received = $socket.ReceiveAsync($reply, $cancel.Token).GetAwaiter().GetResult()
        Write-Verbose ('Browser close reply: ' + [Text.Encoding]::UTF8.GetString($buffer,0,$received.Count))
    } catch { Write-Verbose ('Browser close: ' + $_.Exception.Message) } finally { $socket.Dispose(); $cancel.Dispose() }
}

function Save-Log($Task, [string]$Path) {
    if ($Task -and $Task.Process.HasExited) { [IO.File]::WriteAllText($Path, $Task.Out.Result + $Task.Err.Result, $script:Utf8) }
}
function Install-Desktop($View) {
    Show-Stage $View 'Checking Windows and Ubuntu' 'Checking the installed WSL distributions. Administrator prompts appear only when Windows needs them.'
    $names = @(Get-InstalledDistributions)
    if ($Distro -eq 'Ubuntu' -and $Distro -notin $names) {
        $existing = @($names | Where-Object { $_ -like 'Ubuntu*' })
        if ($existing.Count -gt 0) { $Distro = $existing[0] }
    }
    if ($Distro -notin $names) {
        $answer = [Windows.Forms.MessageBox]::Show("Ubuntu ($Distro) is not installed. Install it now? Windows may request administrator permission and a restart.", 'Viralogix setup', 'YesNo','Question')
        if ($answer -eq 'Yes') {
            $install = Start-Process wsl.exe -ArgumentList ('--install --distribution ' + (Quote-Argument $Distro) + ' --no-launch') -Verb RunAs -PassThru
            while (-not $install.WaitForExit(200)) { [Windows.Forms.Application]::DoEvents() }
        }
        throw "Finish Windows' WSL installation, restart Windows if requested, then open Ubuntu once to create your Linux username and password. Run Viralogix Setup again afterwards."
    }
    if ((Capture @('--distribution',$Distro,'--exec','id','-u')) -eq '0') {
        throw 'Ubuntu is using root. Open Ubuntu and finish creating your regular Linux user, then rerun Setup. Viralogix is installed as that user.'
    }
    Show-Stage $View 'Ubuntu is ready' "Using $Distro as your regular Linux user. Checking prerequisites."
    $null = Find-Browser
    try { $null = Capture @('--distribution',$Distro,'--exec','python3','--version') }
    catch { throw 'Ubuntu needs Python 3. Open Ubuntu and run: sudo apt update && sudo apt install -y python3 git ca-certificates . Then rerun Setup.' }
    New-Item -ItemType Directory -Force -Path $script:Root | Out-Null
    foreach ($name in @('Viralogix.ps1','Viralogix.vbs','Viralogix.cmd','Viralogix-Setup.cmd','install_viralogix.py','brand.ico','brand.png')) {
        $source = Join-Path $PSScriptRoot $name; $target = Join-Path $script:Root $name
        if ([IO.Path]::GetFullPath($source) -ne [IO.Path]::GetFullPath($target)) { Copy-Item -LiteralPath $source -Destination $target -Force }
    }
    $linuxRoot = Capture @('--distribution',$Distro,'--exec','wslpath','-u',$script:Root)
    $result = Join-Path $script:Root 'setup-result.json'
    Remove-Item -LiteralPath $result -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $script:Root 'setup-status.json') -ErrorAction SilentlyContinue
    $task = Start-Owned 'wsl.exe' @('--distribution',$Distro,'--exec','python3',"$linuxRoot/install_viralogix.py",'--install-conda','--upgrade-app','--no-launch','--status-file',"$linuxRoot/setup-status.json",'--result-file',"$linuxRoot/setup-result.json")
    try {
        while (-not $task.Process.WaitForExit(200)) {
            $status = Read-Json (Join-Path $script:Root 'setup-status.json')
            if ($status) {
                Show-Stage $View $status.title $status.detail
                $View.Steps.Text = "Stage $($status.step) of 5`r`nUbuntu  >  Conda  >  viromics  >  Virologix  >  Shortcut"
            }
            [Windows.Forms.Application]::DoEvents()
        }
    } finally { Save-Log $task (Join-Path $script:Root 'setup.log') }
    if ($task.Process.ExitCode -ne 0) {
        $logPath = Join-Path $script:Root 'setup.log'
        $details = (Get-Content -LiteralPath $logPath -Tail 16 -ErrorAction SilentlyContinue) -join "`r`n"
        throw "Application setup stopped.`r`n$details`r`nFull log: $logPath"
    }
    $installed = Read-Json $result
    if (-not $installed.python) { throw 'The installer did not record a Python environment.' }
    $null = Capture @('--distribution',$Distro,'--exec',$installed.python,'-c','import viralogix.desktop')
    Write-Json (Join-Path $script:Root 'installation.json') @{ distro=$Distro; python=$installed.python }
    New-Shortcut $script:Root (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Virologix.lnk')
    Show-Stage $View 'Ready for your next discovery' 'Viralogix is installed. Use the desktop shortcut for a silent Ubuntu launch and controlled shutdown.'
    $View.Bar.Style = 'Continuous'; $View.Bar.Value = 100
    $View.Steps.Text = 'Ubuntu checked   |   Environment ready   |   Shortcut created'
    [Windows.Forms.MessageBox]::Show('Setup complete. Double-click the Viralogix desktop icon to open the app.', 'Virologix', 'OK', 'Information') | Out-Null
}
function Run-Desktop($View) {
    $installed = Read-Json (Join-Path $script:Root 'installation.json')
    if (-not $installed.python -or -not $installed.distro) { throw 'Run Viralogix-Setup.cmd first to create the desktop installation.' }
    $browser = Find-Browser
    $id = [Guid]::NewGuid().ToString('N')
    $directory = Join-Path $script:Root "sessions\$id"
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $linuxDirectory = Capture @('--distribution',$installed.distro,'--exec','wslpath','-u',$directory)
    $heartbeat = { Write-Json (Join-Path $directory 'heartbeat.json') @{session=$id; time=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()} }
    $request = { param($action) Write-Json (Join-Path $directory 'request.json') @{session=$id; action=$action; nonce=[Guid]::NewGuid().ToString('N')} }
    & $heartbeat
    $task = Start-Owned 'wsl.exe' @('--distribution',$installed.distro,'--exec',$installed.python,'-m','viralogix.cli','serve','--desktop-control',$linuxDirectory,'--desktop-session',$id,'--no-browser')
    $window = $null; $opened = $false; $closing = $false; $browserRequest = $null; $asked = $false
    $profile = Join-Path $directory 'browser'
    $browserReady = $false; $browserClock = $null
    $clock = [Diagnostics.Stopwatch]::StartNew()
    Show-Stage $View 'Opening your workspace' 'Starting Viralogix inside Ubuntu. No terminal needs to stay open.'
    try {
        while (-not $task.Process.WaitForExit(250)) {
            & $heartbeat
            $status = Read-Json (Join-Path $directory 'status.json')
            if (-not $status -or $status.session -ne $id) {
                if ($clock.Elapsed.TotalSeconds -gt 90) { throw 'Desktop startup did not respond. The supervisor will request cancellation; check the session log.' }
                [Windows.Forms.Application]::DoEvents(); continue
            }
            if ($status.phase -eq 'ready' -and -not $opened) {
                $uri = [Uri]$status.url
                if ($uri.Scheme -ne 'http' -or $uri.AbsolutePath -ne '/' -or $uri.Query -or $uri.Fragment -or $uri.UserInfo) { throw 'Invalid local application address.' }
                $window = Start-Owned $browser @("--user-data-dir=$profile",'--no-first-run','--no-default-browser-check','--disable-background-mode','--remote-debugging-port=0','--remote-debugging-address=127.0.0.1',"--app=$($status.url)",'--window-size=1440,1000')
                $opened = $true; $closing = $false; $browserReady = $false
                $presence = @{ ready=$false; missing_since=$null }
                $browserClock = [Diagnostics.Stopwatch]::StartNew(); $View.Form.Hide()
            }
            if ($status.browser_request -and $status.browser_request -ne $browserRequest) {
                $browserRequest = $status.browser_request
                $null = Start-Owned $browser @("--user-data-dir=$profile",'--disable-background-mode','--new-window',$status.url)
            }
            if ($opened -and -not $closing) {
                $browserState = Browser-State $profile
                $browserClosed = Update-BrowserPresence $presence $browserState $browserClock.Elapsed.TotalSeconds
                $browserReady = $presence.ready
                if ($browserClosed) {
                    Close-OwnedBrowser $profile
                    & $request 'close'; $closing = $true
                } elseif (-not $browserReady -and $browserClock.Elapsed.TotalSeconds -gt 30) {
                    throw 'The dedicated browser did not become ready. Check local browser policies; this session will stop.'
                }
            }
            if ($status.phase -eq 'ready') { $asked = $false }
            if ($status.phase -eq 'confirming' -and -not $asked) {
                $asked = $true
                # Keep the lease alive while the native dialog is open.
                $timer = New-Object Windows.Forms.Timer; $timer.Interval = 1000
                $timer.Add_Tick($heartbeat); $timer.Start()
                try { $answer = [Windows.Forms.MessageBox]::Show("$($status.jobs) job(s) belong to this window. Stop them and exit? Completed work is retained. Select No to reopen Viralogix.", 'Stop analyses and exit?', 'YesNo', 'Question') }
                finally { $timer.Stop(); $timer.Dispose() }
                if ($answer -eq 'Yes') { & $request 'confirm_close' }
                else { & $request 'reopen'; $opened = $false }
            }
            if ($status.phase -eq 'stopping') {
                $message = if ($status.installing_update) { 'Finishing the application update safely before exit.' } else { 'Stopping only this session''s jobs and allowing cleanup. Other Ubuntu work stays running.' }
                Show-Stage $View 'Closing Viralogix' $message
            }
            [Windows.Forms.Application]::DoEvents()
        }
    } finally {
        if (-not $task.Process.HasExited -and -not (Read-Json (Join-Path $directory 'status.json'))) {
            $task.Process.Kill() # Only our Windows startup client; no UI or jobs were admitted.
        }
        if (-not $task.Process.HasExited) {
            & $request 'confirm_close'
            # Keep the supervisor visible until owned work has actually stopped.
            Show-Stage $View 'Stopping this session' 'Waiting for owned jobs to clean up. Other Ubuntu processes are untouched.'
            while (-not $task.Process.WaitForExit(250)) { & $heartbeat; [Windows.Forms.Application]::DoEvents() }
        }
        Save-Log $task (Join-Path $directory 'launcher.log')
        Close-OwnedBrowser $profile
        if ($window -and -not $window.Process.HasExited) { $null = $window.Process.CloseMainWindow() }
    }
    if ($task.Process.ExitCode -ne 0) { throw "Viralogix stopped unexpectedly. See $directory\launcher.log ." }
}
if (-not $TestMode) {
    $script:AllowClose = $false
    $view = New-Progress $(if ($Setup) { 'Virologix Setup' } else { 'Virologix' })
    try { if ($Setup) { Install-Desktop $view } else { Run-Desktop $view } }
    catch {
        Show-Stage $view 'A step needs your attention' $_.Exception.Message
        $view.Bar.Style = 'Continuous'; $view.Bar.Value = 0
        [Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Virologix', 'OK', 'Warning') | Out-Null
    } finally { $script:AllowClose = $true; $view.Form.Close(); $view.Form.Dispose() }
}
