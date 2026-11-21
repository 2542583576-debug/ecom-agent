import time
import streamlit as st
import streamlit.components.v1 as components
from agent import handle, new_messages, load_tickets, transcribe

st.set_page_config(page_title="在线客服", page_icon="💬", layout="centered")

# ---------- 样式 ----------
st.markdown("""
<style>
.block-container{max-width:460px;margin:0 auto;padding:0 0 20px 0;}
div[data-testid="stAppViewContainer"]{background:#eef1f6;}
[data-testid="stHeader"]{background:#eef1f6;}
.stButton>button{
  font-family:"Segoe UI Emoji","Apple Color Emoji","Microsoft YaHei",sans-serif;
  font-size:19px;border-radius:12px;border:1px solid #e6e9ef;background:#fff;
  box-shadow:0 1px 3px rgba(0,0,0,.05);transition:all .15s ease;color:#333;
}
.stButton>button:hover{border-color:#cfd6e0;background:#f8fafd;transform:translateY(-1px);}
/* 图标按钮：正方形、图标居中、去掉文字标签留白 */
.stButton>button:has([data-testid="stButtonIcon"]),
.stFormSubmitButton>button:has([data-testid="stButtonIcon"]){
  min-width:42px;height:42px;padding:0 10px;display:flex;align-items:center;
  justify-content:center;gap:0;font-size:0;
}
.stButton>button:has([data-testid="stButtonIcon"]) [data-testid="stButtonIcon"],
.stFormSubmitButton>button:has([data-testid="stButtonIcon"]) [data-testid="stButtonIcon"]{
  font-size:22px;margin:0;
}
[data-testid="stTextInput"] input{
  border-radius:20px !important;border:1px solid #e6e9ef !important;height:40px;padding-left:14px;
}
[data-testid="stTextInput"] input:focus{
  border-color:#ff8ba0 !important;box-shadow:0 0 0 2px rgba(255,138,160,.15) !important;
}
/* 快捷问题按钮：小一号、粉色描边 */
.quick-btn>button{
  font-size:12px !important;padding:6px 4px !important;border-radius:16px !important;
  border:1px solid #ffc2cf !important;background:#fff7f9 !important;color:#d3687f !important;
  box-shadow:none !important;
}
.quick-btn>button:hover{background:#ffe6ec !important;border-color:#ff9db2 !important;}
/* ===== 真正的左右对话：用户消息整体翻转到右侧 ===== */
div[data-testid="stChatMessage"]:has(.user-mark){
  flex-direction:row-reverse;
}
div[data-testid="stChatMessage"]:has(.user-mark) [data-testid="stChatMessageContent"]{
  display:flex;flex-direction:column;align-items:flex-end;
}
/* 气泡化：客服白底、用户浅蓝底，圆角 */
div[data-testid="stChatMessage"] [data-testid="stChatMessageContent"] > div:first-child{
  background:#fff;border:1px solid #eef0f4;border-radius:4px 14px 14px 14px;
  padding:8px 12px;box-shadow:0 1px 4px rgba(0,0,0,.06);max-width:100%;
}
div[data-testid="stChatMessage"]:has(.user-mark) [data-testid="stChatMessageContent"] > div:first-child{
  background:#dcecff;border-color:#cfe3fb;border-radius:14px 4px 14px 14px;
}
</style>
""", unsafe_allow_html=True)

# ---------- 会话状态 ----------
defaults = {
    "messages": None, "chat": [], "last_calls": [], "draft": "",
    "pending_image": None, "show_audio": False, "show_emoji": False,
    "show_more": None, "show_plus": False,
    "pending_insert": "", "clear_draft": False, "pending_reply": None,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v
if st.session_state.messages is None:
    st.session_state.messages = new_messages()

WELCOME = "亲亲，您好呀，很高兴为您服务，请问有什么可以帮您的~"

# 欢迎语下方的快捷问题：显示文字 -> 发送给 AI 的问题
QUICK_REPLIES = [
    ("会员专属优惠", "会员有哪些专属优惠？"),
    ("发货问题", "我的订单什么时候发货？"),
    ("下单必看", "下单需要注意什么？"),
    ("七天无理由退货", "七天无理由退货的规则是什么？"),
    ("包邮与运费规则", "包邮和运费的规则是什么？"),
]

TIME_GAP = 300  # 间隔超过 5 分钟才显示时间


def show_time(ts):
    st.markdown(
        f"<div style='text-align:center;color:#aab;font-size:11px;margin:10px 0 4px;'>{ts}</div>",
        unsafe_allow_html=True)


def render_bubble(role, content, image=None, ts=None, with_time=False):
    """原生 chat_message 保证文字渲染；用户消息埋 .user-mark 用 CSS 翻到右侧。"""
    if with_time and ts:
        show_time(ts)
    is_user = role == "user"
    with st.chat_message("user" if is_user else "assistant"):
        if image:
            st.image(image, width=160)
        st.markdown(str(content))
        if is_user:
            # 隐藏标记：CSS 通过 :has(.user-mark) 识别并右对齐
            st.markdown('<span class="user-mark" style="display:none;"></span>',
                        unsafe_allow_html=True)


def send_question(q, image=None):
    """把一条问题作为用户消息写入，并安排 AI 回复。"""
    now = time.time()
    st.session_state.chat.append({
        "role": "user", "content": q, "image": image,
        "ts": time.strftime("%H:%M"), "epoch": now,
    })
    ask = q
    if image:
        ask += "（用户发来图片，但你是文本模型看不了，请礼貌说明并回答文字问题。）"
    st.session_state.pending_reply = ask
    st.session_state.clear_draft = True
    st.session_state.pending_image = None
    st.session_state.show_more = None
    st.session_state.show_plus = False


# ---------- 顶部标题栏 ----------
st.markdown("""
<div style="display:flex;align-items:center;justify-content:center;gap:8px;padding:13px 4px;
            background:#fff;border-bottom:1px solid #eef0f4;margin:0 0 10px 0;
            border-radius:0 0 16px 16px;box-shadow:0 2px 8px rgba(0,0,0,.03);">
  <span style="font-size:19px;">💬</span>
  <span style="font-weight:600;font-size:16px;color:#2b2b2b;letter-spacing:.5px;">在线客服</span>
</div>
""", unsafe_allow_html=True)

# ---------- 聊天记录 ----------
if not st.session_state.chat:
    render_bubble("assistant", WELCOME)
    # 可点击的常用问题
    st.markdown("<div style='margin:4px 42px 8px 42px;'>", unsafe_allow_html=True)
    cols = st.columns(len(QUICK_REPLIES))
    for i, (label, q) in enumerate(QUICK_REPLIES):
        with cols[i]:
            with st.container():
                st.markdown('<div class="quick-btn">', unsafe_allow_html=True)
                if st.button(label, key=f"quick_{i}", use_container_width=True):
                    send_question(q)
                    st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
else:
    prev_epoch = None
    for item in st.session_state.chat:
        cur = item.get("epoch", 0)
        need_time = prev_epoch is None or (cur - prev_epoch) >= TIME_GAP
        render_bubble(item["role"], item["content"], item.get("image"),
                      item.get("ts"), with_time=need_time)
        prev_epoch = cur

st.markdown("<div style='height:6px;'></div>", unsafe_allow_html=True)

# ---------- 客服回复（显示在聊天记录下方、输入框上方）----------
if st.session_state.pending_reply is not None:
    ask = st.session_state.pending_reply
    st.session_state.pending_reply = None
    with st.status("客服正在回复…", expanded=True) as status:
        answer, msgs, calls = handle(ask, st.session_state.messages)
        status.update(label="客服已回复", state="complete", expanded=False)
    st.session_state.messages = msgs
    st.session_state.last_calls = calls
    st.session_state.chat.append({
        "role": "assistant", "content": answer,
        "ts": time.strftime("%H:%M"), "epoch": time.time(),
    })
    st.rerun()

# 在输入框创建之前合并待插入内容（避开 Streamlit 1.67 限制）
if st.session_state.pending_insert:
    st.session_state.draft = st.session_state.get("draft", "") + st.session_state.pending_insert
    st.session_state.pending_insert = ""
if st.session_state.clear_draft:
    st.session_state.draft = ""
    st.session_state.clear_draft = False

# ---------- 底部输入区 ----------
mic, smile, box, clr, plus = st.columns([0.7, 0.7, 3.2, 0.7, 0.7])
with mic:
    if st.button("", icon=":material/mic:", help="语音转文字", use_container_width=True):
        st.session_state.show_audio = not st.session_state.show_audio
        st.session_state.show_emoji = False
        st.session_state.show_plus = False
with smile:
    if st.button("", icon=":material/mood:", help="表情", use_container_width=True):
        st.session_state.show_emoji = not st.session_state.show_emoji
        st.session_state.show_audio = False
        st.session_state.show_plus = False
with clr:
    if st.button("", icon=":material/delete_sweep:", help="清空对话", use_container_width=True):
        st.session_state.messages = new_messages()
        st.session_state.chat = []
        st.session_state.last_calls = []
        st.session_state.pending_image = None
        st.session_state.pending_insert = ""
        st.session_state.clear_draft = True
        st.session_state.pending_reply = None
        st.session_state.show_more = None
        st.session_state.show_plus = False
        st.rerun()
with plus:
    if st.button("", icon=":material/add:", help="更多功能", use_container_width=True):
        st.session_state.show_plus = not st.session_state.show_plus
        st.session_state.show_emoji = False
        st.session_state.show_audio = False

# 用表单支持回车发送
with box:
    with st.form("chat_form", clear_on_submit=False):
        fin, fsend = st.columns([4.0, 1.0])
        with fin:
            st.text_input("输入内容...", key="draft", label_visibility="collapsed")
        with fsend:
            send_clicked = st.form_submit_button(
                "", icon=":material/send:", help="发送", use_container_width=True,
                type="primary")

# 语音转文字面板
if st.session_state.show_audio:
    with st.container(border=True):
        st.caption(":material/mic: 点击录音，说完自动转成文字填入输入框")
        audio = st.audio_input("录音", key="voice")
        if audio is not None:
            with st.spinner("正在识别语音…"):
                text = transcribe(audio.getvalue(), audio.type or "audio/wav")
            if text and not text.startswith("["):
                st.session_state.pending_insert = text
                st.session_state.show_audio = False
                st.rerun()
            else:
                st.warning(text)

# 表情面板
if st.session_state.show_emoji:
    with st.container(border=True):
        ecols = st.columns(8)
        for i, e in enumerate(["😊", "👍", "🙏", "😡", "😂", "❤️", "🎉", "🤝"]):
            with ecols[i]:
                if st.button("", icon=e, key=f"emoji_{i}", use_container_width=True):
                    st.session_state.pending_insert += e
                    st.rerun()

# ＋ 号展开面板：照片 / 拍摄
if st.session_state.show_plus:
    with st.container(border=True):
        st.caption("添加内容")
        p1, p2 = st.columns(2)
        with p1:
            if st.button("照片", icon=":material/image:", use_container_width=True):
                st.session_state.show_more = "photo"
        with p2:
            if st.button("拍摄", icon=":material/photo_camera:", use_container_width=True):
                st.session_state.show_more = "camera"

        if st.session_state.show_more == "photo":
            up = st.file_uploader("选择照片", type=["png", "jpg", "jpeg"], label_visibility="collapsed")
            if up:
                st.session_state.pending_image = up.getvalue()
                st.session_state.show_more = None
                st.session_state.show_plus = False
                st.rerun()
        elif st.session_state.show_more == "camera":
            cam = st.camera_input("拍照", label_visibility="collapsed")
            if cam:
                st.session_state.pending_image = cam.getvalue()
                st.session_state.show_more = None
                st.session_state.show_plus = False
                st.rerun()

if st.session_state.pending_image:
    ic1, ic2 = st.columns([1, 3])
    with ic1:
        st.image(st.session_state.pending_image, width=90)
    with ic2:
        st.caption("图片已添加，点发送即可发出")
        if st.button("移除图片", key="rm_img"):
            st.session_state.pending_image = None
            st.rerun()

# ---------- 发送 ----------
if send_clicked:
    q = st.session_state.draft.strip()
    img = st.session_state.pending_image
    if q or img:
        send_question(q or "我发了一张图片", img)
        st.rerun()

# ---------- 工具调用记录 ----------
with st.expander("本轮工具调用记录", icon=":material/build:"):
    if st.session_state.last_calls:
        for c in st.session_state.last_calls:
            st.json(c)
    else:
        st.caption("本轮未调用工具")

# ---------- 自动滚动到最新消息 ----------
# 零高度 iframe，通过 key 绑定消息数，每次新增消息都重新执行滚动脚本
_scroll_token = f"{len(st.session_state.chat)}_{st.session_state.show_audio}_{st.session_state.show_emoji}_{st.session_state.show_plus}"
# 把 token 作为隐藏属性嵌入 HTML：内容变化会让 iframe 重新挂载，脚本随之重执行
components.html(
    f"""
    <div id="scroll-token" data-token="{_scroll_token}" style="display:none;"></div>
    <script>
    (function() {{
      function doScroll() {{
        try {{
          var doc = window.parent.document;
          var main = doc.querySelector('section.main')
                  || doc.querySelector('[data-testid="stMain"]')
                  || doc.querySelector('.main')
                  || doc.scrollingElement
                  || doc.documentElement;
          if (main) main.scrollTop = main.scrollHeight;
          window.parent.scrollTo({{ top: 99999999, behavior: 'instant' }});
        }} catch (e) {{}}
      }}
      requestAnimationFrame(doScroll);
      setTimeout(doScroll, 120);
      setTimeout(doScroll, 350);
      setTimeout(doScroll, 600);
    }})();
    </script>
    """,
    height=0,
)
