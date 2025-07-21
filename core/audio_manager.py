import sdl2
import sdl2.sdlmixer
import os
import sys
import time
import queue
import atexit
import threading
import wx

# --- DLL 加载路径处理 (仅在此处添加，不修改其他函数逻辑) ---
if sys.platform == "win32":
    # 确定脚本的目录或可执行文件的目录
    # getattr(sys, 'frozen', False) 检查程序是否被打包（例如用 Nuitka）
    # sys.executable 是打包后的 .exe 文件路径
    # __file__ 是脚本本身的文件路径
    # 这个逻辑能正确获取到程序（或脚本）运行的根目录
    program_root_dir = os.path.dirname(os.path.abspath(getattr(sys, 'frozen', False) and sys.executable or __file__))

    # 将程序运行的根目录添加到 DLL 搜索路径
    # 这确保了与 .exe 或主脚本同级的 DLL 可以被找到
    try:
        os.add_dll_directory(program_root_dir)
        # print(f"DLL search path added: {program_root_dir}") # 调试输出
    except Exception as e:
        # Python 3.8+ 支持 os.add_dll_directory
        # 对于旧版本或者权限问题，可能会失败
        print(f"Warning: Failed to add '{program_root_dir}' to DLL search paths using os.add_dll_directory: {e}")
        # 如果 os.add_dll_directory 失败，作为备用方案，尝试修改 PATH 环境变量
        # 注意：修改 PATH 可能会影响整个进程，通常不推荐，但作为兼容性考虑
        # 如果你的 Python 版本低于 3.8，则需要此行
        # if program_root_dir not in os.environ['PATH']:
        #     os.environ['PATH'] = program_root_dir + os.pathsep + os.environ['PATH']
        #     print(f"Warning: Falling back to modifying PATH environment variable.")

    # 尝试查找 PySDL2 自身的 bin 目录，并添加到 DLL 搜索路径
    # 在非打包环境下，PySDL2 的 DLL 默认可能在这里
    try:
        # 导入 sdl2 的内部模块以获取其安装路径
        # _sdl2 是一个内部的、可能包含 DLL 的模块
        import sdl2._sdl2
        sdl2_module_path = os.path.dirname(sdl2._sdl2.__file__)
        sdl2_bin_path = os.path.join(sdl2_module_path, "bin")
        if os.path.isdir(sdl2_bin_path):
            os.add_dll_directory(sdl2_bin_path)
            # print(f"DLL search path added: {sdl2_bin_path}") # 调试输出
    except (ImportError, AttributeError, OSError) as e:
        # 如果 sdl2._sdl2 模块不存在、或 __file__ 不可用、或路径无效
        print(f"Warning: Could not find or add PySDL2's bin directory to DLL search paths: {e}")
# --- DLL 加载路径处理结束 ---


# 尝试导入自定义日志配置，如果失败则使用基础的控制台日志
try:
    from utils.logger_config import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.warning("无法导入 utils.logger_config。正在使用基础控制台日志。")

# 获取脚本的目录，用于查找资源文件。现在这个变量将始终指向程序执行的根目录。
# program_root_dir 是我们在上面 DLL 处理中定义的，现在直接使用它。
script_dir = program_root_dir

# 全局变量
_main_frame_ref = None  # 对主窗口的引用，用于更新GUI
audio_command_queue = queue.Queue() # 用于在不同线程间安全地传递音频命令

_current_music = None  # 当前加载的音乐对象 (sdl2.sdlmixer.Mix_Music*)
_current_file_path = None  # 当前正在播放的文件的完整路径
_audio_system_initialized = False  # 标记音频系统是否已成功初始化

# 音频播放状态常量
PLAYBACK_STATUS_STOPPED = "stopped"
PLAYBACK_STATUS_PLAYING = "playing"
PLAYBACK_STATUS_PAUSED = "paused"
_current_playback_status = PLAYBACK_STATUS_STOPPED  # 当前播放状态

# 跟踪最后成功播放的文件路径
_last_played_file_path = None

# 定义快进快退的默认步长（秒）
DEFAULT_SEEK_STEP = 5.0

def set_frame_reference(frame_instance):
    """设置主窗口的引用，以便音频模块可以更新GUI。"""
    global _main_frame_ref
    _main_frame_ref = frame_instance
    logger.debug("主窗口引用已设置。")

def get_last_played_file_path():
    """返回最后成功播放的音频文件的完整路径。"""
    return _last_played_file_path

def get_mixer_dll_paths():
    """
    辅助函数，用于检查 SDL2_mixer 及其依赖 DLL 是否可能存在于预期路径。
    注意：这不保证 DLL 能被正确加载。
    """
    # 核心 DLLs，这些是 SDL_mixer 运行时可能依赖的
    # 这是基于你最初提供的列表和常见依赖。
    dll_names = [
        "SDL2.dll",
        "SDL2_mixer.dll",
        "libxmp.dll",
        "libwavpack-1.dll",
        "libopusfile-0.dll",
        "libopus-0.dll",
        "libogg-0.dll",
        "libgme.dll",
        # 常见 SDL_mixer 格式支持 DLLs，即使你未明确列出，也可能需要
        "libmpg123-0.dll", # MP3 支持
        "libvorbis-0.dll",
        "libvorbisfile-3.dll",
        "FLAC.dll",        # FLAC 支持
        "zlib1.dll",       # 常见的通用压缩库依赖
        # 其他你系统或 SDL2_mixer 版本可能需要的 DLL
        # 例如 libgcc_s_seh-1.dll, libstdc++-6.dll (如果使用 MinGW 编译的 DLL)
    ]

    missing_dlls = []
    # 确定查找 DLL 的基础目录
    # 现在 `script_dir` 已经正确指向程序运行的根目录
    base_dirs = [script_dir]

    # 在打包后，PySDL2 的 bin 目录中的 DLL 理论上会被 Nuitka 复制到 script_dir
    # 但为了以防万一或非打包环境，仍然可以尝试检查 PySDL2 自身的 bin 目录
    try:
        import sdl2._sdl2 # 导入内部模块
        sdl2_module_path = os.path.dirname(sdl2._sdl2.__file__)
        sdl2_bin_path = os.path.join(sdl2_module_path, "bin")
        if os.path.isdir(sdl2_bin_path) and sdl2_bin_path not in base_dirs:
            base_dirs.append(sdl2_bin_path)
    except (ImportError, AttributeError, OSError):
        pass # 如果找不到或出错，忽略

    # 确保目录列表不包含重复项
    unique_base_dirs = []
    for d in base_dirs:
        if d not in unique_base_dirs:
            unique_base_dirs.append(d)

    found_dlls = set()

    # 遍历所有需要的 DLL 文件
    for dll_name in dll_names:
        found = False
        # 在所有可能的基目录中搜索
        for base_dir in unique_base_dirs:
            full_path = os.path.join(base_dir, dll_name)
            if os.path.exists(full_path):
                found_dlls.add(dll_name)
                found = True
                break # 找到就停止搜索当前 DLL
        if not found:
            missing_dlls.append(dll_name) # 如果在所有目录都没找到，则记录为缺失

    return missing_dlls

def init_audio_system():
    """初始化 SDL2 和 SDL_mixer 音频系统。"""
    global _audio_system_initialized

    if _audio_system_initialized:
        logger.info("音频系统已初始化过。")
        return True

    logger.info("尝试初始化 SDL2 和 SDL_mixer 音频系统...")

    # 初始化 SDL2 的音频子系统
    if sdl2.SDL_Init(sdl2.SDL_INIT_AUDIO) == -1:
        error_msg = sdl2.SDL_GetError().decode()
        logger.error(f"SDL_Init Error: {error_msg}")
        if _main_frame_ref:
            # 使用 CallAfter 确保在主线程上更新 GUI
            wx.CallAfter(_main_frame_ref.show_error_message,
                        f"SDL2 音频初始化失败。\n错误: {error_msg}\n请确保 SDL2.dll 文件在程序同一目录或系统PATH中。",
                        "音频初始化失败")
        return False

    # 定义需要初始化的 SDL_mixer 格式支持（MP3, OGG, FLAC）
    # 保持你原始代码的 Mix_Init 标志
    mixer_flags = sdl2.sdlmixer.MIX_INIT_MP3 | \
                sdl2.sdlmixer.MIX_INIT_OGG | \
                sdl2.sdlmixer.MIX_INIT_FLAC

    # 初始化 SDL_mixer，并检查是否成功加载了所有要求的格式
    # Mix_Init 返回成功加载的标志位
    if (sdl2.sdlmixer.Mix_Init(mixer_flags) & mixer_flags) != mixer_flags:
        error_msg = sdl2.sdlmixer.Mix_GetError().decode()
        logger.error(f"Mix_Init Error: {error_msg}")

        # 提供缺失 DLL 的提示
        missing_dlls = get_mixer_dll_paths()
        dll_hint = ""
        if missing_dlls:
            dll_hint = f"\n提示: 可能缺少以下 DLL 文件: {', '.join(missing_dlls)}。\n请将它们与您的程序放在同一目录或添加到系统PATH中。"

        if _main_frame_ref:
            wx.CallAfter(_main_frame_ref.show_error_message,
                        f"SDL_mixer 初始化失败。\n错误: {error_msg}{dll_hint}",
                        "音频初始化失败")
        sdl2.SDL_Quit() # 如果 Mix_Init 失败，清理 SDL
        return False

    # 打开音频设备，设置采样率、格式、声道数和缓冲区大小
    if sdl2.sdlmixer.Mix_OpenAudio(44100, sdl2.sdlmixer.MIX_DEFAULT_FORMAT, 2, 512) == -1:
        error_msg = sdl2.sdlmixer.Mix_GetError().decode()
        logger.error(f"Mix_OpenAudio Error: {error_msg}")
        if _main_frame_ref:
            wx.CallAfter(_main_frame_ref.show_error_message,
                        f"无法打开音频设备。\n错误: {error_msg}\n请检查您的声卡和驱动。",
                        "音频设备错误")
        sdl2.sdlmixer.Mix_Quit() # 清理 Mixer
        sdl2.SDL_Quit() # 清理 SDL
        return False

    # 尝试获取并记录 SDL_mixer 的版本信息
    try:
        # 现代 PySDL2 的推荐方式
        mixer_version = sdl2.sdlmixer.get_version()
        logger.info(f"SDL_mixer version: {mixer_version.major}.{mixer_version.minor}.{mixer_version.patch}")
    except AttributeError:
        # 兼容旧版本 PySDL2 的方式
        try:
            mixer_version_ptr = sdl2.sdlmixer.Mix_Linked_Version()
            if mixer_version_ptr:
                mixer_version = mixer_version_ptr.contents
                logger.info(f"SDL_mixer linked version: {mixer_version.major}.{mixer_version.minor}.{mixer_version.patch}")
            else:
                logger.warning("无法获取 SDL_mixer 链接版本信息。")
        except Exception as e:
            logger.warning(f"无法从 Mix_Linked_Version() 获取 SDL_mixer 版本信息: {e}")
            logger.info("SDL_mixer 模块已加载，但版本信息可能无法直接获取。")
    except Exception as e:
        logger.warning(f"无法获取 SDL_mixer 版本信息 (通用错误): {e}")
        logger.info("SDL_mixer 模块已加载，但版本信息可能无法直接获取。")

    logger.info("音频系统 (SDL2/SDL_mixer) 初始化成功。")
    _audio_system_initialized = True
    return True

def free_audio_system():
    """在程序退出时释放所有 SDL 和 SDL_mixer 资源。"""
    global _audio_system_initialized, _current_music, _current_playback_status, _current_file_path, _last_played_file_path
    if _audio_system_initialized:
        stop_audio() # 确保停止任何正在播放的音频并释放资源
        try:
            sdl2.sdlmixer.Mix_CloseAudio() # 关闭音频设备
            sdl2.sdlmixer.Mix_Quit()     # 释放 SDL_mixer 模块
            sdl2.SDL_Quit()              # 释放 SDL 模块
            logger.info("音频系统 (SDL2/SDL_mixer) 已释放。")
        except Exception as e:
            logger.error(f"释放音频系统时出错: {e}", exc_info=True)
        finally:
            # 重置全局状态
            _audio_system_initialized = False
            _current_playback_status = PLAYBACK_STATUS_STOPPED
            _current_file_path = None
            _last_played_file_path = None

# 注册清理函数，确保在程序正常退出时调用
atexit.register(free_audio_system)

def play_audio(file_path):
    """开始播放指定的音频文件。"""
    global _current_music, _current_playback_status, _current_file_path, _last_played_file_path

    if not _audio_system_initialized:
        logger.error("音频系统未初始化，无法播放音频。")
        if _main_frame_ref:
            wx.CallAfter(_main_frame_ref.show_error_message, "音频系统未就绪，无法播放。", "播放失败")
        return

    # 如果当前有音乐正在播放，先停止并释放它
    if _current_music:
        try:
            sdl2.sdlmixer.Mix_HaltMusic() # 停止当前播放
            sdl2.sdlmixer.Mix_FreeMusic(_current_music) # 释放音乐对象
            _current_music = None
            _current_file_path = None
            logger.debug("已停止并释放上一个音乐对象。")
        except Exception as e:
            logger.error(f"释放上一个音乐对象时出错: {e}", exc_info=True)

    try:
        logger.info(f"[PLAYBACK] 开始处理播放请求: {os.path.basename(file_path)}")
        normalized_path = os.path.normpath(file_path) # 规范化文件路径

        # 检查文件是否存在且是一个文件
        if not os.path.exists(normalized_path):
            logger.error(f"[PLAYBACK_ERROR] 文件不存在: {normalized_path}")
            if _main_frame_ref:
                wx.CallAfter(_main_frame_ref.show_error_message,
                            f"文件 '{os.path.basename(normalized_path)}' 不存在。\n请检查文件是否已被移动或删除。",
                            "文件不存在")
            _current_playback_status = PLAYBACK_STATUS_STOPPED
            _last_played_file_path = None # 播放失败，清空最后播放路径
            return
        if not os.path.isfile(normalized_path):
            logger.error(f"[PLAYBACK_ERROR] 不是有效文件: {normalized_path}")
            if _main_frame_ref:
                wx.CallAfter(_main_frame_ref.show_error_message,
                            f"'{os.path.basename(normalized_path)}' 不是一个有效的文件。\n请选择一个音频文件。",
                            "无效文件")
            _current_playback_status = PLAYBACK_STATUS_STOPPED
            _last_played_file_path = None # 播放失败，清空最后播放路径
            return

        logger.debug(f"[PLAYBACK] 尝试加载音乐文件: {normalized_path}")
        # 使用 UTF-8 编码路径加载音乐文件 (Mix_LoadMUS 需要 bytes)
        music = sdl2.sdlmixer.Mix_LoadMUS(normalized_path.encode('utf-8'))

        # 检查加载是否成功
        if not music:
            error_msg = sdl2.sdlmixer.Mix_GetError().decode()
            logger.error(f"[PLAYBACK_ERROR] 无法加载音频文件: {error_msg} (File: {normalized_path})")
            if _main_frame_ref:
                wx.CallAfter(_main_frame_ref.show_error_message,
                            f"无法播放文件 '{os.path.basename(file_path)}'。\n原因: {error_msg}\n提示: 检查文件是否损坏，或是否缺少对应的解码器DLL。",
                            "播放失败")
            _current_playback_status = PLAYBACK_STATUS_STOPPED
            _last_played_file_path = None # 播放失败，清空最后播放路径
            return

        _current_music = music # 保存加载的音乐对象
        _current_file_path = normalized_path # 保存文件路径
        logger.debug(f"[PLAYBACK] 音乐文件加载成功，准备播放: {os.path.basename(file_path)}")

        # 开始播放音乐，0 表示只播放一次
        if sdl2.sdlmixer.Mix_PlayMusic(_current_music, 0) == -1:
            error_msg = sdl2.sdlmixer.Mix_GetError().decode()
            logger.error(f"[PLAYBACK_ERROR] 无法开始播放: {error_msg} (File: {normalized_path})")
            sdl2.sdlmixer.Mix_FreeMusic(_current_music) # 播放失败，释放音乐对象
            _current_music = None
            _current_file_path = None
            _current_playback_status = PLAYBACK_STATUS_STOPPED
            _last_played_file_path = None # 播放失败，清空最后播放路径
            if _main_frame_ref:
                wx.CallAfter(_main_frame_ref.show_error_message,
                            f"无法开始播放文件 '{os.path.basename(file_path)}'。\n错误: {error_msg}",
                            "播放启动失败")
            return

        _current_playback_status = PLAYBACK_STATUS_PLAYING # 更新播放状态
        _last_played_file_path = normalized_path # 成功播放，记录最后播放路径
        if _main_frame_ref:
            wx.CallAfter(_main_frame_ref.update_status_message, f"正在播放: {os.path.basename(_current_file_path)}")
        logger.info(f"[PLAYBACK] 成功开始播放: {os.path.basename(file_path)}")

    except Exception as e:
        logger.error(f"[PLAYBACK_ERROR] 播放时发生意外错误: {e} (File: {file_path})", exc_info=True)
        if _main_frame_ref:
            wx.CallAfter(_main_frame_ref.show_error_message, f"播放文件 '{os.path.basename(file_path)}' 时遇到意外问题。\n错误信息: {e}", "播放错误")
        if _current_music: # 确保即使发生意外错误，音乐对象也被释放
            sdl2.sdlmixer.Mix_FreeMusic(_current_music)
        _current_music = None
        _current_file_path = None
        _current_playback_status = PLAYBACK_STATUS_STOPPED
        _last_played_file_path = None # 播放失败，清空最后播放路径

def stop_audio():
    """停止当前音频播放并释放相关资源。"""
    global _current_music, _current_playback_status, _current_file_path, _last_played_file_path

    # 只有在音频系统初始化且有音乐对象时才执行操作
    if _current_music and _audio_system_initialized:
        try:
            # 检查是否正在播放或暂停，如果是，则停止
            if sdl2.sdlmixer.Mix_PlayingMusic() or sdl2.sdlmixer.Mix_PausedMusic():
                logger.info("[PLAYBACK_ACTION] 请求停止当前音乐播放。")
                sdl2.sdlmixer.Mix_HaltMusic()
                logger.debug("已发送停止音乐播放命令。")
            else:
                logger.debug("没有正在播放或暂停的音乐，直接释放资源。")

            sdl2.sdlmixer.Mix_FreeMusic(_current_music) # 释放音乐对象
            _current_music = None
            _current_file_path = None
            _last_played_file_path = None # 停止播放，清空最后播放路径
            logger.info("[PLAYBACK] 音频播放已停止并释放资源。")
        except Exception as e:
            logger.error(f"停止或释放音频播放时出错: {e}", exc_info=True)
            if _main_frame_ref:
                wx.CallAfter(_main_frame_ref.show_error_message,
                            f"停止音频播放时遇到错误: {e}",
                            "停止错误")
        finally:
            _current_playback_status = PLAYBACK_STATUS_STOPPED # 更新状态为停止
            if _main_frame_ref:
                wx.CallAfter(_main_frame_ref.update_status_message, "已停止播放")
    else:
        # 如果没有音乐对象或系统未初始化，确保状态正确
        logger.debug("[PLAYBACK] 无音频正在播放或音频系统未初始化，无需停止。状态已是停止。")
        _current_playback_status = PLAYBACK_STATUS_STOPPED
        _current_file_path = None
        _last_played_file_path = None # 停止播放，清空最后播放路径
        if _main_frame_ref:
            wx.CallAfter(_main_frame_ref.update_status_message, "播放器空闲")

def pause_audio():
    """暂停当前音频播放。"""
    global _current_playback_status
    logger.info("[PLAYBACK_ACTION] 收到暂停音频请求。")
    if not _audio_system_initialized:
        logger.warning("音频系统未初始化，无法暂停。")
        if _main_frame_ref:
            wx.CallAfter(_main_frame_ref.show_error_message, "音频系统未就绪，无法暂停。", "暂停失败")
        return

    if not _current_music:
        logger.warning("没有当前音乐对象，无法暂停。")
        if _main_frame_ref:
            wx.CallAfter(_main_frame_ref.update_status_message, "播放器空闲，无法暂停")
        return

    # 只有在当前音乐正在播放时才能暂停
    if sdl2.sdlmixer.Mix_PlayingMusic():
        try:
            sdl2.sdlmixer.Mix_PauseMusic() # 暂停音乐
            _current_playback_status = PLAYBACK_STATUS_PAUSED # 更新状态
            logger.info("[PLAYBACK] 音频已成功暂停。")
            if _main_frame_ref:
                current_file_name = os.path.basename(_current_file_path) if _current_file_path else "当前文件"
                wx.CallAfter(_main_frame_ref.update_status_message, f"已暂停: {current_file_name}")
        except Exception as e:
            logger.error(f"暂停音频时发生错误: {e}", exc_info=True)
            if _main_frame_ref:
                wx.CallAfter(_main_frame_ref.show_error_message, f"暂停音频时遇到错误。\n错误信息: {e}", "暂停错误")
    elif sdl2.sdlmixer.Mix_PausedMusic():
        # 如果已经是暂停状态，则不需要重复操作
        logger.info("[PLAYBACK] 音频已处于暂停状态，无需重复暂停。")
        if _main_frame_ref:
            current_file_name = os.path.basename(_current_file_path) if _current_file_path else "当前文件"
            wx.CallAfter(_main_frame_ref.update_status_message, f"已暂停: {current_file_name} (已是暂停状态)")
    else:
        # 如果既不是播放也不是暂停状态（例如播放完毕），则无法执行暂停
        logger.debug("[PLAYBACK] 音频未在播放或暂停状态，无法执行暂停操作。")
        if _main_frame_ref:
            wx.CallAfter(_main_frame_ref.update_status_message, "无播放中音频，无法暂停")

def resume_audio():
    """继续（恢复）之前暂停的音频播放。"""
    global _current_playback_status
    logger.info("[PLAYBACK_ACTION] 收到继续播放音频请求。")
    if not _audio_system_initialized:
        logger.warning("音频系统未初始化，无法继续播放。")
        if _main_frame_ref:
            wx.CallAfter(_main_frame_ref.show_error_message, "音频系统未就绪，无法继续播放。", "继续播放失败")
        return

    if not _current_music:
        logger.warning("没有当前音乐对象，无法继续播放。")
        if _main_frame_ref:
            wx.CallAfter(_main_frame_ref.update_status_message, "播放器空闲，无法继续")
        return

    # 只有在当前音乐已暂停时才能继续
    if sdl2.sdlmixer.Mix_PausedMusic():
        try:
            sdl2.sdlmixer.Mix_ResumeMusic() # 继续播放
            _current_playback_status = PLAYBACK_STATUS_PLAYING # 更新状态
            logger.info("[PLAYBACK] 音频已成功继续播放。")
            if _main_frame_ref:
                current_file_name = os.path.basename(_current_file_path) if _current_file_path else "当前文件"
                wx.CallAfter(_main_frame_ref.update_status_message, f"正在播放: {current_file_name}")
        except Exception as e:
            logger.error(f"继续播放音频时发生错误: {e}", exc_info=True)
            if _main_frame_ref:
                wx.CallAfter(_main_frame_ref.show_error_message, f"继续播放音频时遇到错误。\n错误信息: {e}", "继续播放错误")
    elif sdl2.sdlmixer.Mix_PlayingMusic():
        # 如果已经是播放状态，则不需要重复操作
        logger.info("[PLAYBACK] 音频已处于播放状态，无需重复继续播放。")
        if _main_frame_ref:
            current_file_name = os.path.basename(_current_file_path) if _current_file_path else "当前文件"
            wx.CallAfter(_main_frame_ref.update_status_message, f"正在播放: {current_file_name} (已是播放状态)")
    else:
        # 如果未暂停也未播放（例如播放完毕），则无法执行继续操作
        logger.debug("[PLAYBACK] 音频未在暂停或播放状态，无法执行继续播放操作。")
        if _main_frame_ref:
            wx.CallAfter(_main_frame_ref.update_status_message, "无暂停音频，无法继续")

def toggle_play_pause():
    """切换播放和暂停状态。"""
    logger.info("[PLAYBACK_ACTION] 收到切换播放/暂停请求。")
    if not _audio_system_initialized:
        logger.warning("音频系统未初始化，无法切换播放/暂停。")
        if _main_frame_ref:
            wx.CallAfter(_main_frame_ref.show_error_message, "音频系统未就绪。", "操作失败")
        return

    if not _current_music:
        logger.warning("没有当前音乐对象，无法切换播放/暂停。")
        if _main_frame_ref:
            wx.CallAfter(_main_frame_ref.update_status_message, "播放器空闲，无法切换")
        return

    # 首先检查是否已暂停，因为暂停是特定的状态，且恢复操作仅针对暂停
    if sdl2.sdlmixer.Mix_PausedMusic():
        logger.info("[PLAYBACK_ACTION] 检测到已暂停，执行继续播放。")
        resume_audio()
    elif sdl2.sdlmixer.Mix_PlayingMusic():
        logger.info("[PLAYBACK_ACTION] 检测到正在播放，执行暂停。")
        pause_audio()
    else:
        # 如果既没播放也没暂停，但 _current_music 存在（例如播放结束但未清理）
        # 此时应尝试重新播放（从头开始）或停止。
        # 由于有文件监视器的自动播放逻辑，这里更倾向于什么都不做，除非用户手动点击播放按钮。
        logger.info("[PLAYBACK_ACTION] 当前无音频播放或暂停中，无法切换播放/暂停状态。")
        if _main_frame_ref:
            wx.CallAfter(_main_frame_ref.update_status_message, "播放器空闲，无法切换")

def seek_audio(seconds):
    """
    跳转到音频的指定秒数位置。
    seconds: 正数表示快进，负数表示快退。
    """
    global _current_music

    logger.info(f"[PLAYBACK_ACTION] 收到跳转音频请求: {seconds} 秒。")

    if not _current_music or not _audio_system_initialized:
        logger.warning("无音频播放，无法执行快进/快退。")
        if _main_frame_ref:
            wx.CallAfter(_main_frame_ref.update_status_message, "播放器空闲，无法快进/快退")
        return

    # 只有在音乐正在播放或暂停时才能跳转
    if not (sdl2.sdlmixer.Mix_PlayingMusic() or sdl2.sdlmixer.Mix_PausedMusic()):
        logger.warning("音频未在播放或暂停状态，无法执行快进/快退。")
        if _main_frame_ref:
            wx.CallAfter(_main_frame_ref.update_status_message, "当前无播放，无法快进/快退")
        return

    current_pos = -1.0 # 初始化为无效位置

    try:
        # 尝试使用 Mix_GetMusicPlaytime (推荐，应兼容你的 DLL)
        # 此函数在 SDL_mixer 2.0.10+ 中引入，返回 double 类型的秒数。
        current_pos = sdl2.sdlmixer.Mix_GetMusicPlaytime(_current_music)
        logger.debug(f"[SEEK] Mix_GetMusicPlaytime 成功获取当前位置: {current_pos:.3f} 秒。")

    except AttributeError as ae:
        # 如果 Mix_GetMusicPlaytime 不可用，则尝试 Mix_GetMusicPosition
        logger.error(f"[SEEK_ERROR] PySDL2 绑定中缺少 Mix_GetMusicPlaytime。尝试 Mix_GetMusicPosition。错误: {ae}", exc_info=False)
        try:
            # Mix_GetMusicPosition 也返回秒数（double）
            current_pos = sdl2.sdlmixer.Mix_GetMusicPosition(_current_music)
            logger.debug(f"[SEEK] Mix_GetMusicPosition 成功获取当前位置: {current_pos:.3f} 秒。")
            if current_pos < 0: # 如果返回负值，可能表示不支持或发生错误
                logger.warning("[SEEK] Mix_GetMusicPosition 返回负值，可能不支持或无法获取精确播放位置。")
                current_pos = 0.0 # 无法获取真实位置时，强制从头开始计算
        except AttributeError as ae2:
            # 如果 Mix_GetMusicPosition 也不可用
            logger.error(f"[SEEK_ERROR] PySDL2 绑定中也缺少 Mix_GetMusicPosition。无法获取当前播放位置。错误: {ae2}", exc_info=True)
            if _main_frame_ref:
                wx.CallAfter(_main_frame_ref.show_error_message,
                            f"快进/快退失败: 无法获取当前播放位置。\n错误: {ae2}\n请尝试更新 PySDL2 包。",
                            "播放错误")
            return
        except Exception as e_get_pos:
            logger.error(f"[SEEK_ERROR] 调用 Mix_GetMusicPosition 时发生意外错误: {e_get_pos}", exc_info=True)
            if _main_frame_ref:
                wx.CallAfter(_main_frame_ref.show_error_message,
                            f"快进/快退失败: 获取播放位置时出错。\n错误: {e_get_pos}",
                            "播放错误")
            return
    except Exception as e_get_playtime:
        # 如果 Mix_GetMusicPlaytime 调用时发生其他错误
        logger.error(f"[SEEK_ERROR] 调用 Mix_GetMusicPlaytime 时发生意外错误: {e_get_playtime}", exc_info=True)
        if _main_frame_ref:
            wx.CallAfter(_main_frame_ref.show_error_message,
                        f"快进/快退失败: 获取播放时间时出错。\n错误: {e_get_playtime}",
                        "播放错误")
        return

    # 如果所有尝试都无法获取有效位置
    if current_pos < 0:
        logger.error("[SEEK_FATAL] 无法获取任何有效的当前播放位置，快进/快退将不准确或失败。")
        if _main_frame_ref:
            wx.CallAfter(_main_frame_ref.show_error_message,
                        f"快进/快退功能不可用。\n原因: 无法获取当前播放时间，请确保 PySDL2 已最新安装且兼容您的 SDL2_mixer.dll。",
                        "播放错误")
        return

    # 计算新位置
    new_pos = current_pos + seconds
    if new_pos < 0:
        new_pos = 0.0 # 不允许跳转到负数位置（即音频开始之前）

    try:
        # Mix_SetMusicPosition 参数是 double 类型
        if sdl2.sdlmixer.Mix_SetMusicPosition(new_pos) == -1:
            error_msg = sdl2.sdlmixer.Mix_GetError().decode()
            logger.error(f"[SEEK_ERROR] Mix_SetMusicPosition 失败: {error_msg} (尝试跳至: {new_pos:.3f} 秒)。可能是当前音乐类型不支持。")
            if _main_frame_ref:
                wx.CallAfter(_main_frame_ref.show_error_message,
                            f"快进/快退功能失败。\n错误: {error_msg}\n可能当前音频格式不支持此操作。",
                            "操作失败")
        else:
            # 根据跳转方向更新日志和UI消息
            action = "快进" if seconds > 0 else "快退"
            logger.info(f"[PLAYBACK] 音频已 {action} {abs(seconds):.1f} 秒，跳至位置 {new_pos:.1f}。")
            if _main_frame_ref:
                current_file_name = os.path.basename(_current_file_path) if _current_file_path else "当前文件"
                wx.CallAfter(_main_frame_ref.update_status_message, f"正在播放: {current_file_name} ({action})")

    except Exception as e:
        logger.error(f"[SEEK_ERROR] 执行 Mix_SetMusicPosition 时发生意外错误: {e}", exc_info=True)
        if _main_frame_ref:
            wx.CallAfter(_main_frame_ref.show_error_message, f"执行快进/快退时遇到意外问题。\n错误信息: {e}", "播放错误")

def get_current_playback_status():
    """返回当前的播放状态。"""
    return _current_playback_status

def check_and_process_audio_queue():
    """
    检查当前音频播放状态，并处理音频命令队列中的命令。
    这个函数应该在一个定时器或独立线程中定期调用。
    """
    global _current_playback_status 

    # 如果音频系统未初始化，则清空队列并返回
    if not _audio_system_initialized:
        if not audio_command_queue.empty():
            logger.warning("音频系统未准备好，清空音频命令队列。")
            while not audio_command_queue.empty():
                try:
                    audio_command_queue.get(block=False) # 仅移除，不处理
                    audio_command_queue.task_done()
                except queue.Empty:
                    break
        return

    # 检查当前音乐播放状态并更新内部状态
    if _current_music:
        is_playing = sdl2.sdlmixer.Mix_PlayingMusic()
        is_paused = sdl2.sdlmixer.Mix_PausedMusic()

        if is_paused: # 优先级最高：如果暂停了，那就是暂停
            if _current_playback_status != PLAYBACK_STATUS_PAUSED:
                logger.info("内部状态更新为: 已暂停。")
                _current_playback_status = PLAYBACK_STATUS_PAUSED
        elif is_playing: # 如果没有暂停，但正在播放，那就是播放
            if _current_playback_status != PLAYBACK_STATUS_PLAYING:
                logger.info("内部状态更新为: 正在播放。")
                _current_playback_status = PLAYBACK_STATUS_PLAYING
        else: # 既没有暂停也没有播放，那就是停止（例如文件播放完毕）
            if _current_playback_status != PLAYBACK_STATUS_STOPPED:
                logger.info("检测到音乐播放已停止或完成，更新内部状态。")
                # 调用 stop_audio 来处理停止和资源释放
                # 注意：stop_audio 会清理 _current_music 和 _current_file_path
                stop_audio()
    elif _current_playback_status != PLAYBACK_STATUS_STOPPED:
        # 如果没有当前音乐对象，但状态不是停止，强制设为停止
        logger.debug("没有当前音乐对象，但状态不是停止，强制设为停止。")
        _current_playback_status = PLAYBACK_STATUS_STOPPED
        global _current_file_path
        _current_file_path = None

    # 更新GUI状态显示
    current_file_name_display = "播放器空闲"
    if _current_file_path:
        current_file_name_display = os.path.basename(_current_file_path)

    if _main_frame_ref:
        if _current_playback_status == PLAYBACK_STATUS_PLAYING:
            wx.CallAfter(_main_frame_ref.update_status_message, f"正在播放: {current_file_name_display}")
        elif _current_playback_status == PLAYBACK_STATUS_PAUSED:
            wx.CallAfter(_main_frame_ref.update_status_message, f"已暂停: {current_file_name_display}")
        elif _current_playback_status == PLAYBACK_STATUS_STOPPED:
            wx.CallAfter(_main_frame_ref.update_status_message, "播放器空闲")

    # 处理音频命令队列中的命令
    while not audio_command_queue.empty():
        try:
            command, data = audio_command_queue.get(block=False)
            logger.debug(f"从队列中获取命令: {command} with data: {data}")
            if command == "play":
                play_audio(data)
            elif command == "stop":
                stop_audio()
            elif command == "pause":
                pause_audio()
            elif command == "resume":
                resume_audio()
            elif command == "toggle_play_pause":
                toggle_play_pause()
            elif command == "seek":
                seek_audio(data) # data is the number of seconds to seek
            else:
                logger.warning(f"未知音频命令: {command}")
        except queue.Empty:
            break # 队列为空，退出循环
        except Exception as e:
            logger.error(f"处理音频命令时发生错误: {e}", exc_info=True)
            if _main_frame_ref:
                wx.CallAfter(_main_frame_ref.show_error_message, f"处理音频命令时遇到意外问题。\n错误信息: {e}", "音频命令错误")
        finally:
            audio_command_queue.task_done() # 标记任务已完成

# --- Nuitka 打包指令建议 ---
# 为了确保在单文件打包后，所有 DLL 都能被找到，你需要确保它们都被 Nuitka 复制到 .exe 的同级目录。
#
# 1. 整理你的 DLLs：
#    将所有你提到的 DLL (SDL2.dll, SDL2_mixer.dll, libxmp.dll, libwavpack-1.dll, libopusfile-0.dll, libopus-0.dll, libogg-0.dll, libgme.dll)
#    以及 SDL2_mixer 可能隐式需要的其他 DLL (如 libmpg123-0.dll, libvorbis-0.dll, libvorbisfile-3.dll, FLAC.dll, zlib1.dll 等)
#    **全部放在你的项目根目录 (与你的 main_app.py 脚本在同一级)。**
#    例如：
#    your_project_root/
#    ├── main_app.py
#    ├── SDL2.dll
#    ├── SDL2_mixer.dll
#    ├── libxmp.dll
#    ├── libwavpack-1.dll
#    ├── ... (所有需要的 DLL)
#    └── utils/
#        └── logger_config.py
#
# 2. 执行 Nuitka 打包命令：
#    在你项目的根目录下打开命令行，然后运行以下命令。
#    假设你的主脚本文件是 `main_app.py`：

#    python -m nuitka --standalone --windows-disable-console ^
#    --onefile ^
#    --output-dir=dist ^
#    --include-data-dir=./SDL2.dll=. ^
#    --include-data-dir=./SDL2_mixer.dll=. ^
#    --include-data-dir=./libxmp.dll=. ^
#    --include-data-dir=./libwavpack-1.dll=. ^
#    --include-data-dir=./libopusfile-0.dll=. ^
#    --include-data-dir=./libopus-0.dll=. ^
#    --include-data-dir=./libogg-0.dll=. ^
#    --include-data-dir=./libgme.dll=. ^
#    --include-data-dir=./libmpg123-0.dll=. ^
#    --include-data-dir=./libvorbis-0.dll=. ^
#    --include-data-dir=./libvorbisfile-3.dll=. ^
#    --include-data-dir=./FLAC.dll=. ^
#    --include-data-dir=./zlib1.dll=. ^
#    --enable-plugin=pyside6 ^ # 如果你使用了 PySide6 (或者 PyQT6)
#    --enable-plugin=wx.app ^  # 如果你使用了 wxPython
#    main_app.py
#
#    说明：
#    *   `--onefile`: 核心指令，将所有内容打包成一个单文件可执行文件。
#    *   `--include-data-dir=./DLL_NAME.dll=.`: 这一部分是关键！它告诉 Nuitka，将当前目录 (`./`) 下的 `DLL_NAME.dll` 文件复制到 **打包后的 `.exe` 的内部文件系统根目录** (`.`)。你需要为每个 DLL 文件都添加一个这样的条目。
#    *   `--enable-plugin=wx.app`: 推荐为 wxPython 应用启用这个插件，它能更好地处理 wxPython 的内部依赖。

# --- 脚本中的修改总结 ---
# 1.  **添加 DLL 搜索路径：** 在顶部添加了 `os.add_dll_directory()` 调用，确保程序运行目录和 PySDL2 的 bin 目录优先被搜索。
# 2.  **`script_dir` 变量的统一：** 现在 `script_dir` 将始终指向程序（或 `.exe`）的实际运行目录，便于文件查找。
# 3.  **其他代码保持原样：** `init_audio_system` 中的 `mixer_flags` 未做任何改动，`play_audio` 等函数的逻辑也未变。

# --- 示例用法（当脚本直接运行时）
if __name__ == '__main__':
    # 创建一个模拟的主窗口用于测试音频管理器功能
    class MockMainFrame(wx.Frame):
        def __init__(self):
            super().__init__(None, title="Audio Manager Test")
            self.panel = wx.Panel(self)
            self.status_text = wx.StaticText(self.panel, label="Status: Idle")
            self.play_button = wx.Button(self.panel, label="Play Test Audio")
            self.stop_button = wx.Button(self.panel, label="Stop Audio")
            self.pause_button = wx.Button(self.panel, label="Pause")
            self.resume_button = wx.Button(self.panel, label="Resume")
            self.toggle_button = wx.Button(self.panel, label="Toggle Play/Pause")
            self.forward_button = wx.Button(self.panel, label="Fast Forward 5s")
            self.rewind_button = wx.Button(self.panel, label="Rewind 5s")

            # 绑定按钮事件到相应的处理函数
            self.play_button.Bind(wx.EVT_BUTTON, self.on_play)
            self.stop_button.Bind(wx.EVT_BUTTON, self.on_stop)
            self.pause_button.Bind(wx.EVT_BUTTON, self.on_pause)
            self.resume_button.Bind(wx.EVT_BUTTON, self.on_resume)
            self.toggle_button.Bind(wx.EVT_BUTTON, self.on_toggle_play_pause)
            self.forward_button.Bind(wx.EVT_BUTTON, self.on_fast_forward)
            self.rewind_button.Bind(wx.EVT_BUTTON, self.on_rewind)

            # 设置布局
            sizer = wx.BoxSizer(wx.VERTICAL)
            sizer.Add(self.status_text, 0, wx.ALL | wx.EXPAND, 10)
            sizer.Add(self.play_button, 0, wx.ALL | wx.EXPAND, 10)
            sizer.Add(self.stop_button, 0, wx.ALL | wx.EXPAND, 10)
            sizer.Add(self.pause_button, 0, wx.ALL | wx.EXPAND, 10)
            sizer.Add(self.resume_button, 0, wx.ALL | wx.EXPAND, 10)
            sizer.Add(self.toggle_button, 0, wx.ALL | wx.EXPAND, 10)
            sizer.Add(self.forward_button, 0, wx.ALL | wx.EXPAND, 10)
            sizer.Add(self.rewind_button, 0, wx.ALL | wx.EXPAND, 10)

            self.panel.SetSizer(sizer)
            self.SetSize((300, 500)) # 设置窗口大小

            # 设置一个定时器来周期性检查音频状态和队列
            self.timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, self.on_timer, self.timer)
            self.timer.Start(100) # 每 100 毫秒检查一次

            set_frame_reference(self) # 设置全局主窗口引用
            
            # 初始化音频系统
            if not init_audio_system():
                # 如果音频系统初始化失败，显示错误消息
                # self.show_error_message("音频系统未能启动，部分功能可能受限。", "系统启动错误")
                # 已经由 init_audio_system 内部调用 show_error_message
                pass # 允许程序继续，但音频功能将不可用
            self.Show() # 显示窗口

        def on_play(self, event):
            # 尝试找到一个测试音频文件
            # 优先查找 MP3，如果不存在则尝试生成 WAV
            test_audio_path = os.path.join(script_dir, "test_audio.mp3")
            if not os.path.exists(test_audio_path):
                # 如果MP3文件不存在，尝试生成一个简单的WAV文件
                try:
                    import wave
                    import numpy as np
                    wav_path = os.path.join(script_dir, "test_audio.wav")
                    if not os.path.exists(wav_path):
                        samplerate = 44100
                        duration = 30.0 # 增加时长以便测试跳转
                        frequency = 440.0
                        amplitude = 0.5
                        t = np.linspace(0., duration, int(samplerate * duration), endpoint=False)
                        data = amplitude * np.sin(2. * np.pi * frequency * t)
                        data_int16 = (data * 32767).astype(np.int16) # 转换为 16 位 PCM
                        with wave.open(wav_path, 'wb') as wf:
                            wf.setnchannels(1) # 单声道
                            wf.setsampwidth(2) # 16 位采样宽度
                            wf.setframerate(samplerate)
                            wf.writeframes(data_int16.tobytes())
                        print(f"Generated {wav_path}") # 打印生成信息
                    test_audio_path = wav_path # 使用生成的WAV文件进行测试
                except ImportError:
                    print("numpy 或 wave 模块未安装，无法生成测试WAV文件。")
                except Exception as e:
                    print(f"生成 WAV 文件时出错: {e}")


            if not os.path.exists(test_audio_path):
                # 如果仍然找不到测试文件，提示用户
                wx.MessageBox(f"请在 '{script_dir}' 目录下放置一个 'test_audio.mp3' 或 'test_audio.wav' 文件进行测试。", "文件缺失", wx.ICON_WARNING)
                return

            # 将播放命令放入队列
            audio_command_queue.put(("play", test_audio_path))
            self.update_status_message(f"发送播放命令: {os.path.basename(test_audio_path)}")

        def on_stop(self, event):
            audio_command_queue.put(("stop", None)) # 发送停止命令
            self.update_status_message("发送停止命令")

        def on_pause(self, event):
            audio_command_queue.put(("pause", None)) # 发送暂停命令
            self.update_status_message("发送暂停命令")

        def on_resume(self, event):
            audio_command_queue.put(("resume", None)) # 发送继续播放命令
            self.update_status_message("发送继续播放命令")

        def on_toggle_play_pause(self, event):
            audio_command_queue.put(("toggle_play_pause", None)) # 发送切换命令
            self.update_status_message("发送切换播放/暂停命令")

        def on_fast_forward(self, event):
            audio_command_queue.put(("seek", DEFAULT_SEEK_STEP)) # 发送快进命令
            self.update_status_message("发送快进命令")

        def on_rewind(self, event):
            audio_command_queue.put(("seek", -DEFAULT_SEEK_STEP)) # 发送快退命令
            self.update_status_message("发送快退命令")

        def on_timer(self, event):
            # 定时器事件处理，调用检查和处理队列的函数
            check_and_process_audio_queue()

        def update_status_message(self, message):
            """更新状态栏文本。"""
            self.status_text.SetLabel(f"Status: {message}")
            self.panel.Layout() # 重新布局以显示更新

        def show_error_message(self, message, title="错误"):
            """显示一个错误消息对话框。"""
            wx.MessageBox(message, title, wx.OK | wx.ICON_ERROR)
            self.update_status_message(f"错误: {message}") # 同时更新状态栏

    # 运行WX主循环
    app = wx.App(False)
    frame = MockMainFrame()
    app.MainLoop()