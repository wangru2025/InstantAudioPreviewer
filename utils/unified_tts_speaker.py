from utils.logger_config import logger
from utils.zdsr_api_wrapper import zdsr_api
from utils.nvda_api_wrapper import nvda_api
from utils.screen_reader_detector import ScreenReaderDetector

class UnifiedTTSSpeaker:
    """
    统一的文本转语音（TTS）接口，支持自动选择屏幕阅读器或广播给所有支持的屏幕阅读器。
    """
    SPEAKER_STRATEGY = "BROADCAST"  # 默认策略为广播模式
    _allowed_phrases = ["开始监视", "停止监视", "隐藏"]  # 允许朗读的特定短语

    def __init__(self):
        """
        初始化 UnifiedTTSSpeaker。
        根据 SPEAKER_STRATEGY 策略，初始化活跃的屏幕阅读器（如果策略为 AUTO）。
        """
        self._active_sr = None  # 当前活跃的屏幕阅读器
        if self.SPEAKER_STRATEGY == "AUTO":
            self._active_sr = ScreenReaderDetector.get_active_screen_reader()
            logger.info(f"统一TTS接口策略设置为 'AUTO'，检测到活跃屏幕阅读器: {self._active_sr}")
        elif self.SPEAKER_STRATEGY == "BROADCAST":
            logger.info("统一TTS接口策略设置为 'BROADCAST'，将同时向所有支持的屏幕阅读器发送请求。")
        else:
            # 当策略不是 AUTO 或 BROADCAST 时，记录警告并默认使用 BROADCAST
            logger.warning(f"未知的 TTS 策略: {self.SPEAKER_STRATEGY}。将默认使用 'BROADCAST' 策略。")
            self.SPEAKER_STRATEGY = "BROADCAST"

    def speak(self, text: str):
        """
        根据当前的 SPEAKER_STRATEGY 策略朗读文本。
        仅当文本在 _allowed_phrases 中时才进行朗读。

        Args:
            text: 要朗读的文本。
        """
        if not text:  # 如果文本为空，则不执行任何操作
            return

        if text not in self._allowed_phrases:  # 检查文本是否在允许列表中
            logger.debug(f"文本 '{text}' 不在允许朗读列表中，跳过朗读。")
            return

        # 根据策略选择朗读方法
        if self.SPEAKER_STRATEGY == "AUTO":
            self._speak_auto(text)
        elif self.SPEAKER_STRATEGY == "BROADCAST":
            self._speak_broadcast(text)
        else:
            # 理论上不会执行到这里，因为 __init__ 中已经处理了未知策略
            logger.error(f"无效的 TTS 策略 '{self.SPEAKER_STRATEGY}'，无法朗读文本: {text}")

    def _speak_auto(self, text: str):
        """
        在 AUTO 模式下，根据检测到的活跃屏幕阅读器朗读文本。

        Args:
            text: 要朗读的文本。
        """
        if self._active_sr == ScreenReaderDetector.ZDSR:
            logger.debug(f"AUTO模式：使用争渡读屏朗读: {text}")
            zdsr_api.speak(text)
        elif self._active_sr == ScreenReaderDetector.NVDA:
            logger.debug(f"AUTO模式：使用NVDA朗读: {text}")
            nvda_api.speak(text)
        else:
            # 当没有检测到支持的屏幕阅读器时，记录警告
            logger.warning(f"AUTO模式：未检测到可用的屏幕阅读器，无法朗读: {text}")

    def _speak_broadcast(self, text: str):
        """
        在 BROADCAST 模式下，同时使用争渡读屏和 NVDA 朗读文本。

        Args:
            text: 要朗读的文本。
        """
        logger.debug(f"BROADCAST模式：尝试用争渡读屏和NVDA朗读: {text}")
        zdsr_api.speak(text)
        nvda_api.speak(text)

    def stop_speak(self):
        """
        停止所有正在进行的朗读。
        根据 SPEAKER_STRATEGY 策略，停止相应的屏幕阅读器。
        """
        if self.SPEAKER_STRATEGY == "AUTO":
            if self._active_sr == ScreenReaderDetector.ZDSR:
                logger.debug("AUTO模式：停止争渡读屏朗读。")
                zdsr_api.stop_speak()
            elif self._active_sr == ScreenReaderDetector.NVDA:
                logger.debug("AUTO模式：停止NVDA朗读。")
                nvda_api.cancel_speech()
        elif self.SPEAKER_STRATEGY == "BROADCAST":
            logger.debug("BROADCAST模式：停止争渡读屏和NVDA朗读。")
            zdsr_api.stop_speak()
            nvda_api.cancel_speech()
        # else:  # 如果 SPEARER_STRATEGY 是未知值，则不需要执行任何操作，因为 __init__ 会将其修正为 BROADCAST
        #     pass


# 实例化一个 UnifiedTTSSpeaker 对象，供全局使用
unified_speaker = UnifiedTTSSpeaker()