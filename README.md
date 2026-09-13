# 猎聘招聘助手 · liepin-recruit-assistant

> 把招聘里最耗时的重复劳动交给程序 —— **JD 解析、简历匹配、话术起草、台账管理、日报汇总**。
> 但对外发送的每一步,**始终保留人工确认**。

[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)]()

---

## ⚠️ 先读这一段

这个工具是**半自动**的,不是"全自动群发机器人"。这是刻意的设计,不是能力不足:

| 环节 | 谁来做 |
|---|---|
| 解析 JD、筛选简历、打分排序 | 🤖 程序 |
| 起草打招呼话术 | 🤖 程序 |
| 台账维护、日报统计 | 🤖 程序 |
| **把消息真正发给候选人** | 👤 **必须你手动做** |
| 确认话术内容 | 👤 **必须你手动点确认** |

**为什么这样设计:**

1. **平台条款风险** —— 招聘平台的用户协议普遍禁止高频自动化操作。全自动群发会触发风控,轻则限流、重则封号。本工具内置频率护栏(默认 20 次/小时、间隔 ≥60 秒)来降低这个风险,但**无法消除**。
2. **个人信息保护** —— 候选人简历属于个人信息。《个人信息保护法》要求处理个人信息遵循合法、正当、必要原则,并取得同意。批量自动触达很容易越过这条线。
3. **职业声誉** —— 千篇一律的群发消息,候选人一眼就能看出来。

所以:**本工具不逆向平台接口、不绕过风控、不代发消息。** 它只是帮你把案头工作做完,把该你拍板的部分留给你。

如果你需要全自动群发,这个项目不适合你 —— 而且我建议你重新考虑一下。

---

## 功能特性

- **JD 智能解析** —— 从一段自由文本里提取核心技能、加分技能、经验年限、学历要求,零配置
- **可解释的匹配打分** —— 五维加权评分,每一项都给出人话理由,不是黑盒数字
- **批量话术草稿** —— 基于候选人的实际技能个性化生成,4 种语气模板可选
- **强制人工确认** —— 未确认的草稿在数据库层面就无法登记为已发送
- **频率护栏** —— 滑动窗口 + 最小间隔双限制,状态持久化,防封号
- **招聘日报** —— 漏斗转化、待跟进提醒、岗位人才池,纯文本可直接贴群里
- **数据不出本机** —— SQLite 单文件存储,零远程调用
- **零第三方依赖** —— 纯标准库,不需要 `pip install` 任何东西
- **151 个单元测试** —— 覆盖解析、打分、存储、护栏、CLI 全链路

---

## 快速开始

### 环境要求

Python 3.9 或更高。检查一下:

```bash
python --version
```

### 安装

方式一,直接用(无需安装):

```bash
git clone https://github.com/ZTLNB/liepin-recruit-assistant.git
cd liepin-recruit-assistant
export PYTHONPATH=src          # Windows: set PYTHONPATH=src
python -m recruit_assistant --help
```

方式二,装成命令(推荐):

```bash
pip install -e .
recruit --help
```

### 五分钟跑通全流程

用 `examples/` 里的示例数据走一遍:

```bash
# 1. 初始化
recruit init

# 2. 添加岗位(自动解析 JD)
recruit job add --title "后端工程师" --jd-file examples/example_jd.txt

# 3. 批量导入候选人
recruit candidate import examples/example_candidates.csv

# 4. 匹配打分,只看 60 分以上的
recruit match --job "后端工程师" --min-score 60

# 5. 看某人的评分依据
recruit match show --job "后端工程师" --verbose

# 6. 生成一条打招呼草稿
recruit message draft --job "后端工程师" --candidate "张伟" \
    --template warm --company "某某科技"

# 7. 人工确认(看完内容再确认)
recruit message approve <草稿ID>

# 8. 你去猎聘手动发出消息,然后回来登记
recruit message sent <草稿ID>

# 9. 看日报
recruit report --company "某某科技"
```

实际输出长这样:

```
【招聘漏斗】
  待接触　　    4  ███████████████████·····
  已打招呼　    1  █████···················
  已回复　　    0  ························
  面试中　　    0  ························

【岗位人才池】
  后端工程师: 3 人(均分 78.0 · 最高 82.0)
      B 档 82.0  张伟
      B 档 81.3  王强
      B 档 70.7  孙涛
```

---

## 命令速查

| 命令 | 说明 |
|---|---|
| `recruit init` | 初始化数据目录 |
| `recruit job add --title X --jd-file f` | 新增岗位并解析 JD |
| `recruit job list` | 列出所有岗位 |
| `recruit candidate import <file>` | 从 CSV/JSON 批量导入候选人 |
| `recruit candidate list [--status S]` | 列出候选人 |
| `recruit candidate status <人> <状态>` | 更新候选人状态 |
| `recruit match --job X [--min-score N]` | 执行匹配打分 |
| `recruit match show --job X [--verbose]` | 查看匹配结果与依据 |
| `recruit message draft --job X --candidate Y` | 生成单条话术草稿 |
| `recruit message batch --job X --limit N` | 按分数批量生成草稿 |
| `recruit message list [--pending]` | 列出草稿 |
| `recruit message approve <草稿ID>` | **人工确认** |
| `recruit message sent <草稿ID>` | 登记为已发送(需先确认) |
| `recruit report [--stale-days N]` | 生成招聘日报 |
| `recruit export --job X --out f.csv` | 导出匹配结果为 CSV |
| `recruit templates` | 查看内置话术模板 |

全局参数:`--db <路径>` 指定数据库(默认 `~/.recruit-assistant/recruit.db`)。

候选人状态取值:`NEW` `CONTACTED` `REPLIED` `INTERVIEW` `OFFER` `HIRED` `REJECTED` `ARCHIVED`(也接受"待接触""面试中"等中文写法)。

---

## 评分模型

总分 100,五个维度加权,**每一项都会输出可读理由**:

| 维度 | 权重 | 计分方式 |
|---|---|---|
| 核心技能命中 | 50 | 岗位必需技能的覆盖率 |
| 经验年限符合度 | 20 | 低于下限按差距比例扣;高于上限视为资历过高也扣 |
| 加分技能 | 10 | 命中 `nice_to_have` 的比例 |
| 学历符合 | 10 | 达标满分,低一档给一半,低两档为 0 |
| 关键词重合 | 10 | 简历正文与岗位关键词的重合度 |

分数映射档位:**A** ≥85 · **B** ≥70 · **C** ≥55 · **D** <55

技能识别不只看标签 —— 简历正文里散落的技能也会被词典匹配出来,所以**不要只填标签,把简历正文也贴进去**,匹配会准得多。

想调整权重?改 `src/recruit_assistant/matcher.py` 顶部那五个 `WEIGHT_*` 常量即可。

想扩充技能词典?改 `src/recruit_assistant/jd.py` 里的 `SKILL_ALIASES`,格式一目了然。

---

## 候选人数据格式

### CSV

表头支持中英文混用,常见别名都能识别:

```csv
姓名,年限,学历,当前职位,当前公司,技能,简历正文,来源
张伟,5,硕士,高级后端工程师,某电商公司,Python|MySQL|Redis,"精通Python高并发开发,熟悉MySQL调优",猎聘
```

- **技能**用 `|` `;` `、` 分隔均可
- **简历正文含逗号时必须用双引号包住**,否则会和 CSV 的列分隔符冲突
- 年限支持 `5`、`5年` 两种写法
- 编码自动识别 UTF-8 / GBK(Windows 导出的 CSV 常见 GBK)

### JSON

```json
[
  {
    "姓名": "张伟",
    "年限": 5,
    "学历": "硕士",
    "技能": ["Python", "MySQL", "Redis"],
    "简历正文": "精通Python高并发开发"
  }
]
```

也支持 `{"candidates": [...]}` 或 `{"data": [...]}` 的包装形式。

---

## 项目结构

```
liepin-recruit-assistant/
├── src/recruit_assistant/
│   ├── models.py        # 数据模型(候选人/岗位/匹配结果/草稿)
│   ├── store.py         # SQLite 持久化层
│   ├── jd.py            # JD 解析(技能词典 + 规则)
│   ├── matcher.py       # 加权匹配打分
│   ├── message.py       # 话术草稿生成
│   ├── report.py        # 日报统计
│   ├── ratelimit.py     # 频率护栏
│   ├── cli.py           # 命令行入口
│   └── adapters/        # 数据导入适配器
├── tests/               # 151 个单元测试
├── examples/            # 示例 JD 与候选人数据
└── pyproject.toml
```

---

## 运行测试

```bash
python -m unittest discover -s tests
```

预期输出:

```
Ran 151 tests in 1.6s

OK
```

---

## 设计说明:为什么不做浏览器自动化

GitHub 上有一些同类项目用 Puppeteer/CDP 驱动本机 Chrome 去操作猎聘页面。这个项目**没有**内置这类能力,原因是:

1. 这类代码天然脆弱 —— 平台改一次前端结构就失效,维护成本高
2. 它绕不开平台条款问题,风险直接转嫁给使用者
3. 最关键的是:招聘里真正耗时的从来不是"点发送"那一下,而是**判断该发给谁**。那部分才是本工具要解决的。

如果你确实需要浏览器自动化,`adapters/` 目录预留了 `CandidateSource` 接口,可以自己扩展。但请自行确认合规性。

---

## 常见问题

**Q:能自动发消息吗?**
不能,也不会加。设计上就是人工确认后才登记。这是产品立场,不是待办事项。

**Q:会不会被封号?**
本工具不直接操作平台,所以不存在"工具导致封号"。风险来自你手动操作的频率 —— 护栏会提醒你,但拦不住你在客户端里手动狂点。

**Q:简历数据会上传吗?**
不会。全部存在本地 SQLite,零网络请求。你可以拔了网线用。

**Q:匹配不准怎么办?**
先确认简历正文填了没有(技能主要从正文识别)。然后扩充 `SKILL_ALIASES` 词典,或调整 `WEIGHT_*` 权重。

**Q:支持 BOSS 直聘吗?**
数据格式是通用的,导入逻辑不挑平台。JD 解析和匹配打分与平台无关。

---

## 许可证

[MIT](LICENSE) © 2026 ZTLNB

---

## 免责声明

本工具仅用于辅助招聘流程的信息整理与筛选,**不代替**你对候选人信息的判断,也**不代替**你遵守相关法律法规的义务。使用者应自行确保其数据处理行为符合《个人信息保护法》《网络安全法》等规定,以及所使用招聘平台的服务协议。因使用本工具产生的任何后果,由使用者自行承担。
