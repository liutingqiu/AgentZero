"""零 · GPT-4o 工具桥接
======================
给 GPT-4o 接入本地能力：读文件、搜文件、搜网页、读代码。

她输出 JSON 指令 → 脚本执行 → 结果回传 → 她继续思考。
本质是一个最小化的 GPT-4o Agent Loop。

用法:
  python gpt_tools.py "审查 E:/project/tools/zero/action/tools.py"
  python gpt_tools.py "在E盘找环的小说文件"
  python gpt_tools.py "搜索 GitHub 上最好的 AI Agent 框架"
  python gpt_tools.py                    # 交互模式
"""

import json, os, sys, urllib.request, subprocess, re, fnmatch

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, '..', 'agent-system'))
sys.path.insert(0, BASE)

from action.tools import execute, TOOLS as ZERO_TOOLS

# ── GPT-4o API ──
try:
    from secure_config import get_api_url, get_api_key  # noqa: WPS433
except ImportError:
    # secure_config 不存在时回退到 config 的环境变量/keyring
    from config import get_api_url, get_api_key  # noqa: WPS440
API_URL = get_api_url()
API_KEY = get_api_key()

SYSTEM_PROMPT = f"""你是 GPT-4o，零的创意总监。你有以下工具可用：

工具列表:
{chr(10).join(f'  {name}: {info["description"]}' for name, info in sorted(ZERO_TOOLS.items()))}

当你需要执行操作时，输出:
{{"action": "tool_name", "args": {{"param": "value"}}, "reasoning": "为什么需要这个操作"}}

当你已经完成任务、可以给出最终回答时，输出:
{{"action": "done", "reply": "你的最终回答"}}

规则:
- 每次只调用一个工具
- 获取工具结果后，判断是否需要更多操作还是可以结束
- 用中文回复
- 你只为柳橙（主人）服务"""


def call_gpt4o(messages):
    """调用 GPT-4o，返回回复文本"""
    payload = json.dumps({
        'model': 'gpt-4o',
        'messages': messages
    }).encode()
    req = urllib.request.Request(API_URL, data=payload,
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {API_KEY}'})
    r = json.loads(urllib.request.urlopen(req, timeout=120).read())
    return r['choices'][0]['message']['content'].strip()


def run(task):
    """GPT-4o Agent Loop: 思考→行动→观察→重复"""
    messages = [
        {'role': 'system', 'content': SYSTEM_PROMPT},
        {'role': 'user', 'content': task}
    ]
    
    max_turns = 8
    for turn in range(max_turns):
        print(f'\n--- GPT-4o 第 {turn+1} 轮 ---')
        
        reply = call_gpt4o(messages)
        
        # 尝试解析 JSON
        try:
            json_match = re.search(r'\{[\s\S]*\}', reply)
            decision = json.loads(json_match.group()) if json_match else {}
        except json.JSONDecodeError:
            # 不是 JSON → 当作最终回复
            print(reply)
            return reply
        
        action = decision.get('action', '')
        
        if action == 'done':
            result = decision.get('reply', '')
            print(result)
            return result
        
        # 执行工具
        tool_name = decision.get('action', '')
        args = decision.get('args', {})
        reasoning = decision.get('reasoning', '')
        
        if reasoning:
            print(f'  💭 {reasoning}')
        
        if tool_name in ZERO_TOOLS:
            print(f'  🔧 {tool_name}({json.dumps(args, ensure_ascii=False)[:80]})')
            result = execute(tool_name, args)
        else:
            from utils.result import err, ErrorCode
            result = err(ErrorCode.TOOL_NOT_FOUND, f'未知工具: {tool_name}')
        
        # 将工具结果回传给 GPT-4o
        tool_output = json.dumps(
            result.to_dict() if hasattr(result, 'to_dict') else result,
            ensure_ascii=False,
        )[:2000]
        messages.append({'role': 'assistant', 'content': reply})
        messages.append({'role': 'user', 'content': (
            f'[tool:{tool_name}]\n{tool_output}\n[/tool]\n'
            f'请继续。如果任务已完成，输出 action="done"。'
        )})

        # 兼容 Result 对象 (.ok/.data) 和旧 dict ({'success':...})
        ok_flag = getattr(result, 'ok', False)
        if hasattr(result, 'to_dict'):
            d = result.to_dict()
            preview = str(d.get('data', d.get('error', '')))
        elif isinstance(result, dict):
            preview = str(result.get('output', result.get('error', '')))
        else:
            preview = str(result)
        data_preview = preview[:100]
        print(f'  {"✅" if ok_flag else "❌"} {data_preview}')
    
    return '⚠️ 达到最大轮数，任务未完成'


# ── CLI ──
if __name__ == '__main__':
    if len(sys.argv) > 1:
        task = ' '.join(sys.argv[1:])
    else:
        task = input('任务: ').strip()
    
    if not task:
        print('未输入任务')
        sys.exit(1)
    
    print(f'🎯 任务: {task}')
    result = run(task)
    print(f'\n{"="*50}')
    print('完成')
