wpeinit

@rem some nic driver might need to be loaded first
@rem drvload X:\Windows\System32\DriverStore\FileRepository\net1ix64.inf_amd64_8961233d22dc4645\net1ix64.inf
@rem wpeutil initializenetwork
@rem wpeutil waitfornetwork
@rem ipconfig

@rem get samba path from wimboot transfered txt file and mount
set /p samba_share=<X:\Windows\System32\pxe_samba.txt
@rem for /f "tokens=1 delims=\\" %%A in ("%samba_share%") do set samba_ip=%%A
:retrysamba
@set /p = "." < nul
@rem ping %samba_ip%
@ping 127.0.0.1 -n 5 > nul
@net use z: %samba_share% > nul  2>&1
@if %errorlevel% neq 0 @goto :retrysamba

@rem this is for win11 to skip tpm check
@reg add "hklm\system\setup\labconfig" /v "bypasstpmcheck" /t reg_dword /d 1 /f

@rem call setup to auto install
z:\sources\setup.exe /unattend:X:\Windows\System32\pxe_autounattend.xml /m:z:\add-on
