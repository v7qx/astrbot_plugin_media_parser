import asyncio
import time
from typing import Dict

from .config_manager import DedupConfig
from .logger import logger

class DedupGuard:
    def __init__(self, config: DedupConfig):
        self.config = config
        # group_id -> last competitor message timestamp
        self._competitor_msg_times: Dict[str, float] = {}
        # "{group_id}_{url}" -> last parsed timestamp
        self._url_cooldowns: Dict[str, float] = {}
    
    def is_group_enabled(self, group_id: str) -> bool:
        """判断某个群是否启用互斥"""
        if not self.config.enable:
            return False
        if not group_id:
            # 私聊不启用互斥
            return False
        if not self.config.group:
            # 列表为空表示所有群聊启用
            return True
        return str(group_id) in self.config.group

    def is_competitor_message(self, sender_id: str) -> bool:
        """判断消息是否来自互斥机器人"""
        if not self.config.competitor_bot_ids:
            return False
        return str(sender_id) in self.config.competitor_bot_ids

    def record_competitor_message(self, group_id: str):
        """记录互斥机器人发言时间"""
        if not group_id:
            return
        self._competitor_msg_times[str(group_id)] = time.time()
        self._cleanup()
        
    def _normalize_url(self, url: str) -> str:
        """简单清理URL，去空白和末尾标点"""
        url = url.strip()
        while url and url[-1] in ",.，。":
            url = url[:-1]
        return url
        
    def is_url_cooldown(self, group_id: str, url: str) -> bool:
        """判断URL是否处于冷却期"""
        if self.config.url_cooldown_seconds <= 0:
            return False
        
        group_id_str = str(group_id) if group_id else "private"
        url_norm = self._normalize_url(url)
        key = f"{group_id_str}_{url_norm}"
        
        last_time = self._url_cooldowns.get(key, 0)
        return (time.time() - last_time) < self.config.url_cooldown_seconds

    def get_url_cooldown_remain(self, group_id: str, url: str) -> float:
        """获取URL剩余冷却时间（秒）"""
        if self.config.url_cooldown_seconds <= 0:
            return 0.0
            
        group_id_str = str(group_id) if group_id else "private"
        url_norm = self._normalize_url(url)
        key = f"{group_id_str}_{url_norm}"
        
        last_time = self._url_cooldowns.get(key, 0)
        elapsed = time.time() - last_time
        if elapsed < self.config.url_cooldown_seconds:
            return self.config.url_cooldown_seconds - elapsed
        return 0.0

    def record_url_cooldown(self, group_id: str, url: str):
        """记录URL解析时间"""
        if self.config.url_cooldown_seconds <= 0:
            return
            
        group_id_str = str(group_id) if group_id else "private"
        url_norm = self._normalize_url(url)
        key = f"{group_id_str}_{url_norm}"
        
        self._url_cooldowns[key] = time.time()
        self._cleanup()

    async def wait_and_check(self, group_id: str) -> bool:
        """
        等待配置的秒数，返回等待期间是否检测到互斥机器人响应。
        返回 True 表示互斥机器人已响应，应取消解析；False 表示继续。
        """
        if not self.is_group_enabled(group_id):
            return False
        if not self.config.competitor_bot_ids:
            return False
        if self.config.wait_seconds <= 0:
            return False

        group_id_str = str(group_id)
        start_time = time.time()
        
        await asyncio.sleep(self.config.wait_seconds)
        
        last_competitor_time = self._competitor_msg_times.get(group_id_str, 0)
        if last_competitor_time >= start_time:
            return True
            
        return False
        
    def _cleanup(self):
        """清理过期记录，避免内存泄漏"""
        now = time.time()
        
        # 清理过期的 competitor_msg_times（超过 wait_seconds 的 2 倍就没必要留了，这里放宽到 10 倍以策安全，或者固定 300 秒）
        retention = max(300, self.config.wait_seconds * 10)
        expired_groups = [g for g, t in self._competitor_msg_times.items() if (now - t) > retention]
        for g in expired_groups:
            del self._competitor_msg_times[g]
            
        # 清理过期的 url_cooldowns
        if self.config.url_cooldown_seconds > 0:
            expired_urls = [k for k, t in self._url_cooldowns.items() if (now - t) > self.config.url_cooldown_seconds]
            for k in expired_urls:
                del self._url_cooldowns[k]
