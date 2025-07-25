# InstantAudioPreviewer (File Manager Audio Real-Time Preview Tool)

## Project Overview
**InstantAudioPreviewer** is a real-time audio file preview tool designed for Windows File Manager. When a user selects an audio file in the file manager, this program automatically plays the file's sound without needing to open a separate player. It also integrates convenient shortcut key operations, audio tag management features, and supports interaction with mainstream screen readers (such as NVDA and Zhengdu Reader) to provide enhanced accessibility.

## Acknowledgement of Core Function Origin
**The core idea and initial implementation of real-time audio preview within the file manager for this project were inspired by and based on the sharing of Mr. Shen Guangrong on the "zd.hk" forum.** I extend my sincerest gratitude to Mr. Shen Guangrong for his original contributions. I hereby clearly acknowledge that my project's core functionality in this area is developed based on his original concepts.

In the early stages of this project's release, I failed to admit this promptly and candidly and even offered justifications for my actions. I deeply regret this oversight and have since issued a public apology on the forum on **July 20, 2025**, and have ceased the distribution of this project.

## Independent Features and Improvements by This Project
Building upon Mr. Shen Guangrong's original ideas, this project independently implements the following features and improvements:

*   **Enhanced Shortcut Controls:**
    *   Play/Pause, Fast Forward/Rewind, Hide/Show Window, Quick Exit.
    *   **Customizable Shortcut Keys:** Features a "Shortcut Key Settings" dialog for user configuration.

*   **Intelligent Audio Tag Management:**
    *   **Add Tags:** Allows users to add custom tags to audio files, supporting multiple tags (comma-separated).
    *   **Search by Tags:** Enables searching for audio files by tag name (supports fuzzy matching).
    *   **Search Results Preview:** Provides instant preview of files directly from the search results list.

*   **Unified Text-to-Speech (TTS) Interface:**
    *   Offers a unified TTS interface that coordinates interactions with the **NVDA Controller Client API** (wrapped via `utils/nvda_api_wrapper.py`) and the **Zhengdu Reader API** (wrapped via `utils/zdsr_api_wrapper.py`).
    *   Implements strategies for coordinating screen reader voice output, either through automatic detection or simultaneous transmission.

*   **Other Features:**
    *   Update Checking and Downloading (`update_check_and_download.py`)
    *   Logging System Configuration (`utils/logger_config.py`)

## Technology Stack
*   **Python:** 3.12.10
*   **GUI Library:** wxWidgets (via `wxPython`)
*   **Audio Library:** **VLC (via `python-vlc`)**
*   **Database:** SQLite (for tag management)
*   **Screen Reader APIs:** NVDA Controller Client API, Zhengdu Reader API (implemented via custom wrappers)

## Installation and Running Guide

### Prerequisites
*   Windows Operating System
*   Python 3.12.10 installed
*   **VLC Media Player installed (latest stable version recommended)**
*   (Optional) If NVDA-related APIs are to be used, ensure NVDA is installed on your system.
*   (Optional) If Zhengdu Reader-related APIs are to be used, ensure Zhengdu Reader is installed on your system.

### Installation Steps
1.  **Clone or Download the Project:**
2.  **Create and Activate a Python Virtual Environment (Recommended):**
    ```bash
    python -m venv venv
    # Windows
    .\venv\Scripts\activate
    # macOS/Linux
    # source venv/bin/activate
    ```
    *(Virtual environments help isolate project dependencies, preventing conflicts with other Python projects)*

3.  **Install Project Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Run the Application:**
    ```bash
    python InstantAudioPreviewer.py
    ```

## Notes
*   This project is developed solely for learning and exploration purposes, and the origin of its core functionality has been duly acknowledged.
*   Please respect Mr. Shen Guangrong's original work when using this project.

## Open Source License
This project is released under the **MIT License**.