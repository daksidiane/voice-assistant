import os
import sys
import base64
import subprocess
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# Static, parameterized PowerShell script that accesses environment variables safely
# and uses CreateTextNode DOM API to eliminate both PowerShell injection and XML injection.
_POWERSHELL_TOAST_SCRIPT = """
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$nodes = $t.GetElementsByTagName('text')
$title = [System.Environment]::GetEnvironmentVariable('SPUTNIK_TOAST_TITLE')
$msg = [System.Environment]::GetEnvironmentVariable('SPUTNIK_TOAST_MSG')
if ($nodes.Count -gt 0) {
    $nodes.Item(0).AppendChild($t.CreateTextNode($title)) | Out-Null
}
if ($nodes.Count -gt 1) {
    $nodes.Item(1).AppendChild($t.CreateTextNode($msg)) | Out-Null
}
$toast = [Windows.UI.Notifications.ToastNotification]::new($t)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('SPUTNIK').Show($toast)
"""
_ENCODED_TOAST_SCRIPT = base64.b64encode(_POWERSHELL_TOAST_SCRIPT.encode("utf-16le")).decode("ascii")


class Notifier:
    """Delivers native Windows Toast and Tray notifications."""

    _tray_icon = None

    @classmethod
    def set_tray_icon(cls, tray_icon):
        cls._tray_icon = tray_icon

    @classmethod
    def show_toast(cls, title: str, message: str) -> None:
        """Display a Windows notification."""
        # 1. If tray icon is available, use pystray notification
        if cls._tray_icon is not None:
            try:
                cls._tray_icon.notify(message, title)
                return
            except Exception as e:
                logger.debug(f"Pystray notify failed: {e}")

        # 2. PowerShell native toast notification as fallback (securely parameterized)
        def _send_powershell_toast():
            safe_env = os.environ.copy()
            safe_env["SPUTNIK_TOAST_TITLE"] = str(title)
            safe_env["SPUTNIK_TOAST_MSG"] = str(message)

            # Resolve powershell path explicitly from System32 to prevent binary planting
            system32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
            ps_exe = os.path.join(system32, "WindowsPowerShell", "v1.0", "powershell.exe")
            if not os.path.isfile(ps_exe):
                import shutil
                ps_exe = shutil.which("powershell.exe") or "powershell"

            try:
                subprocess.Popen(
                    [
                        ps_exe,
                        "-NoProfile",
                        "-NonInteractive",
                        "-WindowStyle",
                        "Hidden",
                        "-EncodedCommand",
                        _ENCODED_TOAST_SCRIPT,
                    ],
                    env=safe_env,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
            except Exception as e:
                logger.error(f"Failed to display toast notification: {e}")

        threading.Thread(target=_send_powershell_toast, daemon=True).start()

