# Released by rdb under the Unlicense (unlicense.org)
# Further reading about the WinMM Joystick API:
# http://msdn.microsoft.com/en-us/library/windows/desktop/dd757116(v=vs.85).aspx
from __future__ import division, print_function
import ctypes
import _winreg as winreg
from ctypes.wintypes import WORD, UINT, DWORD
from ctypes.wintypes import WCHAR as TCHAR

# Fetch function pointers
joyGetNumDevs = ctypes.windll.winmm.joyGetNumDevs

# Define constants
MAXPNAMELEN = 32
MAX_JOYSTICKOEMVXDNAME = 260

JOY_RETURNX = 0x1
JOY_RETURNY = 0x2
JOY_RETURNZ = 0x4
JOY_RETURNR = 0x8
JOY_RETURNU = 0x10
JOY_RETURNV = 0x20
JOY_RETURNPOV = 0x40
JOY_RETURNBUTTONS = 0x80
JOY_RETURNRAWDATA = 0x100
JOY_RETURNPOVCTS = 0x200
JOY_RETURNCENTERED = 0x400
JOY_USEDEADZONE = 0x800
JOY_RETURNALL = (JOY_RETURNX | JOY_RETURNY | JOY_RETURNZ | JOY_RETURNR |
                 JOY_RETURNU | JOY_RETURNV | JOY_RETURNPOV | JOY_RETURNBUTTONS)

# Define some structures from WinMM that we will use in function calls.
class JOYCAPS(ctypes.Structure):
    _fields_ = [
        ('wMid', WORD),
        ('wPid', WORD),
        ('szPname', TCHAR * MAXPNAMELEN),
        ('wXmin', UINT),
        ('wXmax', UINT),
        ('wYmin', UINT),
        ('wYmax', UINT),
        ('wZmin', UINT),
        ('wZmax', UINT),
        ('wNumButtons', UINT),
        ('wPeriodMin', UINT),
        ('wPeriodMax', UINT),
        ('wRmin', UINT),
        ('wRmax', UINT),
        ('wUmin', UINT),
        ('wUmax', UINT),
        ('wVmin', UINT),
        ('wVmax', UINT),
        ('wCaps', UINT),
        ('wMaxAxes', UINT),
        ('wNumAxes', UINT),
        ('wMaxButtons', UINT),
        ('szRegKey', TCHAR * MAXPNAMELEN),
        ('szOEMVxD', TCHAR * MAX_JOYSTICKOEMVXDNAME),
    ]


class JOYINFO(ctypes.Structure):
    _fields_ = [
        ('wXpos', UINT),
        ('wYpos', UINT),
        ('wZpos', UINT),
        ('wButtons', UINT),
    ]

class JOYINFOEX(ctypes.Structure):
    _fields_ = [
        ('dwSize', DWORD),
        ('dwFlags', DWORD),
        ('dwXpos', DWORD),
        ('dwYpos', DWORD),
        ('dwZpos', DWORD),
        ('dwRpos', DWORD),
        ('dwUpos', DWORD),
        ('dwVpos', DWORD),
        ('dwButtons', DWORD),
        ('dwButtonNumber', DWORD),
        ('dwPOV', DWORD),
        ('dwReserved1', DWORD),
        ('dwReserved2', DWORD),
    ]

def joyGetPos(joy_id, info=None):
    if info is None:
        inplace = False
        info = JOYINFO()
    else:
        inplace=True
    p_info = ctypes.pointer(info)
    if ctypes.windll.winmm.joyGetPos(joy_id, p_info) != 0:
        raise IOError("Joystick %d not plugged in." % joy_id)
    if not inplace:
        return info

# Get device capabilities.
def joyGetDevCaps(joy_id, caps=None):
    if caps is None:
        inplace = False
        caps = JOYCAPS()
    else:
        inplace=True
    p_caps = ctypes.pointer(caps)
    if ctypes.windll.winmm.joyGetDevCapsW(joy_id, p_caps,
                                          ctypes.sizeof(JOYCAPS)) != 0:
        raise IOError('Failed to get device capabilities.')
    if not inplace:
        return caps

def get_name(joy_id, caps):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "System\\CurrentControlSet\\Control\\MediaResources\\Joystick\\%s\\CurrentJoystickSettings" % (caps.szRegKey))
        try:
            oem_name = winreg.QueryValueEx(key, "Joystick%dOEMName" % (joy_id + 1))
        finally:
            key.Close()
        key2 = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "System\\CurrentControlSet\\Control\\MediaProperties\\PrivateProperties\\Joystick\\OEM\\%s" % (oem_name[0]))
        try:
            oem_name = winreg.QueryValueEx(key2, "OEMName")
        finally:
            key2.Close()
    except Exception:
        raise IOError('Joypad name not found.')
    return oem_name[0].strip()

def get_state(joy_id, info=None, caps=None):
    if info is None:
        info = joyGetPos(joy_id)
    else:
        joyGetPos(joy_id, info)

    if caps is None:
        caps = joyGetDevCaps(joy_id)

    # Remap axes to float in range [-0.5, 0.5]
    axes = {'x': (info.wXpos - caps.wXmin) / (caps.wXmax - caps.wXmin) - .5,
            'y': (info.wYpos - caps.wYmin) / (caps.wYmax - caps.wYmin) - .5}

    button_states = [(0 != (1 << b) & info.wButtons)
                     for b in range(caps.wNumButtons)]

    return {'axes': axes, 'button_states': button_states}
