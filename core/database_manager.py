import os
import sqlite3
import sys
import atexit
from utils.logger_config import logger

# 获取程序运行目录
if getattr(sys, 'frozen', False):
    # PyInstaller 打包后的程序
    APPLICATION_ROOT = os.path.dirname(sys.executable)
else:
    # 未打包的开发环境
    APPLICATION_ROOT = os.path.dirname(os.path.abspath(sys.argv[0]))

DEFAULT_DB_FILE = "audio_labels.db"
DB_CONFIG_FILE = "db_path.dat" # 存储数据库路径的配置文件

class DatabaseManager:
    def __init__(self):
        self.db_path = self._get_database_path()
        self.conn = None
        self.cursor = None
        self._connect()
        self._create_tables()
        atexit.register(self.close_connection) # 注册程序退出时关闭数据库连接

    def _get_database_path(self):
        """
        从配置文件或默认位置获取数据库文件路径。
        如果配置文件不存在或无效，则使用默认位置并创建配置文件。
        """
        config_file_path = os.path.join(APPLICATION_ROOT, DB_CONFIG_FILE)
        db_path = os.path.join(APPLICATION_ROOT, DEFAULT_DB_FILE) # 默认路径

        if os.path.exists(config_file_path):
            try:
                with open(config_file_path, 'r', encoding='utf-8') as f:
                    configured_path = f.read().strip()
                    if configured_path and os.path.isabs(configured_path):
                        # 验证路径是否可写，如果目录不存在则尝试创建
                        configured_dir = os.path.dirname(configured_path)
                        if not os.path.exists(configured_dir):
                            os.makedirs(configured_dir, exist_ok=True)
                            logger.info(f"创建数据库目录: {configured_dir}")
                        db_path = configured_path
                        logger.info(f"从配置文件 '{DB_CONFIG_FILE}' 加载数据库路径: '{db_path}'")
                    else:
                        logger.warning(f"配置文件 '{DB_CONFIG_FILE}' 中的数据库路径无效或非绝对路径。将使用默认路径。")
            except Exception as e:
                logger.error(f"读取数据库配置文件 '{DB_CONFIG_FILE}' 失败: {e}。将使用默认路径。", exc_info=True)

        # 确保数据库文件所在的目录存在
        db_dir = os.path.dirname(db_path)
        if not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            logger.info(f"创建数据库目录: {db_dir}")

        # 如果配置文件不存在或加载失败（回退到默认路径），则保存实际使用的路径到配置文件
        if not os.path.exists(config_file_path) or os.path.dirname(db_path) != APPLICATION_ROOT: # 检查是否回退到默认路径
            try:
                with open(config_file_path, 'w', encoding='utf-8') as f:
                    f.write(db_path)
                logger.info(f"已将数据库路径 '{db_path}' 保存到配置文件 '{DB_CONFIG_FILE}'。")
            except Exception as e:
                logger.error(f"保存数据库路径到配置文件 '{DB_CONFIG_FILE}' 失败: {e}", exc_info=True)

        return db_path

    def _connect(self):
        """连接到SQLite数据库。"""
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row # 使查询结果可以通过字典键访问
            self.cursor = self.conn.cursor()
            logger.info(f"成功连接到数据库: {self.db_path}")
        except sqlite3.Error as e:
            logger.error(f"连接数据库失败: {e}", exc_info=True)
            # 尝试通过主窗口显示错误，如果 _main_frame_ref 可用的话
            try:
                import core.audio_manager # 避免循环导入
                if hasattr(core.audio_manager, '_main_frame_ref') and core.audio_manager._main_frame_ref:
                    import wx
                    wx.CallAfter(core.audio_manager._main_frame_ref.show_error_message,
                                f"无法连接到音频标签数据库。\n请检查文件权限或路径设置。\n错误: {e}",
                                "数据库连接失败")
            except Exception as gui_err:
                logger.error(f"在显示数据库连接错误时发生错误: {gui_err}")
            sys.exit(1) # 如果数据库无法连接，则退出程序

    def _create_tables(self):
        """创建数据库表（如果不存在）。"""
        try:
            # audios 表存储音频路径
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS audios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL UNIQUE
                )
            ''')
            # labels 表存储标签名称
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS labels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE
                )
            ''')
            # audio_labels 表存储音频和标签之间的多对多关系
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS audio_labels (
                    audio_id INTEGER,
                    label_id INTEGER,
                    PRIMARY KEY (audio_id, label_id),
                    FOREIGN KEY (audio_id) REFERENCES audios(id) ON DELETE CASCADE,
                    FOREIGN KEY (label_id) REFERENCES labels(id) ON DELETE CASCADE
                )
            ''')
            self.conn.commit()
            logger.info("数据库表已创建或已存在。")
        except sqlite3.Error as e:
            logger.error(f"创建数据库表失败: {e}", exc_info=True)
            # 同理，如果创建表失败，也尝试通过主窗口显示错误
            try:
                import core.audio_manager
                if hasattr(core.audio_manager, '_main_frame_ref') and core.audio_manager._main_frame_ref:
                    import wx
                    wx.CallAfter(core.audio_manager._main_frame_ref.show_error_message,
                                f"无法创建数据库表。\n错误: {e}",
                                "数据库初始化失败")
            except Exception as gui_err:
                logger.error(f"在显示数据库表创建错误时发生错误: {gui_err}")
            sys.exit(1)

    def add_audio_label(self, audio_path, label_name):
        """
        为音频文件添加一个或多个标签。
        如果音频路径或标签不存在，则自动创建。
        """
        try:
            self.cursor.execute("INSERT OR IGNORE INTO audios (path) VALUES (?)", (audio_path,))
            audio_id_row = self.cursor.execute("SELECT id FROM audios WHERE path = ?", (audio_path,)).fetchone()
            if not audio_id_row:
                logger.error(f"无法获取或创建音频ID: {audio_path}")
                return False
            audio_id = audio_id_row[0]

            self.cursor.execute("INSERT OR IGNORE INTO labels (name) VALUES (?)", (label_name,))
            label_id_row = self.cursor.execute("SELECT id FROM labels WHERE name = ?", (label_name,)).fetchone()
            if not label_id_row:
                logger.error(f"无法获取或创建标签ID: {label_name}")
                return False
            label_id = label_id_row[0]

            self.cursor.execute("INSERT OR IGNORE INTO audio_labels (audio_id, label_id) VALUES (?, ?)", (audio_id, label_id))
            self.conn.commit()
            logger.debug(f"已为音频 '{os.path.basename(audio_path)}' 添加标签 '{label_name}'。")
            return True
        except sqlite3.Error as e:
            logger.error(f"添加音频标签失败: {e} (Path: {audio_path}, Label: {label_name})", exc_info=True)
            return False

    def get_audios_by_label(self, label_name):
        """
        根据标签名称搜索所有匹配的音频文件路径。
        支持模糊搜索。
        """
        try:
            # 使用 LIKE 进行模糊匹配，并将搜索词前后加上 %
            search_term = f"%{label_name.strip()}%"
            self.cursor.execute('''
                SELECT DISTINCT a.path
                FROM audios a
                JOIN audio_labels al ON a.id = al.audio_id
                JOIN labels l ON l.id = al.label_id
                WHERE l.name LIKE ?
            ''', (search_term,))
            results = [row['path'] for row in self.cursor.fetchall()]
            logger.debug(f"通过标签 '{label_name}' 搜索到 {len(results)} 个音频文件。")
            return results
        except sqlite3.Error as e:
            logger.error(f"根据标签搜索音频失败: {e} (Label: {label_name})", exc_info=True)
            return []

    def get_labels_for_audio(self, audio_path):
        """
        获取指定音频文件的所有标签。
        """
        try:
            self.cursor.execute('''
                SELECT l.name
                FROM labels l
                JOIN audio_labels al ON l.id = al.label_id
                JOIN audios a ON a.id = al.audio_id
                WHERE a.path = ?
            ''', (audio_path,))
            results = [row['name'] for row in self.cursor.fetchall()]
            return results
        except sqlite3.Error as e:
            logger.error(f"获取音频标签失败: {e} (Path: {audio_path})", exc_info=True)
            return []

    def close_connection(self):
        """关闭数据库连接。"""
        if self.conn:
            self.conn.close()
            self.conn = None
            self.cursor = None
            logger.info("数据库连接已关闭。")

# 简单的测试用例
if __name__ == '__main__':
    # 模拟 logger_config.py 提供的 logger
    import logging
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # 模拟 main_frame 引用，以便在错误时显示消息
    class MockMainFrame:
        def show_error_message(self, msg, title):
            print(f"MockMainFrame Error [{title}]: {msg}")
        def update_status_message(self, msg):
            print(f"MockMainFrame Status: {msg}")

    # 将模拟的 frame 设置到 audio_manager
    class MockAudioManager:
        _main_frame_ref = MockMainFrame()

    # 导入 real audio_manager, 但仅用于访问 _main_frame_ref 属性 (如果存在)
    # 避免直接修改全局状态, 仅模拟其行为.
    try:
        import core.audio_manager
        # 检查 core.audio_manager 是否已经定义了 _main_frame_ref
        if hasattr(core.audio_manager, '_main_frame_ref'):
            core.audio_manager._main_frame_ref = MockAudioManager()._main_frame_ref
        else:
            # 如果没有, 动态添加一个 (如果需要的话, 但通常应该预先定义)
            # core.audio_manager._main_frame_ref = MockAudioManager()._main_frame_ref
            pass # 在此情况下, 假设 _main_frame_ref 不存在, 错误消息将不会通过GUI显示
    except ImportError:
        logger.warning("core.audio_manager 模块未找到，GUI错误消息将不会被模拟显示。")
        # 如果 core.audio_manager 不存在, 那么 _main_frame_ref 也不可能存在
        pass


    db_manager = DatabaseManager()

    # 测试添加标签
    print("\n--- Testing Add Label ---")
    db_manager.add_audio_label("C:\\Audios\\song1.mp3", "Rock")
    db_manager.add_audio_label("C:\\Audios\\song1.mp3", "Classic")
    db_manager.add_audio_label("D:\\Music\\jazz_track.flac", "Jazz")
    db_manager.add_audio_label("C:\\Audios\\song2.mp3", "Rock")
    db_manager.add_audio_label("E:\\Sounds\\effect1.wav", "Sound Effect")
    db_manager.add_audio_label("E:\\Sounds\\effect1.wav", "Sci-Fi")
    db_manager.add_audio_label("C:\\Audios\\song1.mp3", "Rock") # 重复添加

    # 测试获取标签
    print("\n--- Testing Get Labels for Audio ---")
    print(f"Labels for C:\\Audios\\song1.mp3: {db_manager.get_labels_for_audio('C:\\Audios\\song1.mp3')}")
    print(f"Labels for D:\\Music\\jazz_track.flac: {db_manager.get_labels_for_audio('D:\\Music\\jazz_track.flac')}")
    print(f"Labels for E:\\Sounds\\effect1.wav: {db_manager.get_labels_for_audio('E:\\Sounds\\effect1.wav')}")

    # 测试搜索标签
    print("\n--- Testing Search by Label ---")
    print(f"Audios with 'Rock': {db_manager.get_audios_by_label('Rock')}")
    print(f"Audios with 'jazz': {db_manager.get_audios_by_label('jazz')}")
    print(f"Audios with 'effect': {db_manager.get_audios_by_label('effect')}")
    print(f"Audios with 'nonexistent': {db_manager.get_audios_by_label('nonexistent')}")

    # 测试模糊搜索
    print("\n--- Testing Fuzzy Search by Label ---")
    print(f"Audios with 'roc': {db_manager.get_audios_by_label('roc')}") # 应该能搜到 'Rock'
    print(f"Audios with 'sc': {db_manager.get_audios_by_label('sc')}") # 应该能搜到 'Sci-Fi'

    db_manager.close_connection()