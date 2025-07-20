import wx

# 导入 HotkeyManager，以便与 Manager 交互
from hotkey.hotkey_manager import HotkeyManager
from utils.logger_config import logger

class HotkeySettingsDialog(wx.Dialog):
    def __init__(self, parent, hotkey_manager: HotkeyManager):
        super().__init__(parent, title="快捷键设置", size=(450, 350), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.hotkey_manager = hotkey_manager
        
        # 获取所有注册的功能及其显示名称
        self._all_functions_tuple = self.hotkey_manager.get_registered_functions()
        self.functions_internal_to_display = {f[0]: f[1] for f in self._all_functions_tuple}
        self.functions_display_to_internal = {f[1]: f[0] for f in self._all_functions_tuple}

        # 存储对话框中用户修改的临时设置
        self.current_hotkey_settings = {} 
        
        # UI 显示的修饰键
        self.modifier_keys = ["Ctrl", "Alt", "Shift", "Win"]
        
        # 从 HotkeyManager 获取所有可选的普通键，用于 ComboBox
        self.common_keys = self.hotkey_manager.common_keys_for_ui

        self._create_widgets()
        self._layout_widgets()
        self._load_current_settings() # 加载当前实际配置到对话框的临时状态
        
        # 绑定 UI 控件事件，以便实时更新 self.current_hotkey_settings
        for checkbox in self.modifier_checkboxes.values():
            checkbox.Bind(wx.EVT_CHECKBOX, self.on_ui_hotkey_changed)
        self.key_chooser.Bind(wx.EVT_COMBOBOX, self.on_ui_hotkey_changed)
        # 处理用户直接输入 ComboBox 的值
        self.key_chooser.Bind(wx.EVT_TEXT, self.on_ui_hotkey_changed) 

    def _create_widgets(self):
        panel = wx.Panel(self)

        # 功能选择器
        self.function_chooser = wx.ComboBox(panel, choices=list(self.functions_display_to_internal.keys()), style=wx.CB_READONLY)
        self.function_chooser.SetSelection(0) # 默认选中第一个功能
        self.function_chooser.Bind(wx.EVT_COMBOBOX, self.on_function_selected)

        self.modifier_checkboxes = {}
        self.modifier_sizer = wx.BoxSizer(wx.HORIZONTAL)
        for mod_key in self.modifier_keys:
            checkbox = wx.CheckBox(panel, label=mod_key)
            self.modifier_checkboxes[mod_key] = checkbox
            self.modifier_sizer.Add(checkbox, 0, wx.ALL, 5)

        # 普通按键选择框，允许用户输入
        self.key_chooser = wx.ComboBox(panel, choices=self.common_keys, style=wx.CB_DROPDOWN) 
        self.key_chooser.SetStringSelection("") # 默认选择空

        self.ok_button = wx.Button(panel, wx.ID_OK, "确定")
        self.cancel_button = wx.Button(panel, wx.ID_CANCEL, "取消")
        self.clear_button = wx.Button(panel, wx.ID_ANY, "清空当前快捷键")
        self.clear_button.Bind(wx.EVT_BUTTON, self.on_clear_hotkey)
        self.reset_button = wx.Button(panel, wx.ID_ANY, "重置为默认值")
        self.reset_button.Bind(wx.EVT_BUTTON, self.on_reset_to_default)

        self.ok_button.Bind(wx.EVT_BUTTON, self.on_ok)
        self.cancel_button.Bind(wx.EVT_BUTTON, self.on_cancel)

    def _layout_widgets(self):
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        panel = self.function_chooser.GetParent()

        fgs = wx.FlexGridSizer(rows=3, cols=2, vgap=10, hgap=10)
        fgs.AddGrowableCol(1) # 第二列可拉伸

        fgs.Add(wx.StaticText(panel, label="选择功能:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        fgs.Add(self.function_chooser, 1, wx.EXPAND | wx.RIGHT, 5)

        fgs.Add(wx.StaticText(panel, label="修饰键:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        fgs.Add(self.modifier_sizer, 1, wx.EXPAND | wx.RIGHT, 5)

        fgs.Add(wx.StaticText(panel, label="普通按键:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        fgs.Add(self.key_chooser, 1, wx.EXPAND | wx.RIGHT, 5)

        main_sizer.Add(fgs, 1, wx.EXPAND | wx.ALL, 10)

        button_sizer = wx.StdDialogButtonSizer()
        button_sizer.AddButton(self.ok_button)
        button_sizer.AddButton(self.cancel_button)
        button_sizer.AddSpacer(10) # 增加间隔
        button_sizer.AddButton(self.clear_button)
        button_sizer.AddButton(self.reset_button)
        button_sizer.Realize()

        main_sizer.Add(button_sizer, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 10)

        panel.SetSizer(main_sizer)
        self.Layout()
        self.Centre()

    def _load_current_settings(self):
        """
        从 HotkeyManager 加载所有功能的当前快捷键设置到对话框的内部状态。
        """
        for func_internal_name, _ in self._all_functions_tuple:
            hotkey_str_normalized = self.hotkey_manager.get_current_hotkey_for_func(func_internal_name)
            
            # 使用 HotkeyManager 内部的方法来解析字符串到 UI 需要的部分
            mod_list_ui, key_name_for_ui = self.hotkey_manager._get_hotkey_parts_for_ui(hotkey_str_normalized)
            
            self.current_hotkey_settings[func_internal_name] = {'mods': mod_list_ui, 'key': key_name_for_ui}
        
        # 加载完成后，刷新当前选中的功能的 UI
        self.on_function_selected(None)

    def on_function_selected(self, event):
        """当用户选择不同的功能时，更新修饰键和普通按键的选择框。"""
        selected_display_name = self.function_chooser.GetValue()
        selected_func_internal_name = self.functions_display_to_internal.get(selected_display_name)
        
        if not selected_func_internal_name:
            return

        settings = self.current_hotkey_settings.get(selected_func_internal_name, {'mods': [], 'key': ''})

        # 更新修饰键复选框
        for mod_key, checkbox in self.modifier_checkboxes.items():
            checkbox.SetValue(mod_key in settings['mods'])

        # 更新普通按键选择框
        key_value = settings['key']
        self.key_chooser.SetValue(key_value) # 设置为用户输入的值
        
        # 如果 ComboBox 包含该键，则尝试选中它
        if key_value in self.common_keys:
            self.key_chooser.SetStringSelection(key_value)
        # else: 
            # 用户输入的值不在列表中，SetStringSelection 不会改变 Value，保留用户输入

    def on_ui_hotkey_changed(self, event):
        """当用户在 UI 中修改修饰键或普通按键时，更新内部状态。"""
        selected_display_name = self.function_chooser.GetValue()
        selected_func_internal_name = self.functions_display_to_internal.get(selected_display_name)
        
        if not selected_func_internal_name:
            return

        selected_mods = [mod_key for mod_key, checkbox in self.modifier_checkboxes.items() if checkbox.GetValue()]
        selected_key_from_ui = self.key_chooser.GetValue().strip() # 获取用户输入的值，并去除空白

        self.current_hotkey_settings[selected_func_internal_name] = {
            'mods': selected_mods, 
            'key': selected_key_from_ui
        }

    def on_clear_hotkey(self, event):
        """清空当前选中功能的快捷键设置。"""
        selected_display_name = self.function_chooser.GetValue()
        selected_func_internal_name = self.functions_display_to_internal.get(selected_display_name)
        
        if not selected_func_internal_name:
            return

        for checkbox in self.modifier_checkboxes.values():
            checkbox.SetValue(False)
        self.key_chooser.SetValue("") # 清空 ComboBox 的值

        self.current_hotkey_settings[selected_func_internal_name] = {'mods': [], 'key': ''}
        logger.info(f"UI: 功能 '{selected_func_internal_name}' 的快捷键已清空。")

    def on_reset_to_default(self, event):
        """将所有快捷键重置为默认值。"""
        if wx.MessageDialog(self, "确定要将所有快捷键重置为默认值吗？此操作将立即生效。", "确认重置", 
                           wx.YES_NO | wx.ICON_QUESTION).ShowModal() == wx.ID_YES:
            self.hotkey_manager.reset_hotkeys_to_default()
            self._load_current_settings() # 重新加载默认设置到 UI
            wx.MessageBox("所有快捷键已重置为默认值。", "重置成功", wx.OK | wx.ICON_INFORMATION)
            self.EndModal(wx.ID_OK) # 结束对话框并返回 OK 结果

    def on_ok(self, event):
        """处理“确定”按钮点击事件，尝试保存并应用所有修改。"""
        all_success = True
        error_messages = []
        
        # 遍历所有功能，尝试更新它们的快捷键
        for func_name, settings in self.current_hotkey_settings.items():
            mod_str_list_from_ui = "+".join(sorted(settings['mods'])) # 确保修饰键顺序一致
            key_str_from_ui = settings['key']
            
            # 调用 HotkeyManager 的 update_hotkey 方法来处理逻辑和保存
            success, msg = self.hotkey_manager.update_hotkey(func_name, mod_str_list_from_ui, key_str_from_ui)
            if not success:
                all_success = False
                display_name = self.functions_internal_to_display.get(func_name, func_name)
                error_messages.append(f"功能 '{display_name}': {msg}")
        
        if all_success:
            wx.MessageBox("快捷键设置已保存并应用。", "设置成功", wx.OK | wx.ICON_INFORMATION)
            self.EndModal(wx.ID_OK)
        else:
            wx.MessageBox(f"无法保存所有快捷键设置。\n\n详情:\n" + "\n".join(error_messages), "设置失败", wx.OK | wx.ICON_ERROR)

    def on_cancel(self, event):
        """处理“取消”按钮点击事件，放弃所有修改。"""
        self.EndModal(wx.ID_CANCEL)