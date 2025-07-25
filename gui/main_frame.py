import wx
import threading
import queue
import re
import time
import os
import sys
import traceback # 用于更详细的异常信息

import core.audio_manager
from core.file_monitor import monitoring_enabled, monitor_thread, monitor_stop_event, start_monitor, stop_monitor
from hotkey.hotkey_manager import HotkeyManager, EVT_HOTKEY_TRIGGERED, HotkeyEvent
from hotkey.hotkey_dialog import HotkeySettingsDialog
from utils.logger_config import logger
from utils.unified_tts_speaker import unified_speaker # 导入统一的TTS接口

# --- 新增导入：数据库管理器和搜索结果对话框 ---
from core.database_manager import DatabaseManager
from gui.search_results_dialog import SearchResultsDialog

_main_frame_instance = None # 全局引用，用于在其他模块中访问主窗口实例

# --- 添加顶层 try-except 块来捕获类定义过程中的错误 ---
try:
    class MyFrame(wx.Frame):
        def __init__(self, parent, title):
            # MyFrame.__init__ 内部的 try-except 已经有了，用于捕获初始化运行时错误
            try:
                # 尝试创建 Frame，并设置一个合理的默认大小
                super(MyFrame, self).__init__(parent, title=title, size=(400, 150))
                self.panel = wx.Panel(self)
                self.Bind(wx.EVT_CLOSE, self.on_close)
                self.Bind(wx.EVT_ICONIZE, self.on_iconize)

                global _main_frame_instance
                _main_frame_instance = self
                logger.debug("MyFrame 实例已注册到全局。")

                # 快捷键功能映射：功能名 -> 用户显示名称
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
                # 初始化快捷键管理器
                self.hotkey_manager = HotkeyManager(self)
                # 绑定快捷键触发事件
                self.Bind(EVT_HOTKEY_TRIGGERED, self.handle_hotkey_event)

                # --- 初始化数据库管理器 ---
                self.db_manager = DatabaseManager()

                self.create_widgets()
                self.layout_widgets()
                self.update_ui_state()

                # 定时器用于周期性检查音频播放队列和状态
                self.audio_status_timer = wx.Timer(self)
                self.Bind(wx.EVT_TIMER, self.on_check_queue_and_playback, self.audio_status_timer)
                # 启动定时器：每 50 毫秒检查一次。
                # 由于音频系统已提前初始化，这里的定时器启动不会报“音频系统未初始化”的警告。
                self.audio_status_timer.Start(50)

                # 定时器用于长按快进快退
                self._fast_forward_timer = wx.Timer(self)
                self._rewind_timer = wx.Timer(self)
                self.Bind(wx.EVT_TIMER, self.on_fast_forward_timer, self._fast_forward_timer)
                self.Bind(wx.EVT_TIMER, self.on_rewind_timer, self._rewind_timer)

                # 记录快捷键按键状态，用于处理长按和避免重复触发
                self._fast_forward_pressed = False
                self._rewind_pressed = False
                self._toggle_play_pause_pressed = False

                logger.info("GUI 应用程序主窗口已成功初始化。")

            except Exception as e:
                # 捕获 MyFrame 初始化过程中的所有异常
                error_message = f"MyFrame 初始化过程中发生严重错误: {e}"
                logger.critical(error_message, exc_info=True)
                # 尝试显示一个错误对话框
                if wx.App.Get() and wx.App.Get().IsInitialized():
                     wx.MessageBox(f"{error_message}\n应用程序将退出。", "致命错误", wx.OK | wx.ICON_ERROR)
                # 即使wx.App未初始化，也尝试打印到控制台
                else:
                    print(f"FATAL ERROR: {error_message}\n{traceback.format_exc()}", file=sys.stderr)
                # 关键：如果主窗口创建失败，应立即退出，防止后续调用导致更多错误
                sys.exit(1)

        def get_display_name_for_func(self, func_name):
            """根据功能名获取用户友好的显示名称。"""
            return self.hotkey_functions.get(func_name, func_name)

        def create_widgets(self):
            """创建 GUI 控件。"""
            self.status_label = wx.StaticText(self.panel, label="当前状态:")
            self.status_message_label = wx.StaticText(self.panel, label="未开始预览")
            self.toggle_button = wx.Button(self.panel, label="开始预览")
            self.toggle_button.Bind(wx.EVT_BUTTON, self.on_toggle_monitor)
            self.settings_button = wx.Button(self.panel, label="快捷键设置")
            self.settings_button.Bind(wx.EVT_BUTTON, self.on_open_hotkey_settings)

        def layout_widgets(self):
            """布局 GUI 控件。"""
            main_sizer = wx.BoxSizer(wx.VERTICAL)
            status_sizer = wx.BoxSizer(wx.HORIZONTAL)
            status_sizer.Add(self.status_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 5)
            status_sizer.Add(self.status_message_label, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)
            main_sizer.Add(status_sizer, 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 5)
            main_sizer.Add(self.toggle_button, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.ALL, 5)
            main_sizer.Add(self.settings_button, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 5)
            self.panel.SetSizer(main_sizer)
            self.panel.Fit() # 尝试根据子控件自动调整Panel大小
            self.Layout() # 重新布局Frame
            self.Centre() # 居中窗口

        def on_toggle_monitor(self, event=None):
            """处理开始/停止文件监视的逻辑。"""
            global monitoring_enabled

            if not core.audio_manager._audio_system_initialized:
                self.show_error_message("音频播放核心组件未加载或初始化失败，功能无法启动。", "功能无法启动")
                logger.warning("尝试启动监视，但音频系统未初始化。")
                return

            if not monitoring_enabled:
                logger.info("用户点击 '开始预览'，启动文件监视。")
                start_monitor()
                unified_speaker.speak("开始监视")
            else:
                logger.info("用户点击 '停止预览'，停止文件监视和当前播放。")
                # 发送停止命令给音频管理器
                core.audio_manager.audio_command_queue.put(("stop", None))
                stop_monitor()
                unified_speaker.speak("停止监视")

            monitoring_enabled = not monitoring_enabled
            self.update_ui_state()

        def update_ui_state(self):
            """根据当前状态更新界面元素。"""
            if monitoring_enabled:
                self.status_label.SetLabel("当前状态: 正在运行")
                self.toggle_button.SetLabel("停止预览")
                self.status_message_label.SetLabel("请在文件管理器中选择音频文件...")
            else:
                self.status_label.SetLabel("当前状态: 未开始")
                self.toggle_button.SetLabel("开始预览")
                self.status_message_label.SetLabel('点击"开始预览"按钮启动。')
            self.panel.Layout() # 重新布局Panel以适应标签变化

        def update_status_message(self, message):
            """在状态标签中更新消息（线程安全）。"""
            # wx.CallAfter 确保在 GUI 线程执行 GUI 操作
            wx.CallAfter(self._update_status_label, message)

        def _update_status_label(self, message):
            """实际更新状态标签的函数。"""
            # 检查控件是否存在且消息确实有变化，避免不必要的重绘
            if self.status_message_label and self.status_message_label.GetLabel() != message:
                self.status_message_label.SetLabel(message)
                self.panel.Layout() # 重新布局，因为文本长度可能改变

        def show_error_message(self, message, title="出错了"):
            """显示错误消息对话框（线程安全）。"""
            wx.CallAfter(lambda: wx.MessageBox(message, title, wx.OK | wx.ICON_ERROR))
            logger.error(f"显示错误消息: {title} - {message}")

        def on_check_queue_and_playback(self, event):
            """定时器事件处理：检查音频队列并处理播放。"""
            try:
                # 在 Pygame 实现中，这个函数实际上是空操作，因为命令直接由后台线程处理
                # 仅仅保留此函数以保持接口兼容性
                core.audio_manager.check_and_process_audio_queue()
            except Exception as e:
                logger.error(f"定时器事件 on_check_queue_and_playback 发生意外错误: {e}", exc_info=True)
                # 发生严重错误时停止定时器并显示消息
                self.audio_status_timer.Stop()
                self.show_error_message(f"音频检查定时器发生严重错误，已停止。\n请重启程序。\n错误: {e}", "内部错误")

        def on_open_hotkey_settings(self, event):
            """打开快捷键设置对话框。"""
            dialog = HotkeySettingsDialog(self, self.hotkey_manager)
            # ShowModal 会阻塞，直到对话框关闭
            if dialog.ShowModal() == wx.ID_OK:
                self.on_hotkey_config_changed() # 用户确认了更改
            dialog.Destroy() # 销毁对话框以释放资源

        def on_hotkey_config_changed(self):
            """当快捷键配置更改时触发。"""
            logger.info("快捷键配置已更改，GUI 收到通知。")
            # HotkeyManager 内部会处理重新注册监听器

        def handle_hotkey_event(self, event: HotkeyEvent):
            """处理快捷键触发事件。"""
            func_name = event.func_name
            logger.info(f"快捷键触发: {func_name}")

            if func_name == "toggle_monitor":
                self.on_toggle_monitor()
            elif func_name == "toggle_visibility":
                self.toggle_visibility()
            elif func_name == "exit_application":
                self.Close() # 关闭主窗口会触发 EVT_CLOSE
            elif func_name == "toggle_play_pause":
                # 播放/暂停键在按下时触发一次
                if not self._toggle_play_pause_pressed:
                    # 使用 audio_command_queue 避免直接调用 audio_manager 的函数
                    core.audio_manager.audio_command_queue.put(("toggle_play_pause", None))
                    unified_speaker.speak("播放或暂停")
                    self._toggle_play_pause_pressed = True
            elif func_name == "fast_forward":
                # 长按快进：按下时立即执行一次，并启动定时器持续快进
                if not self._fast_forward_pressed:
                    logger.debug("快进快捷键按下，启动快进定时器。")
                    self._fast_forward_pressed = True
                    self._fast_forward_timer.Start(200) # 每200ms快进一次
                    # 第一次立即快进
                    core.audio_manager.audio_command_queue.put(("seek", 1.0))
                    unified_speaker.speak("快进")
            elif func_name == "rewind":
                # 长按快退：按下时立即执行一次，并启动定时器持续快退
                if not self._rewind_pressed:
                    logger.debug("快退快捷键按下，启动快退定时器。")
                    self._rewind_pressed = True
                    self._rewind_timer.Start(200) # 每200ms快退一次
                    # 第一次立即快退
                    core.audio_manager.audio_command_queue.put(("seek", -1.0))
                    unified_speaker.speak("快退")
            # --- 新增功能快捷键处理 ---
            elif func_name == "add_label":
                self.on_add_label_hotkey()
            elif func_name == "search_label":
                self.on_search_label_hotkey()

        def on_fast_forward_timer(self, event):
            """快进定时器回调：持续发送快进命令。"""
            if self._fast_forward_pressed:
                # 每次快进 1 秒
                core.audio_manager.audio_command_queue.put(("seek", 1.0))
                logger.debug("快进定时器触发，发送快进命令。")
            else:
                # 如果按钮被释放，停止定时器
                self._fast_forward_timer.Stop()

        def on_rewind_timer(self, event):
            """快退定时器回调：持续发送快退命令。"""
            if self._rewind_pressed:
                # 每次快退 1 秒
                core.audio_manager.audio_command_queue.put(("seek", -1.0))
                logger.debug("快退定时器触发，发送快退命令。")
            else:
                # 如果按钮被释放，停止定时器
                self._rewind_timer.Stop()

        def toggle_visibility(self):
            """切换窗口的显示/隐藏状态。"""
            if self.IsShown():
                self.Hide()
                logger.info("窗口已隐藏。")
                unified_speaker.speak("隐藏")
            else:
                self.Show()
                self.Raise() # 确保窗口被带到前台
                logger.info("窗口已显示。")
                unified_speaker.speak("显示")

        def on_iconize(self, event):
            """处理窗口最小化（图标化）事件。"""
            if self.IsIconized():
                logger.info("窗口已最小化 (图标化)。")
                unified_speaker.speak("隐藏")
            else:
                logger.info("窗口已还原。")
                unified_speaker.speak("显示")
            event.Skip() # 允许事件继续传递，以便 wxPython 处理其默认行为

        def on_close(self, event):
            """处理窗口关闭事件，清理资源。"""
            logger.info("正在关闭应用程序...")
            # 停止所有音频播放
            core.audio_manager.stop_audio()
            # 停止文件监视
            stop_monitor()
            # 停止所有定时器
            self.audio_status_timer.Stop()
            self._fast_forward_timer.Stop()
            self._rewind_timer.Stop()
            # 取消注册快捷键
            self.hotkey_manager._unregister_hotkeys()
            # 停止 TTS
            unified_speaker.stop_speak()
            logger.info("所有后台服务和资源已停止。")
            # 允许窗口正常关闭
            event.Skip()
            # 销毁窗口对象
            self.Destroy()

        # --- 新功能：添加音频标签 ---
        def on_add_label_hotkey(self):
            """处理添加音频标签的快捷键。"""
            current_audio_path = core.audio_manager.get_last_played_file_path()
            if not current_audio_path or not os.path.exists(current_audio_path):
                msg = "没有正在播放或最近播放的音频文件，无法添加标签。"
                self.show_error_message(msg, "操作失败")
                unified_speaker.speak(msg)
                logger.warning(msg)
                return

            # 弹出对话框让用户输入标签
            dlg = wx.TextEntryDialog(self, f"为 '{os.path.basename(current_audio_path)}' 添加标签 (多个标签用逗号分隔):",
                                    "添加音频标签", "", style=wx.TextEntryDialogStyle | wx.OK | wx.CANCEL)

            # TTS 提示用户输入
            unified_speaker.speak(f"请为音频文件 {os.path.basename(current_audio_path)} 添加标签。多个标签请用逗号分隔。")
            dlg.CenterOnParent() # 居中对话框

            if dlg.ShowModal() == wx.ID_OK:
                labels_input = dlg.GetValue().strip()
                if not labels_input:
                    msg = "未输入任何标签。"
                    self.show_error_message(msg, "添加失败")
                    unified_speaker.speak(msg)
                    logger.info(msg)
                    dlg.Destroy()
                    return

                # 解析标签，过滤空字符串
                labels = [label.strip() for label in labels_input.split(',') if label.strip()]
                if not labels:
                    msg = "标签输入无效，请检查格式。"
                    self.show_error_message(msg, "添加失败")
                    unified_speaker.speak(msg)
                    logger.warning(msg)
                    dlg.Destroy()
                    return

                # 将标签添加到数据库
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
                # 用户取消了添加标签
                msg = "取消添加标签。"
                self.update_status_message(msg)
                unified_speaker.speak(msg)
                logger.info(msg)
            dlg.Destroy() # 销毁对话框

        # --- 新功能：搜索音频标签 ---
        def on_search_label_hotkey(self):
            """处理搜索音频标签的快捷键。"""
            dlg = wx.TextEntryDialog(self, "请输入要搜索的音频标签:", "搜索音频", "", style=wx.TextEntryDialogStyle | wx.OK | wx.CANCEL)

            # TTS 提示用户输入
            unified_speaker.speak("请输入要搜索的音频标签。")
            dlg.CenterOnParent() # 居中对话框

            if dlg.ShowModal() == wx.ID_OK:
                search_label = dlg.GetValue().strip()
                if not search_label:
                    msg = "未输入搜索标签。"
                    self.show_error_message(msg, "搜索失败")
                    unified_speaker.speak(msg)
                    logger.info(msg)
                    dlg.Destroy()
                    return

                # 从数据库搜索匹配的文件
                try:
                    matching_files = self.db_manager.get_audios_by_label(search_label)

                    if not matching_files:
                        msg = f"未找到与标签 '{search_label}' 匹配的音频文件。"
                        self.show_error_message(msg, "搜索结果")
                        unified_speaker.speak(msg)
                        logger.info(msg)
                        dlg.Destroy()
                        return

                    # 显示搜索结果对话框
                    result_dlg = SearchResultsDialog(self, f"搜索结果: {search_label}", matching_files)
                    result_dlg.ShowModal()
                    result_dlg.Destroy() # 销毁结果对话框
                    unified_speaker.speak(f"搜索完成，找到 {len(matching_files)} 个匹配文件。")

                except Exception as e:
                    error_msg = f"搜索标签失败: {e}"
                    self.show_error_message(error_msg, "数据库错误")
                    unified_speaker.speak(error_msg)
                    logger.error(error_msg, exc_info=True)
            else:
                # 用户取消了搜索
                msg = "取消搜索标签。"
                self.update_status_message(msg)
                unified_speaker.speak(msg)
                logger.info(msg)
            dlg.Destroy() # 销毁输入对话框

    logger.info("MyFrame 类已成功定义，没有在类定义过程中抛出异常。")

except Exception as e:
    # --- 捕捉 MyFrame 类定义过程中发生的异常 ---
    error_message = f"MyFrame 类定义过程中发生错误: {e}"
    logger.critical(error_message, exc_info=True)
    # 尝试显示错误消息（如果wx.App已初始化）
    if wx.App.Get() and wx.App.Get().IsInitialized():
        wx.MessageBox(f"{error_message}\n应用程序将退出。", "致命错误", wx.OK | wx.ICON_ERROR)
    else:
        print(f"FATAL ERROR: {error_message}\n{traceback.format_exc()}", file=sys.stderr)
    sys.exit(1)