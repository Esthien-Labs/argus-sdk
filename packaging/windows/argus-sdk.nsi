Unicode true
ManifestDPIAware true
RequestExecutionLevel user

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "StrFunc.nsh"
!include "WinMessages.nsh"
${Using:StrFunc} StrStr
${Using:StrFunc} UnStrRep

!ifndef ARGUS_PAYLOAD_EXE
  !error "ARGUS_PAYLOAD_EXE must point to the PyInstaller executable payload."
!endif
!ifndef ARGUS_TARGET_ARCH
  !error "ARGUS_TARGET_ARCH must identify the payload architecture."
!endif
!ifndef ARGUS_VERSION
  !define ARGUS_VERSION "0.7.4"
!endif
!ifndef ARGUS_OUTFILE
  !define ARGUS_OUTFILE "ArgusSDK-${ARGUS_VERSION}-windows-${ARGUS_TARGET_ARCH}-setup.exe"
!endif
!ifndef ARGUS_LICENSE_FILE
  !define ARGUS_LICENSE_FILE "LICENSE"
!endif

!define PRODUCT_NAME "Argus SDK"
!define PRODUCT_PUBLISHER "Esthien Labs"
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\Esthien Argus SDK"

Name "${PRODUCT_NAME} ${ARGUS_VERSION}"
OutFile "${ARGUS_OUTFILE}"
InstallDir "$LOCALAPPDATA\Programs\Esthien\Argus SDK"
InstallDirRegKey HKCU "${UNINSTALL_KEY}" "InstallLocation"
BrandingText "Esthien Labs"
ShowInstDetails show
ShowUninstDetails show

VIProductVersion "0.7.4.0"
VIAddVersionKey /LANG=1033 "ProductName" "${PRODUCT_NAME}"
VIAddVersionKey /LANG=1033 "ProductVersion" "${ARGUS_VERSION}"
VIAddVersionKey /LANG=1033 "FileVersion" "0.7.4.0"
VIAddVersionKey /LANG=1033 "CompanyName" "${PRODUCT_PUBLISHER}"
VIAddVersionKey /LANG=1033 "FileDescription" "${PRODUCT_NAME} installer"
VIAddVersionKey /LANG=1033 "LegalCopyright" "Copyright 2026 Esthien Labs"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${ARGUS_LICENSE_FILE}"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

Var PathEntry

Function BroadcastEnvironmentChange
  System::Call 'user32::SendMessageTimeout(p 0xffff, i ${WM_SETTINGCHANGE}, p 0, t "Environment", i 0, i 5000, *p .r0)'
FunctionEnd

Function AddToUserPath
  StrCpy $PathEntry "$INSTDIR\bin"
  ReadRegStr $0 HKCU "Environment" "Path"
  ${StrStr} $1 "$0" "$PathEntry"
  ${If} $1 == ""
    ${If} $0 == ""
      WriteRegExpandStr HKCU "Environment" "Path" "$PathEntry"
    ${Else}
      WriteRegExpandStr HKCU "Environment" "Path" "$0;$PathEntry"
    ${EndIf}
    Call BroadcastEnvironmentChange
  ${EndIf}
FunctionEnd

Function un.RemoveFromUserPath
  ReadRegStr $0 HKCU "Environment" "Path"
  ${UnStrRep} $0 "$0" "$INSTDIR\bin;" ""
  ${UnStrRep} $0 "$0" ";$INSTDIR\bin" ""
  ${UnStrRep} $0 "$0" "$INSTDIR\bin" ""
  WriteRegExpandStr HKCU "Environment" "Path" "$0"
  Call un.BroadcastEnvironmentChange
FunctionEnd

Function un.BroadcastEnvironmentChange
  System::Call 'user32::SendMessageTimeout(p 0xffff, i ${WM_SETTINGCHANGE}, p 0, t "Environment", i 0, i 5000, *p .r0)'
FunctionEnd

Section "Argus SDK" SEC_ARGUS
  SetOutPath "$INSTDIR\runtime"
  File "${ARGUS_PAYLOAD_EXE}"

  SetOutPath "$INSTDIR\bin"
  File "argus.cmd"

  WriteUninstaller "$INSTDIR\uninstall.exe"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayName" "${PRODUCT_NAME} ${ARGUS_VERSION} (${ARGUS_TARGET_ARCH})"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayVersion" "${ARGUS_VERSION}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "Publisher" "${PRODUCT_PUBLISHER}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoRepair" 0
  Call AddToUserPath
SectionEnd

Section "Uninstall"
  Call un.RemoveFromUserPath
  Delete "$INSTDIR\bin\argus.cmd"
  RMDir /r "$INSTDIR\runtime"
  Delete "$INSTDIR\uninstall.exe"
  RMDir "$INSTDIR\bin"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "${UNINSTALL_KEY}"
SectionEnd
