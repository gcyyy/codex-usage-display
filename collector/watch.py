"""Windows directory-change signals, with periodic reconciliation as a fallback."""
import os


class DirectorySignals:
    def __init__(self):
        self.handles = {}
        self.kernel = None
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.FindFirstChangeNotificationW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL, wintypes.DWORD]
            kernel.FindFirstChangeNotificationW.restype = wintypes.HANDLE
            kernel.FindNextChangeNotification.argtypes = [wintypes.HANDLE]
            kernel.FindCloseChangeNotification.argtypes = [wintypes.HANDLE]
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            self.kernel = kernel
            self.invalid = ctypes.c_void_p(-1).value

    def register(self, paths):
        if not self.kernel:
            return
        for path in paths:
            if path not in self.handles and os.path.isdir(path):
                handle = self.kernel.FindFirstChangeNotificationW(path, True, 0x1 | 0x2 | 0x8 | 0x10)
                if handle not in (self.invalid, None):
                    self.handles[path] = handle

    def changed(self):
        changed = False
        for handle in self.handles.values():
            if self.kernel.WaitForSingleObject(handle, 0) == 0:
                self.kernel.FindNextChangeNotification(handle)
                changed = True
        return changed

    def close(self):
        for handle in self.handles.values():
            self.kernel.FindCloseChangeNotification(handle)
        self.handles.clear()
