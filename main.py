"""
爆炒江湖图鉴查询插件 (astrbot-plugin-baochaojianghu)

数据源（公开静态 JSON，无鉴权）：
  - https://h5.baochaojianghu.com/data/data.min.json   (白菜菊花图鉴, 默认, ~2MB, 更新更全)
  - https://foodgame.github.io/data/data.min.json      (图鉴站, 较旧, ~1.7MB)
两者 JSON 顶层结构完全一致。

功能指令：
  /菜谱 <名称或关键词>    查询菜谱（品阶/技法/材料/售价/解锁）
  /厨师 <名称或关键词>    查询厨师（星级/技法/技能/修炼任务）
  /厨具 <名称或关键词>    查询厨具（等级/加成）
  /任务 <关键词或编号>    查询任务
  /材料 <名称或关键词>    查询材料
  /遗玉 <名称或关键词>    查询遗玉
  /bcjh源 <foodgame|baochaojianghu>   切换数据源（默认 baochaojianghu）

数据策略：插件加载 10s 后首次拉取，之后按 refresh_hours 定时刷新，内存缓存。
依赖：aiohttp（在 requirements.txt 中声明）
"""
import asyncio
from datetime import datetime, timezone

import aiohttp

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger

DATA_URLS = {
    "foodgame": "https://foodgame.github.io/data/data.min.json",
    "baochaojianghu": "https://h5.baochaojianghu.com/data/data.min.json",
}

# 单条消息最大长度（超过截断，避免刷屏）
MAX_MSG_LEN = 4000

# 技法名称
TECH_NAMES = {
    "stirfry": "炒", "boil": "煮", "knife": "切",
    "fry": "炸", "bake": "烤", "steam": "蒸",
}


def _fmt_tech(item) -> str:
    parts = []
    for key, label in TECH_NAMES.items():
        v = item.get(key, 0) or 0
        if v:
            parts.append(f"{label}{v}")
    return " ".join(parts) if parts else "-"


class BaochaoJianghuPlugin(Star):
    def __init__(self, context: Context, source: str = "baochaojianghu",
                 refresh_hours: float = 6):
        super().__init__(context)
        if source not in DATA_URLS:
            source = "baochaojianghu"
        self.source = source
        self.refresh_hours = refresh_hours
        self._data: dict = {}
        self._material_map: dict = {}
        self._data_ts: float = 0.0
        self._lock = asyncio.Lock()
        # 后台定时刷新（插件加载 10s 后首次拉取）
        asyncio.create_task(self._background_refresh())

    # ---------- 数据层 ----------
    async def _fetch(self, source: str) -> dict:
        url = DATA_URLS[source]
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def _ensure_data(self):
        now = datetime.now(timezone.utc).timestamp()
        async with self._lock:
            if not self._data or (now - self._data_ts) > self.refresh_hours * 3600:
                self._data = await self._fetch(self.source)
                self._data_ts = now
                # 材料 ID -> 名称 映射
                self._material_map = {
                    m.get("id"): m.get("name")
                    for m in self._data.get("materials", [])
                    if m.get("id") is not None
                }
                logger.info(
                    f"[bcjh] 数据已加载: {self.source}, "
                    f"菜谱 {len(self._data.get('recipes', []))}, "
                    f"厨师 {len(self._data.get('chefs', []))}, "
                    f"任务 {len(self._data.get('quests', []))}"
                )

    async def _background_refresh(self):
        await asyncio.sleep(10)
        while True:
            try:
                await self._ensure_data()
            except Exception as e:
                logger.error(f"[bcjh] 数据刷新失败: {e}")
            await asyncio.sleep(self.refresh_hours * 3600)

    # ---------- 检索 ----------
    @staticmethod
    def _search(items: list, keyword: str, limit: int = 5):
        kw = keyword.strip().lower()
        if not items:
            return []
        exact = [it for it in items if str(it.get("name", "")).strip() == keyword.strip()]
        hits = exact or [it for it in items if kw in str(it.get("name", "")).lower()]
        # 精确匹配排前
        return hits[:limit]

    # ---------- 格式化 ----------
    def _fmt_recipe(self, r) -> str:
        mats = ", ".join(
            f"{self._material_map.get(m.get('material'), m.get('material'))}x{m.get('quantity')}"
            for m in r.get("materials", [])
        ) or "-"
        guests = r.get("guests") or []
        guest_str = "/".join(g.get("guest", "?") for g in guests) if guests else "-"
        return (
            f"[菜谱] {r.get('name')}（品阶{r.get('rarity')}）\n"
            f"技法: {_fmt_tech(r)}\n"
            f"材料: {mats}\n"
            f"售价: {r.get('price')}  用时: {r.get('time')}s  日上限: {r.get('limit')}\n"
            f"解锁: {r.get('unlock', '-')}\n"
            f"贵客: {guest_str}"
        )

    def _fmt_chef(self, c) -> str:
        skill = c.get("skill") or c.get("skills") or "-"
        if isinstance(skill, (list, dict)):
            skill = str(skill)
        task = c.get("task") or c.get("quest") or "-"
        return (
            f"[厨师] {c.get('name')}（{'男' if c.get('gender') == 'male' else '女' if c.get('gender') == 'female' else c.get('gender', '?')}）\n"
            f"星级: {c.get('star', c.get('rarity', '?'))}\n"
            f"技法: {_fmt_tech(c)}\n"
            f"技能: {skill}\n"
            f"修炼任务: {task}"
        )

    def _fmt_equip(self, e) -> str:
        return (
            f"[厨具] {e.get('name')}（等级{e.get('level', '?')}）\n"
            f"加成: {e.get('buff', e.get('effect', '-'))}"
        )

    def _fmt_quest(self, q) -> str:
        idx = q.get("id", q.get("questId", "?"))
        return (
            f"[任务 #{idx}] {q.get('name', '-')}\n"
            f"{str(q.get('desc', q.get('description', '-')))[:200]}"
        )

    def _fmt_material(self, m) -> str:
        return (
            f"[材料] {m.get('name')}\n"
            f"获取: {m.get('origin', m.get('source', '-'))}"
        )

    def _fmt_amber(self, a) -> str:
        return (
            f"[遗玉] {a.get('name')}（{a.get('type', '?')}）\n"
            f"加成: {a.get('buff', a.get('effect', '-'))}"
        )

    def _query(self, key: str, keyword: str, formatter) -> str:
        items = self._data.get(key, [])
        hits = self._search(items, keyword)
        if not hits:
            return f"未找到匹配的{key}，试试更完整的关键词。"
        lines = [formatter(it) for it in hits]
        text = "\n\n".join(lines)
        if len(hits) > 1:
            text += f"\n\n共匹配 {len(hits)} 条"
        return text[:MAX_MSG_LEN]

    # ---------- 指令 ----------
    @filter.command("菜谱")
    async def cmd_recipe(self, event: AstrMessageEvent, *args):
        await self._ensure_data()
        kw = " ".join(args).strip()
        if not kw:
            yield event.plain_result("用法: /菜谱 <名称或关键词>")
            return
        yield event.plain_result(self._query("recipes", kw, self._fmt_recipe))

    @filter.command("厨师")
    async def cmd_chef(self, event: AstrMessageEvent, *args):
        await self._ensure_data()
        kw = " ".join(args).strip()
        if not kw:
            yield event.plain_result("用法: /厨师 <名称或关键词>")
            return
        yield event.plain_result(self._query("chefs", kw, self._fmt_chef))

    @filter.command("厨具")
    async def cmd_equip(self, event: AstrMessageEvent, *args):
        await self._ensure_data()
        kw = " ".join(args).strip()
        if not kw:
            yield event.plain_result("用法: /厨具 <名称或关键词>")
            return
        yield event.plain_result(self._query("equips", kw, self._fmt_equip))

    @filter.command("任务")
    async def cmd_quest(self, event: AstrMessageEvent, *args):
        await self._ensure_data()
        kw = " ".join(args).strip()
        if not kw:
            yield event.plain_result("用法: /任务 <关键词或编号>")
            return
        yield event.plain_result(self._query("quests", kw, self._fmt_quest))

    @filter.command("材料")
    async def cmd_material(self, event: AstrMessageEvent, *args):
        await self._ensure_data()
        kw = " ".join(args).strip()
        if not kw:
            yield event.plain_result("用法: /材料 <名称或关键词>")
            return
        yield event.plain_result(self._query("materials", kw, self._fmt_material))

    @filter.command("遗玉")
    async def cmd_amber(self, event: AstrMessageEvent, *args):
        await self._ensure_data()
        kw = " ".join(args).strip()
        if not kw:
            yield event.plain_result("用法: /遗玉 <名称或关键词>")
            return
        yield event.plain_result(self._query("ambers", kw, self._fmt_amber))

    @filter.command("bcjh源")
    async def cmd_source(self, event: AstrMessageEvent, source: str = ""):
        if source not in DATA_URLS:
            yield event.plain_result(
                f"可用数据源: {', '.join(DATA_URLS.keys())}（当前: {self.source}）"
            )
            return
        self.source = source
        self._data = {}
        await self._ensure_data()
        yield event.plain_result(f"已切换数据源为 {source}")

    async def terminate(self):
        """插件卸载时清理（可选）"""
        pass
