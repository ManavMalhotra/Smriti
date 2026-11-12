"""Application-owned private paths; never follow links or Windows reparse points."""

from __future__ import annotations

import ctypes
import os
import stat
from ctypes import wintypes
from pathlib import Path


def check_path(path: Path) -> None:
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Private paths cannot contain links or reparse points")
    if path.exists() and path.is_file() and path.stat().st_nlink != 1:
        raise ValueError("Private files cannot have multiple links")


def private_directory(path: Path) -> None:
    check_path(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        path.chmod(0o700)
        return
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    security = ctypes.WinDLL("advapi32", use_last_error=True)
    signatures = {
        "OpenProcessToken": ([wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)], wintypes.BOOL),
        "GetTokenInformation": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        "ConvertSidToStringSidW": ([ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)], wintypes.BOOL),
        "ConvertStringSecurityDescriptorToSecurityDescriptorW": ([wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p], wintypes.BOOL),
        "SetFileSecurityW": ([wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL),
    }
    for name, (args, result) in signatures.items():
        getattr(security, name).argtypes = args
        getattr(security, name).restype = result
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    token, size = wintypes.HANDLE(), wintypes.DWORD()
    sid, descriptor = wintypes.LPWSTR(), ctypes.c_void_p()

    def checked(ok):
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())

    try:
        checked(security.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)))
        security.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        checked(security.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)))
        checked(security.ConvertSidToStringSidW(ctypes.c_void_p.from_buffer(buffer), ctypes.byref(sid)))
        sddl = f"D:P(A;OICI;FA;;;{sid.value})(A;OICI;FA;;;SY)"
        checked(security.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None))
        checked(security.SetFileSecurityW(str(path.absolute()), 0x80000004, descriptor))
    finally:
        if descriptor:
            kernel.LocalFree(descriptor)
        if sid:
            kernel.LocalFree(ctypes.cast(sid, ctypes.c_void_p))
        if token:
            kernel.CloseHandle(token)
