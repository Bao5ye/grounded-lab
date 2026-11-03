# 项目操作

脚本只使用 Python 标准库，不访问网络、不调用模型。下例将 `<skill>`、项目路径和材料路径替换为实际路径。工作目录和项目数据不得位于待公开的 Git 仓库。

## 建立、导入和检查

```text
python <skill>/scripts/grounded.py init --project <project.json> --title "研究项目"
python <skill>/scripts/grounded.py sample --project <example.json>
python <skill>/scripts/grounded.py import-text --project <project.json> --file <interview.txt> --participant "P01" --role "研究资料"
python <skill>/scripts/grounded.py show --project <project.json>
python <skill>/scripts/grounded.py validate --project <project.json>
```

创建、样例、备份、恢复和导出均拒绝覆盖同名目标。导入每份材料不超过 3 MB；项目保存完整文本及源文件 SHA-256，段落按空行切分，长段拆分，片段记录来源 ID、位置和字符范围。脚本输出 ID 和数量，使用 `show` 查看原文；当上下文不足时逐批读取或切片文件，记录实际覆盖状态。旧版项目如不含覆盖记录，将未知项按未处理显示。

## 结构化修改

模型先生成一个单独的 UTF-8 JSON 操作文件，用户确认前的建议使用 `--actor model`；研究者直接提供的内容使用 `--actor human`。先运行 validate 获取 SHA-256，再以 `--expected-sha256 <hash>` 防止覆盖期间发生的其他修改。整批在内存中校验；任何操作失败时不写入项目。

```text
python <skill>/scripts/grounded.py apply --project <project.json> --ops <operations.json> --actor model --expected-sha256 <hash>
```

最外层格式为 `{"ops":[...]}`。新增项可在 data 中指定不重复 ID；更新项在操作的顶层提供现有 ID。操作按数组顺序应用，可先建立范畴再在后续编码中引用它；证据 ID 必须来自实际项目，切勿沿用下面的占位符。

```json
{
  "ops": [
    {"action":"upsert-category","data":{"id":"K-001","name":"范畴名称","type":"范畴","description":"范畴定义","properties":["属性：维度"],"evidenceIds":["E-实际ID"]}},
    {"action":"upsert-code","data":{"id":"C-001","name":"概念名称","definition":"纳入范围","categoryId":"K-001","evidenceIds":["E-实际ID"],"quote":"原文中的连续引文","rationale":"贴近资料的理由"}},
    {"action":"coverage","id":"E-实际ID","data":{"status":"coded","note":"已人工或模型阅读"}},
    {"action":"upsert-sampling","data":{"title":"采集任务","reason":"理论缺口","question":"具体追问"}}
  ]
}
```

支持操作：

| action | data 字段或用途 |
|---|---|
| set-intent | title、motivation、question、population、unit、boundary、assumptions；confirmed 为 true 需人工核验 |
| source-policy | 顶层 id 为资料 ID；included 布尔值、role 文本 |
| upsert-code | name、definition、categoryId（可空）、evidenceIds、quote、rationale；新增／修改后均为待审核 |
| set-code-status | 顶层 id 为编码 ID；status 为 pending、confirmed 或 rejected |
| upsert-category | name、type、description、properties 数组、evidenceIds 数组；子范畴可设 parentId |
| upsert-relation | from、to 范畴 ID，label、caution、evidenceIds；无证据会提示待核验 |
| set-core | selected、story、alternatives 数组，可选 evidenceIds；修改后重新开放确认 |
| confirm-core | 仅在用户明确确认当前候选时执行 |
| upsert-memo | title、type、text，可选 evidenceId、date |
| upsert-sampling | title、reason、question |
| set-sampling-status | 顶层 id 为任务 ID，done 布尔值；不等于饱和 |
| coverage | 顶层 id 为证据 ID；status 为 coded、read-uncoded、unread，note 为文本 |
| record-run | detail 记录资料范围、角色分工、宿主提供的模型名称、未完成环节等；不写入密钥 |

确认或搁置编码、确认研究意图或核心范畴前必须取得用户对具体内容的明确判断，然后使用 `--actor human --human-review`。此参数只记录调用方提供的人工确认，不代表脚本能够自行核实用户意愿。
并发环境下的 SHA-256 参数只能检测保存前发现的变更，不是文件锁；应避免多个会话同时修改同一个项目。

## 导出与备份

```text
python <skill>/scripts/grounded.py export --project <project.json> --out <new-output-directory>
python <skill>/scripts/grounded.py backup --from <project.json> --to <backup.json>
python <skill>/scripts/grounded.py restore --from <backup.json> --to <new-project.json>
```

导出包含三级编码 CSV、独立 HTML 报告、Mermaid 关系图和完整 JSON 备份。HTML 含原文、编码、范畴关系、理论、备忘、抽样、覆盖记录与审计记录；发送或公开前应按用户授权检查敏感内容。图中只显示已记录关系，没有保存的关系不会被脚本推断。导出结果不包含模型凭据。
