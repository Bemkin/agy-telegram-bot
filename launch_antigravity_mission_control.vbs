Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
ScriptDir = FSO.GetParentFolderName(WScript.ScriptFullName)
WshShell.Run chr(34) & ScriptDir & "\start_bot.bat" & chr(34), 0
Set FSO = Nothing
Set WshShell = Nothing
