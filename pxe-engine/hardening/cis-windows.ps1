# Systronaut -- CIS Benchmark baseline (Windows Server), applied at first boot.
#
# Served read-only by the PXE engine. The Windows unattend/runonce step fetches
# the per-host hardening.env + this script and runs it once, e.g.:
#
#   $h = Invoke-RestMethod http://<engine>/host/<mac>/hardening.env
#   Invoke-WebRequest http://<engine>/hardening/cis-windows.ps1 -OutFile C:\cis.ps1
#   powershell -ExecutionPolicy Bypass -File C:\cis.ps1
#
# Controls gated by HARDEN_* env vars sourced from hardening.env. Pragmatic
# CIS-aligned subset; map to a full CIS Microsoft Windows Server Benchmark /
# Microsoft Security Baseline (LGPO) for formal certification.
$ErrorActionPreference = "Continue"
function Log($m) { Write-Output "[cis] $m" }

# --- CIS baseline ------------------------------------------------------------
if ($env:HARDEN_CIS_BASELINE -eq "1") {
  Log "applying CIS baseline"
  # Account & password policy (CIS 1.1.x).
  secedit /export /cfg C:\secpol.cfg | Out-Null
  (Get-Content C:\secpol.cfg) `
    -replace 'MinimumPasswordLength = \d+', 'MinimumPasswordLength = 14' `
    -replace 'PasswordComplexity = \d+', 'PasswordComplexity = 1' `
    -replace 'LockoutBadCount = \d+', 'LockoutBadCount = 5' |
    Set-Content C:\secpol.cfg
  secedit /configure /db C:\Windows\security\local.sdb /cfg C:\secpol.cfg | Out-Null
  Remove-Item C:\secpol.cfg -ErrorAction SilentlyContinue

  # Disable SMBv1 (CIS 18.3.1).
  Disable-WindowsOptionalFeature -Online -FeatureName SMB1Protocol -NoRestart -ErrorAction SilentlyContinue | Out-Null
}

# --- Disk encryption: BitLocker (CIS 18.9.x) --------------------------------
if ($env:HARDEN_DISK_ENCRYPTION -eq "1") {
  Log "enabling BitLocker on C:"
  try { Enable-BitLocker -MountPoint "C:" -EncryptionMethod XtsAes256 -UsedSpaceOnly -TpmProtector -ErrorAction Stop }
  catch { Log "BitLocker not enabled (no TPM?): $_" }
}

# --- Remote access: RDP NLA (CIS 18.x) --------------------------------------
if ($env:HARDEN_REMOTE_ACCESS_HARDENING -eq "1") {
  Log "enforcing RDP Network Level Authentication"
  Set-ItemProperty 'HKLM:\System\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp' `
    -Name UserAuthentication -Value 1
}

# --- Host firewall default-deny inbound (CIS 9.x) ---------------------------
if ($env:HARDEN_HOST_FIREWALL -eq "1") {
  Log "firewall default-deny inbound"
  Set-NetFirewallProfile -Profile Domain,Public,Private -DefaultInboundAction Block -Enabled True
}

# --- Automatic updates (CIS 18.9.108) ---------------------------------------
if ($env:HARDEN_AUTO_UPDATES -eq "1") {
  Log "enabling automatic updates"
  $p = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU'
  New-Item -Path $p -Force | Out-Null
  Set-ItemProperty -Path $p -Name NoAutoUpdate -Value 0
  Set-ItemProperty -Path $p -Name AUOptions -Value 4
}

# --- Audit logging (CIS 17.x) -----------------------------------------------
if ($env:HARDEN_AUDIT_LOGGING -eq "1") {
  Log "enabling audit policy"
  auditpol /set /category:"Logon/Logoff" /success:enable /failure:enable | Out-Null
  auditpol /set /category:"Account Logon" /success:enable /failure:enable | Out-Null
  auditpol /set /category:"Policy Change" /success:enable /failure:enable | Out-Null
}

# --- Time sync (CIS 2.3.x) ---------------------------------------------------
if ($env:HARDEN_TIME_SYNC -eq "1") {
  Log "configuring w32time"
  w32tm /config /syncfromflags:domhier /update | Out-Null
  Restart-Service w32time -ErrorAction SilentlyContinue
}

Log "done"
