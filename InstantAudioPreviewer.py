import wx
import ctypes
import os
import sys
import atexit

# 导入自定义模块
from gui.main_frame import MyFrame
from core.audio_manager import init_audio_system, set_frame_reference, free_audio_system
from utils.logger_config import logger

# 导入统一的TTS接口
from utils.unified_tts_speaker import unified_speaker

# 导入更新模块
try:
    from update_check_and_download import check_for_updates, UpdateStatus
except ImportError:
    logger.error("无法导入 update_check_and_download 模块，更新功能可能不可用。")
    check_for_updates = None
    UpdateStatus = None

# 应用程序版本
APP_CURRENT_VERSION = "1.0.0"

# 尝试设置应用程序ID以确保任务栏图标显示正确（仅Windows）
if sys.platform == 'win32':
    try:
        myappid = 'com.yourcompany.FileManagerAudioPreview.1.0'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception as e:
        logger.warning(f"设置应用程序用户模型ID失败: {e}")

def main():
    # 创建 wx.App 对象。必须在任何 wx 界面操作之前创建。
    app = wx.App(False)

    # 检查更新
    if check_for_updates and UpdateStatus:
        logger.info(f"当前应用程序版本: {APP_CURRENT_VERSION}")
        SERVER_IP = "101.132.172.172"
        SERVER_PORT = 42593

        update_result = check_for_updates(APP_CURRENT_VERSION, SERVER_IP, SERVER_PORT, logger)

        if update_result == UpdateStatus.UPDATED_AND_EXITING:
            logger.info("已检测到新版本，启动更新程序并退出当前应用。")
            sys.exit(0)
        elif update_result == UpdateStatus.NO_UPDATE:
            logger.info("当前已是最新版本，应用程序将继续运行。")
            # 继续启动主界面
        elif update_result == UpdateStatus.UPDATE_CANCELLED:
            logger.info("用户取消更新，应用程序将退出。")
            sys.exit(0)
        elif update_result == UpdateStatus.UPDATE_FAILED:
            logger.info("更新失败，应用程序将退出。")
            sys.exit(0)
        else:
            logger.error(f"更新检查返回未知状态: {update_result}。应用程序将退出。")
            sys.exit(0)
    else:
        logger.warning("更新检查功能不可用或模块加载失败。应用程序将退出。")
        sys.exit(0)

    # 只有在更新检查成功且不需要退出时，才启动主窗口
    logger.info("应用程序启动主窗口。")
    frame = MyFrame(None, "音频助手")
    set_frame_reference(frame)

    if not init_audio_system():
        logger.error("音频系统初始化失败，应用程序将退出。")
        sys.exit(1)

    frame.Show(True)
    app.MainLoop()
    logger.info("应用程序已退出")


if __name__ == "__main__":
    main()