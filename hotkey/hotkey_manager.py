import atexit
import ctypes
import ctypes.wintypes
import os
import sys
import keyboard # For global hotkey listening
import wx # For CallAfter
import pickle # Used for binary serialization
import time # For debugging timestamps
from collections import OrderedDict

from utils.logger_config import logger

# --- 定义 BASS_manager 快捷键常量 (用于 WinAPI 映射) ---
# 注意：这些常量主要用于 WinAPI 的 RegisterHotKey 函数，
# keyboard 库有自己的键名约定，通常是小写且包含空格，例如 'left arrow', 'page up'。
# 在 HotkeyManager 内部，我们会将这些键名进行标准化以供 keyboard 库使用。
VK_SPACE = 0x20
VK_RETURN = 0x0D # 对应 keyboard 库的 'enter'
VK_ESCAPE = 0x1B # 对应 keyboard 库的 'esc'
VK_TAB = 0x09
VK_DELETE = 0x2E
VK_INSERT = 0x2D
VK_HOME = 0x24 # 注意：Home 的 VK 是 0x24
VK_END = 0x23
VK_PRIOR = 0x21 # Page Up (对应 keyboard 库的 'page up')
VK_NEXT = 0x22 # Page Down (对应 keyboard 库的 'page down')
VK_LEFT = 0x25
VK_RIGHT = 0x27
VK_UP = 0x26
VK_DOWN = 0x28
VK_F1 = 0x70 # F1 key
# F2-F24 follow F1 sequentially (0x71 to 0x87)
VK_SNAPSHOT = 0x2C # Print Screen (对应 keyboard 库的 'print screen')
VK_CAPITAL = 0x14 # Caps Lock (对应 keyboard 库的 'caps lock')
VK_NUMLOCK = 0x90 # Num Lock (对应 keyboard 库的 'num lock')
VK_SCROLL = 0x91 # Scroll Lock (对应 keyboard 库的 'scroll lock')

# Modifier Keys for WinAPI
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

# Windows API for hotkey registration (for conflict detection)
# 仅在 Windows 平台上初始化 WinAPI 相关功能
if sys.platform == "win32":
    try:
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        user32.RegisterHotKey.argtypes = [ctypes.wintypes.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
        user32.RegisterHotKey.restype = ctypes.c_bool
        user32.UnregisterHotKey.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
        user32.UnregisterHotKey.restype = ctypes.c_bool
        user32.VkKeyScanW.argtypes = [ctypes.wintypes.WCHAR]
        user32.VkKeyScanW.restype = ctypes.c_short
    except OSError as e:
        logger.error(f"加载 user32.dll 失败: {e}. Windows API 快捷键冲突检测功能将不可用。")
        user32 = None # 标记为不可用
else:
    logger.warning("非 Windows 平台，Windows API 快捷键冲突检测功能将不可用。")
    user32 = None # 标记为不可用

# --- 配置路径 ---
CONFIG_FILE_NAME = "hotkeys.dat"

# 全局存储已注册的快捷键及其对应的功能名和修饰键组合
# { hotkey_string_normalized: func_name } (例如 'ctrl+alt+t')
# 在 _keyboard_event_handler 中，我们通过实时获取按键来匹配，而不是依赖于这个全局map的键。
# 这个map主要用于 _register_hotkeys 内部维护注册信息。
_registered_hotkey_info = {} # 存储 {hotkey_string_normalized: func_name}

# 存储每个快捷键的修饰键集合，用于 _keyboard_event_handler 实时判断
# { hotkey_string_normalized: set_of_modifier_strings_lower } (例如 {'ctrl', 'alt'})
_hotkey_modifiers_map = {}


# 确保在程序退出时停止键盘监听
@atexit.register
def _stop_keyboard_listening():
    logger.info("程序退出：停止 keyboard 库的全局监听并解除所有热键。")
    keyboard.unhook_all() # 停止所有钩子
    # 这里我们不直接解除 WinAPI 注册的热键，因为在Windows上，进程退出会自动清理。
    # 并且我们只使用 WinAPI 检测冲突，不主动注册。


class HotkeyManager:
    def __init__(self, parent_frame):
        self.parent_frame = parent_frame
        self.config_path = self._get_config_path()
        self.hotkeys = {} # 存储功能名到快捷键字符串的映射 (例如 {"toggle_monitor": "ctrl+alt+shift+t"})

        # 定义所有已知的功能及其显示名称。这是 HotkeyManager 的核心功能列表。
        # 使用 OrderedDict 保持顺序，以便 UI 按照定义顺序显示。
        self._defined_functions = OrderedDict([
            ("toggle_monitor", "开始/停止监视"),
            ("toggle_visibility", "隐藏/显示窗口"),
            ("exit_application", "退出程序"),
            ("toggle_play_pause", "播放/暂停"),
            ("fast_forward", "快进"),
            ("rewind", "快退"),
            ("add_label", "添加标签"),
            ("search_label", "搜索标签")
        ])

        # 定义 UI 需要的普通键及其 keyboard 库对应键名
        # key: UI显示名, value: keyboard库识别名 (小写，可能含空格)
        # 注意：这里只包含特殊的非字母数字键，字母数字键可以直接转换大小写
        self._ui_key_to_keyboard_key = {
            "": "", # 用于清空选项
            "Space": "space",
            "Return": "enter", # keyboard 库是 'enter'
            "Escape": "esc",   # keyboard 库是 'esc'
            "Tab": "tab",
            "Delete": "delete",
            "Insert": "insert",
            "Home": "home",
            "End": "end",
            "PageUp": "page up",  # keyboard 库是 'page up'
            "PageDown": "page down",
            "Left": "left",
            "Right": "right",
            "Up": "up",
            "Down": "down",
            "PrintScreen": "print screen",
            "CapsLock": "caps lock",
            "NumLock": "num lock",
            "ScrollLock": "scroll lock"
        }
        # 反向映射，用于将 keyboard 库的键名转换回 UI 显示名
        self._keyboard_key_to_ui_key = {v: k for k, v in self._ui_key_to_keyboard_key.items()}
        # 补充 F 键，F1-F12 （或更多）
        for i in range(1, 13): # 假设只支持到 F12
            f_key_ui = f"F{i}"
            f_key_kb = f"f{i}"
            self._ui_key_to_keyboard_key[f_key_ui] = f_key_kb
            self._keyboard_key_to_ui_key[f_key_kb] = f_key_ui

        # 生成 UI 中 ComboBox 的所有可选普通键列表
        self.common_keys_for_ui = [""] + sorted([chr(ord('A') + i) for i in range(26)] +
                                               [str(i) for i in range(10)] +
                                               list(self._ui_key_to_keyboard_key.keys())[1:] # 排除空字符串
                                               )

        self._load_config()
        self._register_hotkeys()

        # 注册全局键盘事件监听器，用于区分按下和释放
        keyboard.hook(self._keyboard_event_handler)
        logger.info("Keyboard 全局钩子已注册。")

        # 跟踪当前按下且已注册的快捷键，用于避免重复触发按下事件
        # 存储 (func_name, normalized_hotkey_string)
        self._active_hotkey_presses = set()

        # 跟踪最近一次的释放事件，用于防止在快速点击时，释放事件触发在下一个按压之前
        # 存储 {func_name: last_release_time}
        self._last_release_times = {}

    def _get_config_path(self):
        """
        获取配置文件路径，始终使用主程序文件 (main.py 或打包后的 .exe) 所在的目录。
        """
        if getattr(sys, 'frozen', False):
            # PyInstaller 打包后的程序，sys.executable 是 .exe 文件的完整路径
            application_base_path = os.path.dirname(sys.executable)
        else:
            # 未打包的开发环境，sys.argv[0] 是启动脚本的完整路径 (即 main.py 的路径)
            application_base_path = os.path.dirname(os.path.abspath(sys.argv[0]))

        # 确保目录存在
        if not os.path.exists(application_base_path):
            try:
                os.makedirs(application_base_path)
                logger.warning(f"应用程序基路径 '{application_base_path}' 不存在，已创建。")
            except OSError as e:
                logger.error(f"无法创建应用程序基路径 '{application_base_path}': {e}", exc_info=True)
                # 作为最终备用方案，退回到当前模块文件所在的目录
                application_base_path = os.path.dirname(os.path.abspath(__file__))
                logger.warning(f"由于无法创建目标路径，将使用模块自身目录 '{application_base_path}'。")

        return os.path.join(application_base_path, CONFIG_FILE_NAME)

    def _load_config(self):
        """加载快捷键配置，如果文件不存在或出错则创建默认配置。"""
        loaded_hotkeys = {}
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'rb') as f:
                    loaded_hotkeys = pickle.load(f)
                    if not isinstance(loaded_hotkeys, dict):
                        raise ValueError("加载的数据不是字典格式。")
                logger.info(f"成功从 '{self.config_path}' 加载快捷键配置。")
            except (EOFError, pickle.UnpicklingError, ValueError) as e:
                logger.error(f"读取或解析快捷键配置文件失败: {e}. 文件可能已损坏或为空，将重置为默认配置。", exc_info=True)
                if os.path.exists(self.config_path):
                    try:
                        os.rename(self.config_path, self.config_path + ".bak")
                        logger.warning(f"已备份损坏的配置文件到 '{self.config_path}.bak'")
                    except Exception as backup_e:
                        logger.error(f"备份配置文件失败: {backup_e}")
                loaded_hotkeys = {} # 清空加载的，以便后续生成默认

            except Exception as e:
                logger.error(f"加载配置文件时发生未知错误: {e}. 将重置为默认配置。", exc_info=True)
                loaded_hotkeys = {} # 清空加载的，以便后续生成默认

        # 合并已加载的配置和默认配置，确保所有定义的功能都有一个条目
        # 对于加载到的功能，使用其值；对于新功能或未加载到的功能，将其值设为空字符串，等待用户设置。
        self.hotkeys = {}
        for func_name in self._defined_functions.keys(): # 遍历所有已知功能
            if func_name in loaded_hotkeys:
                # 如果已加载的配置中有该功能，则使用它
                self.hotkeys[func_name] = loaded_hotkeys[func_name]
                # 检查加载的快捷键是否有效，如果无效则重置为空
                if not self._is_valid_hotkey_string(self.hotkeys[func_name]):
                    logger.warning(f"加载的功能 '{func_name}' 对应的快捷键 '{self.hotkeys[func_name]}' 无效，已重置为空。")
                    self.hotkeys[func_name] = ""
            else:
                # 如果是新功能，或加载配置中没有该功能，则初始化为空字符串
                self.hotkeys[func_name] = ""
                logger.info(f"功能 '{func_name}' 为新功能或未在配置中找到，初始化为空快捷键。")

        # 移除已废弃的功能
        keys_to_remove = [k for k in self.hotkeys if k not in self._defined_functions]
        if keys_to_remove:
            for k in keys_to_remove:
                del self.hotkeys[k]
                logger.info(f"已移除废弃功能 '{k}' 的快捷键配置。")

        self._save_config() # 重新保存一次，以确保配置文件的结构与当前定义的功能列表一致

    def _get_default_hotkey_values(self):
        """返回默认的快捷键配置。"""
        return {
            "toggle_monitor": "ctrl+alt+shift+t",
            "toggle_visibility": "ctrl+alt+shift+v",
            "exit_application": "ctrl+alt+shift+q",
            "toggle_play_pause": "ctrl+alt+p",
            "fast_forward": "ctrl+alt+right",
            "rewind": "ctrl+alt+left",
            "add_label": "ctrl+alt+a",
            "search_label": "ctrl+alt+s"
        }

    def _set_default_hotkeys(self):
        """设置默认快捷键配置到 self.hotkeys 字典。"""
        self.hotkeys = self._get_default_hotkey_values()
        logger.info("内部快捷键已设置为默认值。")

    def _save_config(self):
        """保存当前快捷键配置到文件。"""
        try:
            with open(self.config_path, 'wb') as configfile:
                pickle.dump(self.hotkeys, configfile)
            logger.info(f"快捷键配置已保存到 '{self.config_path}'。")
        except Exception as e:
            logger.error(f"保存配置失败: {e}", exc_info=True)

    def reset_hotkeys_to_default(self):
        """将所有快捷键重置为默认值。"""
        self._unregister_hotkeys()
        self._set_default_hotkeys()
        self._save_config()
        self._register_hotkeys()
        # 通知主框架快捷键配置已更改，可能需要刷新 UI 或重新绑定事件
        wx.CallAfter(self.parent_frame.on_hotkey_config_changed)
        logger.info("快捷键已重置为默认并重新注册。")

    def get_registered_functions(self):
        """
        返回所有注册的功能及其显示名称。
        用于 HotkeySettingsDialog 动态构建功能列表。
        """
        return list(self._defined_functions.items()) # 返回 (内部名, 显示名) 对的列表

    def get_current_hotkey_for_func(self, func_name):
        """获取某个功能的当前快捷键字符串（如 "ctrl+alt+t"）。"""
        return self.hotkeys.get(func_name, "")

    def update_hotkey(self, func_name, mod_list_str, key_str):
        """
        更新特定功能的快捷键。
        :param func_name: 功能的内部名称。
        :param mod_list_str: 修饰键字符串，如 "Ctrl+Alt" (来自 UI)。
        :param key_str: 普通按键字符串，如 "T", "Space" (来自 UI)。
        :return: (bool, str) - (是否成功, 错误信息)。
        """
        # Step 1: 将 UI 提供的键名转换为 keyboard 库使用的规范化小写键名
        parts = []
        mod_keys_lower_set = set() # 使用集合存储小写修饰键名

        # 处理修饰键
        if mod_list_str:
            for m in mod_list_str.split('+'):
                m_lower = m.strip().lower()
                if m_lower:
                    # 'win' 是 keyboard 库使用的 Windows 键名
                    if m_lower == 'win':
                        parts.append('windows') # 统一为 'windows'
                    else:
                        parts.append(m_lower)
                    mod_keys_lower_set.add(m_lower) # 存储为 'ctrl', 'alt', 'shift', 'windows'

        # 处理普通键
        key_str_for_keyboard = ""
        if key_str:
            # 查找预定义映射
            if key_str in self._ui_key_to_keyboard_key:
                key_str_for_keyboard = self._ui_key_to_keyboard_key[key_str]
            else:
                # 默认情况下，字母数字键直接小写
                key_str_for_keyboard = key_str.lower()
            parts.append(key_str_for_keyboard)

        # 构建最终用于存储和比较的规范化快捷键字符串 (例如 "ctrl+alt+shift+t")
        # 确保修饰键排序一致 ('alt', 'ctrl', 'shift', 'windows')，然后是普通键
        modifier_order = ["alt", "ctrl", "shift", "windows"] # keyboard 库的默认修饰键排序

        # 过滤掉不存在的修饰键，并按指定顺序排序
        sorted_modifiers_for_hotkey_str = sorted([m for m in mod_keys_lower_set if m in modifier_order],
                                                 key=lambda x: modifier_order.index(x))

        # 添加普通键，确保它不在修饰键列表中
        final_parts = sorted_modifiers_for_hotkey_str
        if key_str_for_keyboard and key_str_for_keyboard not in sorted_modifiers_for_hotkey_str:
             final_parts.append(key_str_for_keyboard)

        new_hotkey_str_normalized = "+".join(final_parts)

        # Step 2: 验证和冲突检测
        if not new_hotkey_str_normalized:
            # 清空快捷键
            self.hotkeys[func_name] = ""
            self._save_config()
            self._unregister_hotkeys()
            self._register_hotkeys()
            logger.info(f"功能 '{func_name}' 的快捷键已清空。")
            return True, ""

        if not key_str and mod_list_str:
            return False, "快捷键必须包含一个普通按键。"

        # 检查内部冲突 (与现有已注册的快捷键冲突)
        for existing_func, existing_hotkey_str in self.hotkeys.items():
            if existing_func != func_name and existing_hotkey_str == new_hotkey_str_normalized:
                display_name = self._defined_functions.get(existing_func, existing_func)
                return False, f"该快捷键 '{new_hotkey_str_normalized}' 已与功能 '{display_name}' 冲突。"

        # 尝试进行系统级冲突检测 (仅限 Windows)
        if sys.platform == "win32" and user32 is not None:
            mod_flags, vk_code = self._parse_hotkey_string_for_winapi(mod_list_str, key_str)
            if vk_code is not None: # 只有当成功解析出VK_CODE时才进行系统冲突检测
                if self.test_hotkey_conflict(mod_flags, vk_code):
                    return False, "该快捷键已被其他程序占用。"
            elif key_str: # 如果有key_str但未能解析，则不进行冲突检测
                logger.warning(f"无法将 '{mod_list_str} + {key_str}' 解析为 WinAPI 键码，跳过系统级冲突检测。")

        # Step 3: 更新配置并重新注册
        self.hotkeys[func_name] = new_hotkey_str_normalized
        self._save_config()

        # 重新注册所有热键，以确保新的设置生效
        self._unregister_hotkeys()
        self._register_hotkeys()

        logger.info(f"功能 '{func_name}' 的快捷键已更新为 '{new_hotkey_str_normalized}'。")
        return True, ""

    def _is_valid_hotkey_string(self, hotkey_str):
        """检查热键字符串是否符合基本格式（至少包含一个普通键）。"""
        if not hotkey_str:
            return True # 空字符串表示清除热键，是有效的

        parts = hotkey_str.split('+')
        # 假设只要包含一个非修饰键（ctrl, alt, shift, win, windows），就认为是有效的普通键
        modifier_keys = {'ctrl', 'alt', 'shift', 'win', 'windows'}

        has_regular_key = False
        for part in parts:
            if part.lower() not in modifier_keys:
                has_regular_key = True
                break
        return has_regular_key and len(parts) > 0 # 至少要有一个键


    def _parse_hotkey_string_for_winapi(self, mod_list_str, key_str_ui):
        """
        将 UI 键名转换为 WinAPI 所需的修饰符标志和虚拟键码。
        :param mod_list_str: 来自 UI 的修饰键字符串，如 "Ctrl+Alt"
        :param key_str_ui: 来自 UI 的普通键字符串，如 "T", "Space", "Return"
        :return: (mod_flags, vk_code) 或者 (None, None) 如果无法解析
        """
        mod_flags = 0
        mod_list = mod_list_str.split('+') if isinstance(mod_list_str, str) else []
        if "Ctrl" in mod_list: mod_flags |= MOD_CONTROL
        if "Alt" in mod_list: mod_flags |= MOD_ALT
        if "Shift" in mod_list: mod_flags |= MOD_SHIFT
        if "Win" in mod_list: mod_flags |= MOD_WIN

        vk_code = None
        key_str_lower = key_str_ui.lower() if key_str_ui else ""

        # 直接映射 UI 显示名到 VK 代码
        if key_str_lower == 'space': vk_code = VK_SPACE
        elif key_str_lower == 'return': vk_code = VK_RETURN # UI 是 Return
        elif key_str_lower == 'escape': vk_code = VK_ESCAPE # UI 是 Escape
        elif key_str_lower == 'tab': vk_code = VK_TAB
        elif key_str_lower == 'delete': vk_code = VK_DELETE
        elif key_str_lower == 'insert': vk_code = VK_INSERT
        elif key_str_lower == 'home': vk_code = VK_HOME
        elif key_str_lower == 'end': vk_code = VK_END
        elif key_str_lower == 'pageup': vk_code = VK_PRIOR # UI 是 PageUp
        elif key_str_lower == 'pagedown': vk_code = VK_NEXT # UI 是 PageDown
        elif key_str_lower == 'left': vk_code = VK_LEFT
        elif key_str_lower == 'right': vk_code = VK_RIGHT
        elif key_str_lower == 'up': vk_code = VK_UP
        elif key_str_lower == 'down': vk_code = VK_DOWN
        elif key_str_lower == 'printscreen': vk_code = VK_SNAPSHOT # UI 是 PrintScreen
        elif key_str_lower == 'capslock': vk_code = VK_CAPITAL # UI 是 CapsLock
        elif key_str_lower == 'numlock': vk_code = VK_NUMLOCK # UI 是 NumLock
        elif key_str_lower == 'scrolllock': vk_code = VK_SCROLL # UI 是 ScrollLock
        elif key_str_lower.startswith('f') and key_str_lower[1:].isdigit():
            f_num = int(key_str_lower[1:])
            if 1 <= f_num <= 24: vk_code = VK_F1 + (f_num - 1)
        elif len(key_str_ui) == 1 and key_str_ui.isalnum(): # For A-Z, 0-9 (UI 是大写)
            try:
                # VkKeyScanW 接受字符，返回 (virtual_key_code | shift_state << 8)
                vk_result = user32.VkKeyScanW(key_str_ui)
                if vk_result != -1:
                    vk_code = vk_result & 0xFF # 提取低8位作为虚拟键码
            except Exception as e:
                logger.warning(f"VkKeyScanW for '{key_str_ui}' failed: {e}")
                pass

        if vk_code is None and key_str_ui: # 如果有普通键但无法解析
            logger.debug(f"无法将 UI 键 '{key_str_ui}' 转换为 WinAPI VK_CODE。")
            return None, None
        return mod_flags, vk_code

    def test_hotkey_conflict(self, mod_flags, vk_code):
        """
        尝试注册一个临时热键来检测冲突。
        :param mod_flags: WinAPI 修饰符标志。
        :param vk_code: WinAPI 虚拟键码。
        :return: True 如果有冲突，False 如果没有冲突。
        """
        if sys.platform != "win32" or user32 is None:
            return False # 非 Windows 平台或 user32 未加载，不执行此检测

        if vk_code is None:
            logger.debug("快捷键冲突检测：VK_CODE 为 None，跳过检测。")
            return False

        test_hotkey_id = 9999 # 一个临时的 ID
        hwnd = self.parent_frame.GetHandle() # 获取主窗口句柄

        if not hwnd:
            logger.warning("无法获取主窗口句柄，跳过系统级快捷键冲突检测。")
            return False

        try:
            # 尝试注册热键
            result = user32.RegisterHotKey(ctypes.wintypes.HWND(hwnd), test_hotkey_id, mod_flags, vk_code)
            if result:
                # 注册成功，说明没有冲突，立即解除
                user32.UnregisterHotKey(ctypes.wintypes.HWND(hwnd), test_hotkey_id)
                logger.debug(f"快捷键冲突检测: {hex(mod_flags)}+{hex(vk_code)} 无冲突。")
                return False
            else:
                # 注册失败，检查错误码
                error_code = ctypes.get_last_error()
                # 错误码 1409 (0x581) 表示该热键已被注册
                if error_code == 1409:
                    logger.debug(f"快捷键冲突检测: {hex(mod_flags)}+{hex(vk_code)} 已被占用 (Error: {error_code})")
                    return True
                else:
                    # 其他注册失败原因
                    logger.warning(f"尝试注册临时热键失败，非冲突错误: {error_code} ({hex(mod_flags)}+{hex(vk_code)})")
                    return False
        except Exception as e:
            logger.error(f"测试快捷键冲突时出错: {e}", exc_info=True)
            return False

    def _get_hotkey_parts_for_ui(self, hotkey_str_normalized):
        """
        将规范化后的快捷键字符串 (如 "ctrl+alt+windows+t") 拆分为 UI 显示所需的修饰键列表和普通键名。
        :param hotkey_str_normalized: 例如 "ctrl+alt+windows+t", "shift+f5"
        :return: (mod_list, key_name_for_ui) 例如 (['Ctrl', 'Alt', 'Win'], 'T')
        """
        mod_list = []
        key_name_for_ui = ""
        if not hotkey_str_normalized:
            return [], ""

        parts = hotkey_str_normalized.split('+')
        # 定义 keyboard 库的修饰键名称 (小写)
        modifier_kb_names = {"ctrl", "alt", "shift", "windows"}

        for part in parts:
            part_lower = part.strip().lower()
            if part_lower == "ctrl": mod_list.append("Ctrl")
            elif part_lower == "alt": mod_list.append("Alt")
            elif part_lower == "shift": mod_list.append("Shift")
            elif part_lower == "windows": mod_list.append("Win") # UI 显示为 'Win'
            else:
                # 尝试从 _keyboard_key_to_ui_key 查找，否则转换为大写
                key_name_for_ui = self._keyboard_key_to_ui_key.get(part_lower, part_lower.upper())

        # 确保修饰键的 UI 显示顺序一致
        ui_modifier_order = ["Ctrl", "Alt", "Shift", "Win"]
        mod_list.sort(key=lambda x: ui_modifier_order.index(x) if x in ui_modifier_order else len(ui_modifier_order))

        return mod_list, key_name_for_ui

    def _unregister_hotkeys(self):
        """
        清除所有在 _registered_hotkey_info 和 _hotkey_modifiers_map 中存储的注册信息。
        这样 _keyboard_event_handler 就不会再匹配这些快捷键了。
        """
        logger.info("解除所有内部热键映射。")
        _registered_hotkey_info.clear()
        _hotkey_modifiers_map.clear()
        self._active_hotkey_presses.clear() # 清空活跃按键状态

    def _register_hotkeys(self):
        """
        根据 self.hotkeys 字典重新填充 _registered_hotkey_info 和 _hotkey_modifiers_map。
        _keyboard_event_handler 将根据这两个全局变量进行匹配。
        """
        global _registered_hotkey_info, _hotkey_modifiers_map
        _registered_hotkey_info.clear()
        _hotkey_modifiers_map.clear()

        # keyboard 库的修饰键顺序 (用于生成匹配键)
        modifier_order_kb = ["alt", "ctrl", "shift", "windows"]

        for func_name, hotkey_str in self.hotkeys.items():
            if hotkey_str:
                try:
                    parts = hotkey_str.split('+')
                    current_modifiers_lower = set()
                    key_part_lower = None

                    # 识别修饰键和普通键
                    for p in parts:
                        p_lower = p.lower()
                        if p_lower in {"ctrl", "alt", "shift", "windows"}:
                            current_modifiers_lower.add(p_lower)
                        else:
                            key_part_lower = p_lower # 最后一个非修饰键是普通键

                    if key_part_lower:
                        # 确保修饰键排序一致，以便生成唯一的匹配键
                        sorted_modifiers_for_map = sorted(list(current_modifiers_lower),
                                                          key=lambda x: modifier_order_kb.index(x) if x in modifier_order_kb else len(modifier_order_kb))

                        normalized_hotkey_for_map = "+".join(sorted_modifiers_for_map + [key_part_lower])

                        _registered_hotkey_info[normalized_hotkey_for_map] = func_name
                        _hotkey_modifiers_map[normalized_hotkey_for_map] = current_modifiers_lower # 存储原始的修饰键集合
                        logger.info(f"已注册内部快捷键映射: '{normalized_hotkey_for_map}' for {func_name}")
                    else:
                        logger.warning(f"快捷键 '{hotkey_str}' for {func_name} 无普通按键，无法注册。")

                except Exception as e:
                    logger.error(f"注册快捷键 '{hotkey_str}' for {func_name} 失败: {e}.", exc_info=True)

        logger.info(f"所有 {len(_registered_hotkey_info)} 个快捷键已成功注册。")


    def _keyboard_event_handler(self, event):
        """
        处理所有键盘事件，判断是否是注册的快捷键。
        这个是 keyboard 库的全局钩子回调函数。
        """
        if not event or not event.name:
            return False

        # 如果没有注册的快捷键，直接返回 False
        if not _registered_hotkey_info:
            return False

        # 获取当前按下的所有修饰键 (keyboard 库的名称是小写的)
        current_modifiers_set = set()
        if keyboard.is_pressed('ctrl'): current_modifiers_set.add('ctrl')
        if keyboard.is_pressed('alt'): current_modifiers_set.add('alt')
        if keyboard.is_pressed('shift'): current_modifiers_set.add('shift')
        if keyboard.is_pressed('windows'): current_modifiers_set.add('windows') # keyboard 库用 'windows'

        # 获取当前按下的普通键 (event.name 已经是 keyboard 库的标准名，如 'right', 'enter', 'a', 'f1')
        key_name_lower = event.name.lower()

        # 构建当前按键组合的规范化字符串，用于查找
        # 确保修饰键排序一致 ('alt', 'ctrl', 'shift', 'windows')
        modifier_order_kb = ["alt", "ctrl", "shift", "windows"]
        sorted_modifiers_for_handler = sorted(list(current_modifiers_set),
                                              key=lambda x: modifier_order_kb.index(x) if x in modifier_order_kb else len(modifier_order_kb))

        current_hotkey_str_normalized = "+".join(sorted_modifiers_for_handler + [key_name_lower])

        # logger.debug(f"Event: {event.event_type}, Key: {event.name}, Full combo: {current_hotkey_str_normalized}")

        # 查找匹配的函数名
        func_name = _registered_hotkey_info.get(current_hotkey_str_normalized)

        if func_name: # 如果是注册的快捷键
            if event.event_type == keyboard.KEY_DOWN:
                # 避免重复触发按下事件 (例如，连续按键事件会触发多次 KEY_DOWN)
                if (func_name, current_hotkey_str_normalized) not in self._active_hotkey_presses:
                    # 检查是否有快速重复按下的情况，以防万一
                    if func_name in self._last_release_times and \
                       (time.time() - self._last_release_times[func_name]) < 0.1: # 100ms 间隔
                        # logger.debug(f"Too quick press for {func_name}, ignoring.")
                        return False # 忽略过快的重复按下

                    self._active_hotkey_presses.add((func_name, current_hotkey_str_normalized))
                    logger.debug(f"Hotkey DOWN detected: {current_hotkey_str_normalized} ({func_name})")
                    # 将事件发布到主 UI 线程
                    wx.CallAfter(self.parent_frame.handle_hotkey_event, HotkeyEvent(func_name, is_pressed=True))
                    return True # 阻止事件向下传递，意味着此事件已被处理

            elif event.event_type == keyboard.KEY_UP:
                # 处理快捷键释放事件
                if (func_name, current_hotkey_str_normalized) in self._active_hotkey_presses:
                    self._active_hotkey_presses.remove((func_name, current_hotkey_str_normalized))
                    self._last_release_times[func_name] = time.time() # 记录释放时间
                    logger.debug(f"Hotkey UP detected: {current_hotkey_str_normalized} ({func_name})")
                    # 调用 MyFrame 中的释放事件处理方法
                    wx.CallAfter(self.parent_frame.on_hotkey_release_event, func_name)
                    return True # 阻止事件向下传递

        return False # 不是我们处理的快捷键，让事件继续传递

# --- 自定义 wx.Event 类型 ---
EVT_HOTKEY_TRIGGERED_ID = wx.NewIdRef()
EVT_HOTKEY_TRIGGERED = wx.PyEventBinder(EVT_HOTKEY_TRIGGERED_ID, 1)

class HotkeyEvent(wx.PyEvent):
    """
    自定义事件，用于从 HotkeyManager 的监听线程将热键事件发送到主 UI 线程。
    """
    def __init__(self, func_name, is_pressed):
        wx.PyEvent.__init__(self, eventType=EVT_HOTKEY_TRIGGERED_ID)
        self.func_name = func_name
        self.is_pressed = is_pressed # 指示是按下 (True) 还是释放 (False) 事件