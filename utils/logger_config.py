import logging
import sys

# --- 日志配置
logger = logging.getLogger('InstantAudioPreviewer')
# 确保在生产环境中将级别设置为 INFO 或 WARNING，而在开发中设置为 DEBUG
logger.setLevel(logging.DEBUG) # 暂时设置为 DEBUG 以便调试朗读功能相关日志

# 确保不会重复添加 handler
if not logger.handlers:
    console_handler = logging.StreamHandler(sys.stdout)
    # console_handler.setLevel(logging.INFO) # 控制台输出级别可以单独设置
    console_handler.setLevel(logging.DEBUG) # 暂时设置为 DEBUG
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s') # 增加了 %(name)s 方便区分模块
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

# 可以添加文件日志 handler
# file_handler = logging.FileHandler('app.log', encoding='utf-8')
# file_handler.setLevel(logging.DEBUG)
# file_handler.setFormatter(formatter)
# logger.addHandler(file_handler)