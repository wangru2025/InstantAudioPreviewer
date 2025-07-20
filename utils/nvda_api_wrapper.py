import ctypes
import sys
import os
import atexit
from utils.logger_config import logger

class NVDACtrlApiWrapper:
    """
    封装 NVDA Controller Client API 的类，采用单例模式。
    """
    _instance = None
    _dll = None
    _is_initialized = False

    def __new__(cls):
        if not cls._instance:
            cls._instance = super(NVDACtrlApiWrapper, cls).__new__(cls)
            # 在新实例创建时进行初始化，确保只有一个实例被初始化
            cls._instance._init_api()
        return cls._instance

    def _init_api(self):
        """加载 NVDA Controller Client DLL 并定义函数签名。"""
        if sys.platform != 'win32':
            logger.warning("当前系统不是 Windows，NVDA Controller Client API 不可用。")
            return

        dll_name = "nvdaControllerClient.dll"
        # 假设dll在项目的根目录，而不是utils子目录
        # 获取当前文件所在的目录，然后向上追溯一层到项目根目录
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root_dir = os.path.dirname(current_dir)
        dll_path = os.path.join(project_root_dir, dll_name)

        if not os.path.exists(dll_path):
            logger.warning(f"NVDA Controller Client DLL '{dll_path}' 未找到。NVDA 朗读功能将不可用。")
            return

        try:
            NVDACtrlApiWrapper._dll = ctypes.windll.LoadLibrary(dll_path)
            logger.info(f"成功加载 NVDA Controller Client DLL: {dll_path}")

            # 定义函数签名
            NVDACtrlApiWrapper._dll.nvdaController_testIfRunning.restype = ctypes.c_int
            NVDACtrlApiWrapper._dll.nvdaController_speakText.argtypes = [ctypes.c_wchar_p]
            NVDACtrlApiWrapper._dll.nvdaController_speakText.restype = ctypes.c_int
            NVDACtrlApiWrapper._dll.nvdaController_brailleMessage.argtypes = [ctypes.c_wchar_p]
            NVDACtrlApiWrapper._dll.nvdaController_brailleMessage.restype = ctypes.c_int
            NVDACtrlApiWrapper._dll.nvdaController_cancelSpeech.restype = ctypes.c_int

            logger.debug("NVDA Controller Client API 函数签名已定义。")
            NVDACtrlApiWrapper._is_initialized = True
            # 注册在程序退出时取消语音，确保清理
            atexit.register(self.cancel_speech)

        except OSError as e:
            logger.error(f"加载 NVDA Controller Client DLL 失败: {e}. 请确保 '{dll_name}' 存在于项目根目录。", exc_info=True)
            NVDACtrlApiWrapper._dll = None
            NVDACtrlApiWrapper._is_initialized = False
        except Exception as e:
            logger.error(f"初始化 NVDA Controller Client API 失败: {e}", exc_info=True)
            NVDACtrlApiWrapper._dll = None
            NVDACtrlApiWrapper._is_initialized = False

    def _check_and_log_error(self, func_name: str, result: int, text: str = None):
        """检查函数调用结果并记录错误。"""
        if result != 0:
            error_message = ctypes.WinError(result).strerror
            log_msg = f"NVDA {func_name} 失败，错误码 {result}: {error_message}."
            if text:
                log_msg += f" 输入: '{text}'"
            logger.error(log_msg)
            return True
        return False

    def speak(self, text: str):
        """
        朗读指定的文本。
        如果 NVDA 未运行或 API 初始化失败，则不执行任何操作。
        """
        if not self._is_initialized or self._dll is None:
            logger.debug(f"NVDA Controller Client API 未加载，无法朗读: '{text}'")
            return

        try:
            # 检查NVDA是否运行
            if self._dll.nvdaController_testIfRunning() != 0:
                logger.debug(f"NVDA 未运行，无法通过 NVDA Controller Client 朗读: '{text}'")
                return

            result = self._dll.nvdaController_speakText(text)
            if not self._check_and_log_error("speakText", result, text):
                logger.debug(f"已发送 NVDA 朗读请求: '{text}'")
        except Exception as e:
            logger.error(f"调用 NVDA speakText 函数时发生错误: {e}. 文本: '{text}'", exc_info=True)

    def braille_message(self, message: str):
        """
        在 NVDA 盲文显示器上显示消息。
        如果 NVDA 未运行或 API 初始化失败，则不执行任何操作。
        """
        if not self._is_initialized or self._dll is None:
            logger.debug(f"NVDA Controller Client API 未加载，无法显示盲文: '{message}'")
            return

        try:
            # 检查NVDA是否运行
            if self._dll.nvdaController_testIfRunning() != 0:
                logger.debug(f"NVDA 未运行，无法通过 NVDA Controller Client 显示盲文: '{message}'")
                return

            result = self._dll.nvdaController_brailleMessage(message)
            if not self._check_and_log_error("brailleMessage", result, message):
                logger.debug(f"已发送 NVDA 盲文消息: '{message}'")
        except Exception as e:
            logger.error(f"调用 NVDA brailleMessage 函数时发生错误: {e}. 消息: '{message}'", exc_info=True)

    def cancel_speech(self):
        """
        取消当前 NVDA 正在进行的朗读。
        如果 NVDA 未运行或 API 初始化失败，则不执行任何操作。
        """
        if not self._is_initialized or self._dll is None:
            return

        try:
            # 检查NVDA是否运行
            if self._dll.nvdaController_testIfRunning() != 0:
                logger.debug("NVDA 未运行，无需取消语音。")
                return

            result = self._dll.nvdaController_cancelSpeech()
            if not self._check_and_log_error("cancelSpeech", result):
                logger.debug("已发送 NVDA 取消朗读命令。")
        except Exception as e:
            logger.error(f"调用 NVDA cancelSpeech 函数时发生错误: {e}", exc_info=True)

# 创建一个全局实例，方便其他模块导入后直接使用
nvda_api = NVDACtrlApiWrapper()