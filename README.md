# InstantAudioPreviewer (文件管理器音频实时预览工具)

## 项目简介
**InstantAudioPreviewer** 是一款用于Windows文件管理器的音频文件实时预览工具。当用户在文件管理器中选择一个音频文件时，本程序能够自动播放该文件的声音，无需打开独立的播放器。它还集成了便捷的快捷键操作、音频标签管理功能，并支持与主流屏幕阅读器（如NVDA、争渡读屏）的交互，以提供更好的辅助功能。

## 核心功能来源说明
**本项目关于“文件管理器中实时音频预览”的核心创意和初步实现，灵感及思路来源于沈广荣先生在“争渡网”论坛的分享。** 我对沈广荣先生在原创方面的贡献表示最诚挚的感谢，并在此明确承认，我的项目在这一核心功能上，是基于他的原创思路进行开发的。

在项目发布初期，我未能及时、坦诚地承认这一点，并对我的错误行为进行了辩解，我对此深感抱歉，并已于 **2025年7月20日** 在论坛上公开道歉，并停止了该项目的传播。

## 本项目独立实现的功能和改进
在沈广荣先生原创思路的基础上，本项目独立实现了以下功能和改进：

*   **增强的快捷键控制：**
    *   播放/暂停、快进/快退、隐藏/显示窗口、快速退出。
    *   **可自定义快捷键**，提供“快捷键设置”对话框。

*   **智能音频标签管理：**
    *   **添加标签：** 可为音频文件添加自定义标签，支持多标签（逗号分隔）。
    *   **搜索标签：** 通过标签名称（支持模糊匹配）搜索音频文件。
    *   **搜索结果预览：** 在搜索结果列表中即时预览文件。

*   **统一的文本转语音 (TTS) 接口：**
    *   提供了统一的TTS接口，协调与**NVDA Controller Client API**（通过`utils/nvda_api_wrapper.py`封装）和**争渡读屏API**（通过`utils/zdsr_api_wrapper.py`封装）的交互。
    *   实现了根据预设策略（自动检测或同时发送）协调屏幕阅读器的语音输出。

*   **其他功能：**
    *   更新检查与下载 (`update_check_and_download.py`)
    *   日志系统配置 (`utils/logger_config.py`)

## 技术栈
*   **Python:** 3.12.10
*   **GUI库:** wxWidgets (通过 `wxPython`)
*   **音频库:** **VLC (通过 `python-vlc`)**
*   **数据库:** SQLite (用于标签管理)
*   **屏幕阅读器API:** NVDA Controller Client API, 争渡读屏API (通过自定义封装实现)

## 如何安装与运行

### 前置条件
*   Windows 操作系统
*   已安装 Python 3.12.10
*   **已安装 VLC 媒体播放器（推荐使用最新稳定版本）**
*   （可选）如果需要使用NVDA相关的API，请确保你的系统已安装NVDA。
*   （可选）如果需要使用争渡读屏相关的API，请确保你的系统已安装争渡读屏。

### 安装步骤
1.  **克隆或下载项目：**
2.  **创建并激活Python虚拟环境（推荐）：**
    ```bash
    python -m venv venv
    # Windows
    .\venv\Scripts\activate
    # macOS/Linux
    # source venv/bin/activate
    ```
    *(虚拟环境可以隔离项目依赖，避免与其他Python项目冲突)*

3.  **安装项目依赖：**
    ```bash
    pip install -r requirements.txt
    ```

4.  **运行应用程序：**
    ```bash
    python InstantAudioPreviewer.py
    ```

## 注意事项
*   本项目仅为学习和探索目的而开发，并已声明对核心功能的原创来源。
*   请在使用本项目时，尊重沈广荣先生的原创工作。

## 开源许可证
本项目采用 **MIT License** 发布。