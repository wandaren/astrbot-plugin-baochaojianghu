# AstrBot 爆炒江湖图鉴插件

在 QQ / 微信 / Telegram / Discord 等聊天中直接查询《爆炒江湖》的游戏数据：菜谱、厨师、厨具、任务、材料、遗玉。支持导入官方存档，查询本人已拥有的菜谱/厨师/修炼进度。

图鉴数据来自玩家社区的公开 JSON（无需鉴权、无需 API Key），官方存档通过游戏校验码拉取（与 h5.baochaojianghu.com 图鉴的官方数据导入一致）。

## 功能指令

| 指令 | 说明 |
| --- | --- |
| `/菜谱 <名称或关键词>` | 查询菜谱：品阶、技法、材料、售价、解锁条件、贵客 |
| `/厨师 <名称或关键词>` | 查询厨师：星级、技法、技能、修炼任务 |
| `/厨具 <名称或关键词>` | 查询厨具：等级、加成 |
| `/任务 <关键词或编号>` | 查询任务 |
| `/材料 <名称或关键词>` | 查询材料获取方式 |
| `/遗玉 <名称或关键词>` | 查询遗玉加成 |
| `/导入 <校验码>` | **导入官方存档**：游戏内 设置→数据 页获取校验码 |
| `/我的菜谱 [关键词]` | 查看本人已拥有的菜谱 |
| `/我的厨师 [关键词]` | 查看本人已拥有的厨师 |
| `/我的进度` | 查看本人存档概览（菜谱/厨师/修炼数量） |
| `/最优 [数量]` | 基于已拥有厨师+菜谱，计算单位时间金币收益最高的搭配（默认 Top 10，最多 20） |
| `/bcjh源 <foodgame\|baochaojianghu>` | 切换图鉴数据源（默认 `baochaojianghu`） |

示例：

```
/菜谱 荷包蛋
/厨师 宫保鸡丁
/导入 aBcD1234   ← 游戏设置页的校验码
/我的菜谱 面
/我的进度
/最优 10         ← 计算收益最高的 10 个厨师+菜谱搭配
```

## 最优搭配计算说明

`/最优` 基于你导入的官方存档（已拥有厨师 + 已拥有菜谱）计算单位时间金币收益：

- **品级**：`min(厨师技法 ÷ 菜谱需求技法)`，封顶 5 级；技法不足的菜谱无法制作，自动跳过
- **品级售价加成**（与白菜菊花图鉴一致）：品级1 +0%、2 +10%、3 +30%、4 +50%、5 +100%
- **单位时间收益** = `加成后售价 × 3600 ÷ 制作时间`（金币/小时）
- 每个菜谱取能做出最高收益的厨师，按金币/h 降序输出 Top N

> 说明：该计算为「基础营业」简化模型（不含食神/宴会活动规则、遗玉/厨具/调料/装修加成、修炼技能）。若需要活动规则级精确收益，建议直接使用白菜菊花图鉴的完整计算器。

## 官方数据导入说明

- 在《爆炒江湖》游戏内 **设置 → 数据** 页面获取校验码（即白菜菊花图鉴网站的「官方数据导入」使用的同一校验码）
- 插件调用 `https://yx518.com/api/archive.do?token=<校验码>` 拉取官方存档
- 存档包含：已拥有菜谱、已拥有厨师、修炼进度，以及遗玉/厨具数据（如官方提供）
- 存档按 QQ/微信 发送者 ID 分别存储于 AstrBot `data` 目录，互不干扰，可随时重新导入覆盖

## 安装

### 方式一：AstrBot 管理面板在线安装（推荐）

1. 打开 AstrBot WebUI，进入「插件管理」
2. 添加插件源：`https://github.com/wandaren/astrbot-plugin-baochaojianghu`
3. 搜索并安装 `baochaojianghu`

### 方式二：本地安装

```bash
git clone https://github.com/wandaren/astrbot-plugin-baochaojianghu.git
astrbot plugin install ./astrbot-plugin-baochaojianghu
```

或使用可编辑安装（便于开发调试）：

```bash
astrbot plugin install --editable ./astrbot-plugin-baochaojianghu
```

## 数据源说明

| 数据源 | 地址 | 说明 |
| --- | --- | --- |
| 白菜菊花图鉴（默认） | `https://h5.baochaojianghu.com/data/data.min.json` | 更新更全，~2MB |
| 图鉴站 | `https://foodgame.github.io/data/data.min.json` | 较旧，~1.7MB |

两个数据源 JSON 结构完全一致，数据版权归原作者及《爆炒江湖》官方所有，本插件仅作查询展示。

## 插件配置

安装后在 AstrBot WebUI 的插件设置中可调整（对应 `_conf_schema.json`）：

- `SOURCE`: 默认数据源，可选 `baochaojianghu`（默认）/ `foodgame`
- `REFRESH_HOURS`: 数据缓存刷新间隔（小时），默认 `6`

## 开发

```bash
# 目录结构
.
├── main.py            # 插件主逻辑
├── metadata.yaml      # 插件元数据
├── _conf_schema.json  # 插件配置 Schema（WebUI 可调）
├── requirements.txt   # 依赖
└── README.md
```

依赖仅 `aiohttp`。

## License

MIT
