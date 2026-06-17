"""零 · 插件加载器
===================
自动发现并加载 interfaces/ 插件实现。

发现路径（按优先级）:
  1. personal/plugins/ — 用户本地插件（被 .gitignore）
  2. ZERO_PLUGINS_DIR 环境变量指向的目录
  3. 内置 Null* 实现（fallback）

用法:
    from interfaces.plugin_loader import load_plugins
    load_plugins()  # 启动时调用一次
"""

import importlib
import importlib.util
import os
import sys
import types

from config import ZERO_ROOT, get_logger

logger = get_logger('zero.plugins')

_PLUGIN_DIRS: list[str] = []


def _get_plugin_dirs() -> list[str]:
    """按优先级返回插件搜索目录。"""
    if _PLUGIN_DIRS:
        return _PLUGIN_DIRS

    # 1. personal/plugins/（最高优先级）
    personal_dir = os.path.join(ZERO_ROOT, 'personal', 'plugins')
    if os.path.isdir(personal_dir):
        _PLUGIN_DIRS.append(personal_dir)

    # 2. 环境变量指定
    env_dir = os.environ.get('ZERO_PLUGINS_DIR', '')
    if env_dir and os.path.isdir(env_dir):
        abspath = os.path.abspath(env_dir)
        if abspath not in _PLUGIN_DIRS:
            _PLUGIN_DIRS.append(abspath)

    # 3. interfaces/ 本身（内置 Null* 实现）
    _PLUGIN_DIRS.append(os.path.join(ZERO_ROOT, 'interfaces'))

    return _PLUGIN_DIRS


def discover_plugins(plugin_dir: str) -> list[str]:
    """扫描插件目录，返回 .py 文件列表（排除 __init__）。"""
    plugins: list[str] = []
    try:
        for fname in sorted(os.listdir(plugin_dir)):
            if fname.startswith('_'):
                continue  # 跳过 __init__.py、_private.py
            if fname.endswith('.py'):
                plugins.append(fname[:-3])  # 去掉 .py
    except FileNotFoundError:
        pass
    return plugins


def load_plugin_module(plugin_dir: str, name: str) -> types.ModuleType | None:
    """从指定目录加载一个 Python 模块。"""
    spec = importlib.util.spec_from_file_location(
        f'zero_plugin_{name}',
        os.path.join(plugin_dir, f'{name}.py'),
    )
    if spec is None or spec.loader is None:
        return None
    try:
        mod = importlib.util.module_from_spec(spec)
        # 按目录名注册到 sys.modules 中，防止重复导入
        sys.modules[mod.__name__] = mod
        spec.loader.exec_module(mod)
        return mod
    except Exception as exc:
        logger.warning('加载插件 %s 失败: %s', name, exc)
        return None


def _try_inject_interface(mod: types.ModuleType,
                          interface_name: str,
                          impl_class_names: list[str]):
    """尝试从模块中找接口实现，注入到 interfaces.* 的全局实例。"""
    for cls_name in impl_class_names:
        cls = getattr(mod, cls_name, None)
        if cls is None:
            continue
        try:
            instance = cls()
            # 注入到对应接口模块的全局变量
            iface_path = f'interfaces.{interface_name}'
            iface_mod = importlib.import_module(iface_path)
            # 找接口模块中首字母小写的全局变量名: publisher, video_producer, skill_engine
            for attr_name in dir(iface_mod):
                if attr_name.startswith('_'):
                    continue
                attr = getattr(iface_mod, attr_name)
                if isinstance(attr, type) and attr.__name__ in impl_class_names:
                    continue
                # 检查这个全局变量是否是我们 Null* 同类型的实例
                if hasattr(attr, '__class__') and attr.__class__.__name__.startswith('Null'):
                    logger.info('覆盖接口 %s 的 Null 实例为 %s', interface_name, cls_name)
                    setattr(iface_mod, attr_name, instance)
                    return
            # 找不到 Null 实例就直接设
            logger.info('注入接口 %s: %s', interface_name, cls_name)
            setattr(iface_mod, attr_name_from_interface(interface_name), instance)
        except Exception as exc:
            logger.warning('注入 %s -> %s 失败: %s', cls_name, interface_name, exc)


def attr_name_from_interface(interface_name: str) -> str:
    """ipublisher -> publisher, ivideo_producer -> video_producer"""
    return interface_name[1:]  # 去掉开头的 'i'


# 接口名 -> 期待的实现类名列表
_INTERFACE_MAP: dict[str, list[str]] = {
    'ipublisher':      ['PersonalPublisher', 'Publisher'],
    'ivideo_producer': ['PersonalVideoProducer', 'VideoProducer'],
    'iskill_engine':   ['PersonalSkillEngine', 'SkillEngine'],
    'iextra_tool':     ['PersonalExtraTool', 'ExtraTool'],
}


def load_plugins():
    """发现并加载所有插件。在应用启动时调用一次。

    扫描 personal/plugins/ → 加载模块 → 匹配接口实现 → 注入全局实例。
    找不到实现时自动使用 interfaces/ 中的 Null* 实现。
    """
    loaded = 0
    for plugin_dir in _get_plugin_dirs():
        for name in discover_plugins(plugin_dir):
            mod = load_plugin_module(plugin_dir, name)
            if mod is None:
                continue
            for interface_name, class_names in _INTERFACE_MAP.items():
                _try_inject_interface(mod, interface_name, class_names)
                loaded += 1

    if loaded:
        logger.info('插件加载完成: %d 次注入尝试', loaded)
    else:
        logger.info('无用户插件，使用内置 Null 实现')
