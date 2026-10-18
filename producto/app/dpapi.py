"""Cifrado con la protección de datos de Windows (DPAPI): solo el mismo usuario de Windows, en el mismo PC,
puede descifrar lo que cifró. Ahí van las llaves (Earth Engine, app de Turnos, publicación)."""
import ctypes
from ctypes import wintypes


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _entrada(datos: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(datos, len(datos))
    return _Blob(len(datos), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _salida(blob: _Blob) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob.pbData)


_ENTROPIA = b"EstimadorTCH"


def cifrar(datos: bytes) -> bytes:
    sal, ent = _Blob(), _entrada(_ENTROPIA)
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(_entrada(datos)), None, ctypes.byref(ent),
                                                  None, None, 0x01, ctypes.byref(sal)):
        raise OSError("Windows no pudo cifrar las llaves")
    return _salida(sal)


def descifrar(datos: bytes) -> bytes:
    sal, ent = _Blob(), _entrada(_ENTROPIA)
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(_entrada(datos)), None, ctypes.byref(ent),
                                                    None, None, 0x01, ctypes.byref(sal)):
        raise OSError("Las llaves guardadas no se pueden leer con este usuario de Windows")
    return _salida(sal)
