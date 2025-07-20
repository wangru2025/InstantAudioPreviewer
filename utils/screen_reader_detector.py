import ctypes
import sys
import os
from utils.logger_config import logger

class ScreenReaderDetector:
    """
    用于检测当前活跃屏幕阅读器的工具类。
    目前支持检测：
    - 争渡读屏 (通过检查其初始化状态)
    - NVDA (通过检查 nvdaControllerClient.dll 是否成功加载并调用 testIfRunning 函数)
    """
    ZDSR = "ZDSRApi"
    NVDA = "NVDACtrl"
    NONE = "None"

    _detected_sr = None

    @classmethod
    def get_active_screen_reader(cls):
        """
        尝试检测当前活跃的屏幕阅读器。
        优先检测争渡读屏。
        """
        if cls._detected_sr is not None:
            return cls._detected_sr

        if cls._is_zdsr_active():
            cls._detected_sr = cls.ZDSR
            logger.info("检测到活跃的屏幕阅读器：争渡读屏。")
            return cls.ZDSR
        elif cls._is_nvda_active():
            cls._detected_sr = cls.NVDA
            logger.info("检测到活跃的屏幕阅读器：NVDA。")
            return cls.NVDA
        else:
            cls._detected_sr = cls.NONE
            logger.info("未检测到已知的屏幕阅读器。")
            return cls.NONE

    @classmethod
    def _is_zdsr_active(cls):
        """
        检查争渡读屏是否活跃。
        通过争渡读屏 API 的初始化状态来判断。
        """
        try:
            from utils.zdsr_api_wrapper import zdsr_api
            # 检查 DLL 是否加载成功且 API 是否已初始化
            return zdsr_api._dll is not None and zdsr_api._is_initialized
        except ImportError:
            # 如果争渡读屏的 wrapper 模块不存在，则认为争渡读屏未激活
            logger.debug("争渡读屏 API wrapper 模块未找到。")
            return False
        except Exception as e:
            logger.debug(f"检查争渡读屏状态时发生错误: {e}")
            return False

    @classmethod
    def _is_nvda_active(cls):
        """
        检查 NVDA 是否活跃。
        通过尝试加载 nvdaControllerClient.dll 并调用 testIfRunning 函数。
        """
        if sys.platform != 'win32':
            return False

        nvda_dll_name = "nvdaControllerClient.dll"
        # 尝试在与当前文件相同目录的上一级目录中查找 DLL
        # 这个路径假设 nvdaControllerClient.dll 位于项目的根目录
        current_dir = os.path.dirname(os.path.abspath(__file__))
        dll_path = os.path.join(os.path.dirname(current_dir), nvda_dll_name)

        if not os.path.exists(dll_path):
            logger.debug(f"NVDA 控制器客户端 DLL '{nvda_dll_name}' 未找到于 {dll_path}。")
            return False

        try:
            # 加载 DLL
            nvda_client_lib = ctypes.windll.LoadLibrary(dll_path)
            # 定义 testIfRunning 函数的返回类型
            nvda_client_lib.nvdaController_testIfRunning.restype = ctypes.c_int

            # 调用 testIfRunning 函数
            # 根据 NVDA 的文档，返回 0 表示 NVDA 正在运行
            if nvda_client_lib.nvdaController_testIfRunning() == 0:
                logger.debug("NVDA 控制器 testIfRunning 成功，NVDA 正在运行。")
                return True
            else:
                # 如果返回非 0，则表示 NVDA 未运行或通信失败
                logger.debug("NVDA 控制器 testIfRunning 失败，NVDA 可能未运行。")
                return False
        except Exception as e:
            logger.debug(f"加载或调用 NVDA 控制器客户端 DLL 时发生错误: {e}")
            return False

# 移除或注释掉此行，因为它在模块导入时执行，如果不需要立即检测，可能会引起不必要的行为。
# ScreenReaderDetector.get_active_screen_reader()