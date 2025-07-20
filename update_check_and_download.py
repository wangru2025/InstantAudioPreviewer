import socket
import json
import os
import sys
import tempfile
import subprocess
import shutil
import time
import wx
from enum import Enum

# 优先使用 packaging.version 进行版本比较，回退到 distutils.version.LooseVersion
try:
    from packaging.version import Version
    LooseVersion = Version
except ImportError:
    print("警告: 未找到 'packaging' 库，将回退使用 'distutils.version.LooseVersion'。建议安装 'packaging' (pip install packaging) 以获得更好的兼容性。")
    from distutils.version import LooseVersion

# 定义更新状态枚举
class UpdateStatus(Enum):
    UPDATED_AND_EXITING = "Updated and Exiting"  # 检测到新版本，已下载并启动安装程序，当前版本将退出
    NO_UPDATE = "No Update"                    # 无新版本可用
    UPDATE_CANCELLED = "Update Cancelled"      # 用户取消了更新操作
    UPDATE_FAILED = "Update Failed"            # 更新过程中发生错误

# 定义接收缓冲区大小
BUFFER_SIZE = 4096

def check_for_updates(current_version, server_ip, server_port, logger) -> UpdateStatus:
    """
    检查是否有新版本可用。如果可用，则下载新版本安装程序，并提示用户是否安装。
    若用户同意，则启动安装程序，当前应用将退出。

    Args:
        current_version (str): 当前应用程序的版本号。
        server_ip (str): 更新服务器的IP地址。
        server_port (int): 更新服务器的端口。
        logger: 用于记录日志的 logger 对象。

    Returns:
        UpdateStatus: 指示更新检查结果的状态。
    """
    logger.info(f"开始检查更新。当前版本: {current_version}")

    progress_dialog = None
    temp_dir = None
    new_installer_path = None

    try:
        # 1. 连接服务器
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(60)  # 设置连接和接收超时
            logger.info(f"尝试连接更新服务器 {server_ip}:{server_port}...")
            sock.connect((server_ip, server_port))
            logger.info("成功连接到服务器。")

            # 2. 发送当前版本信息
            request_data = json.dumps({"action": "check_update", "current_version": current_version})
            sock.sendall(request_data.encode('utf-8') + b'\n') # 使用换行符作为消息分隔
            logger.info(f"已发送请求: {request_data}")

            # 3. 接收服务器响应
            response_header_bytes = b''
            while b'\n' not in response_header_bytes: # 读取直到遇到换行符作为响应头结束
                chunk = sock.recv(BUFFER_SIZE)
                if not chunk:
                    raise EOFError("服务器在发送响应时意外断开连接。")
                response_header_bytes += chunk

            header_str, remaining_bytes = response_header_bytes.split(b'\n', 1)
            header_str = header_str.decode('utf-8')

            response_data = json.loads(header_str)

            logger.info(f"收到服务器响应: {response_data}")

            status = response_data.get("status")

            if status == "no_update":
                logger.info("当前已是最新版本，无需更新。")
                return UpdateStatus.NO_UPDATE

            elif status == "update_available":
                server_latest_version = response_data.get("latest_version")
                file_size = response_data.get("file_size")
                release_notes = response_data.get("release_notes", "无更新日志。")
                release_date = response_data.get("release_date", "未知日期")

                if not server_latest_version or file_size is None:
                    logger.error("服务器响应格式不正确，缺少版本号或文件大小信息。")
                    wx.MessageBox("更新失败：服务器响应格式不正确。", "更新失败", wx.OK | wx.ICON_ERROR)
                    return UpdateStatus.UPDATE_FAILED

                logger.info(f"检测到新版本: {server_latest_version}, 文件大小: {file_size} 字节。")

                # 提示用户是否更新，并显示更新日志
                update_message = (
                    f"发现新版本 {server_latest_version} (发布日期: {release_date})！\n\n"
                    f"更新内容:\n{release_notes}\n\n"
                    "是否立即下载并安装？安装完成后程序将自动重启。"
                )
                if wx.MessageBox(update_message, "发现新版本", wx.YES_NO | wx.ICON_INFORMATION) == wx.NO:
                    logger.info("用户选择取消更新。")
                    return UpdateStatus.UPDATE_CANCELLED

                # 4. 下载新版本安装程序
                temp_dir = os.path.join(tempfile.gettempdir(), "instant_audio_preview_update")
                os.makedirs(temp_dir, exist_ok=True)
                new_installer_path = os.path.join(temp_dir, "new_app_installer.exe") # 假设安装程序为exe

                logger.info(f"开始下载新版本安装程序到: {new_installer_path}")

                progress_dialog = wx.ProgressDialog(
                    "下载更新",
                    f"正在下载 {server_latest_version} (0%)",
                    maximum=file_size,
                    parent=None,
                    style=wx.PD_APP_MODAL | wx.PD_CAN_ABORT | wx.PD_AUTO_HIDE
                )
                progress_dialog.SetSize((400, 150))

                received_bytes = 0
                last_update_time = time.time()

                # 内部函数用于下载文件并更新进度条
                def _download_file(sock_obj, target_path, total_size, initial_bytes=b''):
                    nonlocal received_bytes, last_update_time
                    file_handle = None
                    try:
                        file_mode = 'wb' if not initial_bytes else 'ab' # 根据是否有初始字节决定读写模式
                        file_handle = open(target_path, file_mode)

                        if initial_bytes: # 如果有初始字节（例如，断点续传），写入并更新状态
                            file_handle.write(initial_bytes)
                            received_bytes += len(initial_bytes)
                            if progress_dialog:
                                percentage = min(100, received_bytes * 100 // total_size)
                                keep_going, _ = progress_dialog.Update(received_bytes,
                                                                        f"正在下载 {server_latest_version} ({percentage}%)")
                                if not keep_going:
                                    logger.info("用户在下载过程中取消了更新。")
                                    return False
                                last_update_time = time.time()

                        # 循环接收剩余数据
                        while received_bytes < total_size:
                            bytes_to_read = min(BUFFER_SIZE, total_size - received_bytes) # 确保不会读取超过剩余字节数
                            chunk = sock_obj.recv(bytes_to_read)
                            if not chunk:
                                logger.error("文件下载中断：服务器过早关闭连接或无更多数据。")
                                return False
                            file_handle.write(chunk)
                            received_bytes += len(chunk)

                            current_time = time.time()
                            # 每接收一定量数据或超过一定时间间隔，更新进度条
                            if (progress_dialog and (received_bytes - progress_dialog.GetValue() > 1024 * 1024)) or \
                               (current_time - last_update_time > 0.5):
                                if progress_dialog:
                                    percentage = min(100, received_bytes * 100 // total_size)
                                    keep_going, _ = progress_dialog.Update(received_bytes,
                                                                            f"正在下载 {server_latest_version} ({percentage}%)")
                                    if not keep_going:
                                        logger.info("用户在下载过程中取消了更新。")
                                        return False
                                    last_update_time = current_time
                        return True # 下载成功
                    finally:
                        if file_handle:
                            file_handle.close()

                # 执行下载
                download_success = _download_file(sock, new_installer_path, file_size, remaining_bytes)

                if not download_success: # 用户取消或下载中断
                    if os.path.exists(new_installer_path):
                        try:
                            os.remove(new_installer_path)
                        except OSError as ex:
                            logger.error(f"删除不完整下载文件失败: {ex}", exc_info=True)
                    # 清理空的临时目录
                    if os.path.exists(temp_dir) and not os.listdir(temp_dir):
                        try:
                            os.rmdir(temp_dir)
                        except OSError as ex:
                            logger.error(f"删除空的临时目录失败: {ex}", exc_info=True)

                    # 如果用户取消，返回 UPDATE_CANCELLED；如果是中断，返回 UPDATE_FAILED
                    return UpdateStatus.UPDATE_CANCELLED if received_bytes != file_size else UpdateStatus.UPDATE_FAILED

                logger.info(f"文件下载完成。总共接收 {received_bytes} 字节。")

                # 校验文件大小
                if received_bytes != file_size:
                    logger.error(f"下载文件大小不匹配。预期 {file_size}，实际 {received_bytes}")
                    wx.MessageBox(f"更新文件下载失败！预期大小 {file_size} 字节，实际下载 {received_bytes} 字节。\n请检查网络连接或稍后重试。",
                                  "更新失败", wx.OK | wx.ICON_ERROR)
                    # 清理下载的文件和目录
                    if os.path.exists(new_installer_path):
                        try:
                            os.remove(new_installer_path)
                        except OSError as ex:
                            logger.error(f"删除不完整下载文件失败: {ex}", exc_info=True)
                    if os.path.exists(temp_dir) and not os.listdir(temp_dir):
                        try:
                            os.rmdir(temp_dir)
                        except OSError as ex:
                            logger.error(f"删除空的临时目录失败: {ex}", exc_info=True)
                    return UpdateStatus.UPDATE_FAILED

                logger.info(f"文件成功下载到: {new_installer_path}")

                # 5. 启动新版本安装程序
                logger.info(f"正在启动新安装程序: {new_installer_path}")
                try:
                    if sys.platform == 'win32':
                        # 在Windows上，使用 DETACHED_PROCESS 和 CREATE_NEW_PROCESS_GROUP 避免父进程影响子进程
                        creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                        subprocess.Popen(f'"{new_installer_path}"', shell=True, creation_flags=creation_flags, close_fds=True)
                    else:
                        # 对于非Windows平台，直接执行
                        subprocess.Popen([new_installer_path])
                    logger.info("新安装程序已启动。")
                    return UpdateStatus.UPDATED_AND_EXITING
                except Exception as e:
                    logger.error(f"启动安装程序失败: {e}", exc_info=True)
                    wx.MessageBox(f"更新成功下载，但启动安装程序失败：{e}", "启动安装程序失败", wx.OK | wx.ICON_ERROR)
                    # 清理下载的文件和目录
                    if os.path.exists(new_installer_path):
                        try:
                            os.remove(new_installer_path)
                        except OSError as ex:
                            logger.error(f"删除安装程序文件失败: {ex}", exc_info=True)
                    if os.path.exists(temp_dir) and not os.listdir(temp_dir):
                        try:
                            os.rmdir(temp_dir)
                        except OSError as ex:
                            logger.error(f"删除临时目录失败: {ex}", exc_info=True)
                    return UpdateStatus.UPDATE_FAILED

            else:
                logger.error(f"收到未知服务器响应状态: '{status}'")
                wx.MessageBox(f"更新失败：服务器返回未知状态 '{status}'。", "更新失败", wx.OK | wx.ICON_ERROR)
                return UpdateStatus.UPDATE_FAILED

    except socket.timeout:
        logger.error("连接或接收数据超时。请检查网络连接或服务器状态。", exc_info=True)
        wx.MessageBox("更新失败：连接或接收数据超时。请检查网络连接或稍后重试。", "更新失败", wx.OK | wx.ICON_ERROR)
        return UpdateStatus.UPDATE_FAILED
    except ConnectionRefusedError:
        logger.error("连接被拒绝。请确保更新服务器已运行并监听指定端口。", exc_info=True)
        wx.MessageBox("更新失败：连接被拒绝。请确保更新服务器已运行并监听指定端口。", "更新失败", wx.OK | wx.ICON_ERROR)
        return UpdateStatus.UPDATE_FAILED
    except EOFError as e:
        logger.error(f"服务器连接意外关闭: {e}", exc_info=True)
        wx.MessageBox(f"更新失败：服务器连接意外关闭 ({e})。", "更新失败", wx.OK | wx.ICON_ERROR)
        return UpdateStatus.UPDATE_FAILED
    except json.JSONDecodeError:
        logger.error("接收到的服务器响应不是有效的JSON格式。", exc_info=True)
        wx.MessageBox("更新失败：服务器响应格式不正确。", "更新失败", wx.OK | wx.ICON_ERROR)
        return UpdateStatus.UPDATE_FAILED
    except OSError as e: # 捕捉文件操作、网络等OS相关错误
        logger.error(f"执行更新操作时发生操作系统错误: {e}", exc_info=True)
        wx.MessageBox(f"更新过程中发生系统错误: {e}", "更新失败", wx.OK | wx.ICON_ERROR)
        return UpdateStatus.UPDATE_FAILED
    except Exception as e: # 捕捉所有其他未预料的错误
        logger.error(f"更新检查过程中发生未知错误: {e}", exc_info=True)
        wx.MessageBox(f"更新过程中发生未知错误: {e}", "更新失败", wx.OK | wx.ICON_ERROR)
        return UpdateStatus.UPDATE_FAILED
    finally:
        # 无论如何，确保进度对话框被销毁
        if progress_dialog and progress_dialog.IsShown():
            progress_dialog.Destroy()

# 独立测试块 (仅在直接运行此文件时生效)
if __name__ == '__main__':
    # 模拟一个简单的logger
    class SimpleLogger:
        def info(self, msg):
            print(f"[INFO] {msg}")
        def error(self, msg, exc_info=False):
            print(f"[ERROR] {msg}")
            if exc_info:
                import traceback
                traceback.print_exc()
        def warning(self, msg):
            print(f"[WARNING] {msg}")
        def debug(self, msg):
            pass # 忽略 debug 消息

    test_logger = SimpleLogger()

    # 启动一个简单的 wx.App 以便使用 wx.MessageBox
    test_app = wx.App(False)

    print("\n--- 启动更新检查测试 ---")
    # 这里的服务器地址和端口仅用于示例，实际运行时需要指向真实的更新服务器。
    # 假设服务器IP为 "101.132.172.172", 端口为 42593
    # 模拟不同情况：
    # 1. "1.0.0" -> "1.0.1" (有更新)
    # 2. "1.0.1" -> "1.0.1" (无更新)

    print("\n测试场景1: 检查有新版本 (当前版本 1.0.0)")
    # 假设服务器上的最新版本是 "1.0.1"，并提供更新日志
    result1 = check_for_updates("1.0.0", "127.0.0.1", 42593, test_logger) # 请将 127.0.0.1 替换为实际服务器 IP

    if result1 == UpdateStatus.UPDATED_AND_EXITING:
        print("测试1结果: 检测到新版本，已启动安装程序，预期旧程序退出。")
    elif result1 == UpdateStatus.NO_UPDATE:
        print("测试1结果: 无新版本，预期程序继续运行。")
    elif result1 == UpdateStatus.UPDATE_CANCELLED:
        print("测试1结果: 用户取消了更新，预期旧程序退出。")
    elif result1 == UpdateStatus.UPDATE_FAILED:
        print("测试1结果: 更新失败，预期旧程序退出。")
    else:
        print(f"测试1结果: 返回未知状态 {result1}")

    print("\n测试场景2: 检查无新版本 (当前版本 1.0.1)")
    result2 = check_for_updates("1.0.1", "127.0.0.1", 42593, test_logger) # 请将 127.0.0.1 替换为实际服务器 IP

    if result2 == UpdateStatus.UPDATED_AND_EXITING:
        print("测试2结果: 检测到新版本，已启动安装程序，预期旧程序退出。")
    elif result2 == UpdateStatus.NO_UPDATE:
        print("测试2结果: 无新版本，预期程序继续运行。")
    elif result2 == UpdateStatus.UPDATE_CANCELLED:
        print("测试2结果: 用户取消了更新，预期旧程序退出。")
    elif result2 == UpdateStatus.UPDATE_FAILED:
        print("测试2结果: 更新失败，预期旧程序退出。")
    else:
        print(f"测试2结果: 返回未知状态 {result2}")

    # 销毁 wx.App
    del test_app