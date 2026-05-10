# 洛克王国世界 PVP 战斗信息获取与敌方配置推算系统需求分析 v0.3.3

> 修订日期：2026-05-10  
> 本版重点：保留原 v0.2.3 的属性公式、伤害展示、速度判断、敌方配置推算主干，并根据 140 条状态技能重构状态分类、印记规则、切换清除规则、状态数据库、事件快照和 UI 展示。v0.3.1 进一步修正：星陨属于印记，按减益印记处理，而不是异常 / 层数状态。v0.3.2 进一步补充数据库字段、运行时字段、枚举值、来源、用途、必填性与开发注释。v0.3.3 根据程序性能约束修正多段伤害记录策略：实时运行阶段优先只记录最终显示总伤害，逐段伤害作为可选扩展；同时修正精灵基础字段为唯一 ID、名称、头像，不设置精灵别名字段。

## 一、项目概述

本项目开发一个用于 **洛克王国世界 PVP 对战** 的战斗信息获取、敌方配置推算与伤害计算工具。

系统不负责自动替玩家做战斗决策，而是负责在对战过程中收集信息、计算伤害、推算敌方配置，并将关键结果实时展示给玩家，辅助玩家做出更准确的战斗判断。

系统的核心目标是：

> 基于准备阶段可见的双方六只精灵、己方已知完整配置、敌方未知配置，以及战斗中产生的技能、伤害、血量变化、状态修正等信息，持续收敛敌方精灵的可能配置，并实时计算双方技能伤害。

---

## 二、核心业务流程

### 2.1 准备阶段

对战开始前会进入准备页面。

此时系统可以看到双方出场的六只精灵。

#### 2.1.1 己方信息

己方六只精灵由玩家提前录入完整配置，因此己方信息是确定的。

己方信息包括：

- 精灵唯一 ID
- 精灵名称
- 精灵头像
- 等级，固定为 60
- 种族资质
- 个体资质
- 性格
- 技能组
- 最终面板属性
- 当前生命值
- 当前能量
- 当前状态

己方信息主要用于：

- 计算我方技能对敌方造成的伤害
- 计算敌方技能对我方造成的伤害
- 在敌方攻击我方时，反推敌方攻击属性和技能可能性

#### 2.1.2 敌方信息

敌方六只精灵在准备阶段只能确认精灵种类。

准备阶段可确定的信息包括：

- 精灵唯一 ID
- 精灵名称
- 精灵头像
- 种族资质
- 系别类型
- 可能技能池
- 常见技能组
- 常见性格
- 常见个体资质分布

准备阶段未知的信息包括：

- 性格
- 个体资质分布
- 最终面板属性
- 技能组
- 当前战斗状态变化

系统在准备阶段需要为敌方每只精灵建立候选配置集合。

示例：

```text
敌方精灵 A：

候选配置 1：
性格：物攻 +20%，魔攻 -10%
个体资质：生命 10 / 物攻 10 / 速度 10，其余维度 0

候选配置 2：
性格：速度 +20%，物防 -10%
个体资质：生命 10 / 魔攻 10 / 速度 10，其余维度 0

候选配置 3：
性格：生命 +20%，物攻 -10%
个体资质：生命 10 / 魔防 10 / 速度 10，其余维度 0
```

后续战斗中，每一次伤害事件都会用于过滤这些候选配置。

---

### 2.2 战斗阶段

进入实际对战后，系统持续识别和记录战斗信息。

需要记录的信息包括：

- 当前我方上场精灵
- 当前敌方上场精灵
- 双方生命状态
- 双方能量
- 双方技能使用情况
- 双方战斗效果列表，包括普通增益 / 减益、异常 / 层数状态、行动规则状态、技能槽修正等
- 天气 / 战场状态
- 队伍侧增益印记槽与减益印记槽
- 防御技能状态
- 增伤 / 减伤 / 技能特殊效果
- 状态驱散、转换、转移、继承、切换清除事件
- 精灵切换
- 伤害数值
- 敌方扣血百分比
- 血量百分比变化
- 多段伤害最终显示的总伤害；逐段伤害仅作为可选扩展

每次发生伤害时，系统生成一条伤害事件记录，并用该事件过滤敌方候选配置。

---

### 2.3 信息收敛阶段

敌方配置不是通过一次伤害就能直接确定，而是通过多次战斗证据逐步收敛。

核心流程如下：

```text
准备阶段生成敌方候选配置集合
↓
发生伤害事件
↓
读取伤害发生时的完整状态快照
↓
枚举敌方候选配置
↓
计算理论伤害
↓
与实际伤害、敌方扣血百分比进行对比
↓
排除不可能配置
↓
保留匹配配置
↓
多次伤害后逐渐提高置信度
```

敌方配置状态分为：

- 未知
- 低置信度
- 中置信度
- 高置信度
- 已基本确认

---

## 三、核心概念定义

### 3.1 种族资质

种族资质是精灵种类固定的基础值。

只要知道敌方精灵名称，就可以从数据库读取该精灵的种族资质。

因此，本系统原则上不需要反推敌方种族资质，而是需要反推敌方在种族资质基础上的具体培养配置。

---

### 3.2 个体资质

个体资质是玩家配置差异的一部分，也可以理解为精灵的天赋值。

当前规则如下：

- 单只精灵一定有 **1 到 3 个维度** 存在个体资质。
- 通常情况下，单只精灵存在个体资质的维度数量为 **3 个**。
- 存在个体资质的维度，数值固定范围为 **7 到 10**。
- 没有个体资质的维度，按 **0** 计算。
- 个体资质会参与属性计算。
- 所有 PVP 精灵统一按照 **6 星、0 觉醒、50 成长等级** 计算。
- 后续系统主要使用已经确认的 PVP 属性计算公式，不需要再单独处理突破星级和觉醒等级差异。

示例：

```text
个体资质配置：
生命 10 / 物攻 9 / 速度 10

实际参与计算：
生命：10
物攻：9
物防：0
魔攻：0
魔防：0
速度：10
```

---

### 3.3 培养配置

为避免概念混乱，本文档中不再把“培养值”作为具体字段使用。

后续统一使用：

```text
培养配置 = 性格 + 个体资质分布
```

敌方未知配置主要指：

- 性格
- 个体资质存在的维度
- 每个个体资质维度的数值
- 技能组

---

### 3.4 性格

性格会影响精灵六维属性，生命也可以受到性格影响。

当前规则为：

- 必定存在一个正面修正属性。
- 必定存在一个负面修正属性。
- 正面修正与负面修正不会是同一维。
- 正面修正：该维度属性 **+20%**。
- 负面修正：该维度属性 **-10%**。
- 其他属性不变。
- 生命、物攻、物防、魔攻、魔防、速度均可能被性格修正。

用公式表示：

$$
\text{正面性格修正} = 1.2
$$

$$
\text{负面性格修正} = 0.9
$$

$$
\text{普通性格修正} = 1.0
$$

示例：

```text
固执性格：
物攻 × 1.2
魔攻 × 0.9
其他属性 × 1.0
```

示例：

```text
生命强化性格：
生命 × 1.2
速度 × 0.9
其他属性 × 1.0
```

注意：

- 性格不影响成长值。
- 性格修正后再进行取整。
- 正面维度和负面维度必定不同。

---

### 3.5 面板属性

面板属性是精灵进入战斗前的最终六维属性。

包括：

- 生命
- 物攻
- 物防
- 魔攻
- 魔防
- 速度

面板属性由以下因素计算得到：

- 种族资质
- 个体资质
- 等级
- 成长值
- 性格
- 取整规则

---

### 3.6 战斗有效属性

战斗有效属性是实际参与伤害公式、速度判断和击杀判断的属性。

v0.3.0 起，战斗有效属性不再直接由“增益 / 减益 / 天气 / 印记 / 异常状态”这些分散字段拼接，而是统一从 `BattleEffectSnapshot` 读取所有可计算效果。

它等于：

```text
战斗有效属性 = 面板属性
经过普通属性增益 / 减益修正
经过异常 / 层数状态修正
经过队伍侧印记修正
经过天气 / 战场状态修正
经过技能槽修正
经过技能特殊效果修正
经过防御技能、增伤、减伤等其他战斗效果修正
```

伤害计算时，必须使用战斗有效属性，而不是单纯的面板属性。

为了避免状态遗漏导致敌方配置推算误判，伤害事件必须保存完整的战斗效果快照。

---

### 3.7 出手顺序规则

速度属性决定双方精灵在同一回合中的常规出手先后。

当前规则如下：

- 当双方精灵速度不同时，速度更高的一方优先出手。
- 当双方精灵速度相同时，双方为同速状态。
- 同速状态下，双方出手顺序存在随机性。
- 同速时，我方有 **50% 概率先出手**，敌方有 **50% 概率先出手**。

判断逻辑如下：

```text
if 我方速度 > 敌方速度:
    我方先出手
elif 我方速度 < 敌方速度:
    敌方先出手
else:
    我方先出手概率 = 50%
    敌方先出手概率 = 50%
```

该规则主要用于：

- 判断我方是否能先手击杀敌方。
- 判断敌方是否可能先手击杀我方。
- 评估攻击、换宠、防守等操作的风险。
- 在敌方速度配置未知时，通过候选配置计算双方速度关系，并展示先手概率。

当敌方速度配置未确认时，系统需要基于敌方候选配置输出速度判断结果。

示例：

```text
我方速度：168
敌方速度候选范围：154 ~ 172

先手判断：
- 我方必定先手：部分候选
- 敌方必定先手：部分候选
- 双方同速：部分候选

综合先手概率：
我方先手概率：约 62%
敌方先手概率：约 38%
```

---

### 3.8 防御技能减伤

本游戏当前不存在通用意义上的“护盾”机制。

当对方使用防御类技能时，可能会根据该防御技能的特性产生伤害减免。

因此，本文档不再将“护盾”作为通用战斗状态处理，而是将其归入：

```text
技能特殊效果
防御技能减伤
伤害计算特殊规则
```

防御技能减伤需要由技能数据库单独记录，并在伤害计算时根据技能特性进入公式。

示例：

```text
敌方使用防御技能 A：
本回合受到的伤害降低 50%
```

---

### 3.9 统一战斗效果系统

状态技能表显示，当前“变化 / 状态技能”并不只产生传统意义上的增益、减益、天气、印记或异常，还会产生能耗变化、技能威力变化、连击数变化、技能位置变化、技能替换、先手、迅捷、蓄力、传动、奉献、萌化、驱散、转换、转移、交换、继承等效果。

因此，本系统将所有持续存在、会影响后续计算或需要图标展示的状态统一抽象为：

```text
BattleEffect = 效果类型 + 作用范围 + 持续方式 + 叠层规则 + 清除规则 + 计算钩子 + 显示规则
```

一个 `BattleEffect` 至少需要记录：

| 字段 | 含义 |
| --- | --- |
| effect_id | 效果唯一编号 |
| name | 效果名称，例如冻结、物攻提升、蓄势印记 |
| category | 普通增减益 / 异常层数 / 印记 / 天气 / 技能槽修正 / 行动规则 / 特殊机制等 |
| polarity | 正面 / 负面 / 中性 / 混合 |
| scope | 作用范围：当前精灵、指定精灵、后备精灵、队伍侧、全战场、技能槽、本回合 |
| owner_side | 所属队伍 |
| owner_pet | 所属精灵，可为空 |
| skill_slot | 所属技能槽，可为空 |
| layers | 当前层数 |
| max_layers | 最大层数 |
| duration_type | 回合数、次数、直到切换、直到驱散、永久、直到战斗结束 |
| remaining_turns | 剩余回合 |
| remaining_uses | 剩余次数 |
| clear_on_switch | 切换当前在场精灵时是否清除 |
| clear_by_normal_dispel | 是否可被普通驱散增益 / 减益清除 |
| clear_by_mark_dispel | 是否可被印记驱散技能清除 |
| clear_by_abnormal_cleanse | 是否可被异常清除技能清除 |
| calculation_hooks | 参与属性、伤害、能耗、威力、连击、先手、行动限制等哪些计算 |
| icon_id | 状态图标 |
| source_skill | 来源技能 |
| source_actor | 来源精灵 |

只要某个技能生效后形成了持续存在、可追踪或会影响后续计算的状态，就必须在游戏 UI 或系统 UI 中以图标方式显示。

瞬时效果只记录事件，不作为持续状态显示。例如立即回复生命、立即偷取能量、立即交换生命比例本身不需要常驻图标；但如果该技能同时附加了萌化、能耗变化、属性变化等持续效果，则这些持续效果必须显示图标。

---

### 3.10 状态重新分类

v0.3.0 推荐把战斗效果分为以下 8 类。

| 一级分类 | 典型内容 | 默认作用范围 | 默认切换清除 | 是否显示图标 |
| --- | --- | --- | --- | --- |
| 普通增益 / 减益 | 物攻、物防、魔攻、魔防、速度、双攻、双防、技能威力、连击数、吸血等修正 | 当前在场精灵或技能槽 | 是，除非技能写明永久或特殊继承 | 是 |
| 异常 / 层数状态 | 冻结、中毒、灼烧、寄生、眩晕、萌化、奉献 | 指定精灵，可作用于场下 | 默认不按普通切换清除，需要逐个状态配置 | 是 |
| 印记 | 蓄势、攻击、湿润、蓄电、风起、光合、龙噬、减速、降灵、棘刺、中毒印记、星陨等 | 队伍侧印记槽 | 否 | 是 |
| 天气 / 战场 | 暴风雪、沙暴、雨天 | 全战场 | 否 | 是 |
| 技能槽修正 | 技能能耗、技能威力、冷却、技能位置、使用次数、技能变形 | 技能槽或全技能 | 视技能而定 | 是，建议显示在技能图标上 |
| 行动规则状态 | 先手、迅捷、蓄力、打断、无法更换、脱离、返场 | 本回合、下回合或指定精灵 | 视技能而定 | 是，若持续到后续时点 |
| 资源 / 生命结算 | 回复、偷取能量、失去能量、交换生命比例 | 瞬时事件 | 不适用 | 通常不常驻，仅记录事件 |
| 状态操作 | 驱散、转移、转换、交换、继承、翻倍 | 操作其他状态 | 不适用 | 操作本身不常驻，被操作后的状态显示 |

---

### 3.11 普通增益 / 减益

普通增益 / 减益指直接修正当前精灵属性、技能威力、连击数、吸血等数值的效果。

典型例子包括：

- 物攻 +100%、物攻 +130%、物攻 -130%。
- 物防 +140%、物防 -80%、物防和魔防 -120%。
- 魔攻 +70%、魔攻 +190%。
- 魔防 +170%、魔防 -100%。
- 速度 +80、速度 +120、速度 -90。
- 技能威力 +20、全技能威力 +40、下一次攻击技能威力 +70。
- 连击数 +3、连击数 -4、行动时连击数 +100%。
- 吸血 +100%。

默认规则：

```text
普通增益 / 减益默认绑定当前在场精灵。
如果该精灵切换离场，默认清除。
如果技能说明含有“永久”“继承”“场下”“背包”“下个入场精灵继承”等关键词，则按技能特殊规则处理。
```

也就是说，物攻降低、物防降低、双防降低、魔防降低这类普通减益可以通过切换在场精灵来消除。

---

### 3.12 异常 / 层数状态

异常 / 层数状态不应简单归入普通减益，因为它们往往具有独立层数、独立结算、独立清除规则。

当前状态技能表中至少出现以下异常 / 层数状态：

| 状态 | 典型来源技能 | 处理建议 |
| --- | --- | --- |
| 冻结 | 冰点、霜天、霜降 | 明确设置 `clear_on_switch = false`，因为冰冻不能通过切换消除 |
| 中毒 | 剧毒、毒孢子、束缚、捆缚 | 作为可叠层异常，是否切换保留需要实测确认，建议先配置为可单独调整 |
| 灼烧 | 天火、引燃、焚烧烙印、炎爆术 | 作为可叠层异常，支持翻倍、触发灼烧伤害、印记转换 |
| 寄生 | 孢子 | 作为特殊异常，结算规则单独配置 |
| 眩晕 | 摇篮曲、芳香诱引 | 作为行动控制异常，按回合持续 |
| 萌化 | 退化、甜心续航、生日蛋糕、示弱、赤子之心、柔弱、玩具乐园、逆向演化 | 作为特殊层数状态，可作用于自己、敌方、场下或背包精灵 |
| 奉献 | 假寐、束缚、虫群智慧、虫茧、捆缚 | 作为次数型触发状态，后续触发不同追加效果 |

冻结已经明确不能通过切换消除；中毒、灼烧、萌化、奉献等是否切换消除，不应靠“大类”推断，必须在状态数据库中逐项配置 `clear_on_switch`。星陨已归入印记，按印记规则处理：切换不清除，只有明确消除 / 驱散 / 转换印记的技能才能处理。

---

### 3.13 印记

印记应单独建模，不能和普通增益 / 减益混在一起。

印记的核心规则为：

```text
印记绑定在队伍侧，而不是单纯绑定当前在场精灵。
切换当前在场精灵不会清除印记。
印记只有被明确消除印记、驱散印记、转换印记的技能处理时才会消失或转换。
每个队伍最多同时存在 1 个增益印记和 1 个减益印记。
```

每个队伍维护两个印记槽：

```text
SideMarkState {
  side_id
  positive_mark_slot
  negative_mark_slot
}
```

星陨修正规则：

```text
星陨属于减益印记。
星陨占用目标队伍的 negative_mark_slot。
星陨可以有层数。
星陨不会因为切换当前在场精灵而清除。
如果目标队伍已有其他减益印记，获得星陨时按减益印记同槽冲突策略处理。
会“翻倍星陨层数”的技能，只修改星陨这个印记的层数，不应把星陨当作普通减益或异常状态处理。
```

根据状态技能表，当前至少需要支持以下印记：

| 印记方向 | 印记名称 | 来源技能 | 说明 |
| --- | --- | --- | --- |
| 增益印记 | 蓄势印记 | 蓄势待发 | 自己获得 1 层 |
| 增益印记 | 攻击印记 | 主场优势 | 自己获得 1 层 |
| 增益印记 | 湿润印记 | 打湿 | 自己获得 1 层 |
| 增益印记 | 蓄电印记 | 增程电池 | 自己获得 1 层 |
| 增益印记 | 风起印记 | 风起 | 自己获得 1 层 |
| 增益印记 | 光合印记 | 光合作用 | 自己获得 1 层 |
| 增益印记 | 龙噬印记 | 龙威 | 自己获得 1 层 |
| 减益印记 | 减速印记 | 速冻 | 敌方获得 2 层 |
| 减益印记 | 降灵印记 | 降灵 | 敌方获得 1 层 |
| 减益印记 | 棘刺印记 | 棘刺 | 敌方获得 1 层 |
| 减益印记 | 中毒印记 | 疫病吐息 | 敌方获得 1 层 |
| 减益印记 | 星陨 | 二律背反、心灵洞悉、星轨裂变、星链、超新星馈赠、超维投射 | 敌方获得指定层数；作为减益印记占用减益印记槽，不通过切换清除 |

部分技能会读取、驱散或转换印记：

- 心灵洞悉：读取敌方当前印记层数，使敌方获得等量星陨；星陨本身按减益印记处理。
- 焚烧烙印：驱散双方所有印记，每驱散 1 层，敌方获得 5 层灼烧。
- 食腐：驱散敌方印记，每层印记回复自己 10% 生命。
- 炎爆术：将敌方印记转换为三倍的灼烧层数。

推荐同槽冲突策略：

```text
同名印记再次获得：叠加层数或刷新，取决于该印记的 stack_rule。
不同名但同方向印记获得：默认替换旧印记，并记录 replace_mark 事件。
如果实测发现游戏是“新印记无法覆盖旧印记”，则只修改 MarkDefinition.conflict_policy。
```

---

### 3.14 天气 / 战场状态

天气是全战场状态，不属于任何精灵，也不会因为切换精灵而清除。

当前状态技能表中明确出现：

- 冬至：将天气改为暴风雪。
- 沙涌：将天气改为沙暴。
- 落雨：将天气改为雨天。
- 求雨：将天气变为雨天。

处理规则：

```text
BattlefieldState.weather = 当前天气
同一时间只存在一个天气。
新天气出现时替换旧天气。
天气持续时间如果没有明确说明，则先按“持续到被替换或战斗结束”处理，并保留可配置字段。
```

---

### 3.15 技能槽修正与行动规则状态

状态技能表中有大量效果不是直接修正精灵属性，而是修正技能本身或回合行动规则。

技能槽修正包括：

- 全技能能耗 +1、+2、+3。
- 攻击技能能耗 +3、+6。
- 本回合使用的技能能耗 +7。
- 技能能耗 -1、-2、-3、-4、-6。
- 技能冷却 2 回合。
- 交换两侧技能位置。
- 交换两侧技能能耗。
- 交换携带的技能。
- 技能每回合随机变成其他技能。
- 下回合所选技能使用次数 +1。
- 下次技能无需蓄力。

行动规则状态包括：

- 先手 +1、先手 -1。
- 迅捷。
- 蓄力。
- 打断。
- 眩晕。
- 无法更换精灵。
- 脱离。
- 返场。
- 使敌方精灵返场。
- 下个入场精灵继承自己增益。

这类效果不一定进入伤害公式，但必须进入回合执行器、速度判断器、切换合法性判断器和 UI 状态提示。

---

### 3.16 状态生命周期与切换处理

切换精灵时按以下规则处理：

```text
1. 清除该精灵身上 clear_on_switch = true 的普通增益 / 减益。
2. 保留 clear_on_switch = false 的异常、特殊层数状态、永久效果。
3. 保留队伍侧印记槽，不因切换变化。
4. 保留全战场天气。
5. 保留明确绑定技能槽且未被切换清除的技能槽效果。
6. 记录 switch_clear_event，便于之后回看为什么某个修正消失。
```

默认切换清除：

- 物攻、物防、魔攻、魔防、速度的普通加减。
- 双攻、双防的普通加减。
- 普通技能威力增减。
- 普通连击数增减。
- 普通吸血增益。
- 普通能耗增减，前提是该能耗修正绑定当前在场精灵且未写明永久。

默认切换不清除：

- 印记。
- 天气。
- 冻结。
- 明确写明“永久”的效果。
- 明确作用于场下、背包、队伍侧或战场的效果。
- 萌化、奉献等特殊层数状态，除非实测发现会被切换清除。
- 技能数据库中明确配置为 `clear_on_switch = false` 的效果。

---

## 四、属性计算规则

### 4.1 基础公式

#### 4.1.1 生命资质

$$
\text{生命资质} = 1.00 + \text{种族资质} \times 0.02 + \text{个体资质} \times 0.01
$$

#### 4.1.2 非生命五维资质

$$
\text{五维资质} = \text{种族资质} \times 0.01 + \text{个体资质} \times 0.005
$$

#### 4.1.3 基础值

$$
\text{基础值} = 10.00 + \text{种族资质} \times 0.5 + \text{个体资质} \times 0.25
$$

#### 4.1.4 成长值

PVP 对战中，精灵成长值固定为：

$$
\text{生命成长值} = 100
$$

$$
\text{非生命成长值} = 50
$$

---

### 4.2 通用属性公式

属性值的通用计算方式为：

$$
\text{属性值} = \text{基础值} + \text{等级} \times \text{资质值} + \text{成长值}
$$

性格修正不作用于成长值。

---

### 4.3 PVP 化简公式

由于 PVP 中等级固定为 60，并且成长值固定，因此属性公式可以化简为以下形式。

#### 4.3.1 生命属性

$$
\text{生命属性} =
\operatorname{round}
\left(
\left[
70 + 1.7 \times \text{种族资质} + 0.85 \times \text{个体资质}
\right]
\times \text{性格修正}
+ 100
\right)
$$

#### 4.3.2 非生命属性

$$
\text{非生命属性} =
\operatorname{ceil}
\left(
\left[
10 + 1.1 \times \text{种族资质} + 0.55 \times \text{个体资质}
\right]
\times \text{性格修正}
+ 50
\right)
$$

其中：

- 生命属性使用四舍五入。
- 非生命属性使用向上取整。
- 性格修正不作用于成长值。
- 没有个体资质的维度，个体资质按 0 计算。
- 性格可以影响生命属性，也可以影响任意非生命属性。

---

## 五、伤害计算需求

### 5.1 伤害展示方式

所有伤害计算结果都必须同时展示两种形式：

- 准确伤害值
- 生命百分比

示例：

```text
技能 A：
准确伤害：128
生命百分比：42.7%
```

如果敌方配置未确认，则展示区间：

```text
技能 A：
准确伤害：118 ~ 126
生命百分比：38.2% ~ 41.6%
```

如果敌方配置已基本确认，则展示单值：

```text
技能 A：
准确伤害：122
生命百分比：40.1%
```

---

### 5.2 伤害数值与敌方扣血百分比

当前游戏中，每次攻击可以识别到：

- 本次攻击造成的准确伤害数值
- 本次攻击扣除了敌方多少百分比生命

其中：

- 伤害数值一定是整数。
- 敌方扣血百分比可用于辅助反推敌方最大生命。
- 对敌方造成伤害时，准确伤害值和扣血百分比需要同时记录。
- 如果准确伤害值与扣血百分比对应关系不一致，需要标记该事件为低置信度，等待后续伤害校验。

示例：

```text
本次我方攻击敌方：
准确伤害：128
敌方扣血百分比：42.7%

可反推：
敌方最大生命值约为 128 / 42.7% ≈ 300
```

---

### 5.3 多段伤害记录与展示规则

多段伤害在游戏中可能逐段跳出数值，最后显示一个总伤害。

考虑到实时识别性能和程序实现成本，本系统在 MVP 和默认运行模式下 **不要求记录每一段伤害**，而是采用：

```text
多段伤害默认记录最终显示的总伤害
逐段伤害仅作为可选扩展能力
```

#### 5.3.1 默认记录策略：总伤害优先

系统默认需要记录：

- 技能名称。
- 是否为多段伤害。
- 最终显示的总伤害整数值。
- 总扣血百分比，如果可识别。
- 受击前生命百分比，如果可识别。
- 受击后生命百分比，如果可识别。
- 本次伤害发生时的统一状态快照。

示例：

```text
技能 A 为三段伤害：

游戏最后显示总伤害：128
识别结果：
- is_multi_hit = true
- damage_record_mode = multi_total_only
- damage_value = 128
- total_damage_value = 128
- total_hp_percent_damage = 42.7%
```

在这种模式下，`damage_value` 代表本次伤害事件用于推算和展示的主伤害值。

- 单段技能：`damage_value = 单段伤害值`。
- 多段技能：`damage_value = 最终显示的总伤害值`。

这样可以让敌方配置过滤逻辑统一使用 `damage_value`，避免因为无法稳定识别逐段伤害而影响推算流程。

#### 5.3.2 可选扩展策略：逐段详情

后续如果图像识别性能足够，或某些技能的逐段伤害对推算非常关键，可以扩展记录 `hit_details`。

逐段详情可选记录：

- 每一段伤害的准确整数值。
- 每一段伤害对应的扣血百分比，如果可识别。
- 每一段是否触发额外状态。
- 每一段使用的状态快照 ID。

示例：

```text
hit_details = [
  { hit_index: 1, hit_damage_value: 42 },
  { hit_index: 2, hit_damage_value: 43 },
  { hit_index: 3, hit_damage_value: 43 }
]

total_damage_value = 128
```

该能力不是第一阶段必须实现内容。

#### 5.3.3 伤害计算中的多段技能规则

虽然运行时默认只记录总伤害，但技能数据库仍应保存多段技能规则，因为伤害计算模块可能需要知道：

- 技能是否为多段伤害。
- 固定段数、随机段数或受状态影响的段数。
- 理论上每段是否独立进入伤害公式。
- 理论上每段是否独立取整。
- 是否存在“每段命中后触发状态”的技能效果。

开发优先级建议：

```text
第一阶段：只用总伤害参与推算。
第二阶段：技能数据库记录多段规则，但不强制实时识别逐段伤害。
第三阶段：仅对少数关键技能增加逐段识别和逐段推算。
```

对于多段伤害，系统需要根据技能特性判断：

- 总伤害是否可以直接作为推算依据。
- 如果未来实现逐段记录，逐段伤害之和是否等于最终总伤害。
- 防御技能减伤、增伤、减伤、天气、印记等修正是作用于每段，还是作用于总伤害。
- 无法确认逐段规则时，应降低该伤害事件的推算置信度，而不是直接排除大量候选配置。

---

### 5.4 我方攻击敌方的伤害计算

系统输入：

- 我方当前精灵
- 我方技能
- 我方战斗有效属性
- 敌方当前精灵
- 敌方候选配置
- 敌方战斗状态
- 天气
- 印记
- 异常状态
- 增伤 / 减伤
- 防御技能减伤
- 属性克制
- 技能特殊效果

系统输出：

- 每个技能的准确伤害值
- 每个技能的生命百分比
- 区间或单值
- 是否可能击杀
- 是否先手可击杀
- 伤害置信度

示例：

```text
我方当前精灵：A
敌方当前精灵：B

技能 1：
准确伤害：96 ~ 108
生命百分比：31.4% ~ 35.9%
先手击杀可能性：无法击杀

技能 2：
准确伤害：142 ~ 158
生命百分比：46.2% ~ 52.4%
先手击杀可能性：在我方先手且敌方当前生命低于 52.4% 时可能击杀

技能 3：
准确伤害：状态技能，本回合结算伤害
生命百分比：8.1% ~ 10.3%
```

---

### 5.5 敌方攻击我方的伤害计算

系统输入：

- 敌方当前精灵
- 敌方候选配置
- 敌方已知技能或可能技能池
- 敌方战斗状态
- 我方当前精灵
- 我方战斗有效属性
- 天气
- 印记
- 异常状态
- 增伤 / 减伤
- 防御技能减伤
- 属性克制
- 技能特殊效果

系统输出：

- 敌方已知技能对我方的准确伤害值
- 敌方已知技能对我方的生命百分比
- 敌方可能技能对我方的伤害区间
- 敌方技能对我方后备精灵的伤害区间
- 是否可能击杀
- 是否可能先手击杀

示例：

```text
敌方当前精灵：B
我方当前精灵：A

已确认技能：
技能 X：
准确伤害：132 ~ 146
生命百分比：44.0% ~ 48.7%
是否可能击杀：否

可能技能：
技能 Y：
准确伤害：88 ~ 102
生命百分比：29.3% ~ 34.0%

技能 Z：
准确伤害：170 ~ 196
生命百分比：56.7% ~ 65.3%
是否可能先手击杀：取决于敌方速度候选
```

---

## 六、速度与先手判断需求

### 6.1 速度判断目标

系统需要基于双方速度判断常规出手顺序。

由于己方速度已知，敌方速度可能未知，因此系统需要根据敌方候选配置输出：

- 我方必定先手
- 敌方必定先手
- 双方同速
- 存在多个候选速度结果
- 我方综合先手概率
- 敌方综合先手概率

---

### 6.2 敌方速度已确认时

如果敌方速度已经确认，则直接比较双方速度。

```text
if 我方速度 > 敌方速度:
    我方必定先手
elif 我方速度 < 敌方速度:
    敌方必定先手
else:
    双方同速
    我方 50% 概率先手
    敌方 50% 概率先手
```

---

### 6.3 敌方速度未确认时

如果敌方速度未确认，则系统需要遍历敌方候选配置。

示例：

```text
我方速度：168

敌方候选配置：
配置 1：速度 154
配置 2：速度 160
配置 3：速度 168
配置 4：速度 172

判断：
配置 1：我方先手
配置 2：我方先手
配置 3：同速，各 50%
配置 4：敌方先手
```

综合先手概率可以按候选配置数量或候选权重计算。

如果按候选配置数量计算：

```text
我方先手概率 = 我方先手候选占比 + 同速候选占比 × 50%
敌方先手概率 = 敌方先手候选占比 + 同速候选占比 × 50%
```

示例：

```text
候选共 4 个：
我方必定先手候选：2 个
敌方必定先手候选：1 个
同速候选：1 个

我方先手概率 = 2 / 4 + 1 / 4 × 50% = 62.5%
敌方先手概率 = 1 / 4 + 1 / 4 × 50% = 37.5%
```

---

### 6.4 速度展示需求

在当前对位信息中，需要展示速度判断。

展示内容包括：

- 我方速度
- 敌方速度单值或区间
- 我方是否必定先手
- 敌方是否必定先手
- 是否存在同速
- 同速时双方各 50% 先手
- 综合先手概率
- 速度判断置信度

示例：

```text
速度判断：
我方速度：168
敌方速度：168
结果：双方同速，我方 50% 概率先手，敌方 50% 概率先手
```

示例：

```text
速度判断：
我方速度：168
敌方速度候选范围：160 ~ 175
结果：敌方速度未确认，存在被先手风险
综合先手概率：
我方 62.5%
敌方 37.5%
```

---

## 七、敌方配置推算需求

### 7.1 推算目标

系统需要推算的是敌方具体配置，而不是种族资质。

推算目标包括：

- 性格
- 个体资质存在的维度
- 每个个体资质维度的数值
- 最终生命
- 最终物攻
- 最终物防
- 最终魔攻
- 最终魔防
- 最终速度
- 技能组
- 当前战斗状态

---

### 7.2 候选配置结构

每个敌方精灵拥有一个候选配置集合。

候选配置结构如下：

```text
BuildCandidate {
  nature
  individual_talent_distribution
  final_hp
  final_physical_attack
  final_physical_defense
  final_magic_attack
  final_magic_defense
  final_speed
  possible_skills
  match_score
  confidence
  is_excluded
  excluded_reason
}
```

字段说明：

| 字段                           | 含义                                                        |
| ------------------------------ | ----------------------------------------------------------- |
| nature                         | 性格修正，例如物攻 +20%，魔攻 -10%                          |
| individual_talent_distribution | 个体资质分布，例如生命 10 / 物攻 10 / 速度 10，其余维度为 0 |
| final_hp                       | 候选配置下的最终生命属性                                    |
| final_physical_attack          | 候选配置下的最终物攻                                        |
| final_physical_defense         | 候选配置下的最终物防                                        |
| final_magic_attack             | 候选配置下的最终魔攻                                        |
| final_magic_defense            | 候选配置下的最终魔防                                        |
| final_speed                    | 候选配置下的最终速度                                        |
| possible_skills                | 该配置下仍然可能存在的技能                                  |
| match_score                    | 该候选配置与历史伤害证据的匹配分数                          |
| confidence                     | 该候选配置的置信度                                          |
| is_excluded                    | 是否已被排除                                                |
| excluded_reason                | 被排除的原因                                                |

---

### 7.3 我方造成伤害时的反推逻辑

当我方攻击敌方造成伤害时，主要反推敌方防御侧信息。

可反推内容包括：

- 敌方生命
- 敌方物防
- 敌方魔防
- 敌方防御相关性格
- 敌方防御相关个体资质
- 敌方是否存在防御技能减伤
- 敌方是否存在印记、异常等影响

反推流程：

```text
读取我方技能
↓
读取我方攻击属性
↓
读取技能威力、技能类型、属性克制
↓
读取伤害发生时的状态快照
↓
枚举敌方候选配置
↓
计算理论伤害
↓
与实际伤害和敌方扣血百分比对比
↓
排除不匹配候选
↓
保留匹配候选
↓
更新敌方配置置信度
```

---

### 7.4 敌方造成伤害时的反推逻辑

当敌方攻击我方造成伤害时，主要反推敌方攻击侧信息。

可反推内容包括：

- 敌方物攻
- 敌方魔攻
- 敌方攻击相关性格
- 敌方攻击相关个体资质
- 敌方可能使用的技能
- 敌方是否存在增伤
- 敌方是否受到天气、印记、异常等影响

#### 7.4.1 敌方技能已知时

当敌方技能已经通过识别或手动输入确认时：

```text
敌方技能已知
↓
枚举敌方候选配置
↓
计算理论伤害
↓
与实际伤害对比
↓
过滤候选配置
```

#### 7.4.2 敌方技能未知时

当敌方技能未知时，不能只根据伤害直接反推敌方攻击属性。

此时系统需要把“可能技能”和“候选配置”联合枚举。

流程如下：

```text
敌方技能未知
↓
读取该精灵可能技能池
↓
枚举可能技能
↓
枚举敌方候选配置
↓
形成“技能 + 配置”联合候选
↓
计算每组联合候选的理论伤害
↓
与实际伤害对比
↓
保留可能组合
↓
排除不可能组合
```

展示示例：

```text
敌方本次攻击可能情况：

高匹配：
技能 A + 物攻性格 + 物攻个体资质 10
理论伤害：132
实际伤害：134
误差：2

中匹配：
技能 B + 魔攻性格 + 魔攻个体资质 10
理论伤害：128
实际伤害：134
误差：6

已排除：
技能 C
排除原因：理论最高伤害仅为 91，无法解释实际伤害 134
```

---

## 八、战斗事件日志

系统必须记录每一次关键事件，尤其是伤害事件。

原因是：伤害发生时的天气、印记、异常、增益、减益、防御技能等状态，可能和当前画面状态不同。如果不保存事件快照，后续推算会出错。

---

### 8.1 伤害事件结构

```text
DamageEvent {
  event_id
  turn_number
  timestamp

  attacker
  defender
  skill
  skill_confirmed

  damage_value
  hp_percent_before
  hp_percent_after
  hp_percent_delta
  enemy_hp_percent_damage

  is_multi_hit
  damage_record_mode
  total_hit_count
  total_damage_value
  total_hp_percent_damage
  hit_details

  attacker_status_snapshot
  defender_status_snapshot
  weather_snapshot
  mark_snapshot
  abnormal_status_snapshot
  damage_modifier_snapshot
  defense_skill_snapshot

  type_effectiveness
  special_skill_effect

  source
  recognition_confidence
  manual_override
}
```

字段说明：

| 字段                     | 含义                                         |
| ------------------------ | -------------------------------------------- |
| event_id                 | 事件唯一编号                                 |
| turn_number              | 回合编号                                     |
| timestamp                | 事件发生时间                                 |
| attacker                 | 攻击方精灵                                   |
| defender                 | 防御方精灵                                   |
| skill                    | 本次使用技能                                 |
| skill_confirmed          | 技能是否已确认                               |
| damage_value             | 准确伤害值，整数                             |
| hp_percent_before        | 防御方受击前生命百分比                       |
| hp_percent_after         | 防御方受击后生命百分比                       |
| hp_percent_delta         | 血量百分比变化                               |
| enemy_hp_percent_damage  | 本次攻击扣除敌方多少百分比血量               |
| is_multi_hit             | 是否为多段伤害                               |
| damage_record_mode      | 伤害记录模式。单段为 `single`，多段默认为 `multi_total_only`，逐段扩展为 `multi_with_hits` |
| total_hit_count          | 总段数。可由技能数据库推导，运行时无法确认时可为空 |
| total_damage_value       | 多段最终显示总伤害。当前默认以该值作为多段伤害推算依据 |
| total_hp_percent_damage  | 多段总扣血百分比                             |
| hit_details              | 可选逐段伤害详情。MVP 默认不记录             |
| attacker_status_snapshot | 攻击方状态快照                               |
| defender_status_snapshot | 防御方状态快照                               |
| weather_snapshot         | 天气快照                                     |
| mark_snapshot            | 印记快照                                     |
| abnormal_status_snapshot | 异常状态快照                                 |
| damage_modifier_snapshot | 增伤 / 减伤快照                              |
| defense_skill_snapshot   | 防御技能状态快照                             |
| type_effectiveness       | 属性克制结果                                 |
| special_skill_effect     | 技能特殊效果                                 |
| source                   | 信息来源，可为自动识别 / 手动输入 / 系统推算 |
| recognition_confidence   | 识别置信度                                   |
| manual_override          | 是否被用户手动修正                           |

---


### 8.2 状态变化事件结构

v0.3.0 起，状态变化必须独立成事件，不能只作为伤害事件中的附属字段。

```text
EffectChangeEvent {
  event_id
  turn_number
  timestamp

  change_type            // apply / remove / stack / refresh / convert / transfer / dispel / switch_clear
  effect_id
  effect_name
  category
  target_side
  target_pet
  target_skill_slot

  layers_before
  layers_after
  duration_before
  duration_after

  source_skill
  source_actor
  condition_branch       // normal / against_defense / enemy_switched / etc.
  reason

  source
  recognition_confidence
  manual_override
}
```

### 8.3 统一状态快照

原 `weather_snapshot / mark_snapshot / abnormal_status_snapshot / damage_modifier_snapshot / defense_skill_snapshot` 可作为展示层的分组字段，但计算层应使用统一快照：

```text
BattleEffectSnapshot {
  attacker_effects
  defender_effects
  attacker_side_marks
  defender_side_marks
  battlefield_effects
  attacker_skill_slot_effects
  defender_skill_slot_effects
  turn_effects
}
```

伤害事件、治疗事件、能量变化事件、切换事件都应可引用该快照。

---

## 九、图像识别与手动输入需求

### 9.1 自动识别内容

系统需要通过图像识别或 OCR 捕获：

- 准备阶段双方六只精灵
- 当前对位精灵
- 精灵头像
- 技能名称
- 伤害数值
- 敌方扣血百分比
- 生命百分比或血条变化
- 多段伤害最终显示的总伤害
- 多段伤害的总伤害
- 状态栏增益 / 减益图标
- 天气状态
- 印记状态
- 异常状态
- 防御技能状态
- 能量变化
- 精灵切换信息

---

### 9.2 手动输入优先级

图像识别可能失败，因此必须允许手动补充。

优先级规则：

```text
手动输入 > 自动识别 > 系统推算
```

手动输入适用于：

- 修正精灵名称
- 修正技能名称
- 修正伤害数值
- 修正敌方扣血百分比
- 修正多段伤害最终显示的总伤害
- 修正多段伤害总伤害
- 修正状态层数
- 修正天气
- 修正印记
- 修正异常状态
- 修正防御技能状态
- 确认敌方技能
- 确认准备阶段阵容

---

### 9.3 输入效率优化

为了适应 PVP 实时对战，手动输入必须尽可能快。

建议支持：

- 精灵名称关键字搜索
- 技能名称关键字搜索
- 常见技能一键选择
- 状态图标快速选择
- 天气快速选择
- 印记快速选择
- 防御技能快速选择
- 最近使用项
- 战斗事件快速纠错

---

## 十、数据库需求

本节从 v0.3.2 开始不再只列“需要记录什么”，而是补充为可直接指导数据库建表和代码实体定义的字段字典。

### 10.0 字段注释约定

后续表格统一使用以下列：

| 列名 | 含义 |
| --- | --- |
| 字段 | 建议字段名，优先使用英文小写加下划线，运行时结构可使用 camelCase |
| 类型 | 建议逻辑类型，不强制绑定某一种数据库；例如 string、int、decimal、bool、enum、json、array、object、datetime |
| 必填 | `是` 表示创建记录时必须存在；`否` 表示可以为空；`条件` 表示依赖其他字段 |
| 来源 | 字段数据来源，例如数据库录入、准备阶段识别、战斗识别、手动输入、系统计算、战斗事件推导 |
| 说明 | 字段业务含义、计算用途、边界规则、与其他字段的关系 |

建议实现时区分三类数据：

| 数据类型 | 说明 | 示例 |
| --- | --- | --- |
| 静态定义数据 | 游戏规则本身，通常由数据库维护 | 精灵种族资质、技能定义、状态定义、天气定义、印记定义 |
| 战斗运行时数据 | 某一场战斗中动态变化的数据 | 当前血量、当前能量、当前状态实例、当前天气、当前印记槽 |
| 事件日志数据 | 某个时间点发生过的事实记录 | 某回合使用技能、造成伤害、获得状态、驱散印记、切换精灵 |

开发建议：

- 静态定义表用于“查规则”。
- 运行时状态用于“算当前结果”。
- 事件日志用于“回放、纠错、推算、解释为什么变成现在这样”。
- 不建议只保存当前状态而不保存事件，因为伤害推算必须依赖伤害发生瞬间的状态快照。

---

### 10.1 精灵数据库 `PetDefinition`

每只精灵需要记录基础种族信息、系别、可学习技能、常见配置和头像资源。

当前已确认规则：

- 精灵有唯一 ID。
- 精灵有标准名称。
- 精灵没有别名字段。
- 精灵有头像。

因此精灵静态表不设置 `alias_names`，图像识别和搜索都应以 `pet_id`、`pet_name`、`avatar` 为核心。

```text
PetDefinition {
  pet_id
  pet_name
  avatar
  element_types

  base_hp_talent
  base_physical_attack_talent
  base_physical_defense_talent
  base_magic_attack_talent
  base_magic_defense_talent
  base_speed_talent

  learnable_skill_ids
  common_skill_sets
  common_natures
  common_individual_talent_patterns

  forms
  recognition_templates
  data_source
  data_version
  updated_at
}
```

字段说明：

| 字段 | 类型 | 必填 | 来源 | 说明 |
| --- | --- | --- | --- | --- |
| pet_id | string | 是 | 数据库录入 | 精灵唯一 ID。所有运行时状态、敌方候选配置、事件日志、技能归属都应引用该 ID。 |
| pet_name | string | 是 | 数据库录入 | 精灵标准名称。用于 UI 展示、搜索和日志显示。当前不设置精灵别名字段。 |
| avatar | string | 是 | 数据库录入 / 资源维护 | 精灵头像资源 ID、图片路径或资源 URL。用于准备阶段识别、当前对位识别和 UI 展示。 |
| element_types | array<enum> | 是 | 数据库录入 | 精灵系别。可能存在单系或双系，因此使用数组。 |
| base_hp_talent | int | 是 | 数据库录入 | 生命种族资质。参与 PVP 面板属性计算。 |
| base_physical_attack_talent | int | 是 | 数据库录入 | 物攻种族资质。参与 PVP 面板属性计算。 |
| base_physical_defense_talent | int | 是 | 数据库录入 | 物防种族资质。参与 PVP 面板属性计算。 |
| base_magic_attack_talent | int | 是 | 数据库录入 | 魔攻种族资质。参与 PVP 面板属性计算。 |
| base_magic_defense_talent | int | 是 | 数据库录入 | 魔防种族资质。参与 PVP 面板属性计算。 |
| base_speed_talent | int | 是 | 数据库录入 | 速度种族资质。用于速度区间、先手概率和候选配置过滤。 |
| learnable_skill_ids | array<string> | 是 | 数据库录入 | 该精灵所有可能技能 ID。敌方技能未知时用于枚举“技能 + 配置”联合候选。 |
| common_skill_sets | array<array<string>> | 否 | 数据库录入 / 统计 | 常见技能组。用于候选排序，不应直接排除不常见技能。 |
| common_natures | array<object> | 否 | 数据库录入 / 统计 | 常见性格分布。可作为候选初始权重。 |
| common_individual_talent_patterns | array<object> | 否 | 数据库录入 / 统计 | 常见个体资质维度与数值组合。可作为候选初始权重。 |
| forms | array<object> | 否 | 数据库录入 | 形态、皮肤、进化、同名不同形态。若不同形态种族资质不同，应拆成不同 `pet_id`。 |
| recognition_templates | array<object> | 否 | 图像识别维护 | 头像区域、名称区域、颜色特征等识别模板。由于精灵没有别名，识别纠错不依赖别名表。 |
| data_source | string | 否 | 数据库维护 | 数据来源说明，便于后续校验。 |
| data_version | string | 否 | 数据库维护 | 当前精灵数据版本。游戏平衡调整后应更新。 |
| updated_at | datetime | 否 | 系统维护 | 最后更新时间。 |

说明：

- `pet_id` 是精灵事实主键，代码内部不要使用 `pet_name` 作为关联主键。
- `pet_name` 是显示名称和搜索名称，不承担唯一性以外的复杂匹配逻辑。
- 当前不设置 `alias_names`。如果 OCR 识别需要容错，应通过头像模板、名称识别置信度、手动确认流程处理，而不是在精灵表中维护别名。
- `avatar` 为必填字段，因为准备阶段识别、当前对位识别和 UI 展示都依赖头像。
- `learnable_skill_ids` 是敌方技能推算的上限集合。
- `common_skill_sets` 只能影响候选权重，不能作为唯一事实，否则会漏掉冷门配置。
- 若后续出现不同形态但同名显示，应在 `forms` 或独立 `pet_id` 中处理，避免候选属性错误。

---

### 10.2 性格定义表 `NatureDefinition`

虽然性格可以在代码中硬编码枚举，但建议数据库化，方便后续校验和 UI 展示。

```text
NatureDefinition {
  nature_id
  nature_name
  positive_stat
  positive_multiplier
  negative_stat
  negative_multiplier
  neutral_multiplier
}
```

字段说明：

| 字段 | 类型 | 必填 | 来源 | 说明 |
| --- | --- | --- | --- | --- |
| nature_id | string | 是 | 数据库录入 | 性格唯一 ID。 |
| nature_name | string | 是 | 数据库录入 | 性格名称。若暂未整理具体名称，可用 `物攻+魔攻-` 这类规则名。 |
| positive_stat | enum | 是 | 数据库录入 | 正面修正维度。可取 `hp`、`physical_attack`、`physical_defense`、`magic_attack`、`magic_defense`、`speed`。 |
| positive_multiplier | decimal | 是 | 数据库录入 | 当前规则固定为 `1.2`。 |
| negative_stat | enum | 是 | 数据库录入 | 负面修正维度，不能与 `positive_stat` 相同。 |
| negative_multiplier | decimal | 是 | 数据库录入 | 当前规则固定为 `0.9`。 |
| neutral_multiplier | decimal | 是 | 数据库录入 | 未被性格影响的属性倍率，固定为 `1.0`。 |

---

### 10.3 技能数据库 `SkillDefinition`

每个技能需要记录基础信息、伤害规则、连击规则、状态脚本和识别模板。

```text
SkillDefinition {
  skill_id
  skill_name
  alias_names
  skill_icon
  element_type
  skill_category
  base_power
  base_energy_cost
  priority_modifier
  tags

  damage_rule
  hit_rule
  effect_script
  recognition_template

  data_source
  data_version
  updated_at
}
```

字段说明：

| 字段 | 类型 | 必填 | 来源 | 说明 |
| --- | --- | --- | --- | --- |
| skill_id | string | 是 | 数据库录入 | 技能唯一 ID。建议稳定不变，所有日志和状态来源都引用此 ID。 |
| skill_name | string | 是 | 数据库录入 | 技能标准名称。 |
| alias_names | array<string> | 否 | 数据库录入 / 手动维护 | 别名、OCR 常见误识别名。 |
| skill_icon | string | 否 | 数据库录入 | 技能图标资源 ID 或路径。用于 UI 和图像识别。 |
| element_type | enum | 是 | 数据库录入 | 技能系别。用于属性克制、天气影响、同系增强等规则。 |
| skill_category | enum | 是 | 数据库录入 | 技能大类。建议取 `physical`、`magic`、`status`、`special`。状态技能不直接进入普通伤害公式。 |
| base_power | int | 条件 | 数据库录入 | 基础威力。状态技能可为 0 或 null。若威力由脚本决定，应在 `damage_rule` 标注。 |
| base_energy_cost | int | 是 | 数据库录入 | 基础能耗。运行时实际能耗应由技能槽效果和状态效果计算得到。 |
| priority_modifier | int | 否 | 数据库录入 | 先手修正。普通技能为 0；迅捷、先手+1、先手-1 等写入此字段或 `action_modifiers`。 |
| tags | array<enum> | 否 | 数据库录入 / 结构化整理 | 快速粗分类，用于检索和 UI。示例：`quick`、`charge`、`transmission`、`defense_response`、`multi_hit`、`mark_related`、`weather_setter`。 |
| damage_rule | object | 否 | 数据库录入 | 伤害计算规则。攻击技能必填，纯状态技能可为空。详见 `DamageRule`。 |
| hit_rule | object | 否 | 数据库录入 | 连击 / 多段规则。非多段技能可为空或 `{hit_count:1}`。详见 `HitRule`。 |
| effect_script | array<object> | 否 | 数据库录入 | 技能使用后的效果操作列表。状态技能和附加状态攻击技能都需要。详见 `EffectOperation`。 |
| recognition_template | object | 否 | 图像识别维护 | 技能名称、图标、技能格位置等识别模板。 |
| data_source | string | 否 | 数据库维护 | 原始数据来源。 |
| data_version | string | 否 | 数据库维护 | 技能数据版本。 |
| updated_at | datetime | 否 | 系统维护 | 最后更新时间。 |

#### 10.3.1 `DamageRule` 字段注释

```text
DamageRule {
  damage_type
  attack_stat
  defense_stat
  power_source
  fixed_damage_value
  percent_damage_base
  ignore_defense
  ignore_type_effectiveness
  can_critical
  affected_by_attack_stat_stage
  affected_by_defense_stat_stage
  affected_by_weather
  affected_by_mark
  affected_by_abnormal
  affected_by_damage_modifier
  rounding_policy
  special_formula_id
}
```

| 字段 | 类型 | 必填 | 来源 | 说明 |
| --- | --- | --- | --- | --- |
| damage_type | enum | 是 | 数据库录入 | `normal_formula` 普通公式、`fixed` 固定伤害、`percent_hp` 百分比伤害、`special_formula` 特殊公式。 |
| attack_stat | enum | 条件 | 数据库录入 | 攻击侧属性。物理技能通常为 `physical_attack`，魔法技能通常为 `magic_attack`。固定伤害可为空。 |
| defense_stat | enum | 条件 | 数据库录入 | 防御侧属性。物理技能通常为 `physical_defense`，魔法技能通常为 `magic_defense`。固定伤害可为空。 |
| power_source | enum | 否 | 数据库录入 | 威力来源。建议取 `base_power`、`dynamic_by_effect`、`dynamic_by_hp`、`dynamic_by_energy`、`none`。 |
| fixed_damage_value | int | 条件 | 数据库录入 | 固定伤害值，仅 `damage_type=fixed` 时使用。 |
| percent_damage_base | enum | 条件 | 数据库录入 | 百分比伤害基准。可取 `target_max_hp`、`target_current_hp`、`self_max_hp`、`self_lost_hp` 等。 |
| ignore_defense | bool | 是 | 数据库录入 | 是否无视防御属性。 |
| ignore_type_effectiveness | bool | 是 | 数据库录入 | 是否无视属性克制。 |
| can_critical | bool | 否 | 数据库录入 | 当前阶段暂不考虑暴击，可默认 false 或预留。 |
| affected_by_attack_stat_stage | bool | 是 | 数据库录入 | 是否受攻击方攻/魔攻增减影响。 |
| affected_by_defense_stat_stage | bool | 是 | 数据库录入 | 是否受防御方防/魔防增减影响。 |
| affected_by_weather | bool | 是 | 数据库录入 | 是否受天气影响。具体影响仍由天气 `effect_hooks` 决定。 |
| affected_by_mark | bool | 是 | 数据库录入 | 是否受印记影响。具体影响由印记定义决定。 |
| affected_by_abnormal | bool | 是 | 数据库录入 | 是否受冻结、中毒、灼烧、萌化等异常 / 层数状态影响。 |
| affected_by_damage_modifier | bool | 是 | 数据库录入 | 是否受通用增伤 / 减伤、吸血、反伤等伤害修正影响。 |
| rounding_policy | enum | 条件 | 待实测 / 数据库录入 | 取整策略。完整伤害公式确认后补充，例如 `floor_final`、`round_final`、`ceil_final`、`stepwise`。 |
| special_formula_id | string | 条件 | 数据库录入 / 代码实现 | 特殊公式 ID。复杂技能不要硬塞布尔字段，应指向代码中的特殊公式处理器。 |

#### 10.3.2 `HitRule` 字段注释

`HitRule` 描述技能理论上的多段 / 连击规则。它主要服务于伤害计算和技能效果解释，不代表运行时一定要识别每一段伤害。

```text
HitRule {
  is_multi_hit
  hit_count_type
  fixed_hit_count
  min_hit_count
  max_hit_count
  hit_count_modifier_source
  per_hit_independent_calculation
  per_hit_independent_rounding
  per_hit_effect_script
  total_damage_displayed
  runtime_record_mode
}
```

| 字段 | 类型 | 必填 | 来源 | 说明 |
| --- | --- | --- | --- | --- |
| is_multi_hit | bool | 是 | 数据库录入 | 是否多段 / 连击。 |
| hit_count_type | enum | 是 | 数据库录入 | `single`、`fixed`、`random_range`、`modified_by_effect`、`skill_specific`。 |
| fixed_hit_count | int | 条件 | 数据库录入 | 固定段数，例如 2 连击、3 连击。 |
| min_hit_count | int | 条件 | 数据库录入 | 随机或变动段数下限。 |
| max_hit_count | int | 条件 | 数据库录入 | 随机或变动段数上限。 |
| hit_count_modifier_source | string | 否 | 数据库录入 | 连击数受到哪个状态或技能影响。例如 `combo_count_effect`。 |
| per_hit_independent_calculation | bool | 否 | 数据库录入 / 待实测 | 理论上每段是否独立进入伤害公式。该字段用于公式研究，不要求 MVP 运行时识别逐段伤害。 |
| per_hit_independent_rounding | bool | 否 | 数据库录入 / 待实测 | 理论上每段是否独立取整。该字段用于公式研究，不要求 MVP 运行时识别逐段伤害。 |
| per_hit_effect_script | array<object> | 否 | 数据库录入 | 每段命中后触发的状态脚本。例如“每次连击给敌方 1 层星陨”。MVP 可先不实现逐段触发，只做技能级近似。 |
| total_damage_displayed | bool | 是 | 图像识别 / 数据库录入 | 游戏是否显示总伤害。当前默认依赖最终显示总伤害进行记录和推算。 |
| runtime_record_mode | enum | 是 | 系统配置 / 数据库录入 | 运行时记录策略。建议取 `total_only`、`hit_optional`、`hit_required`。默认 `total_only`。 |

运行时建议：

```text
默认：runtime_record_mode = total_only
含义：只记录最终显示总伤害，不强制记录每段伤害。
```

只有当某个技能的逐段触发会显著影响状态变化或推算结果时，才将其配置为 `hit_optional` 或 `hit_required`。

#### 10.3.3 `EffectOperation` 字段注释

技能效果不要只写自然语言，建议拆成多个原子操作。

```text
EffectOperation {
  op_id
  op_type
  target
  effect_id
  mark_id
  weather_id
  stat_key
  skill_slot_selector
  value_type
  value
  layers
  duration_turns
  duration_uses
  condition
  timing
  probability
  can_be_manual_corrected
  note
}
```

| 字段 | 类型 | 必填 | 来源 | 说明 |
| --- | --- | --- | --- | --- |
| op_id | string | 是 | 数据库录入 / 系统生成 | 技能内原子操作 ID，用于调试和事件解释。 |
| op_type | enum | 是 | 数据库录入 | 操作类型。建议枚举见“附录 B”。例如 `apply_effect`、`apply_mark`、`set_weather`、`modify_energy`、`dispel_effect`、`convert_effect`、`switch_pet`。 |
| target | enum | 是 | 数据库录入 | 操作目标。示例：`self_active_pet`、`enemy_active_pet`、`self_side`、`enemy_side`、`battlefield`、`selected_skill_slot`、`all_bench_pets`。 |
| effect_id | string | 条件 | 数据库录入 | 应用普通状态、异常、技能槽效果时使用。若 `op_type=apply_effect` 必填。 |
| mark_id | string | 条件 | 数据库录入 | 应用印记时使用。若 `op_type=apply_mark` 必填。星陨应作为 `mark_id=starfall` 或类似 ID。 |
| weather_id | string | 条件 | 数据库录入 | 设置天气时使用。若 `op_type=set_weather` 必填。 |
| stat_key | enum | 条件 | 数据库录入 | 修改属性时使用，例如 `physical_attack`、`magic_defense`、`speed`。 |
| skill_slot_selector | enum/object | 条件 | 数据库录入 | 修改技能槽时使用。例如 `all_skills`、`attack_skills`、`current_used_skill`、`left_neighbor`、`right_neighbor`、`slot_1`。 |
| value_type | enum | 条件 | 数据库录入 | 数值类型。建议取 `flat`、`percent`、`multiplier`、`layer_count`、`formula`。 |
| value | decimal/string | 条件 | 数据库录入 | 实际数值或公式引用。例如 `+40`、`-3`、`2x`、`enemy_total_energy_cost / 2`。 |
| layers | int/formula | 条件 | 数据库录入 | 叠加层数。可为固定值，也可为公式，如“等于敌方印记层数”。 |
| duration_turns | int | 否 | 数据库录入 | 持续回合数。不填时读取 `EffectDefinition.default_duration`。 |
| duration_uses | int | 否 | 数据库录入 | 持续使用次数，例如“下次技能”。 |
| condition | enum/object | 否 | 数据库录入 | 生效条件。示例：`normal`、`against_defense`、`enemy_switched`、`if_target_has_mark`、`if_self_slot_1`。 |
| timing | enum | 否 | 数据库录入 | 触发时点。示例：`on_skill_use`、`before_damage`、`after_damage`、`on_turn_end`、`on_switch_in`。 |
| probability | decimal | 否 | 数据库录入 | 概率。当前阶段多数为 1.0，暂不考虑命中率时可保留默认值。 |
| can_be_manual_corrected | bool | 是 | 系统设计 | 是否允许手动修正。状态识别不稳定时建议 true。 |
| note | string | 否 | 数据库维护 | 人类可读备注，保存原始文本或录入说明。 |

---

### 10.4 状态效果数据库 `EffectDefinition`

状态效果数据库记录所有会在战斗中以图标、层数、属性修正、伤害修正、能耗修正、行动规则或结算规则存在的效果。

```text
EffectDefinition {
  effect_id
  name
  category
  sub_category
  polarity
  icon_id

  scope
  can_apply_to_active
  can_apply_to_bench
  can_apply_to_side
  can_apply_to_battlefield
  can_apply_to_skill_slot

  default_layers
  max_layers
  stack_rule
  conflict_group
  conflict_policy

  duration_type
  default_duration
  clear_on_switch
  clear_by_normal_dispel
  clear_by_mark_dispel
  clear_by_abnormal_cleanse

  stat_modifiers
  damage_modifiers
  skill_cost_modifiers
  skill_power_modifiers
  action_modifiers
  trigger_rules
  settlement_rules

  is_visible_icon
  display_group
  manual_editable
}
```

字段说明：

| 字段 | 类型 | 必填 | 来源 | 说明 |
| --- | --- | --- | --- | --- |
| effect_id | string | 是 | 数据库录入 | 状态效果唯一 ID。运行时实例通过该字段引用定义。 |
| name | string | 是 | 数据库录入 | 状态名称，例如冻结、中毒、灼烧、物攻提升、全技能能耗+3、萌化、奉献。 |
| category | enum | 是 | 数据库录入 | 状态大类。建议取值见附录 B：`normal_buff`、`normal_debuff`、`abnormal_stack`、`skill_slot_modifier`、`action_rule`、`damage_modifier`、`defense_skill_state`、`special_mechanic` 等。 |
| sub_category | enum/string | 否 | 数据库录入 | 子类。示例：`stat_change`、`energy_cost_change`、`power_change`、`cannot_switch`、`stun`、`quick`、`charge`、`sacrifice`、`cute化/萌化`。 |
| polarity | enum | 是 | 数据库录入 | 对拥有者的倾向：`positive`、`negative`、`neutral`、`mixed`。例如“自己双攻+130%且双防-40%”可拆成两个实例，也可标为 mixed。 |
| icon_id | string | 否 | 数据库录入 | 状态图标 ID。若 `is_visible_icon=true`，建议必填。 |
| scope | enum | 是 | 数据库录入 | 作用范围。建议取 `pet`、`side`、`battlefield`、`skill_slot`、`turn_context`。 |
| can_apply_to_active | bool | 是 | 数据库录入 | 是否可作用于当前在场精灵。 |
| can_apply_to_bench | bool | 是 | 数据库录入 | 是否可作用于后备精灵。萌化、场下回复等需要支持。 |
| can_apply_to_side | bool | 是 | 数据库录入 | 是否可作用于队伍侧。印记不建议放这里，应进入 `MarkDefinition`，但队伍级普通效果可使用。 |
| can_apply_to_battlefield | bool | 是 | 数据库录入 | 是否可作用于全战场。天气建议独立 `WeatherDefinition`，其他场地效果可使用。 |
| can_apply_to_skill_slot | bool | 是 | 数据库录入 | 是否作用于技能格或技能本身，如能耗+3、威力+40、冷却 2 回合、技能变形。 |
| default_layers | int | 否 | 数据库录入 | 默认层数。无层数概念的状态可为 1。 |
| max_layers | int | 否 | 数据库录入 | 最大层数。未知时可为空，但应在“仍需确认”中标记。 |
| stack_rule | enum | 是 | 数据库录入 | 叠加规则。见附录 B，例如 `add_layers`、`replace`、`refresh_duration`、`keep_max`、`separate_instances`。 |
| conflict_group | string | 否 | 数据库录入 | 冲突组 ID。同组状态可能互斥或替换，例如某些同类技能槽改造。 |
| conflict_policy | enum | 否 | 数据库录入 | 冲突处理。见附录 B，例如 `replace_old`、`reject_new`、`merge_layers`、`skill_specific`。 |
| duration_type | enum | 是 | 数据库录入 | 持续类型。建议取 `instant`、`turns`、`uses`、`permanent_until_switch`、`permanent_until_dispelled`、`battle_permanent`、`skill_specific`。 |
| default_duration | int | 否 | 数据库录入 | 默认持续回合或次数。具体含义由 `duration_type` 决定。 |
| clear_on_switch | bool | 是 | 数据库录入 | 切换当前在场精灵时是否清除。普通攻击/防御下降通常 true；冻结明确 false；印记不使用该表或固定 false。 |
| clear_by_normal_dispel | bool | 是 | 数据库录入 | 是否可被“驱散增益/减益”处理。普通增益/减益通常 true。 |
| clear_by_mark_dispel | bool | 是 | 数据库录入 | 是否可被“驱散印记”处理。普通状态通常 false；印记在 `MarkDefinition` 中处理。 |
| clear_by_abnormal_cleanse | bool | 是 | 数据库录入 | 是否可被异常净化处理。例如中毒、灼烧、冻结等。 |
| stat_modifiers | array<object> | 否 | 数据库录入 | 属性修正列表。示例：`[{stat:"speed", value_type:"flat", value:-90}]` 或 `{stat:"physical_attack", value_type:"percent", value:100}`。 |
| damage_modifiers | array<object> | 否 | 数据库录入 | 增伤、减伤、吸血、反伤、最终伤害倍率等。注意防御技能减伤可作为 `defense_skill_state`。 |
| skill_cost_modifiers | array<object> | 否 | 数据库录入 | 技能能耗修正，例如全技能能耗+3、攻击技能能耗+6、下次技能能耗-6。 |
| skill_power_modifiers | array<object> | 否 | 数据库录入 | 技能威力修正，例如光系技能威力+40%、全技能威力+40、下一次攻击技能威力翻倍。 |
| action_modifiers | array<object> | 否 | 数据库录入 | 行动相关修正，例如先手+1、先手-1、迅捷、蓄力、打断、眩晕、无法更换、脱离、返场。 |
| trigger_rules | array<object> | 否 | 数据库录入 | 触发规则，例如回合结束触发、受击后触发、切换入场触发、应对防御触发。 |
| settlement_rules | array<object> | 否 | 数据库录入 | 结算规则，例如灼烧伤害、中毒伤害、寄生回复、生命交换、能量偷取。 |
| is_visible_icon | bool | 是 | 数据库录入 | 只要状态生效且该值为 true，游戏内应显示图标，系统 UI 也显示。瞬时结算事件通常 false。 |
| display_group | enum | 是 | 数据库录入 | UI 分区。建议取 `pet_status_bar`、`side_mark_bar`、`battlefield_top`、`skill_slot_badge`、`bench_panel`、`event_log_only`。 |
| manual_editable | bool | 是 | 系统设计 | 是否允许用户在战斗中手动修正。识别可能失败的状态建议 true。 |

说明：

- “属性下降”与“印记”必须分开建模。攻击下降、防御下降、速度下降属于普通减益，通常可切换清除；星陨、棘刺、减速印记等属于印记，不因切换清除。
- 星陨应进入 `MarkDefinition`，不应进入普通 `EffectDefinition` 的异常 / 层数状态。
- 冻结属于异常 / 层数状态，但 `clear_on_switch=false`。
- 若某个技能写着“使敌方减益层数翻倍”，默认只影响 `category=normal_debuff` 的状态，不影响印记，除非技能明确写明印记。

---

### 10.5 印记数据库 `MarkDefinition`

印记独立维护，不混入普通增益 / 减益。每个队伍最多同时存在一个增益印记和一个减益印记。

```text
MarkDefinition {
  mark_id
  mark_name
  polarity
  icon_id
  max_layers
  stack_rule
  conflict_policy
  effect_hooks
  clear_on_switch
  clear_by_normal_dispel
  clear_by_mark_dispel
  display_group
  manual_editable
}
```

字段说明：

| 字段 | 类型 | 必填 | 来源 | 说明 |
| --- | --- | --- | --- | --- |
| mark_id | string | 是 | 数据库录入 | 印记唯一 ID。例如 `starfall`、`spike_mark`、`slow_mark`、`charge_mark`。 |
| mark_name | string | 是 | 数据库录入 | 印记显示名称。星陨在此表中维护。 |
| polarity | enum | 是 | 数据库录入 | `positive` 或 `negative`。队伍侧以该字段决定进入增益印记槽还是减益印记槽。 |
| icon_id | string | 否 | 数据库录入 | 印记图标 ID。印记生效后必须在印记槽显示，因此建议必填。 |
| max_layers | int | 否 | 数据库录入 / 待确认 | 最大层数。未知时可为空，但 UI 应展示当前已识别层数。 |
| stack_rule | enum | 是 | 数据库录入 | 同一印记重复获得时如何叠加。常见为 `add_layers`。 |
| conflict_policy | enum | 是 | 数据库录入 | 同一队伍同极性已有其他印记时如何处理。默认建议 `replace_old`，若游戏规则不同再修正。 |
| effect_hooks | array<object> | 否 | 数据库录入 | 印记造成的具体影响，例如受击增伤、行动结算、技能特殊联动。没有明确效果时也要记录层数。 |
| clear_on_switch | bool | 是 | 固定规则 | 印记不因切换精灵清除，固定为 false。 |
| clear_by_normal_dispel | bool | 是 | 固定规则 | 普通驱散增益 / 减益默认不清除印记，固定为 false。 |
| clear_by_mark_dispel | bool | 是 | 固定规则 / 数据库录入 | 是否可被消除印记的技能处理。通常 true。 |
| display_group | enum | 是 | 固定规则 | 固定为 `side_mark_bar`。 |
| manual_editable | bool | 是 | 系统设计 | 是否允许手动修正层数。建议 true。 |

#### 10.5.1 当前明确的印记规则

| 规则 | 说明 |
| --- | --- |
| 作用范围 | 队伍侧，不绑定某一只在场精灵 |
| 槽位限制 | 每队最多一个增益印记和一个减益印记 |
| 切换处理 | 切换在场精灵不清除印记 |
| 普通驱散 | 普通“驱散增益 / 减益”不处理印记 |
| 印记驱散 | 只有明确写明驱散、消除、转换印记的技能可以处理印记 |
| 星陨分类 | 星陨是减益印记，不是异常，也不是普通减益 |

---

### 10.6 天气数据库 `WeatherDefinition`

天气为全战场状态，同一时间只存在一个天气。新天气出现时替换旧天气。

```text
WeatherDefinition {
  weather_id
  weather_name
  icon_id
  duration_type
  default_duration
  replacement_rule
  effect_hooks
  is_visible_icon
  display_group
  manual_editable
}
```

字段说明：

| 字段 | 类型 | 必填 | 来源 | 说明 |
| --- | --- | --- | --- | --- |
| weather_id | string | 是 | 数据库录入 | 天气唯一 ID，例如 `rain`、`sandstorm`、`blizzard`。 |
| weather_name | string | 是 | 数据库录入 | 天气显示名称，例如雨天、沙暴、暴风雪。 |
| icon_id | string | 否 | 数据库录入 | 天气图标 ID。天气生效后应在战场顶部显示。 |
| duration_type | enum | 是 | 数据库录入 | 持续类型。若未确认天气持续回合，可先标记为 `unknown` 或 `skill_specific`。 |
| default_duration | int | 否 | 数据库录入 / 待确认 | 默认持续回合数。永久天气可为空。 |
| replacement_rule | enum | 是 | 数据库录入 | 新天气与旧天气冲突时的规则。当前建议 `replace_existing_weather`。 |
| effect_hooks | array<object> | 否 | 数据库录入 | 天气对技能威力、能耗、伤害、状态结算的影响。 |
| is_visible_icon | bool | 是 | 固定规则 | 天气生效时显示图标，通常 true。 |
| display_group | enum | 是 | 固定规则 | 固定为 `battlefield_top`。 |
| manual_editable | bool | 是 | 系统设计 | 是否允许手动修正天气。建议 true。 |

---

### 10.7 战斗事件日志数据库 `BattleEventLog`

事件日志是后续推算和纠错的核心。建议所有关键变化都落事件表，而不是只改当前状态。

```text
BattleEventLog {
  event_id
  battle_id
  turn_number
  action_order
  timestamp
  event_type
  actor_side
  actor_pet_id
  target_side
  target_pet_id
  skill_id
  payload
  state_snapshot_id
  source
  recognition_confidence
  manual_override
  created_at
}
```

字段说明：

| 字段 | 类型 | 必填 | 来源 | 说明 |
| --- | --- | --- | --- | --- |
| event_id | string | 是 | 系统生成 | 事件唯一 ID。 |
| battle_id | string | 是 | 系统生成 | 所属对战 ID。 |
| turn_number | int | 是 | 系统记录 / 手动修正 | 回合编号。无法稳定识别时允许手动修正。 |
| action_order | int | 否 | 系统记录 | 同一回合内的事件顺序。多段伤害、状态结算需要依赖顺序。 |
| timestamp | datetime | 是 | 系统记录 | 事件发生时间。 |
| event_type | enum | 是 | 系统记录 | 事件类型。示例：`skill_use`、`damage`、`effect_change`、`mark_change`、`weather_change`、`switch`、`energy_change`、`hp_change`。 |
| actor_side | enum | 否 | 识别 / 系统推导 | 行动方队伍：`self` 或 `enemy`。全局天气变化可为空。 |
| actor_pet_id | string | 否 | 识别 / 系统推导 | 行动方精灵 ID。 |
| target_side | enum | 否 | 识别 / 系统推导 | 目标队伍。 |
| target_pet_id | string | 否 | 识别 / 系统推导 | 目标精灵 ID。 |
| skill_id | string | 否 | 识别 / 手动输入 | 关联技能。非技能事件可为空。 |
| payload | json | 是 | 系统记录 | 事件详情。伤害数值、状态变化、印记层数、天气 ID 等放入此字段。 |
| state_snapshot_id | string | 否 | 系统记录 | 事件发生前或发生时的状态快照 ID。伤害事件强烈建议必填。 |
| source | enum | 是 | 系统记录 | 信息来源：`auto_recognition`、`manual_input`、`system_inferred`、`database_rule`。 |
| recognition_confidence | decimal | 否 | 图像识别 | 识别置信度，范围 0 到 1。手动输入可为 1。 |
| manual_override | bool | 是 | 系统记录 | 是否被用户手动修正过。 |
| created_at | datetime | 是 | 系统生成 | 入库时间。 |

---

### 10.8 推荐数据库表拆分

实际落库时可以按以下方式拆分：

| 表名 | 用途 | 关键字段 |
| --- | --- | --- |
| pet_definitions | 精灵静态定义 | pet_id、pet_name、六维种族资质 |
| nature_definitions | 性格定义 | nature_id、positive_stat、negative_stat |
| skill_definitions | 技能静态定义 | skill_id、skill_name、element_type、base_energy_cost |
| skill_effect_operations | 技能效果脚本拆表 | skill_id、op_type、target、effect_id、mark_id、weather_id、condition、timing |
| effect_definitions | 普通状态 / 异常 / 技能槽 / 行动规则定义 | effect_id、category、clear_on_switch、display_group |
| mark_definitions | 印记定义 | mark_id、polarity、max_layers、conflict_policy |
| weather_definitions | 天气定义 | weather_id、replacement_rule、effect_hooks |
| battle_sessions | 单场战斗 | battle_id、started_at、finished_at |
| battle_pet_states | 单场战斗中的精灵运行时状态 | battle_id、side、pet_id、current_hp_percent、energy |
| battle_effect_instances | 当前或历史状态实例 | instance_id、battle_id、effect_id、owner_pet、layers、remaining_turns |
| battle_side_mark_states | 队伍侧印记槽 | battle_id、side_id、positive_mark_slot、negative_mark_slot |
| battle_events | 战斗事件日志 | event_id、battle_id、turn_number、event_type、payload |
| battle_state_snapshots | 伤害 / 推算快照 | snapshot_id、battle_id、turn_number、snapshot_json |
| enemy_build_candidates | 敌方候选配置 | battle_id、enemy_pet_id、nature_id、individual_talent_distribution、match_score、is_excluded |
| damage_calculation_results | 伤害计算缓存 | battle_id、attacker、defender、skill_id、damage_min、damage_max、confidence |

---

### 10.9 索引与唯一约束建议

| 对象 | 建议 |
| --- | --- |
| pet_definitions | `pet_id` 唯一；`pet_name` 建普通索引；`avatar` 建资源引用索引或普通索引 |
| skill_definitions | `skill_id` 唯一；`skill_name` 建普通索引；`element_type` 建过滤索引 |
| effect_definitions | `effect_id` 唯一；`category`、`display_group` 建过滤索引 |
| mark_definitions | `mark_id` 唯一；`polarity` 建过滤索引 |
| battle_events | `(battle_id, turn_number, action_order)` 组合索引，用于回放和推算 |
| battle_effect_instances | `(battle_id, owner_side, owner_pet, effect_id)` 索引，用于快速读取当前状态 |
| enemy_build_candidates | `(battle_id, enemy_pet_id, is_excluded)` 索引，用于快速过滤候选 |
| battle_state_snapshots | `(battle_id, turn_number)` 索引；伤害事件可直接引用 `snapshot_id` |

---

## 十一、信息展示需求

系统需要在独立页面展示所有核心信息。

---

### 11.1 当前对位信息

展示内容：

- 我方当前精灵
- 敌方当前精灵
- 天气
- 印记
- 双方状态
- 双方能量
- 双方生命状态
- 敌方配置置信度
- 双方速度关系
- 先手判断
- 同速概率提示
- 防御技能状态

---


### 11.1.1 状态图标分区展示

状态图标不应全部塞入“双方状态”一个区域，而应按作用范围分区显示：

| 区域 | 显示内容 |
| --- | --- |
| 精灵状态栏 | 当前精灵身上的普通增益 / 减益、异常、萌化、奉献、行动限制等 |
| 队伍侧状态栏 | 增益印记槽、减益印记槽、队伍级状态 |
| 战场顶部 | 天气、全局场地效果 |
| 技能图标角标 | 能耗变化、威力变化、冷却、连击数、使用次数、蓄力变化、传动等 |
| 后备精灵面板 | 场下精灵拥有的萌化、生命 / 能量变化、可见持久状态 |
| 事件日志 | 瞬时回复、偷取能量、交换生命、驱散、转换、转移等操作 |

状态显示规则：

```text
只要 BattleEffectInstance 存在且 is_visible_icon = true，就显示图标。
瞬时事件不显示常驻图标，但必须进入事件日志。
同类状态过多时按 display_group 折叠，鼠标悬停或点击展开层数与来源。
```

印记显示规则：

```text
每个队伍固定显示两个印记槽：
[增益印记槽] [减益印记槽]
```

如果印记槽有印记，需要展示印记图标、印记名称、层数、来源技能、是否可被印记驱散技能处理。

---

### 11.2 速度判断展示

展示内容：

- 我方速度
- 敌方速度单值或区间
- 我方是否必定先手
- 敌方是否必定先手
- 是否存在同速
- 同速时双方各 50% 先手
- 综合先手概率
- 速度判断置信度

示例：

```text
速度判断：
我方速度：168
敌方速度：168
结果：双方同速，我方 50% 概率先手，敌方 50% 概率先手
```

示例：

```text
速度判断：
我方速度：168
敌方速度候选范围：160 ~ 175
结果：敌方速度未确认，存在被先手风险
综合先手概率：
我方 62.5%
敌方 37.5%
```

---

### 11.3 我方技能对敌方伤害

每个技能展示：

- 技能名称
- 准确伤害值
- 生命百分比
- 是否克制
- 是否受天气影响
- 是否受印记影响
- 是否受防御技能减伤影响
- 是否存在区间
- 是否可能击杀
- 是否可能先手击杀
- 伤害置信度

示例：

```text
我方技能伤害预测：

技能 A：
准确伤害：120 ~ 136
生命百分比：39.2% ~ 44.8%
说明：敌方个体资质未完全确认，因此为区间

技能 B：
准确伤害：88
生命百分比：28.9%
说明：敌方配置已基本确认

技能 C：
准确伤害：64
生命百分比：21.3%
说明：敌方本回合使用防御技能，伤害受到减免
```

---

### 11.4 敌方技能对我方伤害

展示内容：

- 敌方已知技能
- 敌方可能技能
- 准确伤害值
- 生命百分比
- 是否可能击杀
- 是否可能先手击杀
- 对我方后备精灵的伤害

示例：

```text
敌方技能伤害预测：

已确认技能 X：
对当前我方精灵：
准确伤害：142 ~ 156
生命百分比：47.3% ~ 52.0%

对后备精灵 1：
准确伤害：98 ~ 112
生命百分比：31.1% ~ 35.6%

对后备精灵 2：
准确伤害：可能秒杀
生命百分比：102.4% ~ 118.7%
```

---

### 11.5 敌方配置推算展示

每只敌方精灵展示：

- 精灵名称
- 配置状态
- 可能性格
- 可能个体资质分布
- 可能技能
- 已确认技能
- 实际属性区间
- 速度区间
- 置信度
- 证据数量
- 最近一次更新原因

示例：

```text
敌方精灵 B：

配置置信度：中

可能性格：
- 物攻 +20%，魔攻 -10%
- 速度 +20%，物防 -10%
- 生命 +20%，速度 -10%

可能个体资质：
- 生命 10 / 物攻 10 / 速度 10，其余维度 0
- 生命 10 / 物防 10 / 速度 10，其余维度 0

速度区间：
160 ~ 175

已确认技能：
- 技能 X

可能技能：
- 技能 Y
- 技能 Z

最近更新：
我方技能 A 造成 132 点伤害，扣除敌方 44.0% 生命，排除了 14 个低物防候选配置。
```

---

## 十二、模块设计

| 模块             | 功能                       | 输入                     | 输出             |
| ---------------- | -------------------------- | ------------------------ | ---------------- |
| 准备阶段识别模块 | 识别双方六只精灵           | 准备页面截图 / 手动输入  | 双方阵容         |
| 己方配置管理模块 | 管理己方完整配置           | 玩家提前输入             | 己方配置数据     |
| 敌方建档模块     | 生成敌方候选配置           | 敌方精灵名称 + 数据库    | 敌方候选配置集合 |
| 属性计算模块     | 计算精灵面板属性           | 种族资质、个体资质、性格 | 六维面板属性     |
| 速度判断模块     | 判断双方出手顺序和先手概率 | 双方速度、敌方速度候选   | 先手判断结果     |
| 状态管理模块     | 管理战斗状态修正           | 识别 / 手动输入          | 当前战斗状态     |
| 伤害计算模块     | 计算双方技能伤害           | 技能、属性、状态、公式   | 准确值 + 百分比  |
| 敌方配置推算模块 | 根据伤害过滤候选配置       | 伤害事件 + 候选配置      | 更新后的候选集合 |
| 战斗事件日志模块 | 记录技能和伤害事件         | 战斗快照                 | 可追溯事件记录   |
| 图像识别模块     | 识别精灵、技能、伤害、状态 | 战斗截图                 | 自动识别结果     |
| 手动补充模块     | 修正识别错误               | 用户输入                 | 高优先级修正数据 |
| 展示模块         | 展示伤害和推算结果         | 所有计算结果             | 独立页面 UI      |
| 数据库维护模块   | 维护精灵、技能、状态数据   | 数据录入                 | 可查询数据库     |

---

## 十三、核心数据结构建议

本节描述运行时数据结构。与“十、数据库需求”的区别是：数据库表偏向持久化和查询，运行时结构偏向计算、展示和推算。

### 13.0 运行时字段通用约定

| 约定 | 说明 |
| --- | --- |
| ID 字段 | 运行时对象优先保存 ID，同时可以缓存名称用于展示 |
| 派生字段 | UI 分组字段可以由统一状态实例派生，不应作为计算唯一来源 |
| 快照字段 | 伤害推算必须使用事件发生瞬间的快照，而不是当前最新状态 |
| 置信度字段 | 置信度统一使用 0 到 1；UI 可映射为未知 / 低 / 中 / 高 / 基本确认 |
| 手动修正 | 手动输入优先级最高，所有可修正字段建议保留 `manual_override` 或来源记录 |

---

### 13.1 敌方精灵状态 `EnemyPetState`

```text
EnemyPetState {
  battle_id
  side_id
  pet_id
  pet_name
  species_talent_stats
  possible_builds
  confirmed_stats
  possible_skills
  confirmed_skills

  current_hp_percent
  estimated_current_hp_value
  energy

  battle_effects
  active_normal_buffs
  active_normal_debuffs
  abnormal_stack_states
  skill_slot_effects
  action_rule_effects

  side_positive_mark
  side_negative_mark
  battlefield_weather

  speed_range
  first_move_probability
  confidence
  evidence_log
  last_update_reason
}
```

字段说明：

| 字段 | 类型 | 必填 | 来源 | 说明 |
| --- | --- | --- | --- | --- |
| battle_id | string | 是 | 系统生成 | 所属战斗 ID。 |
| side_id | enum | 是 | 系统记录 | 所属队伍，通常为 `enemy`。如果结构复用给我方，也可为 `self`。 |
| pet_id | string | 是 | 准备阶段识别 / 手动输入 | 精灵 ID。准备阶段可确定。 |
| pet_name | string | 是 | 精灵数据库 | 精灵显示名称。建议由 `pet_id` 派生，方便 UI。 |
| species_talent_stats | object | 是 | 精灵数据库 | 六维种族资质，固定事实，不通过战斗反推。 |
| possible_builds | array<BuildCandidate> | 是 | 敌方建档模块 | 当前仍可能的候选配置集合。每次伤害事件后更新。 |
| confirmed_stats | object | 否 | 系统推算 / 手动确认 | 已基本确认的面板属性。未确认时为空或只填已确认维度。 |
| possible_skills | array<string> | 是 | 精灵数据库 / 推算模块 | 仍可能存在的技能 ID 集合。准备阶段来自技能池，战斗中逐步缩小。 |
| confirmed_skills | array<string> | 否 | 技能识别 / 手动输入 | 已确认敌方使用过或明确携带的技能。 |
| current_hp_percent | decimal | 是 | 图像识别 / 手动输入 | 当前血量百分比。用于击杀判断和最大生命反推。 |
| estimated_current_hp_value | int | 否 | 系统计算 | 估算当前血量值。敌方最大生命未确认时可能是区间或低置信值。 |
| energy | int | 否 | 图像识别 / 手动输入 | 当前能量。影响技能可用性和技能可能性判断。 |
| battle_effects | array<BattleEffectInstance> | 否 | 状态管理模块 | 与该精灵直接相关的统一状态实例。计算层以此为主。 |
| active_normal_buffs | array<BattleEffectInstance> | 否 | 派生 | 普通增益展示分组，由 `battle_effects` 按 category 派生。 |
| active_normal_debuffs | array<BattleEffectInstance> | 否 | 派生 | 普通减益展示分组，切换时通常清除。 |
| abnormal_stack_states | array<BattleEffectInstance> | 否 | 派生 | 异常 / 层数状态展示分组，如冻结、中毒、灼烧、萌化等。 |
| skill_slot_effects | array<SkillSlotEffect> | 否 | 状态管理模块 | 技能槽修正，例如能耗变化、威力变化、冷却、技能变形。 |
| action_rule_effects | array<BattleEffectInstance> | 否 | 派生 | 迅捷、蓄力、打断、眩晕、无法更换、脱离、返场等行动规则效果。 |
| side_positive_mark | MarkInstance | 否 | 队伍侧印记状态 | 当前队伍增益印记槽引用。注意不是精灵私有状态。 |
| side_negative_mark | MarkInstance | 否 | 队伍侧印记状态 | 当前队伍减益印记槽引用。星陨在这里作为减益印记显示。 |
| battlefield_weather | WeatherInstance | 否 | 战场状态 | 当前全局天气。 |
| speed_range | object | 是 | 候选配置计算 | 敌方速度候选区间，例如 `{min:160,max:175}`。 |
| first_move_probability | object | 是 | 速度判断模块 | 先手概率，例如 `{self:0.625, enemy:0.375, tie_candidates:1}`。 |
| confidence | decimal | 是 | 推算模块 | 整体配置置信度，范围 0 到 1。 |
| evidence_log | array<string/object> | 否 | 推算模块 / 事件日志 | 支撑该状态的证据摘要或事件 ID 列表。 |
| last_update_reason | string | 否 | 推算模块 | 最近一次更新原因，用于 UI 解释。 |

开发注意：

- `active_normal_buffs` 等展示分组不要单独作为真相源，否则容易和 `battle_effects` 不一致。
- 印记和天气不属于某只精灵，但为了当前对位展示，可以在 `EnemyPetState` 中引用。
- 切换精灵时应清除 `clear_on_switch=true` 的精灵状态，但不能清除 `side_positive_mark / side_negative_mark`。

---

### 13.2 候选配置 `BuildCandidate`

```text
BuildCandidate {
  candidate_id
  pet_id
  nature
  individual_talent_distribution
  final_hp
  final_physical_attack
  final_physical_defense
  final_magic_attack
  final_magic_defense
  final_speed
  possible_skills
  skill_weights
  match_score
  confidence
  is_excluded
  excluded_reason
  matched_event_ids
  mismatched_event_ids
}
```

字段说明：

| 字段 | 类型 | 必填 | 来源 | 说明 |
| --- | --- | --- | --- | --- |
| candidate_id | string | 是 | 系统生成 | 候选配置唯一 ID。 |
| pet_id | string | 是 | 准备阶段识别 | 对应敌方精灵 ID。 |
| nature | object/string | 是 | 枚举生成 | 性格修正。建议保存 `nature_id`，也可缓存正负修正维度。 |
| individual_talent_distribution | object | 是 | 枚举生成 | 个体资质分布。六维都应有值，无个体维度填 0。 |
| final_hp | int | 是 | 属性计算模块 | 该候选下的最大生命面板值。 |
| final_physical_attack | int | 是 | 属性计算模块 | 该候选下的物攻面板值。 |
| final_physical_defense | int | 是 | 属性计算模块 | 该候选下的物防面板值。 |
| final_magic_attack | int | 是 | 属性计算模块 | 该候选下的魔攻面板值。 |
| final_magic_defense | int | 是 | 属性计算模块 | 该候选下的魔防面板值。 |
| final_speed | int | 是 | 属性计算模块 | 该候选下的速度面板值，用于先手判断。 |
| possible_skills | array<string> | 是 | 技能池 / 推算模块 | 在该候选下仍可能的技能。技能未知时与配置联合枚举。 |
| skill_weights | object | 否 | 统计 / 推算模块 | 各技能可能性权重。没有统计数据时可为空。 |
| match_score | decimal | 是 | 推算模块 | 与历史伤害和状态证据的匹配分数。分数越高越可信。 |
| confidence | decimal | 是 | 推算模块 | 归一化置信度，范围 0 到 1。 |
| is_excluded | bool | 是 | 推算模块 | 是否已被排除。排除后通常不再参与伤害区间计算。 |
| excluded_reason | string | 否 | 推算模块 | 被排除原因，例如“理论最大伤害低于实际伤害”。 |
| matched_event_ids | array<string> | 否 | 推算模块 | 支持该候选的事件 ID。 |
| mismatched_event_ids | array<string> | 否 | 推算模块 | 与该候选冲突的事件 ID。 |

---

### 13.3 伤害计算结果 `DamageResult`

```text
DamageResult {
  calculation_id
  attacker
  defender
  skill
  candidate_scope

  damage_value_min
  damage_value_max
  damage_percent_min
  damage_percent_max

  hit_results
  is_exact
  can_knock_out
  can_first_move_knock_out
  speed_judgement
  confidence
  explanation
  used_snapshot_id
}
```

字段说明：

| 字段 | 类型 | 必填 | 来源 | 说明 |
| --- | --- | --- | --- | --- |
| calculation_id | string | 是 | 系统生成 | 本次伤害计算结果 ID。 |
| attacker | object/string | 是 | 当前对位状态 | 攻击方，可存 pet_id + side。 |
| defender | object/string | 是 | 当前对位状态 | 防御方，可存 pet_id + side。 |
| skill | string/object | 是 | 技能数据库 / 用户选择 | 技能 ID 或技能摘要。 |
| candidate_scope | enum/object | 否 | 推算模块 | 计算使用的候选范围，例如全部未排除候选、高置信候选、已确认配置。 |
| damage_value_min | int | 是 | 伤害计算模块 | 可能造成的最小准确伤害。 |
| damage_value_max | int | 是 | 伤害计算模块 | 可能造成的最大准确伤害。若与 min 相等则为单值。 |
| damage_percent_min | decimal | 是 | 伤害计算模块 | 对目标最大生命的最小百分比。 |
| damage_percent_max | decimal | 是 | 伤害计算模块 | 对目标最大生命的最大百分比。 |
| hit_results | array<HitDamageResult> | 否 | 伤害计算模块 | 多段技能逐段理论结果。默认不要求生成；MVP 可为空，只展示总伤害区间。 |
| is_exact | bool | 是 | 伤害计算模块 | 是否为确定单值。敌方配置未确认时通常 false。 |
| can_knock_out | bool | 是 | 伤害计算模块 | 不考虑先手，仅按当前生命判断是否可能击杀。 |
| can_first_move_knock_out | bool | 是 | 伤害计算 + 速度判断 | 是否存在先手击杀可能。需要结合速度概率。 |
| speed_judgement | object | 否 | 速度判断模块 | 本次伤害相关的先手判断结果。 |
| confidence | decimal | 是 | 伤害计算模块 | 计算置信度，受配置置信度、识别置信度、状态完整性影响。 |
| explanation | string | 否 | 伤害计算模块 | 解释区间来源，例如“敌方物防候选未确认”。 |
| used_snapshot_id | string | 否 | 状态管理模块 | 计算使用的状态快照 ID，便于复查。 |

---

### 13.4 战斗事件 `BattleEvent`

```text
BattleEvent {
  event_id
  battle_id
  turn_number
  action_order
  timestamp
  event_type

  actor
  target
  skill
  skill_confirmed

  damage_value
  enemy_hp_percent_damage
  hp_percent_before
  hp_percent_after
  hp_percent_delta

  is_multi_hit
  damage_record_mode
  hit_details
  total_hit_count
  total_damage_value
  total_hp_percent_damage

  actor_status_snapshot
  target_status_snapshot
  weather_snapshot
  mark_snapshot
  abnormal_status_snapshot
  defense_skill_snapshot
  damage_modifier_snapshot
  full_effect_snapshot

  type_effectiveness
  special_skill_effect

  source
  confidence
  manual_override
}
```

字段说明：

| 字段 | 类型 | 必填 | 来源 | 说明 |
| --- | --- | --- | --- | --- |
| event_id | string | 是 | 系统生成 | 事件唯一 ID。 |
| battle_id | string | 是 | 系统生成 | 所属战斗 ID。 |
| turn_number | int | 是 | 系统记录 / 手动修正 | 事件所在回合。 |
| action_order | int | 否 | 系统记录 | 同一回合内的顺序。多段伤害和状态结算应按顺序记录。 |
| timestamp | datetime | 是 | 系统记录 | 事件发生时间。 |
| event_type | enum | 是 | 系统记录 | 事件类型，例如 `skill_use`、`damage`、`effect_change`、`mark_change`、`weather_change`、`switch`。 |
| actor | object/string | 否 | 识别 / 手动输入 | 行动方。天气自然结束等事件可为空。 |
| target | object/string | 否 | 识别 / 手动输入 | 目标方。全场事件可为空或为 `battlefield`。 |
| skill | string/object | 否 | 技能识别 / 手动输入 | 关联技能。非技能事件可为空。 |
| skill_confirmed | bool | 是 | 技能识别 / 手动输入 | 技能是否已确认。敌方技能未知时为 false。 |
| damage_value | int | 条件 | 图像识别 / 手动输入 | 本次伤害事件用于推算的主伤害值。单段时为单段伤害；多段时默认等于最终显示总伤害。非伤害事件为空。 |
| enemy_hp_percent_damage | decimal | 条件 | 图像识别 / 手动输入 | 本次攻击扣除敌方生命百分比。用于反推最大生命。 |
| hp_percent_before | decimal | 否 | 图像识别 / 推导 | 受击前生命百分比。 |
| hp_percent_after | decimal | 否 | 图像识别 / 推导 | 受击后生命百分比。 |
| hp_percent_delta | decimal | 否 | 系统计算 | 血量百分比变化。通常等于 before - after，但可能受识别误差影响。 |
| is_multi_hit | bool | 是 | 技能规则 / 识别 | 是否为多段伤害。 |
| damage_record_mode | enum | 是 | 系统记录 | 伤害记录模式。建议取 `single`、`multi_total_only`、`multi_with_hits`。当前多段默认 `multi_total_only`。 |
| hit_details | array<HitDetail> | 否 | 图像识别 / 手动输入 | 多段逐段详情。MVP 默认不记录，可为空。 |
| total_hit_count | int | 否 | 技能数据库 / 识别 | 多段总段数。可由技能规则推导；运行时无法确认时可为空。 |
| total_damage_value | int | 否 | 图像识别 / 手动输入 | 多段最终显示总伤害。若为多段伤害且识别成功，应与 `damage_value` 一致。 |
| total_hp_percent_damage | decimal | 否 | 图像识别 / 系统计算 | 多段总扣血百分比。 |
| actor_status_snapshot | object | 是 | 状态管理模块 | 行动方状态快照。伤害推算必须使用快照。 |
| target_status_snapshot | object | 是 | 状态管理模块 | 目标方状态快照。 |
| weather_snapshot | object | 否 | 状态管理模块 | 事件发生时天气。 |
| mark_snapshot | object | 否 | 状态管理模块 | 双方队伍印记槽快照。星陨在此记录为减益印记。 |
| abnormal_status_snapshot | object | 否 | 状态管理模块 | 异常 / 层数状态快照。 |
| defense_skill_snapshot | object | 否 | 状态管理模块 | 防御技能减伤或防御响应状态快照。 |
| damage_modifier_snapshot | object | 否 | 状态管理模块 | 增伤 / 减伤 / 威力 / 能耗等相关修正快照。 |
| full_effect_snapshot | BattleEffectSnapshot | 否 | 状态管理模块 | 完整统一状态快照。建议保留，避免多个分散快照不一致。 |
| type_effectiveness | object | 否 | 伤害计算模块 | 属性克制结果。 |
| special_skill_effect | object/string | 否 | 技能数据库 / 计算模块 | 本次触发的特殊技能效果说明或 ID。 |
| source | enum | 是 | 系统记录 | 信息来源：自动识别、手动输入、系统推算等。 |
| confidence | decimal | 是 | 系统记录 | 事件整体置信度。手动确认可为 1。 |
| manual_override | bool | 是 | 系统记录 | 是否被用户手动修正。 |

---

### 13.5 状态变化事件 `EffectChangeEvent`

```text
EffectChangeEvent {
  event_id
  battle_id
  turn_number
  action_order
  timestamp

  change_type
  effect_id
  effect_name
  category
  target_side
  target_pet
  target_skill_slot

  layers_before
  layers_after
  duration_before
  duration_after

  source_skill
  source_actor
  condition_branch
  reason

  source
  recognition_confidence
  manual_override
}
```

字段说明：

| 字段 | 类型 | 必填 | 来源 | 说明 |
| --- | --- | --- | --- | --- |
| event_id | string | 是 | 系统生成 | 状态变化事件 ID。 |
| battle_id | string | 是 | 系统生成 | 所属战斗 ID。 |
| turn_number | int | 是 | 系统记录 | 事件所在回合。 |
| action_order | int | 否 | 系统记录 | 同回合内顺序。 |
| timestamp | datetime | 是 | 系统记录 | 事件时间。 |
| change_type | enum | 是 | 状态管理模块 | `apply`、`remove`、`stack`、`refresh`、`convert`、`transfer`、`dispel`、`switch_clear`、`expire`。 |
| effect_id | string | 条件 | 状态数据库 | 普通状态 ID。若是印记变化，也可为空并使用 `mark_id` 扩展。 |
| effect_name | string | 否 | 状态数据库 | 状态名称缓存，用于日志展示。 |
| category | enum | 是 | 状态数据库 | 状态类别，用于判断是否切换清除、是否可被驱散。 |
| target_side | enum | 是 | 识别 / 状态管理 | 目标队伍。 |
| target_pet | string | 条件 | 识别 / 状态管理 | 目标精灵。队伍侧或战场效果可为空。 |
| target_skill_slot | string/int | 条件 | 状态管理 | 目标技能槽。仅技能槽效果需要。 |
| layers_before | int | 否 | 状态管理 | 变化前层数。 |
| layers_after | int | 否 | 状态管理 | 变化后层数。 |
| duration_before | int | 否 | 状态管理 | 变化前剩余持续。 |
| duration_after | int | 否 | 状态管理 | 变化后剩余持续。 |
| source_skill | string | 否 | 技能事件 | 来源技能 ID。 |
| source_actor | string/object | 否 | 技能事件 | 来源行动方。 |
| condition_branch | enum | 否 | 技能脚本 | 条件分支，例如 `normal`、`against_defense`、`enemy_switched`。 |
| reason | string | 否 | 状态管理 | 人类可读原因，例如“切换清除普通减益”。 |
| source | enum | 是 | 系统记录 | 信息来源。 |
| recognition_confidence | decimal | 否 | 图像识别 | 识别置信度。 |
| manual_override | bool | 是 | 系统记录 | 是否手动修正。 |

---

### 13.6 多段伤害详情 `HitDetail`

`HitDetail` 是可选扩展结构，不是第一阶段必须记录的运行时数据。

当前默认策略为：

```text
多段伤害只记录最终显示总伤害
hit_details 默认为空
```

只有在后续识别性能允许，或某个技能必须依赖逐段伤害才能正确推算时，才记录该结构。

```text
HitDetail {
  hit_index
  hit_damage_value
  hit_hp_percent_damage
  hit_snapshot_id
  triggered_effects
}
```

字段说明：

| 字段 | 类型 | 必填 | 来源 | 说明 |
| --- | --- | --- | --- | --- |
| hit_index | int | 条件 | 图像识别 / 系统记录 | 第几段，从 1 开始。只有记录逐段详情时必填。 |
| hit_damage_value | int | 条件 | 图像识别 / 手动输入 | 当前段准确伤害值。只有记录逐段详情时必填。 |
| hit_hp_percent_damage | decimal | 否 | 图像识别 / 手动输入 | 当前段扣血百分比。无法稳定识别时可为空。 |
| hit_snapshot_id | string | 否 | 状态管理模块 | 当前段计算使用的快照。若每段状态可能变化，且系统实现逐段推算时再记录。 |
| triggered_effects | array<string/object> | 否 | 状态管理模块 | 当前段触发的附加效果，例如每段叠星陨。MVP 可不记录。 |

开发说明：

- 第一阶段不要因为无法识别逐段伤害而阻塞功能。
- 多段伤害事件可以只保存 `damage_value`、`total_damage_value`、`total_hp_percent_damage` 和统一状态快照。
- 如果后续补充逐段数据，应作为对同一伤害事件的增强，不应改变事件主伤害值的含义。

---

### 13.7 统一战斗效果实例 `BattleEffectInstance`

```text
BattleEffectInstance {
  instance_id
  effect_id
  effect_name
  category
  polarity

  owner_side
  owner_pet
  target_side
  target_pet
  target_skill_slot
  scope

  layers
  max_layers
  duration_type
  remaining_turns
  remaining_uses

  clear_on_switch
  clear_by_normal_dispel
  clear_by_mark_dispel
  clear_by_abnormal_cleanse

  source_skill
  source_actor
  applied_turn
  applied_order
  icon_id
  is_visible_icon
  display_group
  manual_override
}
```

字段说明：

| 字段 | 类型 | 必填 | 来源 | 说明 |
| --- | --- | --- | --- | --- |
| instance_id | string | 是 | 系统生成 | 状态实例 ID。同一种状态多次独立存在时用不同实例区分。 |
| effect_id | string | 是 | 状态数据库 | 引用 `EffectDefinition`。印记不建议用此结构，除非做统一展示包装。 |
| effect_name | string | 是 | 状态数据库 | 状态名称缓存。 |
| category | enum | 是 | 状态数据库 | 状态大类。用于切换清除、驱散、UI 分组和计算入口。 |
| polarity | enum | 是 | 状态数据库 | 正面、负面、中性或混合。 |
| owner_side | enum | 是 | 状态管理 | 状态归属队伍。 |
| owner_pet | string | 条件 | 状态管理 | 状态归属精灵。精灵级状态必填。 |
| target_side | enum | 否 | 状态管理 | 状态影响目标队伍。多数情况下与 owner_side 相同。 |
| target_pet | string | 否 | 状态管理 | 状态影响目标精灵。 |
| target_skill_slot | int/string | 条件 | 状态管理 | 技能槽效果的目标技能格。 |
| scope | enum | 是 | 状态数据库 | `pet`、`side`、`battlefield`、`skill_slot`、`turn_context`。 |
| layers | int | 是 | 状态管理 | 当前层数。无层数状态填 1。 |
| max_layers | int | 否 | 状态数据库 | 最大层数。 |
| duration_type | enum | 是 | 状态数据库 | 持续类型。 |
| remaining_turns | int | 条件 | 状态管理 | 剩余回合。`duration_type=turns` 时使用。 |
| remaining_uses | int | 条件 | 状态管理 | 剩余次数。`duration_type=uses` 时使用。 |
| clear_on_switch | bool | 是 | 状态数据库快照 | 是否切换清除。实例中保存快照，避免规则更新影响历史事件。 |
| clear_by_normal_dispel | bool | 是 | 状态数据库快照 | 是否可被普通驱散处理。 |
| clear_by_mark_dispel | bool | 是 | 状态数据库快照 | 是否可被印记驱散处理。普通状态通常 false。 |
| clear_by_abnormal_cleanse | bool | 是 | 状态数据库快照 | 是否可被异常净化处理。 |
| source_skill | string | 否 | 技能事件 | 来源技能 ID。 |
| source_actor | object/string | 否 | 技能事件 | 来源行动方。 |
| applied_turn | int | 是 | 状态管理 | 施加回合。 |
| applied_order | int | 否 | 状态管理 | 施加顺序。用于同回合多状态排序。 |
| icon_id | string | 否 | 状态数据库 | 展示图标。 |
| is_visible_icon | bool | 是 | 状态数据库 | 是否在 UI 显示图标。 |
| display_group | enum | 是 | 状态数据库 | UI 显示分组。 |
| manual_override | bool | 是 | 系统记录 | 实例是否被手动修正过。 |

---

### 13.8 队伍侧印记状态 `SideMarkState` 与 `MarkInstance`

```text
SideMarkState {
  battle_id
  side_id
  positive_mark_slot
  negative_mark_slot
  updated_turn
  updated_reason
}
```

字段说明：

| 字段 | 类型 | 必填 | 来源 | 说明 |
| --- | --- | --- | --- | --- |
| battle_id | string | 是 | 系统生成 | 所属战斗 ID。 |
| side_id | enum | 是 | 系统记录 | 队伍：`self` 或 `enemy`。 |
| positive_mark_slot | MarkInstance/null | 否 | 状态管理 | 增益印记槽。每队最多一个。 |
| negative_mark_slot | MarkInstance/null | 否 | 状态管理 | 减益印记槽。星陨属于该槽。 |
| updated_turn | int | 否 | 状态管理 | 最近更新时间。 |
| updated_reason | string | 否 | 状态管理 | 最近更新原因，例如“星轨裂变施加 2 层星陨”。 |

```text
MarkInstance {
  instance_id
  mark_id
  mark_name
  polarity
  owner_side
  layers
  source_skill
  source_pet
  applied_turn
  applied_order
  max_layers
  stack_rule
  conflict_policy
  clear_on_switch
  clear_by_normal_dispel
  clear_by_mark_dispel
  icon_id
  manual_override
}
```

字段说明：

| 字段 | 类型 | 必填 | 来源 | 说明 |
| --- | --- | --- | --- | --- |
| instance_id | string | 是 | 系统生成 | 印记实例 ID。 |
| mark_id | string | 是 | 印记数据库 | 印记 ID。星陨建议使用 `starfall`。 |
| mark_name | string | 是 | 印记数据库 | 印记名称。 |
| polarity | enum | 是 | 印记数据库 | `positive` 或 `negative`。决定槽位。 |
| owner_side | enum | 是 | 状态管理 | 印记所在队伍。注意不是某只精灵。 |
| layers | int | 是 | 状态管理 / 识别 | 当前层数。 |
| source_skill | string | 否 | 技能事件 | 来源技能。 |
| source_pet | string | 否 | 技能事件 | 来源精灵。 |
| applied_turn | int | 是 | 状态管理 | 初次施加回合。 |
| applied_order | int | 否 | 状态管理 | 初次施加顺序。 |
| max_layers | int | 否 | 印记数据库 | 最大层数。未知时为空。 |
| stack_rule | enum | 是 | 印记数据库 | 叠加规则。 |
| conflict_policy | enum | 是 | 印记数据库 | 同极性印记槽冲突规则。 |
| clear_on_switch | bool | 是 | 固定规则 | 固定 false。切换不清除。 |
| clear_by_normal_dispel | bool | 是 | 固定规则 | 固定 false。普通驱散不清除。 |
| clear_by_mark_dispel | bool | 是 | 印记数据库 | 是否可被印记驱散 / 消除 / 转换处理。 |
| icon_id | string | 否 | 印记数据库 | 印记图标。 |
| manual_override | bool | 是 | 系统记录 | 是否手动修正层数或类型。 |

---

### 13.9 技能槽效果 `SkillSlotEffect`

```text
SkillSlotEffect {
  instance_id
  effect_id
  owner_side
  owner_pet
  affected_skill_scope
  affected_skill_slot
  modifier_type
  modifier_value_type
  modifier_value
  duration_type
  remaining_turns
  remaining_uses
  clear_on_switch
  source_skill
  icon_id
  is_visible_icon
}
```

字段说明：

| 字段 | 类型 | 必填 | 来源 | 说明 |
| --- | --- | --- | --- | --- |
| instance_id | string | 是 | 系统生成 | 技能槽效果实例 ID。 |
| effect_id | string | 是 | 状态数据库 | 对应状态定义 ID。 |
| owner_side | enum | 是 | 状态管理 | 所属队伍。 |
| owner_pet | string | 是 | 状态管理 | 所属精灵。 |
| affected_skill_scope | enum | 是 | 技能脚本 | 影响范围，例如 `all_skills`、`attack_skills`、`status_skills`、`current_used_skill`、`selected_slot`、`neighbor_slots`。 |
| affected_skill_slot | int/string | 条件 | 技能脚本 / 识别 | 具体技能格。只影响特定槽位时必填。 |
| modifier_type | enum | 是 | 状态数据库 | 修正类型：`energy_cost`、`power_flat`、`power_percent`、`cooldown`、`hit_count`、`skill_transform`、`use_count`。 |
| modifier_value_type | enum | 是 | 状态数据库 | 数值类型：`flat`、`percent`、`multiplier`、`formula`。 |
| modifier_value | decimal/string | 是 | 状态数据库 / 状态管理 | 修正值。例如 `+3`、`-2`、`+40`、`2x`。 |
| duration_type | enum | 是 | 状态数据库 | 持续类型。 |
| remaining_turns | int | 条件 | 状态管理 | 剩余回合。 |
| remaining_uses | int | 条件 | 状态管理 | 剩余使用次数。 |
| clear_on_switch | bool | 是 | 状态数据库 | 切换是否清除。 |
| source_skill | string | 否 | 技能事件 | 来源技能。 |
| icon_id | string | 否 | 状态数据库 | 图标。 |
| is_visible_icon | bool | 是 | 状态数据库 | 是否在技能图标角标展示。 |

---

### 13.10 战斗效果快照 `BattleEffectSnapshot`

```text
BattleEffectSnapshot {
  snapshot_id
  battle_id
  turn_number
  action_order
  attacker_effects
  defender_effects
  attacker_side_marks
  defender_side_marks
  battlefield_effects
  attacker_skill_slot_effects
  defender_skill_slot_effects
  turn_effects
  created_at
}
```

字段说明：

| 字段 | 类型 | 必填 | 来源 | 说明 |
| --- | --- | --- | --- | --- |
| snapshot_id | string | 是 | 系统生成 | 快照 ID。伤害事件引用该 ID。 |
| battle_id | string | 是 | 系统生成 | 所属战斗 ID。 |
| turn_number | int | 是 | 系统记录 | 快照所在回合。 |
| action_order | int | 否 | 系统记录 | 快照对应同回合内的行动顺序。 |
| attacker_effects | array<BattleEffectInstance> | 是 | 状态管理 | 攻击方精灵状态快照。 |
| defender_effects | array<BattleEffectInstance> | 是 | 状态管理 | 防御方精灵状态快照。 |
| attacker_side_marks | SideMarkState | 是 | 状态管理 | 攻击方队伍印记槽快照。 |
| defender_side_marks | SideMarkState | 是 | 状态管理 | 防御方队伍印记槽快照。 |
| battlefield_effects | array<object> | 否 | 状态管理 | 天气和其他全战场效果。 |
| attacker_skill_slot_effects | array<SkillSlotEffect> | 否 | 状态管理 | 攻击方技能槽效果。 |
| defender_skill_slot_effects | array<SkillSlotEffect> | 否 | 状态管理 | 防御方技能槽效果。 |
| turn_effects | array<object> | 否 | 状态管理 | 只在当前回合有效的临时效果。 |
| created_at | datetime | 是 | 系统生成 | 快照创建时间。 |

开发注意：

- 每次伤害计算和候选过滤必须绑定快照，不能直接读取“当前状态”。
- 多段伤害如果每段之间会触发状态变化，建议每段单独生成快照；如果确认不会变化，可共用总快照。

---

### 13.11 天气实例 `WeatherInstance`

```text
WeatherInstance {
  weather_id
  weather_name
  layers
  duration_type
  remaining_turns
  source_skill
  source_pet
  applied_turn
  icon_id
  manual_override
}
```

字段说明：

| 字段 | 类型 | 必填 | 来源 | 说明 |
| --- | --- | --- | --- | --- |
| weather_id | string | 是 | 天气数据库 | 天气 ID。 |
| weather_name | string | 是 | 天气数据库 | 天气名称。 |
| layers | int | 否 | 状态管理 | 若天气未来存在层数，可使用；当前可固定为 1。 |
| duration_type | enum | 是 | 天气数据库 | 持续类型。 |
| remaining_turns | int | 条件 | 状态管理 | 剩余回合。 |
| source_skill | string | 否 | 技能事件 | 来源技能，例如冬至、沙涌、落雨、求雨。 |
| source_pet | string | 否 | 技能事件 | 来源精灵。 |
| applied_turn | int | 是 | 状态管理 | 施加回合。 |
| icon_id | string | 否 | 天气数据库 | 天气图标。 |
| manual_override | bool | 是 | 系统记录 | 是否手动修正。 |

---

### 13.12 生命 / 能量变化结果 `ResourceChangeResult`

状态技能表中存在大量回复生命、失去能量、偷取能量、交换生命比例等效果，建议单独结构化。

```text
ResourceChangeResult {
  event_id
  resource_type
  change_type
  source_side
  source_pet
  target_side
  target_pet
  value_type
  value
  before_value
  after_value
  confidence
}
```

字段说明：

| 字段 | 类型 | 必填 | 来源 | 说明 |
| --- | --- | --- | --- | --- |
| event_id | string | 是 | 事件日志 | 对应事件 ID。 |
| resource_type | enum | 是 | 技能脚本 | `hp` 或 `energy`。 |
| change_type | enum | 是 | 技能脚本 | `gain`、`lose`、`steal`、`exchange_ratio`、`set_value`。 |
| source_side | enum | 否 | 技能事件 | 来源队伍。 |
| source_pet | string | 否 | 技能事件 | 来源精灵。 |
| target_side | enum | 是 | 技能事件 | 目标队伍。 |
| target_pet | string | 条件 | 技能事件 | 目标精灵。队伍级能量变化时可为空。 |
| value_type | enum | 是 | 技能脚本 | `flat`、`percent_max_hp`、`percent_current_hp`、`formula`。 |
| value | decimal/string | 是 | 技能脚本 / 识别 | 变化值或公式。 |
| before_value | decimal/int | 否 | 识别 / 状态管理 | 变化前数值。 |
| after_value | decimal/int | 否 | 识别 / 状态管理 | 变化后数值。 |
| confidence | decimal | 是 | 系统记录 | 置信度。 |

---

### 13.13 字段优先级与覆盖规则

| 场景 | 规则 |
| --- | --- |
| 自动识别和手动输入冲突 | 手动输入覆盖自动识别，并记录 `manual_override=true` |
| 数据库定义和战斗中识别冲突 | 不直接改数据库，先记录战斗事件异常，必要时手动修正该场战斗 |
| 系统推算和实际伤害冲突 | 降低推算置信度，不直接删除事件；优先检查状态快照是否漏记 |
| 同一状态重复应用 | 按 `stack_rule` 和 `conflict_policy` 处理 |
| 切换精灵 | 只清除 `clear_on_switch=true` 的精灵级效果，不清除印记和天气 |
| 普通驱散增益 / 减益 | 只处理 `clear_by_normal_dispel=true` 的普通状态，不处理印记 |
| 印记驱散 / 转换 | 只处理 `MarkInstance`，包括星陨、棘刺、减速印记等 |

---

## 十四、当前边界条件与假设

当前版本基于以下假设：

- 等级固定为 60。
- PVP 成长值固定为生命 100，非生命 50。
- 所有 PVP 精灵统一按照 6 星、0 觉醒、50 成长等级计算。
- 敌方六只精灵在准备阶段可见。
- 己方六只精灵完整配置由玩家提前输入。
- 敌方精灵种族资质可由精灵名称从数据库读取。
- 敌方未知配置主要包括性格、个体资质分布、技能组。
- 个体资质一定存在于 1 到 3 个维度。
- 通常情况下，个体资质存在于 3 个维度。
- 存在个体资质的维度，数值固定范围为 7 到 10。
- 没有个体资质的维度，按 0 计算。
- 性格必定包含一个正面修正和一个负面修正。
- 性格正面修正为 +20%，负面修正为 -10%。
- 性格正面维度和负面维度不会相同。
- 性格可以影响生命。
- 速度决定常规出手顺序。
- 不同速时，高速精灵先出手。
- 同速时，双方各有 50% 概率先出手。
- 伤害结果同时展示准确值和生命百分比。
- 每次攻击可以识别到扣除了敌方多少百分比血量。
- 伤害数值一定是整数。
- 多段伤害游戏中可能逐段展示，但程序第一阶段只要求记录最终显示的总伤害。
- 天气、异常 / 层数状态、印记、普通增益 / 减益、技能槽修正、行动规则状态、增伤、减伤均通过统一 BattleEffect 系统进入伤害或行动计算。
- 当前游戏没有通用护盾机制。
- 防御技能带来的伤害减免作为技能特殊效果或防御技能状态进入伤害计算。
- 普通属性增减默认可以通过切换在场精灵清除。
- 冻结明确不能通过切换清除。
- 印记不因切换在场精灵清除，且每个队伍最多同时存在一个增益印记和一个减益印记。
- 图像识别结果可以被手动输入覆盖。
- 敌方配置推算采用候选集合过滤方式。
- 敌方技能未知时，需要枚举可能技能池进行联合推算。
- 所有计算结果在独立页面展示。
- 当前阶段暂不考虑命中率。

---

## 十五、仍需确认的问题

以下问题会直接影响开发，建议优先确认。

### 15.1 属性计算相关

当前已经确认：

- 无个体资质的维度按 0 计算。
- 个体资质一定只存在于 1 到 3 个维度。
- 个体资质固定范围为 7 到 10。
- 性格正面修正为 +20%。
- 性格负面修正为 -10%。
- 性格必定存在一正一负。
- 性格正面维度和负面维度不会相同。
- 性格可以影响生命。
- 所有 PVP 精灵统一按照 6 星、0 觉醒、50 成长等级计算。
- 使用 PVP 化简公式计算最终面板属性。

仍需确认：

- 生命属性四舍五入的具体规则是否为标准四舍五入。
- 非生命属性是否始终向上取整。
- 如果后续出现特殊模式，是否仍然沿用当前 PVP 属性公式。

---

### 15.2 伤害公式相关

仍需确认：

- 完整伤害公式是什么。
- 伤害公式每一步是否取整。
- 最终伤害是向下取整、四舍五入还是向上取整。
- 技能威力、攻防属性、克制倍率的计算顺序是什么。
- Buff/Debuff 是先修正属性，还是直接修正最终伤害。
- 多个增伤、减伤、天气、印记倍率的乘法顺序是什么。
- 防御技能减伤在伤害公式中的生效位置是什么。
- 是否存在伤害上限或下限。

---

### 15.3 血量与显示相关

当前已经确认：

- 每次攻击可以识别到扣除了敌方多少百分比血量。
- 伤害数值一定是整数。
- 多段伤害可能逐段展示，但程序默认只记录最终显示的总伤害。

仍需确认：

- 敌方扣血百分比的显示精度。
- 血量百分比显示是否四舍五入。
- 血量百分比变化是否可能受到动画延迟影响。
- 多段伤害最终总伤害是否总能稳定识别。
- 多段伤害总扣血百分比是否能稳定识别。
- 是否存在少数技能必须依赖逐段伤害才能正确推算。

---

### 15.4 技能特殊规则相关

需要整理特殊技能分类，包括：

- 固定伤害
- 百分比伤害
- 无视防御
- 多段伤害
- 追加伤害
- 根据自身生命变化的伤害
- 根据敌方生命变化的伤害
- 根据天气变化的伤害
- 根据异常状态变化的伤害
- 防御技能减伤
- 免疫
- 吸血
- 反伤
- 状态技能
- 本回合结算伤害
- 延迟结算伤害

这些技能不能简单套用普通伤害公式，需要在技能数据库中单独标记。

---

### 15.5 状态规则相关

当前已经确认：

- 所有状态技能使用后，只要形成持续存在、可追踪或会影响后续计算的状态，就会以图标方式显示。
- 普通属性降低，例如减少攻击、减少防御，可以通过切换当前在场精灵消除。
- 冻结不能通过切换当前在场精灵消除。
- 印记不能通过切换当前在场精灵消除。
- 星陨属于印记，按减益印记处理，不能通过切换当前在场精灵消除。
- 印记只有被明确消除印记、驱散印记或转换印记的技能处理时才会消失或转换。
- 一个队伍最多同时存在一个增益印记和一个减益印记。

需要确认：

- 同一队伍已有增益印记时，再获得不同增益印记，是覆盖旧印记、保留旧印记，还是新印记失败？
- 同一队伍已有减益印记时，再获得不同减益印记，是覆盖旧印记、保留旧印记，还是新印记失败？
- 同名印记是否无限叠层，是否有最大层数？
- 印记是完全绑定队伍侧，还是绑定精灵但切换不消失？当前推荐按队伍侧处理。
- 中毒是否切换清除。
- 灼烧是否切换清除。
- 寄生是否切换清除。
- 萌化是否切换清除。
- 奉献是否切换清除。
- 毒雾“将敌方所有增益转化成中毒”的层数换算规则。
- 焚烧烙印“每驱散 1 层印记，敌方获得 5 层灼烧”中，双方印记层数是否都计入。
- 炎爆术“敌方印记转换为三倍灼烧”是否按总层数计算。
- 落井下毒“减益层数翻倍”是否包括异常、中毒、灼烧，还是只包括普通减益；星陨属于印记，除非技能明确影响印记，否则不应归入普通减益翻倍。
- 永久能耗变化是否切换后保留。
- 下次技能能耗 -6 是否切换后保留。
- 下次技能无需蓄力是否切换后保留。
- 技能位置交换和技能能耗交换是否只影响当前在场精灵。
- 技能变形类效果在切换后是否保留。

---

## 十六、开发优先级建议

### 16.1 第一阶段：纯手动输入 MVP

第一阶段先不做图像识别，优先验证核心计算逻辑。

目标：

- 手动录入双方阵容
- 手动录入己方完整配置
- 敌方根据数据库生成候选配置
- 手动输入技能、伤害、扣血百分比、状态
- 手动添加 / 删除 / 修改 BattleEffect 状态实例
- 支持切换时自动清除 `clear_on_switch = true` 的普通增益 / 减益
- 支持队伍侧增益印记槽和减益印记槽
- 支持天气状态
- 系统完成候选配置过滤
- 展示双方技能伤害
- 展示速度与先手判断
- 展示敌方候选配置收敛结果

这是最重要的 MVP 阶段。

---

### 16.2 第二阶段：半自动识别版本

加入部分图像识别能力。

目标：

- 自动识别当前双方精灵
- 自动识别伤害数字
- 自动识别敌方扣血百分比
- 自动识别多段伤害最终显示的总伤害；逐段数值作为后续扩展
- 自动识别技能名称
- 自动识别状态图标
- 自动识别天气和印记
- 自动识别防御技能状态
- 允许手动修正

---

### 16.3 第三阶段：实时辅助版本

目标：

- 战斗中自动刷新
- 自动维护敌方配置候选集合
- 自动展示当前最优伤害数据
- 自动展示速度与先手概率
- 支持场下精灵伤害预估
- 支持切换精灵前的伤害预览
- 支持敌方后备精灵伤害预估

---

### 16.4 第四阶段：高级推算版本

目标：

- 根据多次伤害自动判断敌方技能组
- 根据伤害误差自动提示可能遗漏的减伤 / 增伤状态
- 根据敌方行动习惯更新技能概率
- 支持更多特殊技能
- 支持更多特殊状态
- 支持置信度评分和推算解释
- 支持速度候选与伤害候选的联合判断

---

## 十七、总结版核心需求描述

本系统的核心需求是：

> 在洛克王国世界 PVP 对战中，系统通过准备阶段获取双方六只精灵信息。己方精灵完整配置由玩家提前输入，敌方精灵仅确认种类，具体性格、个体资质分布和技能组未知。系统根据数据库为敌方每只精灵生成可能配置集合，并在战斗过程中通过双方造成的实际整数伤害、敌方扣血百分比、技能信息、增益 / 减益、天气、印记、异常状态、防御技能减伤、增伤 / 减伤等信息，不断过滤和收敛敌方候选配置。同时，系统基于双方速度判断出手顺序：高速先手，同速双方各 50% 概率先手。最终系统实时展示我方技能对敌方的准确伤害值和生命百分比、敌方已知或可能技能对我方的准确伤害值和生命百分比、双方速度关系与先手概率，为玩家提供可靠的战斗数据支持。
---

## 附录 A：140 条状态技能结构化索引

以下索引来自当前上传的状态技能表。结构化标签用于指导后续录入 `effect_script`，不代表最终游戏规则已全部实测确认。

| 序号 | 技能 | 系别 | 能耗 | 结构化标签 | 原始效果 |
| ---: | --- | --- | ---: | --- | --- |
| 1 | 放晴 | 光系 | 0 | 技能威力/技能数值 | 光系技能威力永久+40%，应对防御：改为永久+80%。 |
| 2 | 漫反射 | 光系 | 1 | 技能威力/技能数值 | 每种系别中的至多1个技能，威力+35。 |
| 3 | 冬至 | 冰系 | 7 | 天气/场地；能耗/冷却/技能槽 | 将天气改为暴风雪。本技能能耗降低，降低值等于敌方技能总能耗。 |
| 4 | 冰捆缚 | 冰系 | 3 | 能耗/冷却/技能槽；连击/攻击次数 | 2连击，每次连击敌方获得全技能能耗+1。 |
| 5 | 冰点 | 冰系 | 2 | 异常/层数状态 | 敌方获得5层冻结，应对防御：额外获得5层。 |
| 6 | 瞬间零度 | 冰系 | 0 | 能耗/冷却/技能槽 | 本回合敌方使用的技能能耗+3，应对防御：改为全技能能耗+3。 |
| 7 | 速冻 | 冰系 | 4 | 印记 | 敌方获得2层减速印记。 |
| 8 | 雪球 | 冰系 | 1 | 属性增减 | 敌方获得速度-90。 |
| 9 | 雾气环绕 | 冰系 | 1 | 能耗/冷却/技能槽；生命/能量结算 | 回复能量，回复值等于敌方技能总能耗的一半。 |
| 10 | 霜冻 | 冰系 | 1 | 属性增减 | 敌方获得魔防-100%。 |
| 11 | 霜天 | 冰系 | 4 | 异常/层数状态；能耗/冷却/技能槽 | 敌方获得3层冻结，且每有1层冻结获得全技能能耗+1。 |
| 12 | 霜降 | 冰系 | 1 | 异常/层数状态 | 敌方获得4层冻结。 |
| 13 | 沙涌 | 地系 | 7 | 天气/场地；能耗/冷却/技能槽 | 将天气改为沙暴，每过1回合，本技能能耗永久-1。 |
| 14 | 泥浆铠甲 | 地系 | 2 | 属性增减；驱散/转移/转换/交换/继承 | 自己获得物攻和物防+40%，应对防御：额外使自己的增益翻倍。 |
| 15 | 流沙 | 地系 | 1 | 属性增减；行动控制/切换 | 敌方2回合无法更换精灵，应对防御：敌方获得双防-50%。 |
| 16 | 石肤术 | 地系 | 3 | 属性增减 | 自己获得物防+160%和魔防-60%。 |
| 17 | 蓄势待发 | 地系 | 4 | 印记 | 自己获得1层蓄势印记。 |
| 18 | 钧势 | 地系 | 3 | 属性增减 | 自己获得物防+140%和速度-30。 |
| 19 | 二律背反 | 幻系 | 3 | 印记；驱散/转移/转换/交换/继承 | 敌方获得3层星陨，应对防御：额外使敌方星陨层数翻倍。 |
| 20 | 心灵洞悉 | 幻系 | 7 | 印记 | 敌方获得星陨，获得层数等于敌方印记层数。 |
| 21 | 星轨裂变 | 幻系 | 1 | 印记 | 敌方获得2层星陨。 |
| 22 | 星链 | 幻系 | 3 | 印记；连击/攻击次数 | 2连击，每次连击使敌方获得1层星陨。 |
| 23 | 超新星馈赠 | 幻系 | 2 | 印记 | 敌方获得2层星陨，每使用1次，赋予的星陨层数+1。 |
| 24 | 超维投射 | 幻系 | 4 | 印记 | 敌方获得4层星陨。 |
| 25 | 勾魂 | 幽系 | 1 | 生命/能量结算 | 偷取敌方3能量。 |
| 26 | 嘲弄 | 幽系 | 2 | 属性增减；行动控制/切换 | 自己获得魔攻+70%，若敌方本回合替换精灵，自己获得速度+70。 |
| 27 | 恶作剧 | 幽系 | 0 | 生命/能量结算 | 敌方失去3能量，应对防御：改为敌方失去6能量。 |
| 28 | 降灵 | 幽系 | 2 | 印记 | 敌方获得1层降灵印记。 |
| 29 | 伪造账单 | 恶系 | 1 | 生命/能量结算；行动控制/切换 | 若敌方本回合回复生命，改为失去2倍。先手+1。 |
| 30 | 力量吞噬 | 恶系 | 4 | 技能威力/技能数值 | 敌方获得技能威力-20，自己获得技能威力+20。 |
| 31 | 恶念交换 | 恶系 | 4 | 生命/能量结算；驱散/转移/转换/交换/继承 | 与敌方交换生命比例。 |
| 32 | 恶意逃离 | 恶系 | 1 | 能耗/冷却/技能槽；行动控制/切换 | 脱离，应对防御：额外使敌方攻击技能能耗+6。 |
| 33 | 暗箱操作 | 恶系 | 1 | 属性增减 | 自己获得双攻和双防-100%，应对防御：改为敌方-100%。 |
| 34 | 欺诈契约 | 恶系 | 3 | 驱散/转移/转换/交换/继承 | 与敌方交换增益和减益。 |
| 35 | 贪婪 | 恶系 | 2 | 技能威力/技能数值 | 获得100%吸血。 |
| 36 | 隐藏条款 | 恶系 | 8 | 能耗/冷却/技能槽；驱散/转移/转换/交换/继承 | 与敌方交换携带的技能。 |
| 37 | 三连破 | 普通系 | 1 | 属性增减；连击/攻击次数 | 自己获得物攻+30%，3连击。 |
| 38 | 主场优势 | 普通系 | 3 | 印记 | 自己获得1层攻击印记。 |
| 39 | 休息回复 | 普通系 | 2 | 生命/能量结算 | 自己回复30%生命。 |
| 40 | 伺机而动 | 普通系 | 1 | 技能威力/技能数值；行动控制/切换 | 下一次行动时，攻击技能威力+70。 |
| 41 | 借用 | 普通系 | 0 | 能耗/冷却/技能槽 | 每回合随机变成己方队伍中其他精灵的技能。 |
| 42 | 力量增效 | 普通系 | 1 | 属性增减 | 自己获得物攻+100%。 |
| 43 | 加固 | 普通系 | 2 | 属性增减 | 自己获得物防+140%。 |
| 44 | 取念 | 普通系 | 0 | 能耗/冷却/技能槽 | 每回合随机变成敌方任意精灵的技能，且该技能能耗-2。 |
| 45 | 咆哮 | 普通系 | 1 | 属性增减 | 敌方获得物攻-130%。 |
| 46 | 复写 | 普通系 | 0 | 能耗/冷却/技能槽 | 每回合随机变成自己未携带的技能，且该技能能耗-2。 |
| 47 | 应激反应 | 普通系 | 2 | 生命/能量结算 | 自己回复25%生命，应对防御：改为回复50%生命。 |
| 48 | 快速移动 | 普通系 | 1 | 属性增减 | 自己获得速度+80，应对防御：改为速度+160。 |
| 49 | 摇篮曲 | 普通系 | 5 | 异常/层数状态；能耗/冷却/技能槽；行动控制/切换 | 敌方获得全技能能耗+3，应对防御：额外造成打断，且敌方下回合获得眩晕。 |
| 50 | 操控 | 普通系 | 1 | 能耗/冷却/技能槽 | 敌方本回合使用的技能能耗+7，持续3回合。 |
| 51 | 晒太阳 | 普通系 | 1 | 驱散/转移/转换/交换/继承 | 驱散敌方所有增益。 |
| 52 | 棘刺 | 普通系 | 2 | 印记 | 敌方获得1层棘刺印记。 |
| 53 | 激怒 | 普通系 | 3 | 能耗/冷却/技能槽 | 敌方除本回合使用的技能，其他技能能耗+3，持续3回合。 |
| 54 | 热身运动 | 普通系 | 2 | 连击/攻击次数 | 自己获得连击数+3。 |
| 55 | 精神扰乱 | 普通系 | 0 | 能耗/冷却/技能槽 | 敌方获得全技能能耗+1，应对防御：改为能耗+3。 |
| 56 | 耀眼 | 普通系 | 1 | 连击/攻击次数 | 敌方获得连击数-4。 |
| 57 | 聒噪 | 普通系 | 3 | 能耗/冷却/技能槽 | 敌方获得全攻击技能能耗+3，持续3回合。 |
| 58 | 退化 | 普通系 | 2 | 异常/层数状态；特殊机制标签 | 敌方获得1层萌化。 |
| 59 | 锐利眼神 | 普通系 | 2 | 属性增减 | 敌方获得物防和魔防-120%。 |
| 60 | 魔法增效 | 普通系 | 0 | 属性增减 | 自己获得魔攻+70%。 |
| 61 | 鼓劲 | 普通系 | 3 | 属性增减 | 自己获得魔防+170%。 |
| 62 | 啮合传递 | 机械系 | 2 | 属性增减；能耗/冷却/技能槽；特殊机制标签 | 自己获得速度+100，本技能位于1号位时能耗-2，传动。 |
| 63 | 杠杆置换 | 机械系 | 0 | 能耗/冷却/技能槽；生命/能量结算；驱散/转移/转换/交换/继承 | 自己回复2能量，交换两侧技能位置。 |
| 64 | 联动装置 | 机械系 | 0 | 能耗/冷却/技能槽；驱散/转移/转换/交换/继承；特殊机制标签 | 所有技能传动，应对防御：额外交换两侧技能能耗。 |
| 65 | 轴承支撑 | 机械系 | 3 | 能耗/冷却/技能槽；特殊机制标签 | 主动：本技能被动额外-1能耗，被动：两侧技能能耗-1，传动。 |
| 66 | 化劲 | 武系 | 2 | 技能威力/技能数值 | 获得全技能威力+40。 |
| 67 | 提气 | 武系 | 4 | 技能威力/技能数值；行动控制/切换 | 获得全技能威力+40，若敌方本回合替换精灵，额外获得威力+50。 |
| 68 | 气沉丹田 | 武系 | 10 | 属性增减；能耗/冷却/技能槽；生命/能量结算 | 自己回复60%生命，获得物攻+130%，每次应对后本技能能耗-3，使用后能耗重置。 |
| 69 | 破绽 | 武系 | 1 | 属性增减 | 敌方获得双防-50%，应对防御：自己额外获得物攻+50%。 |
| 70 | 破防 | 武系 | 3 | 属性增减；能耗/冷却/技能槽 | 敌方获得双防-130%，应对防御：额外使被应对技能冷却2回合。 |
| 71 | 预备势 | 武系 | 1 | 属性增减 | 自己获得物攻+80%，应对防御：额外使敌方获得物防-80%。 |
| 72 | 以毒攻毒 | 毒系 | 1 | 异常/层数状态；属性增减 | 敌方每有1层中毒效果，自己获得魔攻+30%。 |
| 73 | 剧毒 | 毒系 | 2 | 异常/层数状态 | 敌方获得3层中毒，应对防御：改为获得8层。 |
| 74 | 毒孢子 | 毒系 | 3 | 异常/层数状态 | 敌方获得5层中毒。 |
| 75 | 毒雾 | 毒系 | 7 | 异常/层数状态；驱散/转移/转换/交换/继承 | 将敌方所有增益，转化成中毒。 |
| 76 | 疫病吐息 | 毒系 | 3 | 印记；异常/层数状态 | 敌方获得1层中毒印记。 |
| 77 | 腐化 | 毒系 | 1 | 异常/层数状态；属性增减 | 敌方每有1层中毒效果，敌方获得双攻-30%。 |
| 78 | 落井下毒 | 毒系 | 6 | 驱散/转移/转换/交换/继承 | 使敌方精灵减益的层数翻倍。 |
| 79 | 打湿 | 水系 | 4 | 印记 | 自己获得1层湿润印记。 |
| 80 | 洗礼 | 水系 | 1 | 能耗/冷却/技能槽；驱散/转移/转换/交换/继承 | 驱散自己的减益，并获得全技能能耗-1。 |
| 81 | 润泽 | 水系 | 7 | 属性增减 | 自己获得魔攻+190%。 |
| 82 | 盐水浴 | 水系 | 1 | 能耗/冷却/技能槽 | 自己获得全技能能耗-2，应对防御：改为技能能耗-3。 |
| 83 | 落雨 | 水系 | 8 | 天气/场地；能耗/冷却/技能槽；驱散/转移/转换/交换/继承 | 将天气改为雨天。本技能受能耗降低效果的影响翻倍。 |
| 84 | 蓄水 | 水系 | 1 | 能耗/冷却/技能槽 | 下次使用的技能能耗-6。 |
| 85 | 充分燃烧 | 火系 | 3 | 异常/层数状态；驱散/转移/转换/交换/继承 | 使敌方身上的灼烧翻倍，并触发1次灼烧伤害。 |
| 86 | 天火 | 火系 | 3 | 异常/层数状态 | 敌方获得10层灼烧，应对防御：改为获得30层。 |
| 87 | 引燃 | 火系 | 2 | 异常/层数状态 | 敌方获得10层灼烧。 |
| 88 | 怒火 | 火系 | 1 | 属性增减 | 自己获得双攻+130%和双防-40%。 |
| 89 | 热身 | 火系 | 1 | 技能威力/技能数值；驱散/转移/转换/交换/继承 | 下一次攻击技能威力翻倍，应对防御：改为威力变为3倍。 |
| 90 | 焚烧烙印 | 火系 | 3 | 印记；异常/层数状态；驱散/转移/转换/交换/继承 | 驱散双方所有印记，每驱散1层，敌方获得5层灼烧。 |
| 91 | 加大功率 | 电系 | 4 | 生命/能量结算；行动控制/切换 | 自己脱离，被替换入场的精灵回复8能量。 |
| 92 | 增程电池 | 电系 | 2 | 印记 | 自己获得1层蓄电印记。 |
| 93 | 电离爆破 | 电系 | 3 | 属性增减；连击/攻击次数 | 敌方获得速度-40，3连击。 |
| 94 | 过载回路 | 电系 | 1 | 能耗/冷却/技能槽；行动控制/切换 | 自己返场，下回合所选技能使用次数+1。 |
| 95 | 远程访问 | 电系 | 2 | 行动控制/切换 | 使敌方精灵返场。 |
| 96 | 麻痹 | 电系 | 2 | 属性增减；行动控制/切换 | 敌方先手-1，应对防御：额外使敌方获得攻击-70%。 |
| 97 | 乘风 | 翼系 | 2 | 属性增减 | 自己获得速度+120。 |
| 98 | 暴风眼 | 翼系 | 2 | 连击/攻击次数；行动控制/切换 | 行动时连击数+100%。 |
| 99 | 疾风连袭 | 翼系 | 0 | 能耗/冷却/技能槽；行动控制/切换；特殊机制标签 | 释放自己释放过的迅捷技能，其能耗之和的二分之一加至本技能能耗，每次使用后能耗+1 |
| 100 | 羽化加速 | 翼系 | 2 | 技能威力/技能数值；行动控制/切换；特殊机制标签 | 自己获得技能威力+20，迅捷。 |
| 101 | 风起 | 翼系 | 4 | 印记 | 自己获得1层风起印记。 |
| 102 | 风隐 | 翼系 | 2 | 行动控制/切换 | 敌方和自己均脱离。先手-1。 |
| 103 | 飞羽 | 翼系 | 0 | 行动控制/切换；驱散/转移/转换/交换/继承；特殊机制标签 | 迅捷，驱散敌方1种增益。 |
| 104 | 丰饶 | 草系 | 3 | 属性增减 | 自己获得物攻和魔攻+130%。 |
| 105 | 光合作用 | 草系 | 4 | 印记 | 自己获得1层光合印记。 |
| 106 | 孢子 | 草系 | 3 | 异常/层数状态 | 敌方获得1层寄生。 |
| 107 | 富养化 | 草系 | 3 | 生命/能量结算 | 为场下每个精灵回复3能量。 |
| 108 | 徒长 | 草系 | 2 | 生命/能量结算 | 自己回复10能量。 |
| 109 | 根吸收 | 草系 | 2 | 生命/能量结算 | 自己回复15%生命和4能量。 |
| 110 | 氧输送 | 草系 | 2 | 属性增减；生命/能量结算 | 自己回复4能量，并获得魔攻+80%。 |
| 111 | 盛开 | 草系 | 1 | 技能威力/技能数值 | 自己获得技能威力+30，应对防御：改为威力+70。 |
| 112 | 移花接木 | 草系 | 2 | 生命/能量结算；行动控制/切换 | 自己回复15%生命，随后脱离。 |
| 113 | 聚盐 | 草系 | 3 | 连击/攻击次数；生命/能量结算 | 2连击，每次连击自己回复5%生命和1能量，使用后本技能连击数永久+1。 |
| 114 | 花炮 | 草系 | 2 | 属性增减；连击/攻击次数 | 2连击，每次连击自己获得魔攻+50%。 |
| 115 | 芳香诱引 | 草系 | 1 | 异常/层数状态；连击/攻击次数；行动控制/切换 | 自己获得连击数+2，应对防御：额外造成打断，并眩晕敌方1回合。 |
| 116 | 击鼓传花 | 萌系 | 3 | 行动控制/切换；驱散/转移/转换/交换/继承 | 自己脱离，下个入场精灵继承自己增益。 |
| 117 | 反弹 | 萌系 | 5 | 异常/层数状态；驱散/转移/转换/交换/继承；特殊机制标签 | 将自己的萌化转移给敌方。 |
| 118 | 甜心续航 | 萌系 | 3 | 异常/层数状态；生命/能量结算；特殊机制标签 | 自己和敌方获得萌化：回复40%生命和4能量。 |
| 119 | 生日蛋糕 | 萌系 | 2 | 异常/层数状态；能耗/冷却/技能槽；特殊机制标签 | 自己获得萌化：全技能能耗永久-4。 |
| 120 | 示弱 | 萌系 | 1 | 异常/层数状态；属性增减；特殊机制标签 | 自己获得萌化：速度永久+150。 |
| 121 | 赤子之心 | 萌系 | 6 | 异常/层数状态；生命/能量结算；特殊机制标签 | 场下每个精灵获得萌化，之后回复40%生命和4能量。 |
| 122 | 假寐 | 虫系 | 2 | 异常/层数状态；能耗/冷却/技能槽；生命/能量结算；特殊机制标签 | 自己回复2能量，获得1次奉献：能耗-2。 |
| 123 | 束缚 | 虫系 | 2 | 异常/层数状态；特殊机制标签 | 敌方获得2层中毒，获得1次奉献：敌方获得2层中毒。 |
| 124 | 虫群智慧 | 虫系 | 3 | 异常/层数状态；特殊机制标签 | 获得2次随机奉献。 |
| 125 | 虫茧 | 虫系 | 1 | 异常/层数状态；技能威力/技能数值；生命/能量结算；特殊机制标签 | 自己回复20%生命，获得1次奉献：获得10%吸血。 |
| 126 | 贮藏 | 虫系 | 2 | 属性增减；能耗/冷却/技能槽 | 自己获得双攻+50%，每携带1个0能耗技能，额外+50%。 |
| 127 | 食腐 | 虫系 | 2 | 印记；生命/能量结算；驱散/转移/转换/交换/继承 | 驱散敌方印记，每层印记回复自己10%生命。 |
| 128 | 架势 | 龙系 | 2 | 能耗/冷却/技能槽；生命/能量结算；行动控制/切换；特殊机制标签 | 自己回复20%生命，下次技能无需蓄力。 |
| 129 | 龙吟 | 龙系 | 3 | 属性增减；行动控制/切换；特殊机制标签 | 蓄力，自己获得双攻+100%和速度+60。 |
| 130 | 龙威 | 龙系 | 3 | 印记 | 自己获得1层龙噬印记。 |
| 131 | 三鼓作气 | 普通系 | 3 | 属性增减；连击/攻击次数 | 获得物攻+30%，3连击。 |
| 132 | 小偷小摸 | 幽系 | 1 | 生命/能量结算 | 偷取敌方3能量。 |
| 133 | 捆缚 | 虫系 | 2 | 异常/层数状态；特殊机制标签 | 敌方获得2层中毒，获得1次奉献：敌方获得2层中毒。 |
| 134 | 极速冷冻 | 冰系 | 2 | 能耗/冷却/技能槽 | 敌方获得全技能能耗+2，应对防御：能耗+4。 |
| 135 | 柔弱 | 萌系 | 1 | 异常/层数状态；属性增减；特殊机制标签 | 获得萌化，敌方获得物攻-70%，敌方获得物防-70%。 |
| 136 | 求雨 | 水系 | 8 | 天气/场地；能耗/冷却/技能槽；驱散/转移/转换/交换/继承 | 将天气变为雨天，本技能能耗降低效果收益翻倍。 |
| 137 | 炎爆术 | 火系 | 2 | 印记；异常/层数状态；驱散/转移/转换/交换/继承 | 将敌方印记转换为三倍的灼烧层数。 |
| 138 | 玩具乐园 | 萌系 | 7 | 异常/层数状态；属性增减；特殊机制标签 | 自身及背包里的精灵获得萌化，并提升30%攻防，速度+20。 |
| 139 | 羽毛舞 | 翼系 | 2 | 行动控制/切换；驱散/转移/转换/交换/继承；特殊机制标签 | 迅捷，驱散敌方一种增益。 |
| 140 | 逆向演化 | 萌系 | 1 | 异常/层数状态；驱散/转移/转换/交换/继承；特殊机制标签 | 解除萌化，每层萌化会给敌方赋予一层萌化。 |


## 附录 B：推荐枚举值与含义

本附录用于统一数据库和代码里的枚举，避免后续字段出现同义不同名。

### B.1 `category` 状态大类

| 枚举值 | 中文含义 | 说明 |
| --- | --- | --- |
| normal_buff | 普通增益 | 物攻提升、物防提升、速度提升等，通常可被普通驱散，部分可切换清除规则视具体效果。 |
| normal_debuff | 普通减益 | 物攻下降、物防下降、速度下降等，通常可通过切换当前在场精灵清除。 |
| abnormal_stack | 异常 / 层数状态 | 冻结、中毒、灼烧、寄生、萌化、奉献等。是否切换清除由字段决定。 |
| skill_slot_modifier | 技能槽修正 | 能耗、威力、冷却、技能变形、技能位置交换、使用次数变化。 |
| action_rule | 行动规则状态 | 先手、迅捷、蓄力、打断、眩晕、无法更换、脱离、返场。 |
| damage_modifier | 伤害修正 | 增伤、减伤、吸血、反伤、最终倍率。 |
| defense_skill_state | 防御技能状态 | 防御类技能产生的减伤、应对防御分支。不是通用护盾。 |
| special_mechanic | 特殊机制 | 传动、萌化联动、奉献、技能复制等难以归入普通计算的机制。 |
| resource_change | 生命 / 能量结算 | 回复生命、失去能量、偷取能量、交换生命比例。多数作为事件，不一定常驻显示。 |
| event_only | 瞬时事件 | 驱散、转换、交换等瞬时操作，只进事件日志。 |

### B.2 `polarity` 倾向

| 枚举值 | 中文含义 | 说明 |
| --- | --- | --- |
| positive | 正面 | 对拥有方有利。 |
| negative | 负面 | 对拥有方不利。 |
| neutral | 中性 | 不明显有利或不利，例如天气、场地。 |
| mixed | 混合 | 同时包含正负效果，建议能拆则拆成多个原子状态。 |

### B.3 `scope` 作用范围

| 枚举值 | 中文含义 | 说明 |
| --- | --- | --- |
| pet | 精灵级 | 绑定某只精灵。 |
| side | 队伍侧 | 绑定己方或敌方队伍。印记虽然是队伍侧，但建议使用独立 Mark 结构。 |
| battlefield | 全战场 | 天气、全局场地效果。 |
| skill_slot | 技能槽 | 绑定某个技能格或技能集合。 |
| turn_context | 当前回合 | 只在本回合计算中存在的临时状态。 |

### B.4 `duration_type` 持续类型

| 枚举值 | 中文含义 | 说明 |
| --- | --- | --- |
| instant | 瞬时 | 立即结算，不形成常驻状态。 |
| turns | 按回合 | 使用 `remaining_turns`。 |
| uses | 按次数 | 使用 `remaining_uses`，例如“下次技能”。 |
| permanent_until_switch | 持续到切换 | 切换当前在场精灵时清除。 |
| permanent_until_dispelled | 持续到被驱散 | 不随回合自然消失。 |
| battle_permanent | 整场持续 | 除非特殊规则，否则整场存在。 |
| skill_specific | 技能特定 | 需要专门脚本处理。 |
| unknown | 未确认 | 暂时未知，等待实测。 |

### B.5 `stack_rule` 叠加规则

| 枚举值 | 中文含义 | 说明 |
| --- | --- | --- |
| add_layers | 层数相加 | 新层数加到旧层数上，受 `max_layers` 限制。 |
| replace | 直接替换 | 新状态替换旧状态。 |
| refresh_duration | 刷新持续 | 层数不变，只刷新回合数。 |
| add_layers_and_refresh | 加层并刷新 | 层数相加，同时刷新持续。 |
| keep_max | 保留较高 | 新旧数值取较高者。 |
| keep_min | 保留较低 | 新旧数值取较低者。 |
| separate_instances | 独立实例 | 每次施加形成独立实例。 |
| skill_specific | 技能特定 | 使用脚本处理。 |

### B.6 `conflict_policy` 冲突规则

| 枚举值 | 中文含义 | 说明 |
| --- | --- | --- |
| none | 无冲突 | 可同时存在。 |
| replace_old | 替换旧效果 | 新效果覆盖旧效果。印记槽默认可先按此处理，待实测修正。 |
| reject_new | 拒绝新效果 | 已有效果时新效果不生效。 |
| merge_layers | 合并层数 | 同组效果合并层数。 |
| keep_higher_value | 保留更高数值 | 常用于同类威力 / 属性提升。 |
| keep_lower_value | 保留更低数值 | 常用于同类能耗降低。 |
| skill_specific | 技能特定 | 由技能脚本决定。 |

### B.7 `op_type` 技能原子操作

| 枚举值 | 中文含义 | 说明 |
| --- | --- | --- |
| apply_effect | 施加普通状态 | 对 `EffectDefinition` 生成实例。 |
| remove_effect | 移除状态 | 移除指定状态。 |
| stack_effect | 叠加状态层数 | 修改状态层数。 |
| apply_mark | 施加印记 | 对 `MarkDefinition` 生成 / 更新 `MarkInstance`。星陨使用该操作。 |
| remove_mark | 移除印记 | 消除印记。 |
| convert_mark | 转换印记 | 将印记转换为其他状态，例如转换为灼烧。 |
| set_weather | 设置天气 | 替换当前天气。 |
| modify_stat | 修改属性 | 物攻、物防、魔攻、魔防、速度、生命等。 |
| modify_skill_cost | 修改技能能耗 | 对技能槽或技能集合生效。 |
| modify_skill_power | 修改技能威力 | 威力固定值、百分比或倍率。 |
| modify_hit_count | 修改连击数 | 连击数增加、降低、翻倍等。 |
| modify_hp | 修改生命 | 回复、失去、交换生命比例。 |
| modify_energy | 修改能量 | 回复、失去、偷取能量。 |
| dispel_effect | 驱散状态 | 驱散普通增益 / 减益。默认不处理印记。 |
| transfer_effect | 转移状态 | 把状态从一方转移到另一方。 |
| convert_effect | 转换状态 | 例如将增益转化为中毒。 |
| exchange_effect | 交换状态 | 例如交换双方增益和减益。 |
| switch_pet | 切换 / 脱离 / 返场 | 行动规则相关。 |
| interrupt_action | 打断 | 造成打断。 |
| apply_stun | 眩晕 | 下回合无法行动等。 |
| special_script | 特殊脚本 | 复杂效果入口。 |

### B.8 `target` 操作目标

| 枚举值 | 中文含义 | 说明 |
| --- | --- | --- |
| self_active_pet | 己方当前精灵 | 技能使用者当前在场精灵。 |
| enemy_active_pet | 敌方当前精灵 | 对方当前在场精灵。 |
| self_side | 己方队伍 | 队伍级效果或印记。 |
| enemy_side | 敌方队伍 | 队伍级效果或印记。 |
| battlefield | 全战场 | 天气或场地。 |
| self_bench_pets | 己方后备精灵 | 后备精灵效果。 |
| enemy_bench_pets | 敌方后备精灵 | 后备精灵效果。 |
| all_self_pets | 己方全部精灵 | 包含在场和后备。 |
| all_enemy_pets | 敌方全部精灵 | 包含在场和后备。 |
| selected_skill_slot | 指定技能槽 | 对某个技能格生效。 |
| current_used_skill | 本回合使用技能 | 对本回合使用技能生效。 |
| all_skill_slots | 全部技能槽 | 对所有技能生效。 |

### B.9 `source` 信息来源

| 枚举值 | 中文含义 | 说明 |
| --- | --- | --- |
| database_rule | 数据库规则 | 来自静态数据库。 |
| auto_recognition | 自动识别 | 来自图像识别或 OCR。 |
| manual_input | 手动输入 | 用户手动录入或修正。优先级最高。 |
| system_calculated | 系统计算 | 属性、伤害、速度等计算结果。 |
| system_inferred | 系统推算 | 敌方配置、未知技能等推算结果。 |

### B.10 `display_group` UI 显示分区

| 枚举值 | 中文含义 | 说明 |
| --- | --- | --- |
| pet_status_bar | 精灵状态栏 | 普通增益 / 减益、异常、行动限制等。 |
| side_mark_bar | 队伍印记栏 | 增益印记槽和减益印记槽。 |
| battlefield_top | 战场顶部 | 天气和全局场地效果。 |
| skill_slot_badge | 技能图标角标 | 能耗、威力、冷却、次数、技能变形等。 |
| bench_panel | 后备精灵面板 | 场下可见持久状态。 |
| event_log_only | 事件日志 | 瞬时事件，不常驻显示图标。 |

---

## 附录 C：字段落库与代码实现优先级

为了避免第一阶段开发量过大，建议按以下顺序实现字段。

### C.1 第一阶段必须实现

| 对象 | 必须字段 |
| --- | --- |
| PetDefinition | pet_id、pet_name、avatar、element_types、六维种族资质、learnable_skill_ids |
| SkillDefinition | skill_id、skill_name、element_type、skill_category、base_power、base_energy_cost、damage_rule、hit_rule、effect_script |
| EffectDefinition | effect_id、name、category、polarity、scope、stack_rule、duration_type、clear_on_switch、stat_modifiers、skill_cost_modifiers、is_visible_icon、display_group |
| MarkDefinition | mark_id、mark_name、polarity、max_layers、stack_rule、conflict_policy、clear_on_switch=false、clear_by_mark_dispel |
| BattleEvent | event_id、turn_number、event_type、actor、target、skill、damage_value、hp_percent_delta、full_effect_snapshot、source、confidence |
| BuildCandidate | nature、individual_talent_distribution、六维最终属性、match_score、confidence、is_excluded |

### C.2 第二阶段再补充

| 对象 | 字段 |
| --- | --- |
| RecognitionTemplate | 图标模板、名称区域、置信度、候选结果 |
| SkillSlotEffect | affected_skill_scope、modifier_type、modifier_value、remaining_turns / uses |
| BattleEffectSnapshot | 完整快照独立存储与回放 |
| ResourceChangeResult | 生命 / 能量变化结构化记录 |
| skill_weights | 根据常见技能组或对战数据更新技能权重 |

### C.3 容易误建模的字段提醒

| 容易出错点 | 正确处理 |
| --- | --- |
| 把星陨放入异常状态 | 星陨是减益印记，应放入 `MarkDefinition` 和 `negative_mark_slot` |
| 把所有状态都放到精灵身上 | 印记是队伍侧，天气是战场侧，技能槽效果是技能槽侧 |
| 切换时清掉所有负面 | 只清除 `clear_on_switch=true` 的普通状态；冻结不清除；印记不清除 |
| 普通驱散清掉印记 | 普通驱散不处理印记，除非技能明确写明印记 |
| 用当前状态推算过去伤害 | 必须使用伤害事件发生时的快照 |
| 用常见技能组排除冷门技能 | 常见技能组只能影响权重，不能直接排除 |
| 把防御技能当护盾 | 本游戏当前没有通用护盾，防御类减伤作为技能特殊效果或防御技能状态 |
| 技能效果只存自然语言 | 必须拆成 `EffectOperation`，自然语言只能作为备注 |

