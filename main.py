"""
爆炒江湖图鉴查询插件 (astrbot-plugin-baochaojianghu)

数据源（公开静态 JSON，无鉴权）：
  - https://h5.baochaojianghu.com/data/data.min.json   (白菜菊花图鉴, 默认, ~2MB, 更新更全)
  - https://foodgame.github.io/data/data.min.json      (图鉴站, 较旧, ~1.7MB)
两者 JSON 顶层结构完全一致。

官方数据导入（与 h5.baochaojianghu.com 图鉴一致）：
  用户在《爆炒江湖》游戏内「设置」页获取校验码，插件调用
  https://yx518.com/api/archive.do?token=<校验码> 拉取官方存档，
  存档按发送者 ID 存储于 AstrBot data 目录，可查询本人拥有的菜谱/厨师/修炼。

功能指令：
  /菜谱 <名称或关键词>       查询菜谱（品阶/技法/材料/售价/解锁）
  /厨师 <名称或关键词>       查询厨师（星级/技法/技能/修炼任务）
  /厨具 <名称或关键词>       查询厨具（等级/加成）
  /任务 <关键词或编号>       查询任务
  /材料 <名称或关键词>       查询材料
  /遗玉 <名称或关键词>       查询遗玉
  /导入 <校验码>             导入官方存档（游戏设置页获取校验码）
  /我的菜谱 [关键词]         查看本人已拥有的菜谱
  /我的厨师 [关键词]         查看本人已拥有的厨师
  /我的进度                  查看本人存档概览（菜谱/厨师/修炼数量）
  /最优 [数量]               基于已拥有厨师+菜谱，计算单位时间金币收益最高的搭配
  /bcjh源 <foodgame|baochaojianghu>   切换图鉴数据源

数据策略：插件加载 10s 后首次拉取图鉴数据，之后按 refresh_hours 定时刷新，内存缓存。
依赖：aiohttp（在 requirements.txt 中声明）
"""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import aiohttp

from astrbot.api import logger, AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, StarTools

DATA_URLS = {
    "foodgame": "https://foodgame.github.io/data/data.min.json",
    "baochaojianghu": "https://h5.baochaojianghu.com/data/data.min.json",
}
# 官方存档接口（与 h5.baochaojianghu.com 图鉴使用同一接口）
ARCHIVE_URL = "https://yx518.com/api/archive.do"

# 单条消息最大长度（超过截断，避免刷屏）
MAX_MSG_LEN = 4000

# 技法名称
TECH_NAMES = {
    "stirfry": "炒", "boil": "煮", "knife": "切",
    "fry": "炸", "bake": "烤", "steam": "蒸",
}

# 品级售价加成（与白菜菊花图鉴 constants.js 一致）
GRADE_BUFF = {1: 0, 2: 10, 3: 30, 4: 50, 5: 100}
TECH_KEYS = ["stirfry", "boil", "knife", "fry", "bake", "steam"]


def _fmt_tech(item) -> str:
    parts = []
    for key, label in TECH_NAMES.items():
        v = item.get(key, 0) or 0
        if v:
            parts.append(f"{label}{v}")
    return " ".join(parts) if parts else "-"


class BaochaoJianghuPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        data_cfg = config.get("DATA_SOURCE", {}) if config else {}
        source = data_cfg.get("SOURCE", "baochaojianghu")
        if source not in DATA_URLS:
            source = "baochaojianghu"
        self.source = source
        try:
            self.refresh_hours = float(data_cfg.get("REFRESH_HOURS", 6))
        except (TypeError, ValueError):
            self.refresh_hours = 6.0
        self._data: dict = {}
        self._material_map: dict = {}
        self._data_ts: float = 0.0
        self._lock = asyncio.Lock()
        # 存档目录：AstrBot data 目录（符合插件数据存储规范）
        self.archives_dir = StarTools.get_data_dir("baochaojianghu") / "archives"
        self.archives_dir.mkdir(parents=True, exist_ok=True)
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
                    f"[bcjh] 图鉴数据已加载: {self.source}, "
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
                logger.error(f"[bcjh] 图鉴数据刷新失败: {e}")
            await asyncio.sleep(self.refresh_hours * 3600)

    # ---------- 官方存档 ----------
    def _archive_path(self, user_id: str) -> Path:
        return self.archives_dir / f"{user_id}.json"

    def _load_archive(self, user_id: str) -> dict:
        """读取某用户存档，不存在返回空 dict"""
        p = self._archive_path(user_id)
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_archive(self, user_id: str, archive: dict):
        p = self._archive_path(user_id)
        p.write_text(json.dumps(archive, ensure_ascii=False, indent=2), encoding="utf-8")

    async def _fetch_archive(self, code: str) -> tuple:
        """调用官方存档接口。返回 (ok, msg_or_data)"""
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.get(ARCHIVE_URL, params={"token": code}) as resp:
                    resp.raise_for_status()
                    rst = await resp.json(content_type=None)
        except Exception as e:
            return False, f"请求存档服务失败: {e}"
        if not isinstance(rst, dict):
            return False, "存档服务返回异常"
        if rst.get("ret") != "S":
            return False, f"导入失败: {rst.get('msg', '未知错误')}"
        data = rst.get("msg")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                return False, "存档数据解析失败"
        return True, data

    @staticmethod
    def _trans(arr, key) -> dict:
        """官方存档字段转换：{id: 是否为'是'}"""
        result = {}
        for item in arr or []:
            result[item.get("id")] = (item.get(key) == "是")
        return result

    def _parse_archive(self, data: dict, with_equip: bool = True) -> dict:
        """解析官方存档，转换为图鉴可关联的结构（与白菜菊花图鉴逻辑一致）"""
        archive = {
            "imported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "repGot": self._trans(data.get("recipes"), "got"),
            "chefGot": self._trans(data.get("chefs"), "got"),
            "chefUlt": self._trans(data.get("chefs"), "ult"),
            "chefAmber": {},
            "chefEquip": {},
            "chefDiskLv": {},
            "decorationEffect": data.get("decorationEffect", {}),
        }
        if with_equip:
            for chef in data.get("chefs") or []:
                cid = chef.get("id")
                if cid is None:
                    continue
                if chef.get("ambers"):
                    archive["chefAmber"][str(cid)] = chef["ambers"]
                if chef.get("equip"):
                    archive["chefEquip"][str(cid)] = chef["equip"]
                if chef.get("dlv"):
                    archive["chefDiskLv"][str(cid)] = chef["dlv"]
        return archive

    # ---------- 检索 ----------
    @staticmethod
    def _search(items: list, keyword: str, limit: int = 5):
        kw = keyword.strip().lower()
        if not items:
            return []
        exact = [it for it in items if str(it.get("name", "")).strip() == keyword.strip()]
        hits = exact or [it for it in items if kw in str(it.get("name", "")).lower()]
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
        gender = c.get("gender", "?")
        gender_str = "男" if gender == "male" else ("女" if gender == "female" else str(gender))
        skill = c.get("skill") or c.get("skills") or "-"
        if isinstance(skill, (list, dict)):
            skill = str(skill)
        task = c.get("task") or c.get("quest") or "-"
        return (
            f"[厨师] {c.get('name')}（{gender_str}）\n"
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

    def _list_got(self, key: str, got_map: dict, id_key: str, keyword: str = "", limit: int = 30) -> str:
        """列出已拥有的条目（got_map: id->bool）"""
        items = self._data.get(key, [])
        owned = [it for it in items if got_map.get(it.get(id_key))]
        if keyword:
            kw = keyword.lower()
            owned = [it for it in owned if kw in str(it.get("name", "")).lower()]
        if not owned:
            return f"没有已拥有的{key}（或关键词无匹配）。"
        lines = [f"· {it.get('name')}" for it in owned[:limit]]
        text = "\n".join(lines)
        if len(owned) > limit:
            text += f"\n…共 {len(owned)} 条，仅显示前 {limit} 条"
        return text[:MAX_MSG_LEN]

    # ---------- 收益计算 ----------
    @staticmethod
    def _calc_grade(chef: dict, recipe: dict) -> int:
        """
        计算厨师做某菜谱的品级（1-5，技法不足则 0 表示做不了）。
        品级 = min(floor(厨师技法 / 菜谱需求技法))，封顶 5。
        """
        grade = 5
        for key in TECH_KEYS:
            need = recipe.get(key, 0) or 0
            if need <= 0:
                continue
            have = chef.get(key, 0) or 0
            if have < need:
                return 0  # 技法不足，做不了
            g = have // need
            grade = min(grade, g)
        return grade if grade >= 1 else 1

    def _calc_recipe_price(self, recipe: dict, grade: int) -> int:
        """加成后的售价 = ceil(基础价 × (100 + 品级加成%) / 100)"""
        price = recipe.get("price", 0) or 0
        ex = recipe.get("exPrice", 0) or 0  # 专精加成价
        buff = GRADE_BUFF.get(grade, 0)
        total = (price + ex) * (100 + buff)
        return -(-total // 100)  # ceil

    def _calc_optimal(self, archive: dict, top_n: int = 10) -> list:
        """
        基于已拥有厨师+菜谱，计算单位时间金币收益（金币/小时）最高的搭配。
        返回 [(gold_per_hour, recipe, chef, grade), ...] 降序。
        """
        rep_got = archive.get("repGot", {})
        chef_got = archive.get("chefGot", {})
        recipes = [r for r in self._data.get("recipes", []) if rep_got.get(r.get("recipeId"))]
        chefs = [c for c in self._data.get("chefs", []) if chef_got.get(c.get("chefId"))]
        if not recipes or not chefs:
            return []

        results = []
        for recipe in recipes:
            time_s = recipe.get("time", 0) or 1
            best_chef = None
            best_grade = 0
            best_eff = 0
            for chef in chefs:
                grade = self._calc_grade(chef, recipe)
                if grade <= 0:
                    continue
                price = self._calc_recipe_price(recipe, grade)
                eff = price * 3600 // time_s
                if eff > best_eff:
                    best_eff = eff
                    best_chef = chef
                    best_grade = grade
            if best_chef and best_eff > 0:
                results.append((best_eff, recipe, best_chef, best_grade))
        results.sort(key=lambda x: x[0], reverse=True)
        return results[:top_n]

    def _fmt_optimal(self, results: list, top_n: int) -> str:
        if not results:
            return "无法计算：请先 /导入 官方存档，并确认已拥有至少一个厨师和一个菜谱。"
        lines = [f"[最优金币搭配 Top {len(results)}]（单位时间收益）"]
        for i, (eff, recipe, chef, grade) in enumerate(results, 1):
            price = self._calc_recipe_price(recipe, grade)
            buff = GRADE_BUFF.get(grade, 0)
            lines.append(
                f"{i}. {recipe.get('name')} × {chef.get('name')} "
                f"[品级{grade} +{buff}% → 售价{price}] {eff}金币/h"
            )
        lines.append(f"\n收益=加成后售价×3600/制作时间；共匹配 {len(results)} 条（显示前 {min(top_n, len(results))} 条）")
        return "\n".join(lines)[:MAX_MSG_LEN]

    # ---------- 指令 ----------
    @filter.command("菜谱", "查询菜谱（品阶/技法/材料/售价/解锁）")
    async def cmd_recipe(self, event: AstrMessageEvent, keyword: str = ""):
        await self._ensure_data()
        kw = keyword.strip()
        if not kw:
            yield event.plain_result("用法: /菜谱 <名称或关键词>")
            return
        yield event.plain_result(self._query("recipes", kw, self._fmt_recipe))

    @filter.command("厨师", "查询厨师（星级/技法/技能/修炼任务）")
    async def cmd_chef(self, event: AstrMessageEvent, keyword: str = ""):
        await self._ensure_data()
        kw = keyword.strip()
        if not kw:
            yield event.plain_result("用法: /厨师 <名称或关键词>")
            return
        yield event.plain_result(self._query("chefs", kw, self._fmt_chef))

    @filter.command("厨具", "查询厨具（等级/加成）")
    async def cmd_equip(self, event: AstrMessageEvent, keyword: str = ""):
        await self._ensure_data()
        kw = keyword.strip()
        if not kw:
            yield event.plain_result("用法: /厨具 <名称或关键词>")
            return
        yield event.plain_result(self._query("equips", kw, self._fmt_equip))

    @filter.command("任务", "查询任务")
    async def cmd_quest(self, event: AstrMessageEvent, keyword: str = ""):
        await self._ensure_data()
        kw = keyword.strip()
        if not kw:
            yield event.plain_result("用法: /任务 <关键词或编号>")
            return
        yield event.plain_result(self._query("quests", kw, self._fmt_quest))

    @filter.command("材料", "查询材料获取方式")
    async def cmd_material(self, event: AstrMessageEvent, keyword: str = ""):
        await self._ensure_data()
        kw = keyword.strip()
        if not kw:
            yield event.plain_result("用法: /材料 <名称或关键词>")
            return
        yield event.plain_result(self._query("materials", kw, self._fmt_material))

    @filter.command("遗玉", "查询遗玉加成")
    async def cmd_amber(self, event: AstrMessageEvent, keyword: str = ""):
        await self._ensure_data()
        kw = keyword.strip()
        if not kw:
            yield event.plain_result("用法: /遗玉 <名称或关键词>")
            return
        yield event.plain_result(self._query("ambers", kw, self._fmt_amber))

    @filter.command("导入", "导入官方存档（游戏设置页获取校验码）")
    async def cmd_import(self, event: AstrMessageEvent, code: str = ""):
        code = code.strip()
        if not code:
            yield event.plain_result(
                "用法: /导入 <校验码>\n"
                "在《爆炒江湖》游戏内 设置 → 数据 页面获取校验码后粘贴至此，"
                "与 h5.baochaojianghu.com 图鉴的官方数据导入一致。"
            )
            return
        yield event.plain_result("正在拉取官方存档，请稍候…")
        ok, result = await self._fetch_archive(code)
        if not ok:
            yield event.plain_result(result)
            return
        user_id = str(event.get_sender_id())
        archive = self._parse_archive(result)
        self._save_archive(user_id, archive)
        got_rep = sum(1 for v in archive["repGot"].values() if v)
        got_chef = sum(1 for v in archive["chefGot"].values() if v)
        got_ult = sum(1 for v in archive["chefUlt"].values() if v)
        yield event.plain_result(
            f"导入成功 ✅（存档时间 {archive['imported_at']}）\n"
            f"已拥有菜谱: {got_rep}  厨师: {got_chef}  已修炼: {got_ult}\n"
            f"可用 /我的菜谱 /我的厨师 /我的进度 查询。"
        )

    @filter.command("我的菜谱", "查看本人已拥有的菜谱")
    async def cmd_my_recipes(self, event: AstrMessageEvent, keyword: str = ""):
        await self._ensure_data()
        user_id = str(event.get_sender_id())
        archive = self._load_archive(user_id)
        if not archive:
            yield event.plain_result("尚未导入官方存档，先使用 /导入 <校验码>。")
            return
        yield event.plain_result(self._list_got("recipes", archive.get("repGot", {}), "recipeId", keyword))

    @filter.command("我的厨师", "查看本人已拥有的厨师")
    async def cmd_my_chefs(self, event: AstrMessageEvent, keyword: str = ""):
        await self._ensure_data()
        user_id = str(event.get_sender_id())
        archive = self._load_archive(user_id)
        if not archive:
            yield event.plain_result("尚未导入官方存档，先使用 /导入 <校验码>。")
            return
        yield event.plain_result(self._list_got("chefs", archive.get("chefGot", {}), "chefId", keyword))

    @filter.command("我的进度", "查看本人存档概览")
    async def cmd_my_progress(self, event: AstrMessageEvent):
        await self._ensure_data()
        user_id = str(event.get_sender_id())
        archive = self._load_archive(user_id)
        if not archive:
            yield event.plain_result("尚未导入官方存档，先使用 /导入 <校验码>。")
            return
        total_rep = len(self._data.get("recipes", []))
        total_chef = len(self._data.get("chefs", []))
        got_rep = sum(1 for v in archive.get("repGot", {}).values() if v)
        got_chef = sum(1 for v in archive.get("chefGot", {}).values() if v)
        got_ult = sum(1 for v in archive.get("chefUlt", {}).values() if v)
        yield event.plain_result(
            f"[存档概览] 导入时间: {archive.get('imported_at', '?')}\n"
            f"菜谱: {got_rep}/{total_rep}\n"
            f"厨师: {got_chef}/{total_chef}\n"
            f"已修炼厨师: {got_ult}\n"
            f"遗玉/厨具数据: {'已导入' if archive.get('chefAmber') or archive.get('chefEquip') else '未导入'}"
        )

    @filter.command("最优", "计算已拥有厨师+菜谱中单位时间金币收益最高的搭配")
    async def cmd_optimal(self, event: AstrMessageEvent, num: str = ""):
        await self._ensure_data()
        user_id = str(event.get_sender_id())
        archive = self._load_archive(user_id)
        if not archive:
            yield event.plain_result("尚未导入官方存档，先使用 /导入 <校验码>。")
            return
        try:
            top_n = max(1, min(20, int(num))) if num.strip() else 10
        except ValueError:
            top_n = 10
        yield event.plain_result("正在计算最优搭配，请稍候…")
        results = self._calc_optimal(archive, top_n)
        yield event.plain_result(self._fmt_optimal(results, top_n))

    @filter.command("bcjh源", "切换图鉴数据源（foodgame 或 baochaojianghu）")
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
