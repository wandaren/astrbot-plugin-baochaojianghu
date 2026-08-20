# AstrBot 爆炒江湖图鉴插件

在 QQ / 微信 / Telegram / Discord 等聊天中直接查询《爆炒江湖》的游戏数据：菜谱、厨师、厨具、任务、材料、遗玉。

数据来自玩家社区的公开图鉴 JSON（无需鉴权、无需 API Key），插件启动后自动拉取并缓存，定时刷新。

## 功能指令

| 指令 | 说明 |
| --- | --- |
| `/菜谱 <名称或关键词>` | 查询菜谱：品阶、技法、材料、售价、解锁条件、贵客 |
| `/厨师 <名称或关键词>` | 查询厨师：星级、技法、技能、修炼任务 |
| `/厨具 <名称或关键词>` | 查询厨具：等级、加成 |
| `/任务 <关键词或编号>` | 查询任务 |
| `/材料 <名称或关键词>` | 查询材料获取方式 |
| `/遗玉 <名称或关键词>` | 查询遗玉加成 |
| `/bcjh源 <foodgame\|baochaojianghu>` | 切换数据源（默认 `baochaojianghu`） |

示例：

```
/菜谱 荷包蛋
/厨师 宫保鸡丁
/任务 900
```

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
