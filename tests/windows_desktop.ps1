$ErrorActionPreference = 'Stop'
$VerbosePreference = 'Continue'
$repo = Split-Path $PSScriptRoot -Parent
function Assert($Condition, $Message) { if (-not $Condition) { throw $Message } }
$temporary = Join-Path $env:TEMP ('viralogix-test-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $temporary | Out-Null
python (Join-Path $repo 'scripts/build_windows_bundle.py')
Expand-Archive -LiteralPath (Join-Path $repo 'dist/Viralogix-Windows.zip') -DestinationPath $temporary
. (Join-Path $temporary 'Viralogix/Viralogix.ps1') -TestMode
$views = @(); $profiles = @(); $browserProcesses = @()
try {
    $listing = (@('--list','--quiet') | ForEach-Object { Quote-Argument $_ }) -join ' '
    Assert ($listing -eq '--list --quiet') 'WSL switches must not be quoted into Linux commands'
    $execution = (@('--distribution','Ubuntu-24.04','--exec','id','-u') | ForEach-Object { Quote-Argument $_ }) -join ' '
    Assert ($execution -eq '--distribution Ubuntu-24.04 --exec id -u') 'WSL execution options were quoted'
    # Exercise the Windows WSL executable itself, not just Python's CRT parser.
    # --help does not need a distro and must never be routed into Bash.
    $wslHelp = Start-Owned 'wsl.exe' @('--help') -Unicode
    Assert ($wslHelp.Process.WaitForExit(30000)) 'Native WSL help timed out'
    $null = $wslHelp.Copy.GetAwaiter().GetResult()
    $helpText = Decode-WslOutput ($wslHelp.Bytes.ToArray()); $wslHelp.Bytes.Dispose()
    # Some Windows builds return a nonzero code for valid --help. Compare with
    # a literal bare-option invocation rather than assuming Unix help semantics.
    $baselineInfo = [Diagnostics.ProcessStartInfo]::new('wsl.exe','--help')
    $baselineInfo.UseShellExecute = $false; $baselineInfo.CreateNoWindow = $true
    $baselineInfo.RedirectStandardOutput = $true; $baselineInfo.RedirectStandardError = $true
    $baseline = [Diagnostics.Process]::Start($baselineInfo)
    $baselineOut = $baseline.StandardOutput.ReadToEndAsync(); $baselineErr = $baseline.StandardError.ReadToEndAsync()
    Assert ($baseline.WaitForExit(30000)) 'Native WSL baseline timed out'
    Assert ($wslHelp.Process.ExitCode -eq $baseline.ExitCode -and $helpText -match '--distribution' -and $helpText -match '--exec') ('Native WSL option parsing failed: ' + $helpText + $wslHelp.Err.Result)
    Write-Output 'Native wsl.exe option parsing passed.'
    foreach ($encoding in @('utf-8','utf-8-sig','utf-16','utf-16-le','utf-16-be')) {
        $code = 'import sys; sys.stdout.buffer.write(("Ubuntu\\r\\nUbuntu-24.04\\r\\n".replace("\\r",chr(13)).replace("\\n",chr(10))).encode("' + $encoding + '"))'
        if ($encoding -eq 'utf-16-be') { $code = 'import sys; sys.stdout.buffer.write(bytes([254,255])+"Ubuntu\\r\\nUbuntu-24.04\\r\\n".replace("\\r",chr(13)).replace("\\n",chr(10)).encode("utf-16-be"))' }
        $probe = Start-Owned 'python.exe' @('-c',$code) -Unicode
        Assert ($probe.Process.WaitForExit(15000)) 'WSL encoding fixture timed out'
        Assert ($probe.Process.ExitCode -eq 0) $probe.Err.Result
        $null = $probe.Copy.GetAwaiter().GetResult()
        $decoded = Decode-WslOutput ($probe.Bytes.ToArray()); $probe.Bytes.Dispose()
        Assert ($decoded -eq "Ubuntu`r`nUbuntu-24.04") ('WSL names corrupted for ' + $encoding)
    }
    $originalCapture = (Get-Item Function:Capture).ScriptBlock
    try {
        function Capture { return "Ubuntu-24.04`r`nUbuntu`r`n" }
        Assert ((@(Get-InstalledDistributions) -join ',') -eq 'Ubuntu-24.04,Ubuntu') 'Installed distribution names not preserved'
        function Capture { throw 'fixture WSL detection error' }
        $message = ''
        try { Get-InstalledDistributions } catch { $message = $_.Exception.Message }
        Assert ($message -like '*Could not read installed WSL distributions*fixture WSL detection error*') 'Detection failure was treated as missing Ubuntu'
    } finally { Set-Item Function:Capture $originalCapture }
    $scriptPath = Join-Path $repo 'scripts/windows/Viralogix.ps1'
    $tokens=$null; $errors=$null
    $null = [Management.Automation.Language.Parser]::ParseFile($scriptPath,[ref]$tokens,[ref]$errors)
    Assert ($errors.Count -eq 0) ($errors | Out-String)
    $values = @('--list','--distribution','Ubuntu-24.04','--exec','/home/jimi/miniconda3/bin/python','space and apostrophe''s','double"quote','C:\ends\','a&b;$x', '')
    $task = Start-Owned 'python.exe' (@('-c','import json,sys; print(json.dumps(sys.argv[1:]))') + $values)
    Assert ($task.Process.WaitForExit(15000)) 'Argument echo timed out'
    $actual = $task.Out.Result | ConvertFrom-Json
    Assert (($actual | ConvertTo-Json -Compress) -eq ($values | ConvertTo-Json -Compress)) 'Windows arguments changed'
    Write-Json (Join-Path $temporary 'state.json') @{session='test'; phase='starting'}
    Write-Json (Join-Path $temporary 'state.json') @{session='test'; phase='ready'}
    Assert ((Read-Json (Join-Path $temporary 'state.json')).phase -eq 'ready') 'Atomic control replacement failed'
    Add-Type -TypeDefinition @'
using System.IO;
using System.Threading;
using System.Threading.Tasks;
public static class ControlFileFixture {
 public static Task Hold(string path, int milliseconds, bool shareDelete) {
  var sharing = shareDelete ? FileShare.ReadWrite | FileShare.Delete : FileShare.Read;
  var reader = new FileStream(path, FileMode.Open, FileAccess.Read, sharing);
  return Task.Run(() => { try { Thread.Sleep(milliseconds); } finally { reader.Dispose(); } });
 }
}
'@
    $controlPath = Join-Path $temporary 'state.json'
    $readerLock = [ControlFileFixture]::Hold($controlPath,250,$false)
    Write-Json $controlPath @{session='test';phase='after-transient-lock'}
    $readerLock.Wait()
    Assert ((Read-Json $controlPath).phase -eq 'after-transient-lock') 'Transient reader lock stopped control updates'
    $readerLock = [ControlFileFixture]::Hold($controlPath,250,$true)
    Write-Json $controlPath @{session='test';phase='shared-reader'}
    $readerLock.Wait()
    Assert ((Read-Json $controlPath).phase -eq 'shared-reader') 'Delete-sharing reader prevented atomic replacement'
    $readerLock = [ControlFileFixture]::Hold($controlPath,3500,$false)
    $failure = ''
    try { Write-Json $controlPath @{session='test';phase='must-not-replace'} } catch { $failure = $_.Exception.Message }
    finally { $readerLock.Wait() }
    Assert ($failure -like '*state.json*Windows error*') 'Persistent lock failure lacked actionable diagnostics'
    Assert ((Read-Json $controlPath).phase -eq 'shared-reader') 'Failed replacement damaged last valid control file'
    Assert (@(Get-ChildItem $temporary -Filter '*.writing').Count -eq 0) 'Control temporary files leaked'
    $presence = @{ready=$false;missing_since=$null}
    $present = @{reachable=$true;pages=1}; $absent = @{reachable=$false;pages=0}
    Assert (-not (Update-BrowserPresence $presence $absent 0)) 'Startup was treated as a close'
    Assert (-not (Update-BrowserPresence $presence $present 1)) 'Live browser was treated as a close'
    Assert (-not (Update-BrowserPresence $presence $absent 2)) 'One missed response triggered shutdown'
    Assert (-not (Update-BrowserPresence $presence $absent 11.9)) 'Transient absence triggered shutdown'
    Assert (-not (Update-BrowserPresence $presence $present 12)) 'Restored browser triggered shutdown'
    Assert (-not (Update-BrowserPresence $presence $absent 13)) 'Recovery did not reset absence timer'
    Assert (Update-BrowserPresence $presence $absent 23) 'Sustained close was not detected'
    Assert (-not (Update-BrowserPresence $presence $present 24)) 'Live browser did not recover'
    Assert (-not (Update-BrowserPresence $presence @{reachable=$true;pages=0} 25)) 'One empty tab response triggered shutdown'
    Write-Output 'Control-file sharing, bounded retry, preservation and browser grace checks passed.'
    $shortcut = Join-Path $temporary 'Viralogix.lnk'
    New-Shortcut $temporary $shortcut
    $link = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcut)
    Assert ($link.IconLocation -eq ((Join-Path $temporary 'brand.ico') + ',0')) 'Shortcut icon not bound to app brand'
    Assert ($link.TargetPath -like '*wscript.exe') 'Silent shortcut entry missing'
    $script:AllowClose = $true
    $view = New-Progress 'Viralogix setup preview'
    $views += $view
    # Load the exact application asset used in the distribution bundle.
    $view.Form.Icon = New-Object Drawing.Icon((Join-Path $repo 'src/viralogix/assets/brand.ico'))
    Show-Stage $view 'Preparing Viralogix' 'Reusing your existing environment. Your pipelines, databases and completed work stay in place.'
    $view.Steps.Text = "Stage 3 of 5`r`nUbuntu  >  Conda  >  Viralogix  >  Viralogix  >  Desktop shortcut"
    $bitmap = New-Object Drawing.Bitmap($view.Form.Width, $view.Form.Height)
    $view.Form.DrawToBitmap($bitmap, (New-Object Drawing.Rectangle(0,0,$view.Form.Width,$view.Form.Height)))
    $bitmap.Save((Join-Path $repo 'windows-setup-preview.png')); $bitmap.Dispose()
    $view.Form.Hide()
    $browser = Find-Browser
    foreach ($name in @('owned','independent')) {
        $profile = Join-Path $temporary $name; $profiles += $profile
        $task = Start-Owned $browser @('--headless=new',"--user-data-dir=$profile",'--remote-debugging-port=0','--remote-debugging-address=127.0.0.1','--no-first-run','--disable-background-mode','about:blank')
        $browserProcesses += $task.Process
        $deadline = [Diagnostics.Stopwatch]::StartNew()
        while ($deadline.Elapsed.TotalSeconds -lt 45 -and -not (Browser-State $profile).reachable) { Start-Sleep -Milliseconds 200 }
        Assert ((Browser-State $profile).pages -ge 1) 'Dedicated browser was not observable'
    }
    Close-OwnedBrowser $profiles[0]
    # Headless Edge runs in this foreground process. Check actual termination:
    # its HTTP endpoint can briefly accept empty responses during teardown.
    Assert ($browserProcesses[0].WaitForExit(30000)) 'Owned browser process did not exit'
    Assert (-not $browserProcesses[1].HasExited) 'Independent browser process exited'
    Assert ((Browser-State $profiles[1]).reachable) 'Independent browser was affected'
    Write-Output 'Windows desktop checks passed: syntax, exact argument transport, atomic control, shortcut icon, installer render and isolated browser shutdown.'
} finally {
    foreach ($profile in $profiles) { Close-OwnedBrowser $profile }
    foreach ($view in $views) { $view.Form.Close(); $view.Form.Dispose() }
}
