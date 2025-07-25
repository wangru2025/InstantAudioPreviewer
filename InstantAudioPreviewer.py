import wx
import ctypes
import os
import sys
import atexit
import traceback

# 导入核心功能模块
try:
    import core.audio_manager
    from core.file_monitor import monitoring_enabled, monitor_thread, monitor_stop_event, start_monitor, stop_monitor
    from hotkey.hotkey_manager import HotkeyManager, EVT_HOTKEY_TRIGGERED, HotkeyEvent
    from hotkey.hotkey_dialog import HotkeySettingsDialog
    from utils.unified_tts_speaker import unified_speaker
    from core.database_manager import DatabaseManager
    from gui.search_results_dialog import SearchResultsDialog
    from utils.logger_config import logger # 确保 logger 导入自同一个源
except ImportError as e:
    print(f"FATAL ERROR: 无法导入核心模块，请检查依赖项: {e}", file=sys.stderr)
    sys.exit(1)

_main_frame_instance = None # 全局引用，用于在其他模块中访问主窗口实例

class MyFrame(wx.Frame):
    def __init__(self, parent, title):
        try:
            super(MyFrame, self).__init__(parent, title=title, size=(400, 150))
            self.panel = wx.Panel(self)
            self.Bind(wx.EVT_CLOSE, self.on_close)
            self.Bind(wx.EVT_ICONIZE, self.on_iconize)

            global _main_frame_instance
            _main_frame_instance = self
            logger.debug("MyFrame 实例已注册到全局。")

            self.hotkey_functions = {
                "toggle_monitor": "开始/停止监视",
                "toggle_visibility": "隐藏/显示窗口",
                "exit_application": "退出程序",
                "toggle_play_pause": "播放/暂停",
                "fast_forward": "快进",
                "rewind": "快退",
                "add_label": "添加音频标签",
                "search_label": "搜索音频标签"
            }
            self.hotkey_manager = HotkeyManager(self)
            # 绑定处理热键事件的函数
            self.Bind(EVT_HOTKEY_TRIGGERED, self.handle_hotkey_event)

            self.db_manager = DatabaseManager()

            self.create_widgets()
            self.layout_widgets()
            self.update_ui_state()

            # 检查音频系统是否初始化成功
            if not core.audio_manager.is_audio_system_initialized():
                self.show_error_message("音频播放核心组件未能成功初始化，部分功能可能受限。", "音频系统警告")
                logger.warning("音频系统未初始化，部分功能可能无法使用。")

            self.audio_status_timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, self.on_check_queue_and_playback, self.audio_status_timer)
            self.audio_status_timer.Start(50)

            self._fast_forward_timer = wx.Timer(self)
            self._rewind_timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, self.on_fast_forward_timer, self._fast_forward_timer)
            self.Bind(wx.EVT_TIMER, self.on_rewind_timer, self._rewind_timer)

            self._fast_forward_pressed = False
            self._rewind_pressed = False
            # --- 修复第二个问题：为 toggle_play_pause 添加释放事件处理 ---
            self._toggle_play_pause_pressed = False # 跟踪 toggle_play_pause 按下的状态

            logger.info("GUI 应用程序主窗口已成功初始化。")

        except Exception as e:
            error_message = f"MyFrame 初始化过程中发生严重错误: {e}"
            logger.critical(error_message, exc_info=True)
            if wx.App.Get() and wx.App.Get().IsInitialized():
                 wx.MessageBox(f"{error_message}\n应用程序将退出。", "致命错误", wx.OK | wx.ICON_ERROR)
            else:
                print(f"FATAL ERROR: {error_message}\n{traceback.format_exc()}", file=sys.stderr)
            sys.exit(1)

    def get_display_name_for_func(self, func_name):
        return self.hotkey_functions.get(func_name, func_name)

    def create_widgets(self):
        self.status_label = wx.StaticText(self.panel, label="当前状态:")
        self.status_message_label = wx.StaticText(self.panel, label="未开始预览")
        self.toggle_button = wx.Button(self.panel, label="开始预览")
        self.toggle_button.Bind(wx.EVT_BUTTON, self.on_toggle_monitor)
        self.settings_button = wx.Button(self.panel, label="快捷键设置")
        self.settings_button.Bind(wx.EVT_BUTTON, self.on_open_hotkey_settings)

    def layout_widgets(self):
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        status_sizer = wx.BoxSizer(wx.HORIZONTAL)
        status_sizer.Add(self.status_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 5)
        status_sizer.Add(self.status_message_label, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)
        main_sizer.Add(status_sizer, 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 5)
        main_sizer.Add(self.toggle_button, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.ALL, 5)
        main_sizer.Add(self.settings_button, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 5)
        self.panel.SetSizer(main_sizer)
        self.panel.Fit()
        self.Layout()
        self.Centre()

    def on_toggle_monitor(self, event=None):
        global monitoring_enabled

        if not core.audio_manager.is_audio_system_initialized():
            self.show_error_message("音频播放核心组件未加载或初始化失败，功能无法启动。", "功能无法启动")
            logger.warning("尝试启动监视，但音频系统未初始化。")
            return

        if not monitoring_enabled:
            logger.info("用户点击 '开始预览'，启动文件监视。")
            start_monitor()
            unified_speaker.speak("开始监视")
        else:
            logger.info("用户点击 '停止预览'，停止文件监视和当前播放。")
            core.audio_manager.stop_audio() # 停止播放
            stop_monitor()
            unified_speaker.speak("停止监视")

        monitoring_enabled = not monitoring_enabled
        self.update_ui_state()

    def update_ui_state(self):
        if monitoring_enabled:
            self.status_label.SetLabel("当前状态: 正在运行")
            self.toggle_button.SetLabel("停止预览")
            self.status_message_label.SetLabel("请在文件管理器中选择音频文件...")
        else:
            self.status_label.SetLabel("当前状态: 未开始")
            self.toggle_button.SetLabel("开始预览")
            self.status_message_label.SetLabel('点击"开始预览"按钮启动。')
        self.panel.Layout()

    def update_status_message(self, message):
        # 使用 CallAfter 确保在主线程中更新 UI
        wx.CallAfter(self._update_status_label, message)

    def _update_status_label(self, message):
        # 仅当消息发生变化时更新，避免不必要的 UI 刷新
        if self.status_message_label and self.status_message_label.GetLabel() != message:
            self.status_message_label.SetLabel(message)
            self.panel.Layout()

    def show_error_message(self, message, title="出错了"):
        # 使用 CallAfter 确保在主线程中弹出消息框
        wx.CallAfter(lambda: wx.MessageBox(message, title, wx.OK | wx.ICON_ERROR))
        logger.error(f"显示错误消息: {title} - {message}")

    def on_check_queue_and_playback(self, event):
        try:
            core.audio_manager.check_and_process_audio_queue()
        except Exception as e:
            logger.error(f"定时器事件 on_check_queue_and_playback 发生意外错误: {e}", exc_info=True)
            if self.audio_status_timer.IsRunning():
                self.audio_status_timer.Stop()
                self.show_error_message(f"音频检查定时器发生严重错误，已停止。\n请重启程序。\n错误: {e}", "内部错误")

    def on_open_hotkey_settings(self, event):
        dialog = HotkeySettingsDialog(self, self.hotkey_manager)
        if dialog.ShowModal() == wx.ID_OK:
            self.on_hotkey_config_changed()
        dialog.Destroy()

    def on_hotkey_config_changed(self):
        logger.info("快捷键配置已更改，GUI 收到通知。")
        # 可以在这里刷新 UI 或执行其他更新

    def handle_hotkey_event(self, event: HotkeyEvent):
        """处理快捷键按下事件"""
        func_name = event.func_name
        logger.info(f"快捷键触发 (按下): {func_name}")

        if func_name == "toggle_monitor":
            self.on_toggle_monitor()
        elif func_name == "toggle_visibility":
            self.toggle_visibility()
        elif func_name == "exit_application":
            self.Close() # 发送关闭事件
        elif func_name == "toggle_play_pause":
            # --- 修复第二个问题：防止快速多次触发 ---
            if not self._toggle_play_pause_pressed: # 仅在未按下时处理
                core.audio_manager.toggle_play_pause()
                unified_speaker.speak("播放或暂停")
                self._toggle_play_pause_pressed = True # 标记为已按下
        elif func_name == "fast_forward":
            if not self._fast_forward_pressed:
                logger.debug("快进快捷键按下，启动快进定时器。")
                self._fast_forward_pressed = True
                self._fast_forward_timer.Start(200) # 200ms 间隔触发一次
                # 立即快进1秒，即使定时器未触发，也能立即响应
                core.audio_manager.audio_command_queue.put(("seek", 1.0))
                unified_speaker.speak("快进")
        elif func_name == "rewind":
            if not self._rewind_pressed:
                logger.debug("快退快捷键按下，启动快退定时器。")
                self._rewind_pressed = True
                self._rewind_timer.Start(200) # 200ms 间隔触发一次
                # 立即快退1秒
                core.audio_manager.audio_command_queue.put(("seek", -1.0))
                unified_speaker.speak("快退")
        elif func_name == "add_label":
            self.on_add_label_hotkey()
        elif func_name == "search_label":
            self.on_search_label_hotkey()

    def on_hotkey_release_event(self, func_name):
        """处理快捷键释放事件"""
        logger.info(f"快捷键释放: {func_name}")

        # --- 修复第二个问题：重置状态标志 ---
        if func_name == "toggle_play_pause":
            self._toggle_play_pause_pressed = False # 释放时重置标志
        elif func_name == "fast_forward":
            if self._fast_forward_pressed: # 只有在按下了才停止
                self._fast_forward_timer.Stop()
                self._fast_forward_pressed = False # 重置标志
        elif func_name == "rewind":
            if self._rewind_pressed: # 只有在按下了才停止
                self._rewind_timer.Stop()
                self._rewind_pressed = False # 重置标志

    def on_fast_forward_timer(self, event):
        if self._fast_forward_pressed:
            # continue sending seek commands while the key is held down
            core.audio_manager.audio_command_queue.put(("seek", 1.0))
            logger.debug("快进定时器触发，发送快进命令。")
        else:
            # 如果标志被重置了（例如在释放事件中），停止定时器
            self._fast_forward_timer.Stop()

    def on_rewind_timer(self, event):
        if self._rewind_pressed:
            # continue sending seek commands while the key is held down
            core.audio_manager.audio_command_queue.put(("seek", -1.0))
            logger.debug("快退定时器触发，发送快退命令。")
        else:
            # 如果标志被重置了，停止定时器
            self._rewind_timer.Stop()

    def toggle_visibility(self):
        if self.IsShown():
            self.Hide()
            logger.info("窗口已隐藏。")
            unified_speaker.speak("隐藏")
        else:
            self.Show()
            self.Raise() # 确保窗口显示在最前面
            logger.info("窗口已显示。")
            unified_speaker.speak("显示")

    def on_iconize(self, event):
        # This event fires when the window is minimized (becomes an icon)
        if self.IsIconized():
            logger.info("窗口已最小化 (图标化)。")
            unified_speaker.speak("隐藏")
        else:
            logger.info("窗口已还原。")
            unified_speaker.speak("显示")
        event.Skip() # Allow default handling

    def on_close(self, event):
        logger.info("正在关闭应用程序...")
        # 确保停止正在进行的音频播放
        core.audio_manager.stop_audio()
        # 停止文件监视
        stop_monitor()
        
        # 停止所有活动的定时器
        if hasattr(self, 'audio_status_timer') and self.audio_status_timer.IsRunning():
            self.audio_status_timer.Stop()
        if hasattr(self, '_fast_forward_timer') and self._fast_forward_timer.IsRunning():
            self._fast_forward_timer.Stop()
        if hasattr(self, '_rewind_timer') and self._rewind_timer.IsRunning():
            self._rewind_timer.Stop()
            
        # 显式解除热键（虽然 atexit 也会处理，但显式执行更好）
        if hasattr(self, 'hotkey_manager'):
            self.hotkey_manager._unregister_hotkeys() # 清除内部注册状态

        unified_speaker.stop_speak() # 停止任何正在进行的语音播报
        logger.info("所有后台服务和资源已停止。")
        
        # 销毁窗口会导致 MainLoop 退出
        event.Skip() # 允许关闭事件继续传播
        self.Destroy()

    def on_add_label_hotkey(self):
        current_audio_path = core.audio_manager.get_last_played_file_path()
        if not current_audio_path or not os.path.exists(current_audio_path):
            msg = "没有正在播放或最近播放的音频文件，无法添加标签。"
            self.show_error_message(msg, "操作失败")
            unified_speaker.speak(msg)
            logger.warning(msg)
            return

        dlg = wx.TextEntryDialog(self, f"为 '{os.path.basename(current_audio_path)}' 添加标签 (多个标签用逗号分隔):",
                                "添加音频标签", "", style=wx.TextEntryDialogStyle | wx.OK | wx.CANCEL)

        unified_speaker.speak(f"请为音频文件 {os.path.basename(current_audio_path)} 添加标签。多个标签请用逗号分隔。")
        dlg.CenterOnParent()

        if dlg.ShowModal() == wx.ID_OK:
            labels_input = dlg.GetValue().strip()
            if not labels_input:
                msg = "未输入任何标签。"
                self.show_error_message(msg, "添加失败")
                unified_speaker.speak(msg)
                logger.info(msg)
                dlg.Destroy()
                return

            labels = [label.strip() for label in labels_input.split(',') if label.strip()]
            if not labels:
                msg = "标签输入无效，请检查格式。"
                self.show_error_message(msg, "添加失败")
                unified_speaker.speak(msg)
                logger.warning(msg)
                dlg.Destroy()
                return

            try:
                for label in labels:
                    self.db_manager.add_audio_label(current_audio_path, label)
                msg = f"已成功为 '{os.path.basename(current_audio_path)}' 添加标签: {', '.join(labels)}"
                self.update_status_message(msg)
                unified_speaker.speak(msg)
                logger.info(msg)
            except Exception as e:
                error_msg = f"添加标签到数据库失败: {e}"
                self.show_error_message(error_msg, "数据库错误")
                unified_speaker.speak(error_msg)
                logger.error(error_msg, exc_info=True)
        else:
            msg = "取消添加标签。"
            self.update_status_message(msg)
            unified_speaker.speak(msg)
            logger.info(msg)
        dlg.Destroy()

    def on_search_label_hotkey(self):
        dlg = wx.TextEntryDialog(self, "请输入要搜索的音频标签:", "搜索音频", "", style=wx.TextEntryDialogStyle | wx.OK | wx.CANCEL)

        unified_speaker.speak("请输入要搜索的音频标签。")
        dlg.CenterOnParent()

        if dlg.ShowModal() == wx.ID_OK:
            search_label = dlg.GetValue().strip()
            if not search_label:
                msg = "未输入搜索标签。"
                self.show_error_message(msg, "搜索失败")
                unified_speaker.speak(msg)
                logger.info(msg)
                dlg.Destroy()
                return

            try:
                matching_files = self.db_manager.get_audios_by_label(search_label)

                if not matching_files:
                    msg = f"未找到与标签 '{search_label}' 匹配的音频文件。"
                    self.show_error_message(msg, "搜索结果")
                    unified_speaker.speak(msg)
                    logger.info(msg)
                    dlg.Destroy()
                    return

                result_dlg = SearchResultsDialog(self, f"搜索结果: {search_label}", matching_files)
                result_dlg.ShowModal()
                result_dlg.Destroy()
                unified_speaker.speak(f"搜索完成，找到 {len(matching_files)} 个匹配文件。")

            except Exception as e:
                error_msg = f"搜索标签失败: {e}"
                self.show_error_message(error_msg, "数据库错误")
                unified_speaker.speak(error_msg)
                logger.error(error_msg, exc_info=True)
        else:
            msg = "取消搜索标签。"
            self.update_status_message(msg)
            unified_speaker.speak(msg)
            logger.info(msg)
        dlg.Destroy()

APP_CURRENT_VERSION = "1.0.0"

if sys.platform == 'win32':
    try:
        myappid = 'com.yourcompany.FileManagerAudioPreview.1.0'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception as e:
        logger.warning(f"设置应用程序用户模型ID失败: {e}")

def main():
    # 确保只创建一个 wx.App 实例
    app = wx.App.Get()
    if not app:
        app = wx.App(False)

    # 初始化音频系统，在创建主窗口之前
    if not core.audio_manager.init_audio_system():
        logger.critical("音频系统初始化失败，应用程序将退出。")
        # 尝试显示错误信息（如果 wx 已经初始化）
        if app and app.IsInitialized():
            wx.MessageBox("音频系统初始化失败。请检查 VLC 安装以及配置。\n应用程序将退出。", "致命错误", wx.OK | wx.ICON_ERROR)
        sys.exit(1)

    logger.info("应用程序准备启动主窗口。")

    frame = None
    try:
        frame = MyFrame(None, "音频助手")

        frame.Show(True)
        frame.Raise()
        frame.SetFocus()

        if frame:
             core.audio_manager.set_frame_reference(frame)

        app.MainLoop()

    except Exception as e:
        error_message = f"应用程序启动或运行过程中发生严重错误: {e}"
        logger.critical(error_message, exc_info=True)
        # 仅当 App 已初始化但 MainLoop 未运行时显示 MessageBox
        if wx.App.Get() and wx.App.Get().IsInitialized() and not wx.App.Get().IsMainLoopRunning():
             wx.MessageBox(f"{error_message}\n请检查日志文件以获取详细信息。", "致命错误", wx.OK | wx.ICON_ERROR)
        else:
            print(f"FATAL ERROR: {error_message}\n{traceback.format_exc()}", file=sys.stderr)
        sys.exit(1)

    finally:
        # 确保在程序退出时清理音频系统资源
        core.audio_manager.free_audio_system()
        logger.info("应用程序主流程结束。")

if __name__ == "__main__":
    main()