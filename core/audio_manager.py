import wx
import threading
import queue
import atexit
import os
import time
import sys
import vlc # 导入 python-vlc

# 导入 logger
try:
    from utils.logger_config import logger
    logger.info("utils.logger_config 模块已成功导入。")
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)
    logger.warning("使用备用的基础 logger。")

# 播放状态常量
PLAYBACK_STATUS_STOPPED = "stopped"
PLAYBACK_STATUS_PLAYING = "playing"
PLAYBACK_STATUS_PAUSED = "paused"

# VLC 实例和播放器
_vlc_instance = None
_vlc_player = None
_audio_system_initialized = False
_last_played_file_path = None # 记录最后播放的文件路径
_music_duration_ms = 0 # 记录当前音乐的总时长（毫秒）
_playback_status = PLAYBACK_STATUS_STOPPED # 初始化播放状态

# 队列用于从其他线程向音频播放线程发送命令
audio_command_queue = queue.Queue()

# 用于主窗口的引用，以便在其他线程中更新 GUI
_main_frame_ref = None

# --- 硬编码 VLC 的安装路径 ---
# 请根据你的实际安装路径修改此变量，指向 VLC 的安装目录，例如 C:\Program Files\VideoLAN\VLC
VLC_INSTALL_PATH = r"C:\Program Files\VideoLAN\VLC"

def set_frame_reference(frame):
    """设置主窗口的引用，用于通过 wx.CallAfter 更新 GUI。"""
    global _main_frame_ref
    _main_frame_ref = frame
    logger.debug("audio_manager: 主窗口引用已设置。")

def is_audio_system_initialized():
    """检查音频系统是否已初始化。"""
    return _audio_system_initialized

def _vlc_playback_thread():
    """
    VLC 音频播放线程。负责处理 command_queue 中的命令。
    VLC 播放器本身在内部处理大部分播放逻辑，此线程主要用于调度命令和更新状态。
    """
    global _vlc_player, _vlc_instance, _playback_status, _last_played_file_path, _music_duration_ms

    logger.info("VLC 音频播放线程已启动。")
    _playback_status = PLAYBACK_STATUS_STOPPED

    while True:
        try:
            command, arg = audio_command_queue.get(timeout=0.1) # 短暂超时，以便线程可以被终止
            logger.debug(f"音频线程收到命令: {command}, 参数: {arg}")

            if command == "play":
                if _vlc_player:
                    _vlc_player.stop() # 停止当前播放
                    media = _vlc_instance.media_new(arg)
                    _vlc_player.set_media(media)
                    _vlc_player.play()
                    _playback_status = PLAYBACK_STATUS_PLAYING
                    _last_played_file_path = arg
                    # 尝试获取媒体时长
                    media.parse() # 解析媒体信息
                    # 等待媒体解析完成并获取时长
                    for _ in range(50): # 尝试5秒内获取时长，每100ms一次
                        duration = media.get_duration()
                        if duration > 0:
                            _music_duration_ms = duration
                            break
                        time.sleep(0.1)
                    if _music_duration_ms <= 0:
                        logger.warning(f"未能获取媒体时长: {arg}")
                    logger.info(f"开始播放: {arg}, 时长: {_music_duration_ms / 1000:.2f}s")
                    if _main_frame_ref:
                        wx.CallAfter(_main_frame_ref.update_status_message, f"正在播放: {os.path.basename(arg)}")

            elif command == "stop":
                if _vlc_player and (_vlc_player.is_playing() or _vlc_player.get_state() == vlc.State.Paused):
                    _vlc_player.stop()
                    _playback_status = PLAYBACK_STATUS_STOPPED
                    logger.info("停止播放。")
                    if _main_frame_ref:
                        wx.CallAfter(_main_frame_ref.update_status_message, "播放已停止。")

            elif command == "pause":
                if _vlc_player and _vlc_player.is_playing():
                    _vlc_player.set_pause(1)
                    _playback_status = PLAYBACK_STATUS_PAUSED
                    logger.info("暂停播放。")
                    if _main_frame_ref:
                        wx.CallAfter(_main_frame_ref.update_status_message, "播放已暂停。")

            elif command == "resume":
                if _vlc_player and _vlc_player.get_state() == vlc.State.Paused:
                    _vlc_player.set_pause(0)
                    _playback_status = PLAYBACK_STATUS_PLAYING
                    logger.info("恢复播放。")
                    if _main_frame_ref:
                        wx.CallAfter(_main_frame_ref.update_status_message, "播放已恢复。")

            elif command == "toggle_play_pause":
                if _vlc_player:
                    current_state = _vlc_player.get_state()
                    if current_state == vlc.State.Playing:
                        _vlc_player.set_pause(1)
                        _playback_status = PLAYBACK_STATUS_PAUSED
                        logger.info("播放器状态切换到暂停。")
                        if _main_frame_ref:
                            wx.CallAfter(_main_frame_ref.update_status_message, "播放已暂停。")
                    elif current_state == vlc.State.Paused:
                        _vlc_player.set_pause(0)
                        _playback_status = PLAYBACK_STATUS_PLAYING
                        logger.info("播放器状态切换到播放。")
                        if _main_frame_ref:
                            wx.CallAfter(_main_frame_ref.update_status_message, "播放已恢复。")
                    elif current_state == vlc.State.Stopped and _last_played_file_path:
                        # 如果是停止状态，尝试重新播放上次的媒体
                        media = _vlc_instance.media_new(_last_played_file_path)
                        _vlc_player.set_media(media)
                        _vlc_player.play()
                        _playback_status = PLAYBACK_STATUS_PLAYING
                        logger.info(f"重新播放上次媒体: {_last_played_file_path}")
                        if _main_frame_ref:
                            wx.CallAfter(_main_frame_ref.update_status_message, f"正在播放: {os.path.basename(_last_played_file_path)}")

            elif command == "seek":
                if _vlc_player and (_vlc_player.is_playing() or _vlc_player.get_state() == vlc.State.Paused) and _music_duration_ms > 0:
                    current_time_ms = _vlc_player.get_time()
                    if current_time_ms == -1: # get_time() might return -1 if media is not ready or playing
                        logger.warning("VLC get_time() returned -1, cannot seek accurately.")
                        continue
                    
                    # arg 是秒数，转换为毫秒
                    seek_delta_ms = int(arg * 1000)
                    new_time_ms = current_time_ms + seek_delta_ms

                    # 边界检查
                    if new_time_ms < 0:
                        new_time_ms = 0
                    elif new_time_ms > _music_duration_ms:
                        new_time_ms = _music_duration_ms

                    _vlc_player.set_time(new_time_ms)
                    logger.info(f"跳转到: {new_time_ms / 1000:.2f}s (从 {current_time_ms / 1000:.2f}s 调整 {arg}s)")
                    if _main_frame_ref:
                        wx.CallAfter(_main_frame_ref.update_status_message,
                                     f"快进/退: {new_time_ms / 1000:.1f}s / {_music_duration_ms / 1000:.1f}s")
            
            elif command == "quit_thread":
                logger.info("音频播放线程收到退出命令，正在关闭。")
                break # 退出循环，线程结束

            audio_command_queue.task_done() # 标记任务完成

        except queue.Empty:
            # 队列为空，继续等待命令
            # 可以在这里做一些定期的状态检查或更新
            if _vlc_player:
                current_state = _vlc_player.get_state()
                if current_state == vlc.State.Ended:
                    if _playback_status != PLAYBACK_STATUS_STOPPED:
                        logger.info("VLC 播放结束。")
                        _playback_status = PLAYBACK_STATUS_STOPPED
                        if _main_frame_ref:
                            wx.CallAfter(_main_frame_ref.update_status_message, "播放结束。")
                    # 防止连续触发Ended状态的日志
                    # _vlc_player.stop() # 确保播放器状态真正停止并重置 - 谨慎使用，可能导致状态误判

                elif current_state == vlc.State.Playing and _playback_status != PLAYBACK_STATUS_PLAYING:
                    _playback_status = PLAYBACK_STATUS_PLAYING
                    logger.debug("VLC 播放器状态更新为播放中。")
                elif current_state == vlc.State.Paused and _playback_status != PLAYBACK_STATUS_PAUSED:
                    _playback_status = PLAYBACK_STATUS_PAUSED
                    logger.debug("VLC 播放器状态更新为暂停。")
                elif current_state == vlc.State.Stopped and _playback_status != PLAYBACK_STATUS_STOPPED:
                    _playback_status = PLAYBACK_STATUS_STOPPED
                    logger.debug("VLC 播放器状态更新为停止。")
        except Exception as e:
            logger.error(f"音频播放线程发生未处理错误: {e}", exc_info=True)

# 启动音频播放线程
_audio_thread = threading.Thread(target=_vlc_playback_thread, daemon=True)

def init_audio_system():
    """
    初始化 VLC 音频系统。
    """
    global _vlc_instance, _vlc_player, _audio_system_initialized, _audio_thread

    if _audio_system_initialized:
        logger.info("音频系统已初始化，无需重复初始化。")
        return True

    logger.info("正在初始化 VLC 音频系统...")
    try:
        # --- 指定 libvlc.dll 的路径 ---
        # python-vlc 会自动查找 libvlc.dll，我们只需确保 VLC_INSTALL_PATH 指向 VLC 的安装目录
        # 并且 libvlc.dll 存在于该目录下。
        vlc_dll_dir = VLC_INSTALL_PATH 
        libvlc_path = os.path.join(vlc_dll_dir, "libvlc.dll")

        if not os.path.exists(libvlc_path):
            raise FileNotFoundError(f"libvlc.dll 未在指定路径找到: {libvlc_path}")
        
        # 设置 vlc 库的搜索路径。python-vlc 会使用此路径找到 libvlc.dll
        vlc.libvlc_dll_path = libvlc_path

        # 创建 VLC 实例，传递其他需要的命令行参数
        # --no-video 和 --vout=dummy 是用于纯音频播放的合理参数
        # 移除 --libvlc-dll 参数，因为它现在通过 vlc.libvlc_dll_path 管理
        _vlc_instance = vlc.Instance("--no-video", "--vout=dummy")
        
        if not _vlc_instance:
            raise RuntimeError("VLC 实例创建失败。")
            
        _vlc_player = _vlc_instance.media_player_new()
        if not _vlc_player:
            raise RuntimeError("VLC 播放器创建失败。")

        _audio_system_initialized = True
        logger.info(f"VLC 音频系统初始化成功。libvlc.dll 路径已配置为: {vlc.libvlc_dll_path}")

        # 确保播放线程只启动一次
        if not _audio_thread.is_alive():
            _audio_thread.start()
            logger.info("VLC 音频播放调度线程已启动。")

        # 注册退出函数，确保清理
        atexit.register(free_audio_system)
        logger.info("已注册 free_audio_system 到 atexit。")

        return True

    except FileNotFoundError as e:
        logger.critical(f"VLC 库文件未找到: {e}", exc_info=True)
        if _main_frame_ref:
            wx.CallAfter(_main_frame_ref.show_error_message, f"{e}\n请确认 VLC 已安装，并且 VLC_INSTALL_PATH 变量在 audio_manager.py 中设置正确。\n"
                         f"当前设置的 VLC 安装路径: {VLC_INSTALL_PATH}", "VLC 库文件未找到")
        _audio_system_initialized = False
        return False
    except RuntimeError as e:
        logger.critical(f"VLC 运行时错误: {e}", exc_info=True)
        if _main_frame_ref:
            wx.CallAfter(_main_frame_ref.show_error_message, f"VLC 运行时错误: {e}", "VLC 初始化错误")
        _audio_system_initialized = False
        return False
    except Exception as e:
        logger.critical(f"VLC 音频系统初始化失败（未知错误）: {e}", exc_info=True)
        if _main_frame_ref:
            wx.CallAfter(_main_frame_ref.show_error_message, f"VLC 音频系统初始化失败：{e}", "VLC 初始化错误")
        _audio_system_initialized = False
        return False

def free_audio_system():
    """
    释放 VLC 音频系统资源。
    """
    global _vlc_instance, _vlc_player, _audio_system_initialized, _audio_thread

    if not _audio_system_initialized and not (_audio_thread and _audio_thread.is_alive()):
        logger.info("音频系统未初始化或线程未运行，无需释放。")
        return

    logger.info("正在释放 VLC 音频系统资源...")

    # 1. 发送退出线程命令，并等待线程结束
    if _audio_thread and _audio_thread.is_alive():
        try:
            logger.debug("发送 quit_thread 命令给音频线程。")
            audio_command_queue.put(("quit_thread", None))
            _audio_thread.join(timeout=2.0) # 等待线程结束
            if _audio_thread.is_alive():
                logger.warning("VLC 音频播放线程在超时时间内未能退出。")
            else:
                logger.info("VLC 音频播放线程已成功退出。")
        except Exception as e:
            logger.error(f"在退出音频线程时发生错误: {e}", exc_info=True)

    # 2. 停止并释放 VLC 播放器
    if _vlc_player:
        try:
            if _vlc_player.is_playing() or _vlc_player.get_state() == vlc.State.Paused:
                _vlc_player.stop()
            _vlc_player.release() # 释放播放器资源
            _vlc_player = None
            logger.info("VLC 播放器已释放。")
        except Exception as e:
            logger.error(f"释放 VLC 播放器时出错: {e}", exc_info=True)

    # 3. 释放 VLC 实例
    if _vlc_instance:
        try:
            _vlc_instance.release() # 释放 VLC 实例
            _vlc_instance = None
            logger.info("VLC 实例已释放。")
        except Exception as e:
            logger.error(f"释放 VLC 实例时出错: {e}", exc_info=True)

    _audio_system_initialized = False
    logger.info("VLC 音频系统资源已释放。")

def play_audio(file_path):
    """
    播放指定路径的音频文件。
    """
    if not _audio_system_initialized:
        logger.warning("无法播放音频：音频系统未初始化。")
        if _main_frame_ref:
            wx.CallAfter(_main_frame_ref.show_error_message, "音频系统未初始化，无法播放。", "操作错误")
        return
    
    if not os.path.exists(file_path):
        logger.error(f"文件不存在，无法播放: {file_path}")
        if _main_frame_ref:
            wx.CallAfter(_main_frame_ref.show_error_message, f"文件不存在或无法访问: {file_path}", "播放错误")
        return

    # 发送播放命令到音频线程
    audio_command_queue.put(("play", file_path))
    logger.info(f"播放命令已发送: {file_path}")

def stop_audio():
    """
    停止当前正在播放的音频。
    """
    if not _audio_system_initialized:
        logger.warning("尝试停止音频，但音频系统未准备好。")
        return
    audio_command_queue.put(("stop", None))
    logger.info("停止音频命令已发送。")

def pause_audio():
    """
    暂停当前正在播放的音频。
    """
    if not _audio_system_initialized:
        logger.warning("无法暂停音频：音频系统未初始化。")
        return
    audio_command_queue.put(("pause", None))
    logger.info("暂停音频命令已发送。")

def resume_audio():
    """
    恢复暂停的音频。
    """
    if not _audio_system_initialized:
        logger.warning("无法恢复音频：音频系统未初始化。")
        return
    audio_command_queue.put(("resume", None))
    logger.info("恢复音频命令已发送。")

def toggle_play_pause():
    """
    切换播放/暂停状态。
    """
    if not _audio_system_initialized:
        logger.warning("无法切换播放/暂停：音频系统未初始化。")
        return
    audio_command_queue.put(("toggle_play_pause", None))
    logger.info("切换播放/暂停命令已发送。")

def seek_audio(seconds_delta):
    """
    调整音频播放进度。
    seconds_delta: 正数表示快进，负数表示快退。
    """
    if not _audio_system_initialized:
        logger.warning("无法调整进度：音频系统未初始化。")
        return
    # 检查是否有媒体正在播放或暂停，并且时长已知，否则seek可能无效
    if _music_duration_ms <= 0:
        logger.warning("当前媒体时长未知，无法进行精确跳转。")
        # 仍然可以尝试发送命令，VLC 可能会处理，但可能不如预期
    audio_command_queue.put(("seek", seconds_delta))
    logger.info(f"跳转命令已发送: {seconds_delta}s")

def get_current_playback_status():
    """
    获取当前音频播放的状态 ("stopped", "playing", "paused")。
    """
    return _playback_status

def get_last_played_file_path():
    """
    返回最后一次成功播放的音频文件的路径。
    """
    return _last_played_file_path

def check_and_process_audio_queue():
    """
    这个函数被主线程的定时器调用，用于检查音频命令队列。
    在 VLC 实现中，此函数的主要作用是让音频线程有机会处理命令和更新状态。
    此处不需要额外逻辑，因为_vlc_playback_thread负责处理队列。
    """
    pass # 队列处理已经由 _vlc_playback_thread 完成

logger.info("audio_manager 模块已加载。")