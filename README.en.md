# InstantAudioPreviewer (File Manager Audio Real-Time Preview Tool)
##Project Introduction
**InstantAudioPreviewer** is a real-time audio file preview tool for Windows File Manager. When a user selects an audio file in the file manager, this program can automatically play the sound of the file without having to open a separate player. It also integrates convenient shortcut key operations, audio label management functions, and supports interaction with mainstream screen readers (such as NVDA, competing screen reading) to provide better assistive functions.
##Source description of core functions
** The inspiration and ideas of this project on "Real-time Audio Preview in File Manager" come from Mr. Shen Guangrong's sharing in the "Zhengdu.com" forum. ** I would like to express my most sincere gratitude to Mr. Shen Guangrong for his contribution to originality, and hereby acknowledge clearly that my project is developed based on his original ideas in this core function.
In the early days of the project's release, I failed to admit this in a timely and candid manner and defended my wrongful behavior. I am deeply sorry for this and have publicly apologized on the forum on July 20, 2025 ** and stopped the spread of the project.
##Features and improvements implemented independently by this project
Based on Mr. Shen Guangrong's original ideas, this project has independently achieved the following functions and improvements:
*   ** Enhanced shortcut control: **
    *   Play/pause, fast forward/rewind, hide/show windows, and quickly exit.
    *   ** You can customize shortcut keys ** and provide a "shortcut key settings" dialog box.
*   ** Intelligent audio label management: **
    *   ** Add tags: ** Custom tags can be added to audio files, and multiple tags (separated by commas) are supported.
    *   ** Search for tags: ** Search for audio files by tag name (support fuzzy matching).
    *   ** Search results preview: ** Instant preview of files in the search results list.
*   ** Unified text-to-speech (TTS) interface: **
    *   Provides a unified TTS interface to coordinate interactions with the **NVDA Controller Client API**(encapsulated by `utils/nvda_api_wrapper.py`) and the ** contention screen reading API**(encapsulated by `utils/zdsr_api_wrapper.py`).
    *   Coordinates the voice output of the screen reader according to a preset strategy (automatic detection or simultaneous transmission).
*   ** Other functions: **
    *   Update checking and downloading (`update_check_and_download.py`)
    *   Logging system configuration (`utils/logger_config.py`)
##Technology Stack
*   **Python:** 3.12.10
*   **GUI library:** wxWidgets (via wxPython)
*   ** Audio library:** SDL2/SDL_mixer (via PySDL2)
*   ** Database:** SQLite (for label management)
*   ** Screen Reader API:** NVDA Controller Client API, Competition Screen Reader API (implemented through custom packaging)
##How to install and run
###Preconditions
*   Windows operating system
*   Python 3.12.10 is installed
*   wxPython is installed
*   PySDL2 is installed (or make sure SDL2/SDL_mixer is available)
*   (Optional) If you need to use NVDA related APIs, make sure your system has NVDA installed.
*   (Optional) If you need to use contention screen reading related APIs, make sure that contention screen reading is installed on your system.
###Installation steps
1.  ** Clone or download projects: **
2.  ** Create and activate a Python virtual environment (recommended): **
    ```bash
    python -m venv venv
    # Windows
    .\ venv\Scripts\activate
    # macOS/Linux
    # source venv/bin/activate
    ```
    *(Virtual environments can isolate project dependencies and avoid conflicts with other Python projects)*
3.  ** Installation project dependencies: **
    ```bash
    pip install -r requirements.txt
    ```
4.  ** Running the application: **
    ```bash
    python InstantAudioPreviewer.py
    ```
##Notes
*   This project has been developed for learning and exploration purposes only, and has been declared the original source of core functions.
*   Please respect Mr. Shen Guangrong's original work when using this project.
##Open Source License
This project is released under the **MIT License**.