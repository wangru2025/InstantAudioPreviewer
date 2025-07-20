import ctypes
import os
import sys
import atexit
from utils.logger_config import logger

if sys.platform == 'win32':
    dll_name = "ZDSRAPI_x64.dll" if sys.maxsize > 2**32 else "ZDSRAPI.dll"
    current_dir = os.path.dirname(os.path.abspath(__file__))
    dll_path = os.path.join(os.path.dirname(current_dir), dll_name)
else:
    dll_path = None

class ZDSRApiWrapper:
    """
    封装争渡读屏API的类，采用单例模式。
    """
    _instance = None
    _dll = None
    _is_initialized = False

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(ZDSRApiWrapper, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self):
        if not ZDSRApiWrapper._is_initialized:
            self._init_api()
            ZDSRApiWrapper._is_initialized = True

    def _init_api(self):
        """加载DLL并定义函数签名。"""
        if sys.platform != 'win32' or not dll_path or not os.path.exists(dll_path):
            logger.warning(f"争渡读屏API DLL '{dll_name}' 未找到或当前系统不支持。朗读功能将不可用。")
            ZDSRApiWrapper._dll = None
            return

        try:
            ZDSRApiWrapper._dll = ctypes.WinDLL(dll_path)
            logger.info(f"成功加载争渡读屏API DLL: {dll_path}")

            self._dll.InitTTS.argtypes = [ctypes.c_int, ctypes.c_wchar_p, ctypes.c_bool]
            self._dll.InitTTS.restype = ctypes.c_int

            self._dll.Speak.argtypes = [ctypes.c_wchar_p, ctypes.c_bool]
            self._dll.Speak.restype = ctypes.c_int

            self._dll.GetSpeakState.argtypes = []
            self._dll.GetSpeakState.restype = ctypes.c_int

            self._dll.StopSpeak.argtypes = []
            self._dll.StopSpeak.restype = None

            logger.debug("争渡读屏API函数签名已定义。")

            self._perform_tts_init()

        except Exception as e:
            logger.error(f"加载或初始化争渡读屏API失败: {e}", exc_info=True)
            ZDSRApiWrapper._dll = None
            self._is_initialized = False

    def _perform_tts_init(self):
        """执行 InitTTS 调用。"""
        if self._dll is None:
            return

        tts_type = 0
        channel_name = None
        b_key_down_interrupt = True

        result = self._dll.InitTTS(tts_type, channel_name, b_key_down_interrupt)
        if result == 0:
            logger.info(f"争渡读屏TTS接口初始化成功。类型: {'读屏通道' if tts_type == 0 else '独立通道'}, 按键打断: {b_key_down_interrupt}")
            atexit.register(self.stop_speak)
        elif result == 1:
            logger.error("争渡读屏TTS接口初始化失败: 版本不匹配。")
            ZDSRApiWrapper._dll = None
        else:
            logger.error(f"争渡读屏TTS接口初始化失败，错误码: {result}。")
            ZDSRApiWrapper._dll = None

    def speak(self, text: str):
        """朗读文本。"""
        if self._dll is None:
            logger.debug(f"争渡读屏API未加载或初始化失败，无法朗读: '{text}'")
            return

        try:
            b_interrupt = True
            result = self._dll.Speak(text, b_interrupt)
            if result == 0:
                logger.debug(f"成功发送朗读请求: '{text}'")
            elif result == 1:
                logger.error(f"朗读失败: 版本不匹配。文本: '{text}'")
            elif result == 2:
                logger.warning(f"朗读失败: ZDSR没有运行或没有授权。文本: '{text}'")
            else:
                logger.error(f"朗读失败，未知错误码: {result}。文本: '{text}'")
        except Exception as e:
            logger.error(f"调用争渡读屏Speak函数时发生错误: {e}. 文本: '{text}'", exc_info=True)

    def get_speak_state(self) -> int:
        """获取朗读状态。"""
        if self._dll is None:
            return -1

        try:
            return self._dll.GetSpeakState()
        except Exception as e:
            logger.error(f"调用争渡读屏GetSpeakState函数时发生错误: {e}", exc_info=True)
            return -1

    def stop_speak(self):
        """停止当前朗读。"""
        if self._dll is None:
            return

        try:
            self._dll.StopSpeak()
            logger.debug("已发送停止朗读命令。")
        except Exception as e:
            logger.error(f"调用争渡读屏StopSpeak函数时发生错误: {e}", exc_info=True)

zdsr_api = ZDSRApiWrapper()