import ctypes
from ctypes import wintypes

# 从 Windows 注册表读取用户环境变量
try:
    import winreg
    print("Using winreg:")
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Environment', 0, winreg.KEY_READ) as key:
        try:
            value, _ = winreg.QueryValueEx(key, 'AGNES_API_KEY')
            print(f'AGNES_API_KEY: {value[:30]}...' if value else '未设置')
        except FileNotFoundError:
            print('AGNES_API_KEY: 未找到')
        try:
            value, _ = winreg.QueryValueEx(key, 'LLM_API_KEY')
            print(f'LLM_API_KEY: {value[:30]}...' if value else '未设置')
        except FileNotFoundError:
            print('LLM_API_KEY: 未找到')
except Exception as e:
    print(f'winreg 错误: {e}')

# 也检查 Machine 级别
try:
    import winreg
    print("\nChecking Machine-level environment:")
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment', 0, winreg.KEY_READ) as key:
        try:
            value, _ = winreg.QueryValueEx(key, 'AGNES_API_KEY')
            print(f'AGNES_API_KEY: {value[:30]}...' if value else '未设置')
        except FileNotFoundError:
            print('AGNES_API_KEY: 未找到')
except Exception as e:
    print(f'Machine-level 错误: {e}')
