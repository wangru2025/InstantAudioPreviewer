import threading
import time
import os
import urllib.parse
import hashlib
import pythoncom
import win32com.client
import win32gui # For getting foreground window
import wx # for wx.CallAfter (indirectly via main_frame)

from utils.logger_config import logger
# 导入新的音频命令队列
from core.audio_manager import audio_command_queue, get_last_played_file_path

monitoring_enabled = False
monitor_thread = None
last_detected_file = None
last_detected_file_hash = None
monitor_stop_event = threading.Event()

def is_audio_file(file_path):
    """判断文件是否是支持的音频格式。"""
    audio_extensions = ('.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a', '.wma', '.aiff', '.opus')
    if file_path and os.path.isfile(file_path):
        return file_path.lower().endswith(audio_extensions)
    return False

def get_file_hash(file_path):
    """生成文件路径的哈希值，用于快速比较避免重复处理。"""
    try:
        file_size = os.path.getsize(file_path)
        return hashlib.md5(f"{file_path}-{file_size}".encode('utf-8')).hexdigest()
    except Exception as e:
        logger.warning(f"获取文件哈希时出错: {file_path}, {e}. 仅使用路径哈希。")
        return hashlib.md5(file_path.encode('utf-8')).hexdigest()

def get_selected_file_path_optimized(shell_app):
    """
    通过 COM 接口获取当前文件管理器中选中的文件路径。
    尝试优先获取前台 Explorer 窗口的选中项。
    """
    selected_file_path = None
    foreground_hwnd = win32gui.GetForegroundWindow()

    potential_files = []

    try:
        if not shell_app:
            return None

        # 限制检查的窗口数量，避免遍历过多不相关的窗口
        max_windows_to_check = 10

        for i in range(min(shell_app.Windows().Count, max_windows_to_check)):
            try:
                window = shell_app.Windows().Item(i)

                # 检查是否是文件浏览器窗口，并且包含 LocationURL 属性
                if hasattr(window, 'LocationURL') and window.LocationURL.startswith("file:///"):
                    if hasattr(window, 'Document'):
                        doc = window.Document
                        if hasattr(doc, 'SelectedItems'):
                            items = doc.SelectedItems()
                            if items and items.Count > 0:
                                item = items.Item(0) # 只关心第一个选中项
                                if hasattr(item, 'Path') and item.Path:
                                    item_path = item.Path

                                    # 解析并标准化路径
                                    extracted_path = None
                                    if item_path.startswith("file:///"):
                                        parsed_url = urllib.parse.urlparse(item_path)
                                        extracted_path = urllib.parse.unquote(parsed_url.path)
                                        # Windows 下处理盘符和 UNC 路径
                                        if os.name == 'nt':
                                            if len(extracted_path) > 2 and extracted_path[2] == ':' and extracted_path[1].isalpha():
                                                extracted_path = extracted_path[1:] # 移除开头的斜杠，例如 /C:/ -> C:/
                                            elif extracted_path.startswith('//'): # UNC 路径
                                                extracted_path = '\\\\' + extracted_path[2:].replace('/', '\\')
                                            elif extracted_path.startswith('/'): # 路径以斜杠开头
                                                extracted_path = extracted_path[1:]
                                    elif os.path.isabs(item_path):
                                        extracted_path = item_path

                                    # 验证路径有效性
                                    if extracted_path and os.path.isabs(extracted_path) and os.path.exists(extracted_path) and os.path.isfile(extracted_path):
                                        hwnd = 0
                                        try:
                                            hwnd = window.HWND # 获取窗口句柄
                                        except Exception:
                                            pass # 某些 Shell 窗口可能没有 HWND 属性

                                        potential_files.append({'path': extracted_path, 'hwnd': hwnd})

            except Exception:
                # 忽略单个窗口处理错误，继续检查其他窗口
                pass

    except Exception as e:
        # 捕获 COM 相关的常见错误
        if not ("CoInitialize" in str(e) or "disconnected" in str(e) or "Interface not registered" in str(e) or "server execution failed" in str(e)):
            logger.error(f"获取选中文件时发生COM错误: {e}")

    # 优先返回与前台窗口匹配的文件
    for file_info in potential_files:
        if file_info['hwnd'] == foreground_hwnd:
            return file_info['path']

    # 如果没有前台匹配，则返回第一个检测到的有效文件
    if potential_files:
        return potential_files[0]['path']

    return None


def monitor_explorer_for_audio_files():
    """后台线程函数，持续监视文件管理器选中状态。"""
    global last_detected_file, last_detected_file_hash, monitoring_enabled, audio_command_queue, monitor_stop_event

    # 在 COM 线程中初始化 COM 库
    pythoncom.CoInitialize()
    shell_app_instance = None

    # 检查间隔，50毫秒
    check_interval = 0.02

    try:
        shell_app_instance = win32com.client.Dispatch("Shell.Application")
        logger.info("文件监视器已启动")

        # 异步更新GUI状态信息
        import core.audio_manager as am
        if am._main_frame_ref:
            wx.CallAfter(am._main_frame_ref.update_status_message, "程序已就绪，正在等待您的操作...")

        while not monitor_stop_event.is_set():
            if not monitoring_enabled:
                # 短暂休眠以避免CPU占用过高，同时响应停止信号
                if monitor_stop_event.wait(0.1):
                    break
                continue

            # 优先检查停止事件，确保及时响应
            if monitor_stop_event.wait(0.001):
                break

            try:
                current_selected_file = get_selected_file_path_optimized(shell_app_instance)

                if current_selected_file:
                    current_file_hash = get_file_hash(current_selected_file)

                    if is_audio_file(current_selected_file):
                        # 仅当文件发生变化时处理
                        if current_file_hash != last_detected_file_hash:
                            logger.info(f"检测到新音频文件: {os.path.basename(current_selected_file)}")
                            audio_command_queue.put(("play", current_selected_file))
                            last_detected_file = current_selected_file
                            last_detected_file_hash = current_file_hash
                    else:
                        # 选中了非音频文件，如果之前有播放，则停止
                        if last_detected_file:
                            logger.info(f"选中非音频文件，发送停止播放命令。")
                            audio_command_queue.put(("stop", None))
                            last_detected_file = None
                            last_detected_file_hash = None
                else:
                    # 没有选中任何文件，如果之前有播放，则停止
                    if last_detected_file:
                        logger.info(f"没有选中文件，发送停止播放命令。")
                        audio_command_queue.put(("stop", None))
                        last_detected_file = None
                        last_detected_file_hash = None

            except Exception as inner_e:
                logger.error(f"监视循环中发生错误: {inner_e}", exc_info=True)
                # 发生错误时短暂休眠，避免错误日志刷屏
                time.sleep(0.5)

            # 定期休眠，控制CPU占用
            time.sleep(check_interval)

    except Exception as e:
        logger.error(f"文件监视器发生严重错误: {e}", exc_info=True)
        import core.audio_manager as am
        if am._main_frame_ref:
            wx.CallAfter(am._main_frame_ref.show_error_message, f"文件监视器后台错误：{e}", "监视器错误")
    finally:
        # 释放 COM 对象
        if shell_app_instance is not None:
            try:
                del shell_app_instance
            except Exception:
                pass
            shell_app_instance = None
        # 释放 COM 库资源
        pythoncom.CoUninitialize()
        logger.info("文件监视器线程已退出。")


def start_monitor():
    global monitoring_enabled, monitor_thread, monitor_stop_event
    # 确保只有一个监视线程在运行
    if monitor_thread and monitor_thread.is_alive():
        logger.warning("已存在的监视线程正在运行，尝试停止并重启。")
        stop_monitor() # 尝试优雅停止旧线程
        monitor_thread.join(timeout=2.0) # 等待旧线程结束

    monitoring_enabled = True
    monitor_stop_event.clear() # 清除停止信号
    monitor_thread = threading.Thread(target=monitor_explorer_for_audio_files, daemon=True)
    monitor_thread.start()
    logger.info("文件监视已启用。")

def stop_monitor():
    global monitoring_enabled, monitor_stop_event, last_detected_file, last_detected_file_hash
    if not monitoring_enabled:
        logger.info("文件监视器已处于禁用状态。")
        return

    monitoring_enabled = False
    monitor_stop_event.set() # 发送停止信号
    logger.info("文件监视已禁用，等待线程停止。")

    # 确保在停止时，如果当前有文件正在播放，也发送停止命令
    if last_detected_file:
        audio_command_queue.put(("stop", None))
        logger.info("监视器停止时，发送了停止播放命令。")
    last_detected_file = None
    last_detected_file_hash = None

    if monitor_thread and monitor_thread.is_alive():
        # 等待线程结束，给2秒超时
        monitor_thread.join(timeout=2.0)
        if monitor_thread.is_alive():
            logger.warning("文件监视器线程在超时时间内未能停止。")
        else:
            logger.info("文件监视器线程已成功停止。")