import socket
import json
import os
import sys
import threading
import time
from distutils.version import LooseVersion # 用于规范版本比较

# 服务器配置
HOST = '0.0.0.0'  # 监听所有可用的网络接口
PORT = 42593      # 用于更新服务的端口

# 假设服务器脚本与 app.exe 和 version.json 在同一目录下
UPDATE_DIR = os.path.dirname(os.path.abspath(__file__))
LATEST_APP_INSTALLER = os.path.join(UPDATE_DIR, 'app.exe')  # 最新应用程序的安装程序
VERSION_FILE = os.path.join(UPDATE_DIR, 'version.json')    # 包含版本信息的文件

BUFFER_SIZE = 4096 # 网络通信缓冲区大小

def get_latest_version_info():
    """
    从 version.json 文件中读取最新版本信息。
    该文件应包含 'latest_version' (str), 'file_size' (int), 'release_notes' (str), 'release_date' (str)。
    """
    if not os.path.exists(VERSION_FILE):
        print(f"错误: 版本文件 '{VERSION_FILE}' 未找到。", file=sys.stderr)
        return None
    try:
        with open(VERSION_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # 验证 essential 字段是否存在
            if not all(k in data for k in ["latest_version", "file_size", "release_notes", "release_date"]):
                print(f"错误: '{VERSION_FILE}' 文件缺少必要字段 (latest_version, file_size, release_notes, release_date)。", file=sys.stderr)
                return None
            return data
    except json.JSONDecodeError:
        print(f"错误: '{VERSION_FILE}' 文件格式不正确，无法解析为JSON。", file=sys.stderr)
        return None
    except Exception as e:
        print(f"读取 '{VERSION_FILE}' 时发生意外错误: {e}", file=sys.stderr)
        return None

def handle_client(conn, addr):
    """
    处理单个客户端连接。接收客户端的当前版本，并根据服务器上的最新版本信息，
    返回是否需要更新、最新版本号、文件大小、更新日志等信息。
    如果需要更新，则发送安装程序文件。
    """
    print(f"接受到来自 {addr} 的连接。")
    
    try:
        # 接收客户端请求，直到收到换行符作为消息结束标志
        request_bytes = b''
        while b'\n' not in request_bytes:
            chunk = conn.recv(BUFFER_SIZE)
            if not chunk:
                raise EOFError("客户端在发送请求时断开连接。")
            request_bytes += chunk
        
        # 解析请求
        request_str = request_bytes.split(b'\n', 1)[0].decode('utf-8')
        request_data = json.loads(request_str)
        
        action = request_data.get("action")
        client_version_str = request_data.get("current_version")
        
        print(f"收到来自 {addr} 的请求: action='{action}', current_version='{client_version_str}'")
        
        # 验证请求是否有效
        if action != "check_update" or not client_version_str:
            response = {"status": "error", "message": "无效的请求格式。"}
            conn.sendall(json.dumps(response).encode('utf-8') + b'\n')
            print(f"向 {addr} 发送错误响应: 无效请求。")
            return

        # 转换客户端版本号以供比较
        try:
            client_version = LooseVersion(client_version_str)
        except Exception as e:
            response = {"status": "error", "message": f"无效的客户端版本号格式: {client_version_str}"}
            conn.sendall(json.dumps(response).encode('utf-8') + b'\n')
            print(f"向 {addr} 发送错误响应: 无效版本号 '{client_version_str}'. 错误: {e}")
            return
        
        # 获取服务器的最新版本信息
        latest_info = get_latest_version_info()
        if not latest_info:
            response = {"status": "error", "message": "服务器未能加载最新版本信息。"}
            conn.sendall(json.dumps(response).encode('utf-8') + b'\n')
            print(f"向 {addr} 发送错误响应: 无法获取服务器版本信息。")
            return
            
        server_latest_version_str = latest_info["latest_version"]
        server_latest_version = LooseVersion(server_latest_version_str)
        
        release_notes = latest_info.get("release_notes", "无更新日志。")
        release_date = latest_info.get("release_date", "未知日期")
        
        # 比较版本号
        if client_version < server_latest_version:
            # 客户端版本过旧，需要更新
            if not os.path.exists(LATEST_APP_INSTALLER):
                response = {"status": "error", "message": f"服务器上的更新文件 '{LATEST_APP_INSTALLER}' 不存在。"}
                conn.sendall(json.dumps(response).encode('utf-8') + b'\n')
                print(f"向 {addr} 发送错误响应: 更新文件不存在。")
                return

            file_size = os.path.getsize(LATEST_APP_INSTALLER)
            
            # 构建响应，包含更新信息
            response_payload = {
                "status": "update_available",
                "latest_version": server_latest_version_str,
                "file_size": file_size,
                "release_notes": release_notes,
                "release_date": release_date
            }
            
            # 先发送包含文件元数据的JSON响应，然后发送实际文件内容
            conn.sendall(json.dumps(response_payload).encode('utf-8') + b'\n')
            print(f"客户端 {addr} 需要更新。最新版本: {server_latest_version_str}. 文件大小: {file_size} 字节。")
            
            # 发送安装程序文件
            print(f"正在发送安装程序: {LATEST_APP_INSTALLER}...")
            with open(LATEST_APP_INSTALLER, 'rb') as f:
                while True:
                    bytes_read = f.read(BUFFER_SIZE)
                    if not bytes_read:
                        break # 文件已读完
                    conn.sendall(bytes_read)
            print(f"安装程序 '{LATEST_APP_INSTALLER}' 已成功发送到 {addr}。")
            
        else:
            # 客户端版本已经是最新或更高
            response = {"status": "no_update", "message": "您已安装最新版本。"}
            conn.sendall(json.dumps(response).encode('utf-8') + b'\n')
            print(f"客户端 {addr} 的版本 ({client_version_str}) 已是最新。")

    except json.JSONDecodeError:
        print(f"警告: 客户端 {addr} 发送了格式错误的JSON。", file=sys.stderr)
    except ConnectionResetError:
        print(f"警告: 客户端 {addr} 在通信过程中重置了连接。", file=sys.stderr)
    except EOFError:
        print(f"警告: 客户端 {addr} 在接收数据时断开连接。", file=sys.stderr)
    except FileNotFoundError:
        print(f"错误: 尝试访问不存在的文件（可能是安装程序或版本文件）。", file=sys.stderr)
    except OSError as e:
        print(f"处理客户端 {addr} 时发生操作系统错误: {e}", file=sys.stderr)
    except Exception as e:
        print(f"处理客户端 {addr} 时发生未知错误: {e}", file=sys.stderr)
    finally:
        conn.close() # 确保每次连接后都关闭套接字
        print(f"与 {addr} 的连接已关闭。")

def start_server():
    """
    启动网络服务器，监听客户端连接，并为每个连接创建新的线程来处理。
    """
    try:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # SO_REUSEADDR 允许服务器立即重用TIME_WAIT状态的端口，避免服务器重启时端口被占用
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((HOST, PORT))
        server_socket.listen(5) # 允许最多5个挂起的连接
        print(f"更新服务器已启动，正在监听 {HOST}:{PORT}...")
        
        while True:
            # 接受客户端连接
            conn, addr = server_socket.accept()
            
            # 为每个客户端连接创建一个新线程
            client_handler_thread = threading.Thread(target=handle_client, args=(conn, addr))
            client_handler_thread.daemon = True # 设置为守护线程，允许主程序退出时该线程也被终止
            client_handler_thread.start()
            
    except OSError as e:
        print(f"启动服务器时发生错误: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"发生未知错误，服务器停止: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if 'server_socket' in locals() and server_socket:
            server_socket.close()
            print("服务器套接字已关闭。")

if __name__ == '__main__':
    # 启动前进行必要的文件检查
    if not os.path.exists(LATEST_APP_INSTALLER):
        print(f"错误: 找不到最新安装程序 '{LATEST_APP_INSTALLER}'。请确保文件存在。", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(VERSION_FILE):
        print(f"错误: 找不到版本信息文件 '{VERSION_FILE}'。请确保文件存在。", file=sys.stderr)
        sys.exit(1)
    
    # 启动服务器
    start_server()