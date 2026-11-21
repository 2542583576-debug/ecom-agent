import base64, json, re, time, urllib.request, urllib.error
from pathlib import Path


def load_env():
    data = {}
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip().strip('"').strip("'")
    return data


cfg = load_env()
KEY = cfg["BAILIAN_API_KEY"]
BASE = cfg["BAILIAN_BASE_URL"].rstrip("/")
MODEL = cfg["BAILIAN_MODEL"]
ME = "U1001"

TICKETS_FILE = Path("tickets.json")


def load_tickets():
    if not TICKETS_FILE.exists():
        return []
    try:
        return json.loads(TICKETS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_ticket(kind, summary, reason=""):
    tickets = load_tickets()
    tid = "T" + time.strftime("%Y%m%d%H%M%S") + str(len(tickets) % 100).zfill(2)
    ticket = {
        "ticket_id": tid, "type": kind, "user_id": ME,
        "summary": summary, "reason": reason,
        "status": "待处理", "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    tickets.append(ticket)
    TICKETS_FILE.write_text(json.dumps(tickets, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "ticket_id": tid, "status": "待处理"}


ORDERS = {
    "1001": {"user_id": "U1001", "status": "已发货", "amount": 99.0},
    "1002": {"user_id": "U1002", "status": "已签收", "amount": 199.0},
    "1003": {"user_id": "U1001", "status": "待发货", "amount": 59.0}
}


def shipping_info(amount):
    fee = 0 if amount >= 99 else 8
    return {"free_shipping": fee == 0, "shipping_fee": fee}


SHIP = {
    "1001": {"carrier": "顺丰", "no": "SF123", "status": "运输中"}
}

POLICY = [
    {"id": "P1", "title": "七天无理由", "text": "签收后7天内可申请，商品需完好。", "kw": ["退货", "七天", "无理由"]},
    {"id": "P2", "title": "发票", "text": "下单时可申请电子发票（填写抬头和税号）；订单完成后30天内可联系客服补开。", "kw": ["发票", "开票"]},
    {"id": "P3", "title": "运费规则", "text": "订单满99元包邮；未满99元收取8元运费；偏远地区需人工确认。", "kw": ["包邮", "运费", "邮费", "满99"]},
    {"id": "P4", "title": "运费险", "text": "订单默认赠送运费险，退货运费可理赔。", "kw": ["运费险", "退货险"]},
    {"id": "P5", "title": "优惠券", "text": "优惠券下单时自动匹配最优一张，不可叠加使用。", "kw": ["优惠券", "券", "优惠"]},
]

# 命中这些词的问题属于政策类，必须由程序保证查过知识库，不能让模型自由发挥
POLICY_HINTS = ["发票", "开票", "包邮", "运费险", "退货", "七天", "无理由", "优惠券"]

# 命中这些词说明用户带情绪，回答里必须出现安抚，否则程序补一句
EMOTION_HINTS = ["投诉", "等好久", "生气", "太慢", "着急", "催", "不满意", "什么破", "垃圾", "多久了"]
SOOTHE_WORDS = ["抱歉", "理解", "不好意思", "对不起", "让您久等", "马上帮您", "马上为您", "确实"]


def soften(question, answer):
    """用户带情绪但回答没有安抚时，补一句真诚道歉，避免冷冰冰地直接报结果"""
    if any(k in question for k in EMOTION_HINTS) and not any(w in answer for w in SOOTHE_WORDS):
        return "真的很抱歉让您久等了，我特别理解您的心情～" + answer
    return answer


def get_order(args):
    oid = str(args.get("order_id", "")).strip()
    if oid not in ORDERS:
        return {"ok": False, "msg": "订单不存在"}
    if ORDERS[oid]["user_id"] != ME:
        return {"ok": False, "msg": "无权查看该订单"}
    return {"ok": True, "order_id": oid, **ORDERS[oid], **shipping_info(ORDERS[oid]["amount"])}


def get_shipment(args):
    oid = str(args.get("order_id", "")).strip()
    if ORDERS.get(oid, {}).get("user_id") != ME:
        return {"ok": False, "msg": "无权查看或订单不存在"}
    if oid not in SHIP:
        return {"ok": False, "msg": "暂无物流信息"}
    return {"ok": True, **SHIP[oid]}


def search_policy(args):
    q = str(args.get("query", ""))
    hit = next((p for p in POLICY if any(k in q for k in p["kw"])), None)
    return {"ok": True, "policy": hit} if hit else {"ok": False, "msg": "未找到相关政策"}


def handoff_to_human(args):
    summary = str(args.get("summary", "")).strip()
    reason = str(args.get("reason", "")).strip()
    if not summary:
        return {"ok": False, "msg": "缺少转人工摘要"}
    return save_ticket("转人工", summary, reason)


def create_ticket(args):
    problem_type = str(args.get("problem_type", "")).strip()
    description = str(args.get("description", "")).strip()
    if not description:
        return {"ok": False, "msg": "缺少问题描述"}
    return save_ticket(problem_type or "咨询", description)


def tool(name, desc, props=None, required=None):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": props or {
                    "order_id": {"type": "string", "description": "订单号"},
                    "query": {"type": "string", "description": "查询关键词"}
                },
                "required": required or []
            }
        }
    }


TOOLS = [
    tool("get_order", "查询当前用户订单状态、金额、是否包邮和运费，需要order_id"),
    tool("get_shipment", "查询订单物流和发货进度。用户问'啥时候发货''发货了吗''到哪了''快递单号'都调用，需要order_id"),
    tool("search_policy", "查询售后政策、运费规则，需要query"),
    tool("handoff_to_human", "转人工：用户投诉、要求赔偿、情绪激烈或问题超出客服能力时调用，会生成工单并把工单号告知用户。需要summary(问题摘要)和reason(原因)",
         props={"summary": {"type": "string", "description": "用户问题摘要"},
                "reason": {"type": "string", "description": "转人工原因"}},
         required=["summary"]),
    tool("create_ticket", "创建工单：用户明确要求登记/反馈问题时调用，会生成工单号。需要problem_type(问题类型)和description(问题描述)",
         props={"problem_type": {"type": "string", "description": "问题类型"},
                "description": {"type": "string", "description": "问题描述"}},
         required=["description"]),
]

IMPL = {
    "get_order": get_order, "get_shipment": get_shipment, "search_policy": search_policy,
    "handoff_to_human": handoff_to_human, "create_ticket": create_ticket
}


def chat(messages):
    payload = {"model": MODEL, "messages": messages, "tools": TOOLS, "tool_choice": "auto", "max_tokens": 1000}
    request = urllib.request.Request(
        BASE + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def judge_answer(question, answer, criteria):
    """语义裁判：判断客服回答是否满足条件，返回 (是否通过, 理由)"""
    system = (
        "你是评测裁判。判断客服回答在语义上是否满足预期要求。"
        "不要纠结字面措辞，只要意思对就算满足，"
        "例如'没查到'和'查不到'、'不好意思'和'抱歉'是同一个意思。"
        '只返回 JSON：{"pass": true 或 false, "reason": "简短理由"}'
    )
    user = (
        f"用户问题：{question}\n"
        f"预期要求：{criteria}\n"
        f"客服回答：{answer}\n"
        "请判断客服回答是否满足预期。"
    )
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ],
        "max_tokens": 200
    }
    request = urllib.request.Request(
        BASE + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
        text = (result["choices"][0]["message"]["content"] or "").strip()
        if "```" in text:
            text = text.split("```")[1].strip()
            if text.startswith("json"):
                text = text[4:].strip()
        data = json.loads(text)
        return bool(data.get("pass")), data.get("reason", "")
    except Exception as error:
        return None, f"裁判调用失败：{type(error).__name__}"


SYSTEM_PROMPT = (
    "你是电商客服，回复要有人情味、温暖、口语化，像真人客服一样。"
    "【一条回答里既安抚又解决】先调用工具查询，拿到结果后再写最终回答。"
    "最终回答的第一句必须是共情或道歉（用户有情绪时），紧接着给出查到的结果，"
    "不要把安抚和结果拆成两次回复。"
    "禁止只说'我来帮您查/看看'就结束，这样等于什么都没做。"
    "普通咨询也要用'亲~'这类亲切开头。"
    "【权限优先】任何人问不属于当前用户的订单，必须明确拒绝，不要说'我帮您查'。"
    "【政策类不用订单号】问包邮、发票、运费险、优惠券、退货规则等一般政策时，"
    "直接调用 search_policy 查原文，禁止追问订单号。"
    "【政策只复述原文】政策问题的回答只能使用工具返回的政策原文，"
    "不许增加原文里没有的任何细节，尤其禁止编造时效、材料、流程、办理方式。"
    "【高风险调用转人工工具】退款、赔偿、投诉涉及资金或责任时，先真诚道歉安抚，"
    "再调用 handoff_to_human 生成工单，并把返回的工单号告诉用户；"
    "此时不要用撒娇语气，也不要问订单号后自己处理。"
    "用户明确要求登记或反馈问题时调用 create_ticket 建单。"
    "【安抚之后必须办事】不能只安抚不行动，该查订单就调用工具查。"
    "只有查询具体订单状态或物流时才需要订单号；缺少订单号时，在安抚之后再追问。"
    "具体订单是否包邮、运费多少要查订单；一般包邮规则要查政策。"
    "禁止说'我不知道''这不归我管'，禁止冷冰冰地只给结论。"
)


def new_messages():
    return [{"role": "system", "content": SYSTEM_PROMPT}]


def handle(question, messages=None):
    """对外入口：情绪类问题保证有安抚，其余逻辑交给 _handle_raw"""
    answer, msgs, calls = _handle_raw(question, messages)
    return soften(question, answer), msgs, calls


def _handle_raw(question, messages=None):
    """处理一轮提问，返回 (回答文本, 更新后的历史, 工具调用记录)"""
    if messages is None:
        messages = new_messages()
    messages = list(messages) + [{"role": "user", "content": question}]
    calls_log = []
    nudged = False  # 兜底提醒只做一次，避免无限循环

    # 政策类问题：程序强制查知识库；但带订单号的问题要查具体订单，不走这里
    if any(k in question for k in POLICY_HINTS) and not re.search(r"\d{4}", question):
        result = {"ok": True, "policies": POLICY}
        calls_log.append({"name": "search_policy", "args": {"query": question}})
        call_id = "force_policy"
        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": call_id,
                "type": "function",
                "function": {
                    "name": "search_policy",
                    "arguments": json.dumps({"query": question}, ensure_ascii=False)
                }
            }]
        })
        messages.append({
            "role": "tool",
            "tool_call_id": call_id,
            "content": json.dumps(result, ensure_ascii=False)
        })

    for _ in range(5):
        try:
            msg = chat(messages)["choices"][0]["message"]
        except urllib.error.HTTPError as error:
            return f"[API错误 {error.code}]", messages, calls_log
        except Exception as error:
            return f"[错误 {type(error).__name__}]", messages, calls_log

        messages.append(msg)
        calls = msg.get("tool_calls") or []
        if not calls:
            content = msg.get("content") or ""
            if not nudged and any(k in content for k in ("帮您查", "帮您看", "查一下", "看看", "马上查", "这就查")):
                nudged = True
                messages.append({"role": "user", "content": "请立即调用工具查询，不要只说要查。"})
                continue
            return content, messages, calls_log

        for call in calls:
            name = call["function"]["name"]
            args = json.loads(call["function"].get("arguments") or "{}")
            calls_log.append({"name": name, "args": args})
            result = IMPL.get(name, lambda a: {"ok": False, "msg": "未知工具"})(args)
            messages.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "content": json.dumps(result, ensure_ascii=False)
            })

    return "步骤过多，建议转人工。", messages, calls_log


def transcribe(audio_bytes, mime="audio/wav"):
    """把录音字节转成文字，用百炼 qwen3-asr-flash（OpenAI 兼容）。
    成功返回文字；失败返回以 [语音识别失败] 开头的说明。"""
    if not mime.startswith("audio/"):
        mime = "audio/wav"
    uri = "data:" + mime + ";base64," + base64.b64encode(audio_bytes).decode()
    payload = {
        "model": "qwen3-asr-flash",
        "messages": [{
            "role": "user",
            "content": [{"type": "input_audio", "input_audio": {"data": uri}}]
        }],
        "stream": False,
    }
    request = urllib.request.Request(
        BASE + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))
        return (result["choices"][0]["message"]["content"] or "").strip()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="ignore")[:300]
        return f"[语音识别失败 {error.code}] {detail}"
    except Exception as error:
        return f"[语音识别失败 {type(error).__name__}] {error}"


if __name__ == "__main__":
    messages = new_messages()
    print("命令行客服已启动，输入 exit 退出，输入 clear 清空对话历史")

    while True:
        user = input("\n用户：").strip()
        if user.lower() in ("exit", "quit", "退出"):
            break
        if user.lower() in ("clear", "清空", "新会话"):
            messages = new_messages()
            print("已清空对话历史，后续问题不会带上之前的聊天内容。")
            continue

        answer, messages, _ = handle(user, messages)
        print("客服：", answer)
