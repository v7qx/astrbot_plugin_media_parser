"""消息发送封装，统一不同会话场景下的发送行为。"""
from typing import Any, List, Optional

from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Nodes, Plain, Image, Node, Video

from .node_builder import is_pure_image_gallery
from ..logger import logger


class MessageSender:

    """消息发送器，封装统一的私聊/群聊发送接口。"""

    FORWARD_CHUNK_SIZE = 8
    DIRECT_IMAGE_BATCH_SIZE = 4

    def get_sender_info(self, event: AstrMessageEvent) -> tuple:
        """获取发送者信息

        Args:
            event: 消息事件对象

        Returns:
            包含发送者名称和ID的元组 (sender_name, sender_id)
        """
        sender_name = "视频解析bot"
        platform = event.get_platform_name()
        sender_id = event.get_self_id()
        if platform not in ("wechatpadpro", "webchat", "gewechat"):
            try:
                sender_id = int(sender_id)
            except (ValueError, TypeError):
                sender_id = 10000
        return sender_name, sender_id

    async def send_packed_results(
        self,
        event: AstrMessageEvent,
        link_metadata: list,
        sender_name: str,
        sender_id: Any,
        large_video_threshold_mb: float = 0.0
    ):
        """发送打包的结果（使用Nodes）

        Args:
            event: 消息事件对象
            link_metadata: 链接元数据列表
            sender_name: 发送者名称
            sender_id: 发送者ID
            large_video_threshold_mb: 大视频阈值(MB)
        """
        normal_metadata = [
            meta for meta in link_metadata if meta.get('is_normal', True)
        ]
        large_media_metadata = [
            meta for meta in link_metadata if meta.get('is_large_media', False)
        ]
        large_media_link_nodes = [
            meta['link_nodes'] for meta in large_media_metadata
        ]
        separator = "-------------------------------------"

        if normal_metadata:
            await self._send_forward_results(
                event,
                normal_metadata,
                sender_name,
                sender_id,
                separator,
            )

        if large_media_link_nodes:
            await self.send_large_media_results(
                event,
                large_media_metadata,
                large_media_link_nodes,
                sender_name,
                sender_id,
                large_video_threshold_mb
            )

    async def _send_forward_results(
        self,
        event: AstrMessageEvent,
        normal_metadata: list,
        sender_name: str,
        sender_id: Any,
        separator: str,
    ) -> None:
            forward_nodes = []
            forward_items = []
            direct_nodes = []
            for link_idx, meta in enumerate(normal_metadata):
                link_nodes = meta.get('link_nodes', [])
                metadata = meta.get('metadata', {}) or {}
                image_index = 0
                video_index = 0
                for node in link_nodes:
                    if node is None:
                        continue
                    if isinstance(node, Plain):
                        # NapCat/QQ 对“一个转发子消息里包含多张图片”的兼容性较差；
                        # 每个文本或图片单独作为一个 Node 更接近 OneBot 的 node_custom 用法。
                        forward_nodes.append(Node(
                            name=sender_name,
                            uin=sender_id,
                            content=[node],
                        ))
                        forward_items.append(("text", self._plain_text(node)))
                    elif isinstance(node, Image):
                        image_file = self._get_forward_image_file(
                            metadata,
                            image_index,
                        )
                        image_index += 1
                        if not image_file:
                            direct_nodes.append(node)
                            continue
                        forward_image = self._build_forward_image(image_file)
                        if forward_image is None:
                            direct_nodes.append(node)
                            continue
                        forward_nodes.append(Node(
                            name=sender_name,
                            uin=sender_id,
                            content=[forward_image],
                        ))
                        forward_items.append(("image", image_file))
                    elif isinstance(node, Video):
                        video_file = self._get_forward_video_file(
                            metadata,
                            video_index,
                        )
                        video_index += 1
                        if not video_file:
                            direct_nodes.append(node)
                            continue
                        forward_video = self._build_forward_video(video_file)
                        if forward_video is None:
                            direct_nodes.append(node)
                            continue
                        forward_nodes.append(Node(
                            name=sender_name,
                            uin=sender_id,
                            content=[forward_video],
                        ))
                        forward_items.append(("video", video_file))
                    else:
                        direct_nodes.append(node)
                if link_idx < len(normal_metadata) - 1:
                    forward_nodes.append(Node(
                        name=sender_name,
                        uin=sender_id,
                        content=[Plain(separator)],
                    ))
                    forward_items.append(("text", separator))
            if forward_nodes:
                sent = await self._send_onebot_forward_items(
                    event,
                    forward_items,
                    sender_name,
                    sender_id,
                )
                if not sent:
                    await self._send_forward_nodes(event, forward_nodes)
            for node in direct_nodes:
                try:
                    await event.send(event.chain_result([node]))
                except Exception as e:
                    logger.warning(f"发送非转发节点失败: {e}")

    async def send_large_media_results(
        self,
        event: AstrMessageEvent,
        metadata: list,
        link_nodes_list: list,
        sender_name: str,
        sender_id: Any,
        large_video_threshold_mb: float = 0.0
    ):
        """发送大媒体结果（单独发送）

        Args:
            event: 消息事件对象
            metadata: 元数据列表
            link_nodes_list: 链接节点列表
            sender_name: 发送者名称
            sender_id: 发送者ID
            large_video_threshold_mb: 大视频阈值(MB)
        """
        separator = "-------------------------------------"
        threshold_mb = (
            int(large_video_threshold_mb)
            if large_video_threshold_mb > 0
            else 50
        )
        notice_text = (
            f"⚠️ 链接中包含超过{threshold_mb}MB的视频时"
            f"将单独发送所有媒体"
        )
        await event.send(event.plain_result(notice_text))
        for link_idx, link_nodes in enumerate(link_nodes_list):
            for node in link_nodes:
                if node is not None:
                    try:
                        await event.send(event.chain_result([node]))
                    except Exception as e:
                        logger.warning(f"发送大媒体节点失败: {e}")
            if link_idx < len(link_nodes_list) - 1:
                try:
                    await event.send(event.plain_result(separator))
                except Exception as e:
                    logger.warning(f"发送分隔符失败: {e}")

    async def send_unpacked_results(
        self,
        event: AstrMessageEvent,
        all_link_nodes: list
    ):
        """发送非打包的结果（独立发送）

        Args:
            event: 消息事件对象
            all_link_nodes: 所有链接节点列表
        """
        separator = "-------------------------------------"
        for link_idx, link_nodes in enumerate(all_link_nodes):
            if is_pure_image_gallery(link_nodes):
                texts = [
                    node for node in link_nodes
                    if isinstance(node, Plain)
                ]
                images = [
                    node for node in link_nodes
                    if isinstance(node, Image)
                ]
                for text in texts:
                    await event.send(event.chain_result([text]))
                if images:
                    await event.send(event.chain_result(images))
            else:
                for node in link_nodes:
                    if node is not None:
                        try:
                            await event.send(event.chain_result([node]))
                        except Exception as e:
                            logger.warning(f"发送节点失败: {e}")
            if link_idx < len(all_link_nodes) - 1:
                await event.send(event.plain_result(separator))

    async def _send_private_direct_results(
        self,
        event: AstrMessageEvent,
        normal_metadata: list,
    ) -> None:
        """NapCat 私聊合并转发图片上传易失败，私聊改为普通分组发送。"""
        separator = "-------------------------------------"
        for link_idx, meta in enumerate(normal_metadata):
            link_nodes = meta.get('link_nodes', [])
            batch = []
            for node in link_nodes:
                if node is None:
                    continue
                if isinstance(node, Plain):
                    if batch:
                        await event.send(event.chain_result(batch))
                        batch = []
                    await event.send(event.chain_result([node]))
                elif isinstance(node, Image):
                    batch.append(node)
                    if self.DIRECT_IMAGE_BATCH_SIZE > 0 and len(batch) >= self.DIRECT_IMAGE_BATCH_SIZE:
                        await event.send(event.chain_result(batch))
                        batch = []
                else:
                    if batch:
                        await event.send(event.chain_result(batch))
                        batch = []
                    await event.send(event.chain_result([node]))
            if batch:
                await event.send(event.chain_result(batch))
            if link_idx < len(normal_metadata) - 1:
                await event.send(event.plain_result(separator))

    async def _send_forward_nodes(
        self,
        event: AstrMessageEvent,
        nodes: List[Node],
    ) -> None:
        """按批发送合并转发节点，降低 QQ/NapCat 对大转发的解析压力。"""
        chunk_size = self.FORWARD_CHUNK_SIZE if self.FORWARD_CHUNK_SIZE > 0 else len(nodes)
        if chunk_size == 0:
            chunk_size = 1
        for start in range(0, len(nodes), chunk_size):
            chunk = nodes[start:start + chunk_size]
            await event.send(event.chain_result([Nodes(chunk)]))

    @staticmethod
    def _get_forward_image_file(metadata: dict, image_index: int) -> str:
        """合并转发中优先使用 URL 图片，避免本地 file 图片在 QQ 客户端不可查看。"""
        video_count = len(metadata.get('video_urls') or [])
        token_urls = metadata.get('file_token_urls') or []
        token_index = video_count + image_index
        if token_index < len(token_urls) and token_urls[token_index]:
            return str(token_urls[token_index]).strip()

        image_urls = metadata.get('image_urls') or []
        if image_index >= len(image_urls):
            return ""
        url_list = image_urls[image_index]
        if not isinstance(url_list, list) or not url_list:
            return ""
        return str(url_list[0] or "").strip()

    @staticmethod
    def _build_forward_image(image_file: str) -> Optional[Image]:
        try:
            return Image.fromURL(image_file)
        except Exception as e:
            logger.warning(f"构建转发URL图片失败: {e}")
            return None

    @staticmethod
    def _get_forward_video_file(metadata: dict, video_index: int) -> str:
        token_urls = metadata.get('file_token_urls') or []
        if video_index < len(token_urls) and token_urls[video_index]:
            return str(token_urls[video_index]).strip()

        video_urls = metadata.get('video_urls') or []
        if video_index < len(video_urls):
            url_list = video_urls[video_index]
            if isinstance(url_list, list) and url_list:
                return str(url_list[0] or "").strip()
        
        file_paths = metadata.get('file_paths') or []
        if video_index < len(file_paths) and file_paths[video_index]:
            return str(file_paths[video_index]).strip()
        
        return ""

    @staticmethod
    def _build_forward_video(video_file: str) -> Optional[Video]:
        try:
            if video_file.startswith("http"):
                return Video.fromURL(video_file)
            else:
                return Video.fromFileSystem(video_file)
        except Exception as e:
            logger.warning(f"构建转发视频节点失败: {e}")
            return None

    async def _send_onebot_forward_items(
        self,
        event: AstrMessageEvent,
        items: list,
        sender_name: str,
        sender_id: Any,
    ) -> bool:
        """aiocqhttp/NapCat 下直接调用 OneBot 合并转发 API，贴近 nonebot 实现。"""
        if not items or event.get_platform_name() != "aiocqhttp":
            return False
        bot = getattr(event, "bot", None)
        if bot is None:
            return False

        message_chunks = self._build_onebot_forward_message_chunks(
            items,
            sender_name,
            sender_id,
        )
        if not message_chunks:
            return False

        try:
            for messages in message_chunks:
                if event.is_private_chat():
                    await bot.send_private_forward_msg(
                        user_id=int(event.get_sender_id()),
                        messages=messages,
                    )
                else:
                    await bot.send_group_forward_msg(
                        group_id=int(event.get_group_id()),
                        messages=messages,
                    )
            return True
        except Exception as e:
            logger.warning(f"OneBot合并转发直调失败，回退AstrBot Nodes: {e}")
            return False

    def _build_onebot_forward_message_chunks(
        self,
        items: list,
        sender_name: str,
        sender_id: Any,
    ) -> list:
        chunks = []
        chunk_size = self.FORWARD_CHUNK_SIZE if self.FORWARD_CHUNK_SIZE > 0 else len(items)
        if chunk_size == 0:
            chunk_size = 1
        for start in range(0, len(items), chunk_size):
            messages = []
            for kind, value in items[start:start + chunk_size]:
                segment = self._build_onebot_segment(kind, value)
                if not segment:
                    continue
                messages.append({
                    "type": "node",
                    "data": {
                        "name": sender_name,
                        "uin": str(sender_id),
                        "content": [segment],
                    },
                })
            if messages:
                chunks.append(messages)
        return chunks

    @staticmethod
    def _build_onebot_segment(kind: str, value: Any) -> Optional[dict]:
        if kind == "text":
            text = str(value or "").strip()
            if not text:
                return None
            return {"type": "text", "data": {"text": text}}
        if kind == "image":
            file = str(value or "").strip()
            if not file:
                return None
            return {"type": "image", "data": {"file": file}}
        if kind == "video":
            file = str(value or "").strip()
            if not file:
                return None
            return {"type": "video", "data": {"file": file}}
        return None

    @staticmethod
    def _plain_text(node: Plain) -> str:
        for attr in ("text", "message", "content"):
            value = getattr(node, attr, None)
            if value:
                return str(value)
        return str(node)
