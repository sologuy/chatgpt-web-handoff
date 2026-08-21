# Handoff ID
{{JOB_ID}}

# 追问
{{SUBJECT}}

# 补充上下文
<只写「上一轮之后新发生的事」：新证据、你按建议做了什么、结果如何。
 对话里已经有的背景不要重复贴——对方看得见。没有新增就写「无」。>

# 输出要求
请在回答的最后，用一个 fenced code block 原样输出下面这段，字段名与顺序不要改；没有内容的列表写 `- none`：

```
CGH_RESULT_{{JOB_ID}}
verdict: pass | revise | reject
confidence: 0.0-1.0
summary: <一句话结论>
findings:
- <发现 1>
recommended_actions:
- <行动 1>
missing_information:
- <还缺什么信息才能更确定>
CGH_END_{{JOB_ID}}
```
