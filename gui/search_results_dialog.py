import wx
import os
import threading
import queue
import time
from concurrent.futures import ThreadPoolExecutor

from utils.logger_config import logger
import core.audio_manager
from utils.unified_tts_speaker import unified_speaker

class SearchResultsDialog(wx.Dialog):
    """
    一个用于显示搜索结果并提供音频预览功能的对话框。
    支持分批加载、后台文件存在性检查和即时预览。
    """
    def __init__(self, parent, title, all_results):
        """
        初始化搜索结果对话框。

        Args:
            parent (wx.Frame): 父窗口。
            title (str): 对话框的标题。
            all_results (list): 包含所有搜索结果文件路径的列表。
        """
        super().__init__(parent, title=title, size=(600, 400), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.parent_frame = parent
        self.all_results = list(all_results)
        self.loaded_results = []
        self.pending_results_queue = queue.Queue()
        self.current_playing_path = None
        self.last_preview_time = 0

        # --- UI Elements ---
        self.panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        self.list_box = wx.ListBox(self.panel, style=wx.LB_SINGLE | wx.LB_HSCROLL)
        self.list_box.Bind(wx.EVT_LISTBOX, self.on_list_selected)
        self.list_box.Bind(wx.EVT_LISTBOX_DCLICK, self.on_list_double_click)

        self.status_label = wx.StaticText(self.panel, label="正在初始化...")

        main_sizer.Add(self.list_box, 1, wx.EXPAND | wx.ALL, 10)
        main_sizer.Add(self.status_label, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.panel.SetSizer(main_sizer)
        self.Layout()
        self.Centre()

        # --- 分批加载逻辑 ---
        self.batch_size = 50
        self.initial_load_size = 100
        self.load_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_load_more_results, self.load_timer)

        # --- 线程池用于后台文件存在性检查 ---
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.future_to_path = {}

        # 启动初始加载
        self._start_initial_load()

    def _start_initial_load(self):
        """启动初始加载并开始后台分批加载。"""
        if not self.all_results:
            self.status_label.SetLabel("没有匹配的音频文件。")
            logger.warning("搜索结果对话框初始化时，all_results 为空。")
            return

        # 加载初始批次到列表
        initial_batch_end_index = min(self.initial_load_size, len(self.all_results))
        initial_batch = self.all_results[:initial_batch_end_index]
        for path in initial_batch:
            self.list_box.Append(os.path.basename(path))
            self.loaded_results.append(path)

        # 将剩余文件放入待加载队列
        for path in self.all_results[initial_batch_end_index:]:
            self.pending_results_queue.put(path)

        # 更新状态标签
        self.status_label.SetLabel(f"已加载 {len(self.loaded_results)} / {len(self.all_results)} 条。")

        # 如果还有待加载项，启动定时器
        if not self.pending_results_queue.empty():
            self.load_timer.Start(500) # 每 500ms 尝试加载一批
            logger.info(f"开始分批加载，初始加载 {len(self.loaded_results)} 条，剩余 {self.pending_results_queue.qsize()} 条。")
        else:
            logger.info("所有搜索结果已一次性加载完毕。")

    def on_load_more_results(self, event):
        """定时器事件处理，从队列加载更多结果到列表。"""
        items_added_this_batch = 0
        while items_added_this_batch < self.batch_size and not self.pending_results_queue.empty():
            try:
                path = self.pending_results_queue.get_nowait()
                # 异步提交文件存在性检查
                future = self.executor.submit(self._check_file_exists, path)
                self.future_to_path[future] = path

                # 立即将文件名添加到列表框
                self.list_box.Append(os.path.basename(path))
                self.loaded_results.append(path)
                items_added_this_batch += 1
            except queue.Empty:
                break # 队列为空时退出循环

        # 处理已完成的文件存在性检查
        self._process_completed_file_checks()

        # 更新状态标签
        self.status_label.SetLabel(f"已加载 {len(self.loaded_results)} / {len(self.all_results)} 条。")

        # 如果队列已空，停止定时器
        if self.pending_results_queue.empty():
            self.load_timer.Stop()
            self.status_label.SetLabel(f"所有 {len(self.all_results)} 条结果已加载。")
            logger.info("所有搜索结果分批加载完成。")

    def _check_file_exists(self, path):
        """在后台线程中检查文件是否存在。"""
        return path, os.path.exists(path)

    def _process_completed_file_checks(self):
        """处理已完成的文件存在性检查结果，并更新UI（如果需要）。"""
        completed_futures = [f for f in self.future_to_path if f.done()]
        for future in completed_futures:
            path, exists = future.result()
            if not exists:
                logger.warning(f"文件不存在，将可能在UI中被标记: {path}")
                # TODO: 可以在这里实现更复杂的UI反馈，例如改变列表项的颜色或添加图标
                # 简单起见，此处仅记录警告，未来可以根据需要实现UI更新
            del self.future_to_path[future] # 清理已处理的future

    def on_list_selected(self, event):
        """列表项被选中时触发，进行即时音频预览。"""
        selected_index = self.list_box.GetSelection()
        if selected_index == wx.NOT_FOUND:
            return

        current_time = time.time()
        # 限制预览频率，避免用户快速上下滚动时频繁播放
        if current_time - self.last_preview_time < 0.5:
            return

        selected_path = self.loaded_results[selected_index]

        # 检查文件是否存在
        if not os.path.exists(selected_path):
            self.parent_frame.show_error_message(f"文件 '{os.path.basename(selected_path)}' 不存在，无法预览。", "文件缺失")
            core.audio_manager.audio_command_queue.put(("stop", None)) # 尝试停止可能存在的播放
            self.current_playing_path = None
            return

        # 如果当前选中的是正在播放的文件，则什么也不做，避免重复播放
        if selected_path == self.current_playing_path and core.audio_manager.get_current_playback_status() == core.audio_manager.PLAYBACK_STATUS_PLAYING:
            logger.debug(f"相同文件 {os.path.basename(selected_path)} 已在播放，跳过预览。")
            return

        # 发送播放命令
        core.audio_manager.audio_command_queue.put(("play", selected_path))
        self.current_playing_path = selected_path
        self.last_preview_time = current_time
        logger.info(f"即时预览: {os.path.basename(selected_path)}")

        # 使用TTS朗读文件名
        unified_speaker.speak(f"正在预览: {os.path.basename(selected_path)}")

    def on_list_double_click(self, event):
        """列表项双击时，切换播放/暂停或播放新文件。"""
        selected_index = self.list_box.GetSelection()
        if selected_index == wx.NOT_FOUND:
            return

        selected_path = self.loaded_results[selected_index]

        # 检查文件是否存在
        if not os.path.exists(selected_path):
            self.parent_frame.show_error_message(f"文件 '{os.path.basename(selected_path)}' 不存在，无法播放。", "文件缺失")
            core.audio_manager.audio_command_queue.put(("stop", None))
            self.current_playing_path = None
            return

        # 如果双击的是当前正在播放的文件，则切换播放/暂停
        if selected_path == self.current_playing_path:
            core.audio_manager.audio_command_queue.put(("toggle_play_pause", None))
            logger.info(f"双击切换播放/暂停: {os.path.basename(selected_path)}")
        else:
            # 如果双击的是不同的文件，则直接播放新文件
            core.audio_manager.audio_command_queue.put(("play", selected_path))
            self.current_playing_path = selected_path
            logger.info(f"双击播放新文件: {os.path.basename(selected_path)}")

        unified_speaker.speak(f"播放/暂停: {os.path.basename(selected_path)}")

    def OnClose(self, event):
        """对话框关闭时执行清理操作。"""
        core.audio_manager.audio_command_queue.put(("stop", None)) # 停止所有音频
        self.load_timer.Stop() # 停止加载定时器
        self.executor.shutdown(wait=True) # 等待所有后台任务完成并关闭线程池
        logger.info("搜索结果对话框已关闭，已停止音频播放并清理线程。")
        self.Destroy() # 销毁对话框自身

# --- 独立测试部分 ---
if __name__ == '__main__':
    # 模拟 wx.App 环境
    app = wx.App(False)

    # 模拟 logger
    import logging
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # 模拟 unified_speaker
    class MockUnifiedSpeaker:
        def speak(self, text):
            print(f"[TTS] {text}")
        def stop_speak(self):
            print("[TTS] Stop speaking.")

    # 临时覆盖 unified_speaker 为 Mock 实现
    original_unified_speaker = unified_speaker
    unified_speaker = MockUnifiedSpeaker()

    # 模拟 core.audio_manager
    class MockAudioManager:
        PLAYBACK_STATUS_STOPPED = 0
        PLAYBACK_STATUS_PLAYING = 1
        PLAYBACK_STATUS_PAUSED = 2

        _audio_system_initialized = True
        audio_command_queue = queue.Queue()
        _main_frame_ref = None
        _current_playback_status = PLAYBACK_STATUS_STOPPED
        _last_played_file_path = None

        def set_frame_reference(self, frame):
            self._main_frame_ref = frame

        def init_audio_system(self):
            print("Mock Audio Manager initialized.")

        def check_and_process_audio_queue(self):
            # 模拟处理音频命令
            try:
                command, path = self.audio_command_queue.get_nowait()
                if command == "play":
                    print(f"[MockAudio] Playing: {path}")
                    self._current_playback_status = self.PLAYBACK_STATUS_PLAYING
                    self._last_played_file_path = path
                elif command == "stop":
                    print(f"[MockAudio] Stopping.")
                    self._current_playback_status = self.PLAYBACK_STATUS_STOPPED
                    self._last_played_file_path = None
                elif command == "toggle_play_pause":
                    if self._current_playback_status == self.PLAYBACK_STATUS_PLAYING:
                        print(f"[MockAudio] Pausing: {self._last_played_file_path}")
                        self._current_playback_status = self.PLAYBACK_STATUS_PAUSED
                    elif self._current_playback_status == self.PLAYBACK_STATUS_PAUSED:
                        print(f"[MockAudio] Resuming: {self._last_played_file_path}")
                        self._current_playback_status = self.PLAYBACK_STATUS_PLAYING
                    else:
                        print(f"[MockAudio] No audio to toggle.")
                self.audio_command_queue.task_done()
            except queue.Empty:
                pass

        def get_current_playback_status(self):
            return self._current_playback_status

        def show_error_message(self, msg, title):
            print(f"Mock Audio Manager Error [{title}]: {msg}")
            if self._main_frame_ref:
                self._main_frame_ref.show_error_message(msg, title)

        def update_status_message(self, msg):
            print(f"Mock Audio Manager Status: {msg}")
            if self._main_frame_ref:
                self._main_frame_ref.update_status_message(msg)

    # 确保core.audio_manager 能够使用 mock 实现
    mock_am_instance = MockAudioManager()
    # 动态设置 mock_am_instance 到 core.audio_manager 的全局引用
    if hasattr(core.audio_manager, 'set_frame_reference'):
        core.audio_manager.set_frame_reference(mock_am_instance)
    else: # 如果没有set_frame_reference函数，直接覆盖全局变量
        core.audio_manager._audio_manager_instance = mock_am_instance # 假设存在这样的全局实例

    core.audio_manager.init_audio_system() # 调用 mock 的初始化

    # 启动一个定时器来模拟处理音频命令队列
    process_timer = wx.Timer(app)
    process_timer.Bind(wx.EVT_TIMER, lambda event: mock_am_instance.check_and_process_audio_queue())
    process_timer.Start(50) # 每 50ms 检查一次队列

    # 创建一些虚拟文件路径用于测试
    test_files = []
    num_test_files = 150
    for i in range(1, num_test_files + 1):
        filename = f"test_audio_{i}.mp3"
        filepath = os.path.join(os.getcwd(), filename)
        test_files.append(filepath)
        # 隔3个文件创建一个实际存在的文件
        if i % 3 == 0:
            try:
                with open(filepath, 'w') as f:
                    f.write(f"Dummy content for {filename}")
            except Exception as e:
                print(f"Warning: Could not create dummy file {filepath}: {e}")
        else:
            # 确保不存在的文件确实不存在
            if os.path.exists(filepath):
                os.remove(filepath)

    # 模拟主窗口
    class MockParentFrame(wx.Frame):
        def __init__(self):
            super().__init__(None, title="Mock Parent Frame")
            # 确保 audio_manager 能够访问父窗口的方法
            if hasattr(core.audio_manager, 'set_frame_reference'):
                core.audio_manager.set_frame_reference(self)

        def show_error_message(self, msg, title):
            print(f"Parent Frame Error [{title}]: {msg}")
            wx.MessageBox(msg, title, wx.OK | wx.ICON_ERROR)

        def update_status_message(self, msg):
            print(f"Parent Frame Status: {msg}")

    parent_frame = MockParentFrame()

    # 创建并显示对话框
    dialog = SearchResultsDialog(parent_frame, "测试搜索结果对话框", test_files)
    dialog.ShowModal()
    dialog.Destroy() # 对话框关闭后销毁

    # 清理测试文件
    print("Cleaning up test files...")
    for f in test_files:
        if os.path.exists(f):
            try:
                os.remove(f)
            except Exception as e:
                print(f"Warning: Could not remove test file {f}: {e}")

    # 恢复原始的 unified_speaker
    unified_speaker = original_unified_speaker

    # app.MainLoop() # 在测试时不需要主循环，除非需要交互