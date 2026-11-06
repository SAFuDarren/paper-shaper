---
name: paper-shaper
description: Author-led paper planning and section-by-section collaboration from research files. Use to inventory findings, implementation, evidence and references, adapt journal or conference goals, compare mainlines and outlines, and support explicitly authorized writing units. The author controls value, structure, emphasis and wording. 默认只规划，逐轮人审。
metadata:
  runtime: "Python 3.9+; Windows, macOS, Linux; standard library only. Run doctor with the intended interpreter."
---

# PaperShaper

人决定价值、目标、结构、详略和最终表达；AI完成当前任务，交人复核。AI推荐、自查或其他skill的PASS不算人的同意。讨论和交付使用用户要求的语言。

首次选择当前环境的 Python 3.9+：虚拟环境优先用`python`；Windows常用`py -3`或`python`；macOS/Linux常用`python3`。以下命令均调用所选解释器与`<本skill>/scripts/framework.py`；首次使用或换环境先运行`doctor`，不要额外安装包。

1. 复用项目工作目录。首次用`init <工作目录> --project-root <项目>`；已有进度直接运行`packet <工作目录>`恢复当前任务。返回等待人审、等待授权或完成停止时，按该状态停止，不重做前轮。
2. 只加载当前任务、已定决定、选定材料及所需能力，不读取全部阶段/历史/skill。材料不足用`attach`登记；超限可同ID重选较短片段，或用`detach`移出片段（保留来源哈希）。文件移动/移除时先`reopen`最早受影响轮，再用`retire-input --path <旧路径> --reason <原因>`留存旧哈希并退役当前输入，然后登记替代材料。基础任务超限须重定范围或明确增预算，不自动拆任务或截断内容。
3. 外接能力先`discover`、`bind`；用`start`冻结版本。`request`可为单个能力、选定材料和一个输出生成小任务包，具体参数见`help`；逐项处理并保存结果，不一次读入所有原文。只读选中skill的适用入口，不启动整套管线或改变人审状态。中途换版本需`reopen`并重新绑定；大型入口需更轻提供者或另定任务，不能省略必读指令。
4. R02/R04按当前包指针读`references/research-records.md`，用`research_map.py`索引实际入口、逐项记录成果去向和推理依据；程序检查来源、覆盖、关系及主线绑定，不能替代科学判断。其余轮不加载该说明。完成当前任务，用 `form <工作目录>` 获取结果格式；提交真实成果及自查，再运行 `submit <工作目录> --result <结果JSON>`。程序检查角色、文件、选择项和依赖，输出复核包，然后停止等待。
5. 收到针对该交付的真实人类同意后才运行 `review ... --decision approve --message-ref ... --quote ...`；多方案时传 `--selection-file`，不能代选。修改用 `review --decision revise`；上游/输入变化用 `reopen`处理受影响节点。重开R05或其上游会退役旧写作节点并撤销旧授权，新架构确认后须重新授权。不会因“继续讨论”自动批准。

`help`列命令和结果契约。所有状态写入、版本检查、依赖、缺项、审批绑定、任务选择与上下文大小由程序处理，不在提示词中重演。默认`plan_only`；明确写作授权用`authorize`登记到指定单元。规划通过不自动授权正文。

外接skill只交当前任务成果，经同一提交/人审入口；缺少skill可直接使用可用工具完成能力或报告缺项，不自动安装。框架不联网调用模型、不投稿。程序检查记录一致性，不能认证人类身份或学术正确性；任务包预算也不能控制宿主已经加载的上下文。
