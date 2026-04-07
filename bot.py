import os, asyncio, platform, re, json, io, copy, subprocess
import nest_asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

nest_asyncio.apply()

# ════════════════════════════════════════════════════════════
# ⚙️  CONFIG
# ════════════════════════════════════════════════════════════
API_ID    = int(os.environ.get("API_ID"))
API_HASH  = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_IDS = [6099442155, 7128257853]


# ════════════════════════════════════════════════════════════
# 🔍  ENV DETECTION
# ════════════════════════════════════════════════════════════
def detect_env() -> str:
    try:
        import google.colab; return "🟠 Google Colab"
    except ImportError: pass
    if os.path.exists("/kaggle/working"): return "🔵 Kaggle"
    return f"🖥️ Local ({platform.system()})"

ENV_NAME = detect_env()

# ════════════════════════════════════════════════════════════
# 🗄️  GLOBALS
# ════════════════════════════════════════════════════════════
app           = Client("encoder_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user_data     : dict = {}
task_queue    = asyncio.Queue()
is_processing : bool = False
current_proc         = None
active_tasks  : int  = 0
_task_counter : int  = 0
pending_audios: dict = {} # For interactive audio selection

for _d in ["fonts", "downloads"]: os.makedirs(_d, exist_ok=True)

def is_admin(uid: int) -> bool: return uid in ADMIN_IDS

def next_tid() -> int:
    global _task_counter
    _task_counter += 1
    return _task_counter

# ════════════════════════════════════════════════════════════
# 📐  DEFAULT SETTINGS
# ════════════════════════════════════════════════════════════
DEFAULT_SETTINGS = {
    'mode'            : 'gpu',
    'status'          : 'idle',
    'font'            : 'Arial',
    'custom_field'    : None,
    'custom_msg_id'   : None,
    'pending_import'  : None,
    'parallel_workers': 1,

    # ── Pending Operations ───────────────────────────────
    'pending_sub_cmd'   : None,
    'pending_extract'   : False,
    'pending_rename_raw': False,

    # ── Batch Mode ───────────────────────────────────────
    'batch': {
        'active'               : False,
        'videos'               : [],
        'waiting_sub_for'      : None,
        'summary_msg_id'       : None,
        'panel_msg_id'         : None,
        'rename_panel_msg_id'  : None,
        'rename_pending_idx'   : None,
        'rename_awaiting_custom': False,
    },

    # ── GPU H.264 (h264_nvenc) ───────────────────────────
    'gpu_codec'    : 'h264',
    'gpu_preset'   : 'p4',
    'gpu_cq'       : '21',
    'gpu_res'      : 'original',
    'gpu_threads'  : 'auto',
    'gpu_maxrate'  : 'none',
    'gpu_tune'     : 'none',
    'gpu_pix_fmt'  : 'yuv420p',

    # ── GPU H.265 (hevc_nvenc) ───────────────────────────
    'gpu265_preset' : 'p4',
    'gpu265_cq'     : '24',
    'gpu265_res'    : 'original',
    'gpu265_threads': 'auto',
    'gpu265_maxrate': 'none',
    'gpu265_tune'   : 'none',
    'gpu265_pix_fmt': 'yuv420p',

    # ── CPU H.264 (libx264) ──────────────────────────────
    'cpu_codec'    : 'h264',
    'cpu_preset'   : 'faster',
    'cpu_crf'      : '23',
    'cpu_res'      : 'original',
    'cpu_threads'  : 'auto',
    'cpu_maxrate'  : 'none',
    'cpu_tune'     : 'none',
    'cpu_pix_fmt'  : 'yuv420p',

    # ── CPU H.265 (libx265) ──────────────────────────────
    'cpu265_preset' : 'faster',
    'cpu265_crf'    : '28',
    'cpu265_res'    : 'original',
    'cpu265_threads': 'auto',
    'cpu265_maxrate': 'none',
    'cpu265_tune'   : 'none',
    'cpu265_pix_fmt': 'yuv420p',
}

GPU_EXPORT_KEYS = [
    'mode','font','gpu_codec','parallel_workers',
    'gpu_preset','gpu_cq','gpu_res','gpu_threads','gpu_maxrate','gpu_tune','gpu_pix_fmt',
    'gpu265_preset','gpu265_cq','gpu265_res','gpu265_threads','gpu265_maxrate','gpu265_tune','gpu265_pix_fmt',
]
CPU_EXPORT_KEYS = [
    'mode','font','cpu_codec','parallel_workers',
    'cpu_preset','cpu_crf','cpu_res','cpu_threads','cpu_maxrate','cpu_tune','cpu_pix_fmt',
    'cpu265_preset','cpu265_crf','cpu265_res','cpu265_threads','cpu265_maxrate','cpu265_tune','cpu265_pix_fmt',
]

def get_data(chat_id: int) -> dict:
    if chat_id not in user_data:
        user_data[chat_id] = copy.deepcopy(DEFAULT_SETTINGS)
    return user_data[chat_id]

# ════════════════════════════════════════════════════════════
# 🔧  SETTINGS EXPORT / IMPORT
# ════════════════════════════════════════════════════════════
def export_settings(chat_id: int, export_type: str = 'gpu') -> bytes:
    d    = get_data(chat_id)
    keys = GPU_EXPORT_KEYS if export_type == 'gpu' else CPU_EXPORT_KEYS
    out  = {k: d[k] for k in keys if k in d}
    out['_type'] = export_type
    return json.dumps(out, indent=2).encode('utf-8')

def import_settings(chat_id: int, raw: bytes, import_type: str = None) -> tuple:
    try:
        obj = json.loads(raw.decode('utf-8'))
    except Exception:
        return False, "❌ Invalid JSON file."
    if import_type is None:
        import_type = obj.get('_type', 'gpu')
    keys = GPU_EXPORT_KEYS if import_type == 'gpu' else CPU_EXPORT_KEYS
    d    = get_data(chat_id)
    applied = []
    for k in keys:
        if k in obj:
            d[k] = obj[k]
            applied.append(k)
    if not applied:
        return False, "❌ Koi valid setting nahi mili."
    label = "🎮 GPU" if import_type == 'gpu' else "🖥️ CPU"
    return True, f"✅ **{label} — {len(applied)} settings applied!**"

# ════════════════════════════════════════════════════════════
# 🎛️  UI CONSTANTS
# ════════════════════════════════════════════════════════════
RESOLUTIONS     = ['original', '1080p', '720p', '480p']
GPU_TUNES       = ['none', 'hq', 'll', 'ull', 'lossless']
CPU_TUNES       = ['none', 'animation', 'film', 'grain', 'zerolatency']
CPU265_TUNES    = ['none', 'animation', 'grain', 'fastdecode', 'zerolatency']
PIX_FMTS        = ['yuv420p', 'yuv420p10le', 'yuv444p']
PIX_FMTS_H264   = ['yuv420p', 'yuv444p']
MAXRATES        = ['none', '2M', '4M', '6M', '8M']
MAXRATE_LBLS    = ['Uncap', '2M', '4M', '6M', '8M']
THREAD_OPTS     = ['auto', '2', '4', '8']
CPU_PRESET_LIST = ['ultrafast','superfast','veryfast','faster','fast','medium','slow']

def _ck(label: str, active: bool) -> str:
    return f"✅ {label}" if active else label

# ─── MAIN MENU ────────────────────────────────────────────
def main_menu(chat_id: int) -> InlineKeyboardMarkup:
    d  = get_data(chat_id)
    qs = task_queue.qsize()
    pi = "🔥" if (current_proc and current_proc.returncode is None) else "💤"
    gc = d.get('gpu_codec', 'h264').upper()
    cc = d.get('cpu_codec', 'h264').upper()
    pw = d.get('parallel_workers', 1)
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(_ck("🎮 GPU", d['mode'] == 'gpu'), callback_data="set_gpu"),
            InlineKeyboardButton(_ck("🖥️ CPU", d['mode'] == 'cpu'), callback_data="set_cpu"),
        ],
        [
            InlineKeyboardButton(f"⚙️ GPU [{gc}] ▸", callback_data="menu_gpu"),
            InlineKeyboardButton(f"⚙️ CPU [{cc}] ▸", callback_data="menu_cpu"),
        ],
        [InlineKeyboardButton(f"🖋️ Font: {d['font']}", callback_data="menu_fonts")],
        [InlineKeyboardButton(f"⚡ Parallel Workers: {pw}x", callback_data="menu_parallel")],
        [
            InlineKeyboardButton("📤 Export GPU", callback_data="export_gpu"),
            InlineKeyboardButton("📤 Export CPU", callback_data="export_cpu"),
        ],
        [
            InlineKeyboardButton("📥 Import GPU", callback_data="import_gpu_prompt"),
            InlineKeyboardButton("📥 Import CPU", callback_data="import_cpu_prompt"),
        ],
        [InlineKeyboardButton(f"{pi} Queue: {qs} | Act: {active_tasks} | {ENV_NAME}", callback_data="refresh_main")],
    ])

# ─── GPU SETTINGS MENU ────────────────────────────────────
def gpu_settings_menu(chat_id: int) -> InlineKeyboardMarkup:
    d = get_data(chat_id)
    codec = d.get('gpu_codec', 'h264')
    codec_row = [
        InlineKeyboardButton(_ck("H.264 NVENC", codec == 'h264'), callback_data="gpu_codec_h264"),
        InlineKeyboardButton(_ck("H.265 HEVC",  codec == 'h265'), callback_data="gpu_codec_h265"),
    ]
    if codec == 'h264':
        pfx = 'gpu'; pre_key = 'gpu_preset'; cq_key = 'gpu_cq'; res_key = 'gpu_res'
        thr_key = 'gpu_threads'; mr_key = 'gpu_maxrate'; tn_key = 'gpu_tune'; px_key = 'gpu_pix_fmt'
        codec_label = "h264_nvenc"; pix_opts = PIX_FMTS_H264
        cq_v = ['18','21','24','28']; cq_l = ['18 HQ','21 Bal','24 Fast','28 Draft']
    else:
        pfx = 'gpu265'; pre_key = 'gpu265_preset'; cq_key = 'gpu265_cq'; res_key = 'gpu265_res'
        thr_key = 'gpu265_threads'; mr_key = 'gpu265_maxrate'; tn_key = 'gpu265_tune'; px_key = 'gpu265_pix_fmt'
        codec_label = "hevc_nvenc"; pix_opts = PIX_FMTS
        cq_v = ['20','24','28','32']; cq_l = ['20 HQ','24 Bal','28 Fast','32 Draft']

    pre_r1 = [InlineKeyboardButton(_ck(f"P{i}{'⚡' if i<=2 else ''}", d[pre_key]==f"p{i}"), callback_data=f"{pfx}_preset_p{i}") for i in range(1,5)]
    pre_r2 = [InlineKeyboardButton(_ck(f"P{i}{'🎯' if i>=6 else ''}", d[pre_key]==f"p{i}"), callback_data=f"{pfx}_preset_p{i}") for i in range(5,8)]
    cq_r  = [InlineKeyboardButton(_ck(cq_l[i], d[cq_key]==cq_v[i]), callback_data=f"{pfx}_cq_{cq_v[i]}") for i in range(4)]
    res_r = [InlineKeyboardButton(_ck(r, d[res_key]==r), callback_data=f"{pfx}_res_{r}") for r in RESOLUTIONS]
    thr_r = [InlineKeyboardButton(_ck(t, d.get(thr_key,'auto')==t), callback_data=f"{pfx}_threads_{t}") for t in THREAD_OPTS]
    mr_r1 = [InlineKeyboardButton(_ck(MAXRATE_LBLS[i], d.get(mr_key,'none')==MAXRATES[i]), callback_data=f"{pfx}_maxrate_{MAXRATES[i]}") for i in range(3)]
    mr_r2 = [InlineKeyboardButton(_ck(MAXRATE_LBLS[i], d.get(mr_key,'none')==MAXRATES[i]), callback_data=f"{pfx}_maxrate_{MAXRATES[i]}") for i in range(3,5)]
    tn_r1 = [InlineKeyboardButton(_ck(t, d.get(tn_key,'none')==t), callback_data=f"{pfx}_tune_{t}") for t in GPU_TUNES[:3]]
    tn_r2 = [InlineKeyboardButton(_ck(t, d.get(tn_key,'none')==t), callback_data=f"{pfx}_tune_{t}") for t in GPU_TUNES[3:]]
    px_r  = [InlineKeyboardButton(_ck(p, d.get(px_key,'yuv420p')==p), callback_data=f"{pfx}_pix_{p}") for p in pix_opts]

    cq_label = "CQ" if codec == 'h264' else "CQ/RF"
    rows = [
        [InlineKeyboardButton("━━ 🎮 GPU Codec ━━", callback_data="noop")],
        codec_row,
        [InlineKeyboardButton(f"━━ Preset (now: {d[pre_key].upper()}) [{codec_label}] ⚡fast 🎯quality ━━", callback_data="noop")],
        pre_r1, pre_r2,
        [InlineKeyboardButton("✏️ Custom Preset (e.g. p3)", callback_data=f"custom_{pfx}_preset")],
        [InlineKeyboardButton(f"━━ {cq_label} Quality (now: {d[cq_key]}) lower=better ━━", callback_data="noop")],
        cq_r,
        [InlineKeyboardButton(f"✏️ Custom {cq_label} (0–51)", callback_data=f"custom_{pfx}_cq")],
        [InlineKeyboardButton(f"━━ Resolution (now: {d[res_key]}) ━━", callback_data="noop")],
        res_r,
        [InlineKeyboardButton("✏️ Custom Resolution (e.g. 1366:768)", callback_data=f"custom_{pfx}_res")],
        [InlineKeyboardButton(f"━━ Threads (now: {d.get(thr_key,'auto')}) ━━", callback_data="noop")],
        thr_r,
        [InlineKeyboardButton("✏️ Custom Threads", callback_data=f"custom_{pfx}_threads")],
        [InlineKeyboardButton(f"━━ Max Bitrate (now: {d.get(mr_key,'none')}) ━━", callback_data="noop")],
        mr_r1, mr_r2,
        [InlineKeyboardButton("✏️ Custom Maxrate (e.g. 5M)", callback_data=f"custom_{pfx}_maxrate")],
        [InlineKeyboardButton(f"━━ Tune (now: {d.get(tn_key,'none')}) — NVENC ━━", callback_data="noop")],
        tn_r1, tn_r2,
        [InlineKeyboardButton(f"━━ Pixel Format (now: {d.get(px_key,'yuv420p')}) ━━", callback_data="noop")],
        px_r,
        [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="back_main")],
    ]
    return InlineKeyboardMarkup(rows)

# ─── CPU SETTINGS MENU ────────────────────────────────────
def cpu_settings_menu(chat_id: int) -> InlineKeyboardMarkup:
    d = get_data(chat_id)
    codec = d.get('cpu_codec', 'h264')
    codec_row = [
        InlineKeyboardButton(_ck("H.264 x264", codec == 'h264'), callback_data="cpu_codec_h264"),
        InlineKeyboardButton(_ck("H.265 x265", codec == 'h265'), callback_data="cpu_codec_h265"),
    ]
    if codec == 'h264':
        pfx = 'cpu'; pre_key = 'cpu_preset'; cf_key = 'cpu_crf'; res_key = 'cpu_res'
        thr_key = 'cpu_threads'; mr_key = 'cpu_maxrate'; tn_key = 'cpu_tune'; px_key = 'cpu_pix_fmt'
        codec_label = "libx264"; tunes = CPU_TUNES; pix_opts = PIX_FMTS_H264
        cf_v = ['18','21','23','26']; cf_l = ['18 HQ','21','23 Bal','26 Fast']
    else:
        pfx = 'cpu265'; pre_key = 'cpu265_preset'; cf_key = 'cpu265_crf'; res_key = 'cpu265_res'
        thr_key = 'cpu265_threads'; mr_key = 'cpu265_maxrate'; tn_key = 'cpu265_tune'; px_key = 'cpu265_pix_fmt'
        codec_label = "libx265"; tunes = CPU265_TUNES; pix_opts = PIX_FMTS
        cf_v = ['20','24','28','32']; cf_l = ['20 HQ','24 Bal','28 Fast','32 Draft']

    pre_r1 = [InlineKeyboardButton(_ck(p[:7].title(), d[pre_key]==p), callback_data=f"{pfx}_preset_{p}") for p in CPU_PRESET_LIST[:4]]
    pre_r2 = [InlineKeyboardButton(_ck(p[:7].title(), d[pre_key]==p), callback_data=f"{pfx}_preset_{p}") for p in CPU_PRESET_LIST[4:]]
    cf_r  = [InlineKeyboardButton(_ck(cf_l[i], d[cf_key]==cf_v[i]), callback_data=f"{pfx}_crf_{cf_v[i]}") for i in range(4)]
    res_r = [InlineKeyboardButton(_ck(r, d[res_key]==r), callback_data=f"{pfx}_res_{r}") for r in RESOLUTIONS]
    thr_r = [InlineKeyboardButton(_ck(t, d.get(thr_key,'auto')==t), callback_data=f"{pfx}_threads_{t}") for t in THREAD_OPTS]
    mr_r1 = [InlineKeyboardButton(_ck(MAXRATE_LBLS[i], d.get(mr_key,'none')==MAXRATES[i]), callback_data=f"{pfx}_maxrate_{MAXRATES[i]}") for i in range(3)]
    mr_r2 = [InlineKeyboardButton(_ck(MAXRATE_LBLS[i], d.get(mr_key,'none')==MAXRATES[i]), callback_data=f"{pfx}_maxrate_{MAXRATES[i]}") for i in range(3,5)]
    tn_r1 = [InlineKeyboardButton(_ck(t, d.get(tn_key,'none')==t), callback_data=f"{pfx}_tune_{t}") for t in tunes[:3]]
    tn_r2 = [InlineKeyboardButton(_ck(t, d.get(tn_key,'none')==t), callback_data=f"{pfx}_tune_{t}") for t in tunes[3:]]
    px_r  = [InlineKeyboardButton(_ck(p, d.get(px_key,'yuv420p')==p), callback_data=f"{pfx}_pix_{p}") for p in pix_opts]

    rows = [
        [InlineKeyboardButton("━━ 🖥️ CPU Codec ━━", callback_data="noop")],
        codec_row,
        [InlineKeyboardButton(f"━━ Preset (now: {d[pre_key]}) [{codec_label}] ━━", callback_data="noop")],
        pre_r1, pre_r2,
        [InlineKeyboardButton("✏️ Custom Preset", callback_data=f"custom_{pfx}_preset")],
        [InlineKeyboardButton(f"━━ CRF Quality (now: {d[cf_key]}) lower=better ━━", callback_data="noop")],
        cf_r,
        [InlineKeyboardButton("✏️ Custom CRF (0–51)", callback_data=f"custom_{pfx}_crf")],
        [InlineKeyboardButton(f"━━ Resolution (now: {d[res_key]}) ━━", callback_data="noop")],
        res_r,
        [InlineKeyboardButton("✏️ Custom Resolution (e.g. 1366:768)", callback_data=f"custom_{pfx}_res")],
        [InlineKeyboardButton(f"━━ Threads (now: {d.get(thr_key,'auto')}) ━━", callback_data="noop")],
        thr_r,
        [InlineKeyboardButton("✏️ Custom Threads", callback_data=f"custom_{pfx}_threads")],
        [InlineKeyboardButton(f"━━ Max Bitrate (now: {d.get(mr_key,'none')}) ━━", callback_data="noop")],
        mr_r1, mr_r2,
        [InlineKeyboardButton("✏️ Custom Maxrate (e.g. 5M)", callback_data=f"custom_{pfx}_maxrate")],
        [InlineKeyboardButton(f"━━ Tune (now: {d.get(tn_key,'none')}) — {codec_label} ━━", callback_data="noop")],
        tn_r1, tn_r2,
        [InlineKeyboardButton(f"━━ Pixel Format (now: {d.get(px_key,'yuv420p')}) ━━", callback_data="noop")],
        px_r,
        [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="back_main")],
    ]
    return InlineKeyboardMarkup(rows)

# ─── PARALLEL WORKERS MENU ────────────────────────────────
def parallel_menu(chat_id: int) -> InlineKeyboardMarkup:
    d  = get_data(chat_id)
    pw = d.get('parallel_workers', 1)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("━━ ⚡ Parallel Encoding Workers ━━", callback_data="noop")],
        [
            InlineKeyboardButton(_ck("1x Sequential", pw == 1), callback_data="parallel_1"),
            InlineKeyboardButton(_ck("2x Parallel",   pw == 2), callback_data="parallel_2"),
        ],
        [
            InlineKeyboardButton(_ck("3x Parallel",   pw == 3), callback_data="parallel_3"),
            InlineKeyboardButton(_ck("4x Parallel",   pw == 4), callback_data="parallel_4"),
        ],
        [InlineKeyboardButton("💡 GPU: 2x | CPU: 3–4x recommend", callback_data="noop")],
        [InlineKeyboardButton("⚠️ Zyada workers = zyada RAM/VRAM", callback_data="noop")],
        [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="back_main")],
    ])

# ─── FONT MENU ────────────────────────────────────────────
def fonts_menu(chat_id: int):
    fonts = sorted([f for f in os.listdir("fonts") if f.endswith(".ttf")])
    d = get_data(chat_id)
    current_font = d['font']
    if not fonts:
        return (InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_main")]]),
                "❌ Koi font nahi mila.\n📌 .ttf file directly bhejein — auto install ho jaayegi.")
    btns = []
    for f in fonts:
        name = os.path.splitext(f)[0]
        btns.append([InlineKeyboardButton(_ck(name, current_font == name), callback_data=f"use_font_{name}")])
    btns.append([InlineKeyboardButton("🔙 Back to Dashboard", callback_data="back_main")])
    return InlineKeyboardMarkup(btns), (
        f"🖋️ **Font Select Karein** — {len(fonts)} fonts\n"
        f"✅ Current: **{current_font}**\n\n"
        f"💡 Naya font chahiye? .ttf file bhejein!"
    )

# ─── BATCH UI HELPERS ─────────────────────────────────────
def batch_file_selector_menu(chat_id: int) -> InlineKeyboardMarkup:
    d = get_data(chat_id)
    videos = d['batch']['videos']
    rows = [[InlineKeyboardButton("━━ 📁 Subtitle Upload Panel ━━", callback_data="noop")]]
    for i, v in enumerate(videos):
        has_sub  = v['subtitle'] is not None
        icon     = "✅" if has_sub else "📂"
        short    = v['fname'][:28] + ("…" if len(v['fname']) > 28 else "")
        label    = f"{icon} {i+1}. {short}"
        rows.append([InlineKeyboardButton(label, callback_data=f"batch_pick_{i}")])
    ready = sum(1 for v in videos if v['subtitle'])
    if ready > 0:
        rows.append([InlineKeyboardButton(
            f"🚀 Queue mein Add ({ready}/{len(videos)} ready)",
            callback_data="batch_add_queue"
        )])
    rows.append([InlineKeyboardButton("❌ Cancel Batch", callback_data="batch_cancel")])
    return InlineKeyboardMarkup(rows)

def batch_summary_text(videos: list) -> str:
    lines = ["📋 **Batch Status:**\n"]
    for i, v in enumerate(videos):
        icon    = "✅" if v['subtitle'] else "⏳"
        sub_lbl = f"[{v['sub_ext'].upper()}]" if v['subtitle'] else "[sub missing]"
        lines.append(f"{icon} `{i+1}.` `{v['fname']}` {sub_lbl}")
    ready = sum(1 for v in videos if v['subtitle'])
    lines.append(f"\n📊 {ready}/{len(videos)} subtitles linked")
    return "\n".join(lines)

# ─── RENAME PANEL ─────────────────────────────────────────
def _rename_panel_text(videos: list) -> str:
    if not videos:
        return "📋 **Batch Naam Panel**\n\nAbhi koi video nahi. Videos bhejte raho!"
    lines = []
    for i, v in enumerate(videos):
        st = "✅" if v.get('name_confirmed') else "⏳"
        lines.append(f"{st} **{i+1}.** `{v['fname']}`")
    confirmed = sum(1 for v in videos if v.get('name_confirmed'))
    return (
        f"📋 **Batch Naam Panel** — {len(videos)} file(s)\n"
        f"✅ {confirmed}/{len(videos)} naam confirm\n\n"
        + "\n".join(lines)
        + "\n\n👇 File ka button dabao naam set karne ke liye:"
    )

def _rename_panel_kb(videos: list) -> InlineKeyboardMarkup:
    rows = []
    btns = [
        InlineKeyboardButton(
            f"{'✅' if v.get('name_confirmed') else '📁'} File {i+1}",
            callback_data=f"brfile_{i}"
        )
        for i, v in enumerate(videos)
    ]
    for i in range(0, len(btns), 2):
        rows.append(btns[i:i+2])
    return InlineKeyboardMarkup(rows)

def _rename_file_menu_text(idx: int, v: dict) -> str:
    return (
        f"✏️ **File {idx+1} — Naam Choose Karo**\n\n"
        f"📁 Current naam:\n`{v['fname']}`\n\n"
        f"Original: `{v['original_fname']}`"
    )

def _rename_file_menu_kb(idx: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📁 Original Rakho", callback_data=f"bro_{idx}"),
            InlineKeyboardButton("✏️ Custom Naam",    callback_data=f"brc_{idx}"),
        ],
        [InlineKeyboardButton("🔙 Back",              callback_data="brp")],
    ])

def _rename_confirm_text(idx: int, v: dict) -> str:
    return (
        f"✅ **Are you sure?**\n\n"
        f"File {idx+1} ka naam rakha jayega:\n"
        f"📁 `{v['original_fname']}`"
    )

def _rename_confirm_kb(idx: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Haan, Rakho",     callback_data=f"broc_{idx}"),
            InlineKeyboardButton("❌ Cancel",           callback_data=f"brfile_{idx}"),
        ],
    ])

async def _refresh_rename_panel(client, chat_id: int):
    d       = get_data(chat_id)
    videos  = d['batch']['videos']
    msg_id  = d['batch'].get('rename_panel_msg_id')
    if not msg_id:
        return
    try:
        await client.edit_message_text(
            chat_id, msg_id,
            _rename_panel_text(videos),
            reply_markup=_rename_panel_kb(videos)
        )
    except Exception:
        pass

async def _refresh_batch_panel(client, chat_id: int):
    d = get_data(chat_id)
    panel_id = d['batch'].get('panel_msg_id')
    if not panel_id:
        return
    videos = d['batch']['videos']
    text = (
        f"📋 **Subtitle Upload Panel**\n\n"
        f"{batch_summary_text(videos)}\n\n"
        f"💡 **Upload karne ke 2 tarike:**\n"
        f"1️⃣ **Reply method** — subtitle file ko video ka reply karo\n"
        f"2️⃣ **Button method** — neeche file ka button dabao, phir sub bhejo\n\n"
        f"✏️ Galat sub? `/changesub <filename>` ya `/changesub <number>`\n"
        f"🛑 Upload cancel karne ke liye `/cancel`"
    )
    try:
        await client.edit_message_text(chat_id, panel_id, text,
                                       reply_markup=batch_file_selector_menu(chat_id))
    except Exception:
        pass

def _get_audio_streams(v_path: str) -> list:
    try:
        probe = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json',
             '-show_streams', '-select_streams', 'a', v_path],
            capture_output=True, text=True
        )
        data = json.loads(probe.stdout or '{}')
        return data.get('streams', [])
    except:
        return []

def _build_audio_kb(task_id: int) -> InlineKeyboardMarkup:
    data = pending_audios[task_id]
    streams = data['streams']
    deleted = data['deleted']
    rows = []
    for i, s in enumerate(streams):
        lang = s.get('tags', {}).get('language', 'Unknown').title()
        title = s.get('tags', {}).get('title', f'Track {i+1}')
        label = f"{lang} {title}"
        if i in deleted:
            label = f"🗑️ {label} (Deleted)"
        else:
            label = f"✅ {label}"
        rows.append([InlineKeyboardButton(label, callback_data=f"del_aud_{task_id}_{i}")])
    rows.append([InlineKeyboardButton("▶️ Continue", callback_data=f"cont_aud_{task_id}")])
    return InlineKeyboardMarkup(rows)

# ════════════════════════════════════════════════════════════
# 🔨  FFMPEG HELPERS
# ════════════════════════════════════════════════════════════
RESOLUTION_MAP = {'original': None, '1080p': '1920:1080', '720p': '1280:720', '480p': '854:480'}

def _escape_sub(path: str) -> str:
    return path.replace("\\", "/").replace("'", r"'\''").replace(":", r"\:")

def _resolve_res(val: str):
    if not val or val == 'original': return None
    return RESOLUTION_MAP.get(val, val)

def _maxrate_args(mr: str) -> list:
    if not mr or mr == 'none': return []
    try:
        num  = float(re.sub(r'[MmKk]', '', mr))
        unit = mr[-1].upper()
        buf  = f"{int(num * 2)}{unit}"
    except: return []
    return ['-maxrate', mr.upper(), '-bufsize', buf]

def _inject_font_into_ass(ass_path: str, font: str) -> None:
    with open(ass_path, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()
    out = []; in_styles = False; format_cols = []
    for line in lines:
        stripped = line.strip()
        if stripped.lower() == '[v4+ styles]':
            in_styles = True; out.append(line); continue
        elif stripped.startswith('[') and stripped.endswith(']'):
            in_styles = False
        if in_styles:
            if stripped.lower().startswith('format:'):
                format_cols = [c.strip().lower() for c in stripped[7:].split(',')]
                out.append(line); continue
            if stripped.lower().startswith('style:') and format_cols:
                vals = stripped[6:].split(',')
                try:
                    fi = format_cols.index('fontname')
                    if fi < len(vals):
                        vals[fi] = font
                        out.append('Style: ' + ','.join(vals) + '\n'); continue
                except ValueError: pass
        out.append(line)
    with open(ass_path, 'w', encoding='utf-8') as f:
        f.writelines(out)

def _convert_to_ass(s_path: str, font: str, uid: str) -> str:
    sub_ext = os.path.splitext(s_path)[1].lower()
    if sub_ext == '.ass':
        import shutil
        ass_out = f"downloads/s_{uid}_ready.ass"
        shutil.copy2(s_path, ass_out)
        _inject_font_into_ass(ass_out, font)
        return ass_out
    ass_out = f"downloads/s_{uid}_conv.ass"
    ret = subprocess.run(['ffmpeg', '-y', '-i', s_path, ass_out], capture_output=True)
    if ret.returncode != 0 or not os.path.exists(ass_out):
        raise RuntimeError(f"Sub convert fail: {ret.stderr.decode(errors='replace')[-400:]}")
    _inject_font_into_ass(ass_out, font)
    return ass_out

def build_ffmpeg_cmd(task: dict, v_path: str, s_path: str, out_path: str) -> tuple:
    font     = task['font']
    mode     = task['mode']
    uid      = f"{task['chat_id']}_{task['task_id']}"

    if s_path:
        ass_path = _convert_to_ass(s_path, font, uid)
        esc_sub  = _escape_sub(ass_path)
        fonts_dir = os.path.abspath("fonts").replace("\\", "/").replace(":", r"\:")
        sub_vf   = f"ass='{esc_sub}':fontsdir='{fonts_dir}'"
    else:
        ass_path = None
        sub_vf   = ""

    map_args = []
    if 'keep_audios' in task:
        map_args.extend(['-map', '0:v:0'])
        for a_idx in task['keep_audios']:
            map_args.extend(['-map', f'0:a:{a_idx}'])

    if mode == 'gpu':
        codec = task.get('gpu_codec', 'h264')
        if codec == 'h265':
            res  = _resolve_res(task.get('gpu265_res', 'original'))
            vf   = (f"scale={res}," if res else "") + sub_vf
            vf   = vf.rstrip(',')
            vf_args = ['-vf', vf] if vf else []
            thr  = [] if task.get('gpu265_threads', 'auto') == 'auto' else ['-threads', task['gpu265_threads']]
            mr   = _maxrate_args(task.get('gpu265_maxrate', 'none'))
            tune = task.get('gpu265_tune', 'none')
            tn   = [] if tune == 'none' else ['-tune', tune]
            pix  = task.get('gpu265_pix_fmt', 'yuv420p')
            return (['ffmpeg'] + thr + ['-hwaccel', 'cuda', '-i', v_path] +
                     vf_args + ['-c:v', 'hevc_nvenc',
                     '-preset', task.get('gpu265_preset', 'p4'),
                     '-cq', task.get('gpu265_cq', '24'),
                     '-pix_fmt', pix] + mr + tn + map_args +
                    ['-c:a', 'copy', '-sn', '-tag:v', 'hvc1', '-y', out_path]), ass_path
        else:
            res  = _resolve_res(task.get('gpu_res', 'original'))
            vf   = (f"scale={res}," if res else "") + sub_vf
            vf   = vf.rstrip(',')
            vf_args = ['-vf', vf] if vf else []
            thr  = [] if task.get('gpu_threads', 'auto') == 'auto' else ['-threads', task['gpu_threads']]
            mr   = _maxrate_args(task.get('gpu_maxrate', 'none'))
            tune = task.get('gpu_tune', 'none')
            tn   = [] if tune == 'none' else ['-tune', tune]
            pix  = task.get('gpu_pix_fmt', 'yuv420p')
            return (['ffmpeg'] + thr + ['-hwaccel', 'cuda', '-i', v_path] +
                     vf_args + ['-c:v', 'h264_nvenc',
                     '-preset', task.get('gpu_preset', 'p4'),
                     '-cq', task.get('gpu_cq', '21'),
                     '-pix_fmt', pix] + mr + tn + map_args +
                    ['-c:a', 'copy', '-sn', '-y', out_path]), ass_path
    else:
        codec = task.get('cpu_codec', 'h264')
        if codec == 'h265':
            res  = _resolve_res(task.get('cpu265_res', 'original'))
            vf   = (f"scale={res}," if res else "") + sub_vf
            vf   = vf.rstrip(',')
            vf_args = ['-vf', vf] if vf else []
            thr  = [] if task.get('cpu265_threads', 'auto') == 'auto' else ['-threads', task['cpu265_threads']]
            mr   = _maxrate_args(task.get('cpu265_maxrate', 'none'))
            tune = task.get('cpu265_tune', 'none')
            tn   = [] if tune == 'none' else ['-x265-params', f'tune={tune}']
            pix  = task.get('cpu265_pix_fmt', 'yuv420p')
            return (['ffmpeg'] + thr + ['-i', v_path] +
                     vf_args + ['-c:v', 'libx265',
                     '-preset', task.get('cpu265_preset', 'faster'),
                     '-crf', task.get('cpu265_crf', '28'),
                     '-pix_fmt', pix] + mr + tn + map_args +
                    ['-c:a', 'copy', '-sn', '-tag:v', 'hvc1', '-y', out_path]), ass_path
        else:
            res  = _resolve_res(task.get('cpu_res', 'original'))
            vf   = (f"scale={res}," if res else "") + sub_vf
            vf   = vf.rstrip(',')
            vf_args = ['-vf', vf] if vf else []
            thr  = [] if task.get('cpu_threads', 'auto') == 'auto' else ['-threads', task['cpu_threads']]
            mr   = _maxrate_args(task.get('cpu_maxrate', 'none'))
            tune = task.get('cpu_tune', 'none')
            tn   = [] if tune == 'none' else ['-tune', tune]
            pix  = task.get('cpu_pix_fmt', 'yuv420p')
            return (['ffmpeg'] + thr + ['-i', v_path] +
                     vf_args + ['-c:v', 'libx264',
                     '-preset', task.get('cpu_preset', 'faster'),
                     '-crf', task.get('cpu_crf', '23'),
                     '-pix_fmt', pix] + mr + tn + map_args +
                    ['-c:a', 'copy', '-sn', '-y', out_path]), ass_path

# ════════════════════════════════════════════════════════════
# 🔧  VALIDATORS
# ════════════════════════════════════════════════════════════
def validate_custom(field: str, raw: str):
    v = raw.strip()
    if field.endswith('_preset'):
        if 'gpu' in field:
            if v.lower() in [f"p{i}" for i in range(1, 8)]: return v.lower(), None
            return None, "❌ GPU preset p1–p7 chahiye (e.g. p3)"
        else:
            valid = ['ultrafast','superfast','veryfast','faster','fast','medium','slow','veryslow']
            if v.lower() in valid: return v.lower(), None
            return None, f"❌ Valid: {', '.join(valid)}"
    elif field.endswith(('_cq', '_crf')):
        try:
            n = int(v)
            if 0 <= n <= 51: return str(n), None
            return None, "❌ 0–51 ke beech chahiye"
        except: return None, "❌ Sirf number likhein (e.g. 19)"
    elif field.endswith('_threads'):
        if v.lower() == 'auto': return 'auto', None
        try:
            n = int(v)
            if 1 <= n <= 64: return str(n), None
            return None, "❌ 1–64 ya 'auto'"
        except: return None, "❌ Number ya 'auto' likhein"
    elif field.endswith('_res'):
        if v.lower() == 'original': return 'original', None
        p = {'1080p': '1920:1080', '720p': '1280:720', '480p': '854:480'}
        if v.lower() in p: return p[v.lower()], None
        if re.fullmatch(r'\d+:\d+', v): return v, None
        return None, "❌ Format: W:H (e.g. 1366:768) ya 'original'/'720p'/'1080p'"
    elif field.endswith('_maxrate'):
        if v.lower() == 'none': return 'none', None
        if re.fullmatch(r'\d+(\.\d+)?[MmKk]', v): return v.upper(), None
        return None, "❌ Format: '5M', '2.5M', '500K' ya 'none'"
    return v, None

# ════════════════════════════════════════════════════════════
# 📨  COMMAND HANDLERS
# ════════════════════════════════════════════════════════════

# ──────────────────────────────────────────────────────────
# ❓  /htu — How To Use
# ──────────────────────────────────────────────────────────
@app.on_message(filters.command("htu"))
async def cmd_htu(client, message):
    if not is_admin(message.from_user.id): return
    await message.reply_text(
        "📖 **HOW TO USE — Encoder Bot**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

        "🎬 **SINGLE VIDEO (ek video + sub)**\n"
        "1️⃣ `/hsub` — single mode start karo\n"
        "2️⃣ Video file bhejo (.mp4 / .mkv / .avi)\n"
        "3️⃣ Subtitle bhejo — 2 tarike:\n"
        "   • **Reply method** — sub file ko video message ka reply karo → auto-link!\n"
        "   • **Normal method** — bas sub file bhejo → video se match ho jaayega\n"
        "4️⃣ **Add to Queue** button dabao → encoding shuru!\n"
        "🎵 **Multiple Audio Support:** Agar video me ek se zyada audio tracks hain, to encoding start hone se pehle bot aapse poochega ki kon se tracks rakhne/delete karne hain!\n"
        "5️⃣ Done! Naam choose karo (original ya custom)\n\n"
        "   ✏️ Galat sub? `/changesub` → naya sub bhejo\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔄 **RESOLUTION CONVERT (Without Subtitles)**\n"
        "`/c1080`, `/c720`, `/c480` → Kisi bhi video par reply karo convert karne ke liye (current CPU/GPU encoding settings use hongi, bas resolution change hogi).\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📦 **BATCH MODE (multiple videos)**\n"
        "1️⃣ `/hsubm` — batch mode start karo\n"
        "2️⃣ Saari videos bhejo ek ek karke\n"
        "3️⃣ `/end` — sending khatam karo\n"
        "4️⃣ Bot video list dikhayega — subtitle assign karo:\n"
        "   • **Reply method** — sub file ko video ka directly reply karo → auto-assign!\n"
        "   • **Button method** — file ka button dabao → phir sub bhejo → auto-assign!\n"
        "5️⃣ Naam panel se har file ka naam set karo (original ya custom)\n"
        "6️⃣ Jab sabke liye sub assign ho jaye → **Queue mein Add** dabao\n"
        "   ➡️ Naam confirm nahi hua? Bot poochega — sab original ya rename panel\n"
        "7️⃣ Saari videos encode ho jayengi automatically!\n\n"
        "   ✏️ Galat sub? `/changesub filename` ya `/changesub 3` (number se)\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔄 **SUBTITLE CONVERT**\n"
        "`/crtoass` `/ctosrt` `/ctovtt` \n"
        "Command ke baad sub file bhejo → converted file milegi!\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔍 **SUBTITLE EXTRACT**\n"
        "`/extract` → command ke baad video bhejo → sabhi sub tracks milenge!\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "✏️ **RENAME**\n"
        "`/rename` → encoded ya uploaded video rename + re-upload\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚙️ **SETTINGS**\n"
        "`/settings` — GPU/CPU codec, quality, resolution, threads, maxrate, tune\n"
        "Export/Import settings as JSON!\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🛑 **CANCEL / STATUS**\n"
        "`/cancel` — encoding stop, queue clear, sab reset\n"
        "`/status` — current settings + queue info\n\n"
    )

@app.on_message(filters.command(["start", "settings"]))
async def cmd_start(client, message):
    if not is_admin(message.from_user.id): return
    await message.reply_text(
        f"👑 **Encoder Bot v2**\n🌍 {ENV_NAME}\n\n"
        f"📋 **Commands:**\n"
        f"`/hsub` — Single video encode\n"
        f"`/c1080` `/c720` `/c480` — Convert video resolution\n"
        f"`/hsubm` — Batch mode start\n"
        f"`/end` — Batch complete\n"
        f"`/changesub` — Subtitle change karo\n"
        f"`/rename` — File rename\n"
        f"`/extract` — Video se subtitles nikalo\n"
        f"`/crtoass` `/ctosrt` `/ctovtt` — Sub format convert\n"
        f"`/status` `/cancel` `/settings`\n"
        f"`/htu` — Full guide!\n\n"
        f"📂 **Single Workflow:**\n"
        f"1️⃣ `/hsub` → Video bhejein\n"
        f"2️⃣ Subtitle bhejein ya **reply** karo video pe\n"
        f"3️⃣ Add to Queue ✅\n\n"
        f"🖋️ Font: .ttf directly bhejein\n"
        f"⚡ Parallel Workers — multiple videos ek saath!",
        reply_markup=main_menu(message.chat.id)
    )

# ──────────────────────────────────────────────────────────
# 🔄  RESOLUTION CONVERT SHORTCUTS
# ──────────────────────────────────────────────────────────
@app.on_message(filters.command(["c1080", "c720", "c480"]))
async def cmd_convert_res(client, message):
    if not is_admin(message.from_user.id): return
    if not message.reply_to_message or not (message.reply_to_message.video or getattr(message.reply_to_message.document, "file_name", "").lower().endswith(('.mp4', '.mkv', '.avi', '.mov', '.ts'))):
        await message.reply_text("❌ Pehle kisi video par reply karein!"); return

    res_map = {"c1080": "1080p", "c720": "720p", "c480": "480p"}
    cmd = message.command[0].lower()
    target_res = res_map.get(cmd)

    chat_id = message.chat.id
    d = get_data(chat_id)

    video_msg = message.reply_to_message
    original_fname = getattr(video_msg.video, "file_name", None) or getattr(video_msg.document, "file_name", None) or "video.mkv"

    task = _build_task(chat_id, d, video_msg, None, original_fname, is_batch=False)
    
    # Override resolution for this specific task
    if task['mode'] == 'gpu':
        if task.get('gpu_codec', 'h264') == 'h265':
            task['gpu265_res'] = target_res
        else:
            task['gpu_res'] = target_res
    else:
        if task.get('cpu_codec', 'h264') == 'h265':
            task['cpu265_res'] = target_res
        else:
            task['cpu_res'] = target_res

    await task_queue.put(task)
    pos = task_queue.qsize()
    codec_disp = _codec_display(task)
    pw = task.get('parallel_workers', 1)

    await message.reply_text(
        f"✅ **Conversion Queue mein add!** #{pos}\n"
        f"⚙️ {task['mode'].upper()} [{codec_disp}] | Target: {target_res}\n"
        f"📁 `{original_fname}`"
    )

    if not is_processing:
        asyncio.create_task(process_queue(client))

@app.on_message(filters.command(["hardsub", "hsub"]))
async def cmd_hardsub(client, message):
    if not is_admin(message.from_user.id): return
    chat_id = message.chat.id
    d = get_data(chat_id)
    for k in ['video','subtitle','temp_file','original_fname','subtitle_ext']:
        d.pop(k, None)
    d['status'] = 'idle'
    d['pending_sub_cmd'] = None
    d['pending_extract'] = False
    d['batch']['active'] = False
    d['batch']['videos'] = []
    await message.reply_text(
        "🎬 **Single HardSub Mode**\n\n"
        "Ab video bhejein (.mp4 / .mkv / .avi)\n\n"
        "📤 **Subtitle upload ke 2 tarike:**\n"
        "1️⃣ **Reply method** — sub file ko video ka reply karo → auto-link!\n"
        "2️⃣ **Normal method** — pehle video, phir sub bhejo → match hoga\n\n"
        "✏️ Galat sub assign ho gayi? `/changesub` karke naya bhejo\n"
        "🛑 `/cancel` se reset karo",
        reply_markup=main_menu(chat_id)
    )

# ──────────────────────────────────────────────────────────
# ✏️  /changesub — Change subtitle (single or batch)
# ──────────────────────────────────────────────────────────
@app.on_message(filters.command("changesub"))
async def cmd_changesub(client, message):
    if not is_admin(message.from_user.id): return
    chat_id = message.chat.id
    d = get_data(chat_id)
    args = message.text.strip().split(maxsplit=1)
    arg  = args[1].strip() if len(args) > 1 else ""

    # ── Batch mode changesub ──────────────────────────────
    if d['batch']['videos']:
        videos = d['batch']['videos']
        idx = None

        if arg:
            if arg.isdigit():
                n = int(arg) - 1
                if 0 <= n < len(videos):
                    idx = n
                else:
                    await message.reply_text(
                        f"❌ Invalid number `{arg}`!\n"
                        f"1–{len(videos)} ke beech likhein."
                    ); return
            else:
                arg_lower = arg.lower()
                matches = [(i, v) for i, v in enumerate(videos)
                           if arg_lower in v['fname'].lower()]
                if not matches:
                    await message.reply_text(
                        f"❌ `{arg}` naam ka koi file nahi mila batch mein!\n\n"
                        f"{batch_summary_text(videos)}"
                    ); return
                if len(matches) > 1:
                    lines = [f"⚠️ Multiple matches mili! Exact naam ya number use karo:\n"]
                    for i, v in matches:
                        lines.append(f"  `{i+1}.` `{v['fname']}`")
                    await message.reply_text("\n".join(lines)); return
                idx = matches[0][0]
        else:
            await message.reply_text(
                f"✏️ **Changesub** — Kis file ka sub change karna hai?\n\n"
                f"{batch_summary_text(videos)}\n\n"
                f"Use: `/changesub 2` ya `/changesub filename`"
            ); return

        old_fname = videos[idx]['fname']
        had_sub = videos[idx]['subtitle'] is not None
        videos[idx]['subtitle'] = None
        videos[idx]['sub_ext']  = None
        d['batch']['waiting_sub_for'] = idx
        await message.reply_text(
            f"🔄 **Subtitle Change**\n"
            f"📁 File {idx+1}: `{old_fname}`\n"
            f"{'🗑️ Old sub cleared.' if had_sub else ''}\n\n"
            f"Ab naya subtitle bhejo (.srt / .ass / .vtt)\n"
            f"Ya video ka **reply** karo sub se!\n"
            f"🛑 Cancel: `/cancel`"
        )
        await _refresh_batch_panel(client, chat_id)
        return

    # ── Single mode changesub ─────────────────────────────
    if 'video' not in d:
        await message.reply_text(
            "❌ Pehle video upload karo!\n"
            "`/hsub` se start karo."
        ); return

    had_sub = 'subtitle' in d
    d.pop('subtitle', None)
    d.pop('subtitle_ext', None)
    vname = d.get('original_fname', 'video.mkv')
    await message.reply_text(
        f"🔄 **Subtitle Change**\n"
        f"📺 Video: `{vname}`\n"
        f"{'🗑️ Old sub cleared.' if had_sub else ''}\n\n"
        f"Ab naya subtitle bhejo (.srt / .ass / .vtt)\n"
        f"Ya video ka **reply** karo sub se!\n"
        f"🛑 Cancel: `/cancel`"
    )

# ──────────────────────────────────────────────────────────
# 🗂️  BATCH MODE: /hsubm and /end
# ──────────────────────────────────────────────────────────
@app.on_message(filters.command("hsubm"))
async def cmd_hsubm(client, message):
    if not is_admin(message.from_user.id): return
    chat_id = message.chat.id
    d = get_data(chat_id)
    d['batch']['active']               = True
    d['batch']['videos']               = []
    d['batch']['waiting_sub_for']      = None
    d['batch']['summary_msg_id']       = None
    d['batch']['panel_msg_id']         = None
    d['batch']['rename_panel_msg_id']  = None
    d['batch']['rename_pending_idx']   = None
    d['batch']['rename_awaiting_custom'] = False
    await message.reply_text(
        "✅ **Batch Mode ON!**\n\n"
        "Ab apni videos bhejein (ek ke baad ek)\n"
        "Jab sab videos bhej do → `/end` type karo\n\n"
        "⚠️ Batch mode mein single hardsub off hai\n"
        "`/cancel` se cancel kar sakte ho"
    )

@app.on_message(filters.command("end"))
async def cmd_end(client, message):
    if not is_admin(message.from_user.id): return
    chat_id = message.chat.id
    d = get_data(chat_id)
    batch = d['batch']
    if not batch['active']:
        await message.reply_text("❌ Batch mode active nahi hai. Pehle `/hsubm` karo."); return
    batch['active'] = False
    videos = batch['videos']
    if not videos:
        await message.reply_text("❌ Koi video nahi mili batch mein. Dobara `/hsubm` se start karo."); return

    summary = "\n".join([f"{i+1}️⃣ `{v['fname']}`" for i, v in enumerate(videos)])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Subtitles Upload Karo", callback_data="batch_upload_subs"),
         InlineKeyboardButton("❌ Cancel",                callback_data="batch_cancel")],
    ])
    sent = await message.reply_text(
        f"✅ **{len(videos)} videos ready!**\n\n{summary}\n\n"
        f"👆 **Subtitles Upload Karo** dabao",
        reply_markup=kb
    )
    batch['summary_msg_id'] = sent.id

# ──────────────────────────────────────────────────────────
# ✏️  /rename — Rename last encoded or uploaded video
# ──────────────────────────────────────────────────────────
@app.on_message(filters.command("rename"))
async def cmd_rename(client, message):
    if not is_admin(message.from_user.id): return
    chat_id = message.chat.id
    d = get_data(chat_id)
    has_encoded  = d.get('temp_file') and os.path.exists(d.get('temp_file',''))
    has_uploaded = 'video' in d

    if not has_encoded and not has_uploaded:
        await message.reply_text(
            "❌ Rename ke liye kuch nahi mila!\n\n"
            "• Video bhejo phir encode karo → encoded file rename hogi\n"
            "• Ya sirf video upload karo → `/rename` se direct re-upload with new name"
        ); return

    buttons = []
    if has_encoded:
        orig = d.get('_last_orig', d.get('original_fname', 'output.mkv'))
        buttons.append([InlineKeyboardButton(f"📁 Rename Encoded: {orig[:30]}", callback_data="rename_encoded")])
    if has_uploaded:
        fname = d.get('original_fname', 'video.mkv')
        buttons.append([InlineKeyboardButton(f"📺 Rename & Re-upload: {fname[:28]}", callback_data="rename_uploaded")])
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="rename_cancel")])

    await message.reply_text(
        "✏️ **Rename — Kya rename karna hai?**",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ──────────────────────────────────────────────────────────
# 🔍  /extract — Extract subtitles from video
# ──────────────────────────────────────────────────────────
@app.on_message(filters.command("extract"))
async def cmd_extract(client, message):
    if not is_admin(message.from_user.id): return
    chat_id = message.chat.id
    d = get_data(chat_id)
    d['pending_extract'] = True
    d['pending_sub_cmd'] = None
    await message.reply_text(
        "🔍 **Subtitle Extract Mode**\n\n"
        "Ab video bhejein jis ke subtitles nikalne hain\n"
        "Bot sabhi subtitle tracks detect karke de dega!\n\n"
        "`/cancel` se cancel karo"
    )

# ──────────────────────────────────────────────────────────
# 🔄  Subtitle Conversion Commands
# ──────────────────────────────────────────────────────────
@app.on_message(filters.command("crtoass"))
async def cmd_crtoass(client, message):
    if not is_admin(message.from_user.id): return
    d = get_data(message.chat.id)
    d['pending_sub_cmd'] = 'crtoass'; d['pending_extract'] = False
    await message.reply_text("🔄 **Convert → ASS**\n\nSRT ya VTT subtitle bhejein!")

@app.on_message(filters.command("ctosrt"))
async def cmd_ctosrt(client, message):
    if not is_admin(message.from_user.id): return
    d = get_data(message.chat.id)
    d['pending_sub_cmd'] = 'ctosrt'; d['pending_extract'] = False
    await message.reply_text("🔄 **Convert → SRT**\n\nASS ya VTT subtitle bhejein!")

@app.on_message(filters.command("ctovtt"))
async def cmd_ctovtt(client, message):
    if not is_admin(message.from_user.id): return
    d = get_data(message.chat.id)
    d['pending_sub_cmd'] = 'ctovtt'; d['pending_extract'] = False
    await message.reply_text("🔄 **Convert → VTT**\n\nSRT ya ASS subtitle bhejein!")

# ──────────────────────────────────────────────────────────
# 🛑  /cancel
# ──────────────────────────────────────────────────────────
@app.on_message(filters.command("cancel"))
async def cmd_cancel(client, message):
    global current_proc, is_processing
    if not is_admin(message.from_user.id): return
    chat_id = message.chat.id
    d = get_data(chat_id)
    killed = False
    if current_proc and current_proc.returncode is None:
        current_proc.terminate()
        await asyncio.sleep(1)
        if current_proc.returncode is None: current_proc.kill()
        current_proc = None; killed = True
    cleared = 0
    while not task_queue.empty():
        try: task_queue.get_nowait(); task_queue.task_done(); cleared += 1
        except asyncio.QueueEmpty: break
    is_processing = False
    d['status'] = 'idle'
    d['pending_sub_cmd']    = None
    d['pending_extract']    = False
    d['pending_rename_raw'] = False
    d['batch']['active']               = False
    d['batch']['videos']               = []
    d['batch']['waiting_sub_for']      = None
    d['batch']['panel_msg_id']         = None
    d['batch']['rename_panel_msg_id']  = None
    d['batch']['rename_pending_idx']   = None
    d['batch']['rename_awaiting_custom'] = False
    for k in ['video','subtitle','temp_file','original_fname','subtitle_ext','custom_field','_last_orig']:
        d.pop(k, None)
    parts = []
    if killed:  parts.append("🔴 Encoding terminated.")
    if cleared: parts.append(f"🗑️ {cleared} queued task(s) cleared.")
    parts.append("🧹 Batch + pending ops reset.")
    await message.reply_text("🛑 **Cancelled!**\n" + "\n".join(parts) if parts else "ℹ️ Koi task nahi tha.")

@app.on_message(filters.command("status"))
async def cmd_status(client, message):
    if not is_admin(message.from_user.id): return
    d   = get_data(message.chat.id)
    qs  = task_queue.qsize()
    proc = f"🔥 Encoding ({active_tasks} active)" if active_tasks > 0 else "💤 Idle"
    m   = d['mode'].upper()
    pw  = d.get('parallel_workers', 1)
    if m == 'GPU':
        codec = d.get('gpu_codec', 'h264').upper()
        if codec == 'H265':
            info = (f"hevc_nvenc P{d.get('gpu265_preset','p4')[1:]} | CQ:{d.get('gpu265_cq','24')} | "
                    f"Res:{d.get('gpu265_res','original')} | T:{d.get('gpu265_threads','auto')}")
        else:
            info = (f"h264_nvenc P{d['gpu_preset'][1:]} | CQ:{d['gpu_cq']} | "
                    f"Res:{d['gpu_res']} | T:{d.get('gpu_threads','auto')}")
    else:
        codec = d.get('cpu_codec', 'h264').upper()
        if codec == 'H265':
            info = (f"libx265 {d.get('cpu265_preset','faster')} | CRF:{d.get('cpu265_crf','28')} | "
                    f"Res:{d.get('cpu265_res','original')} | T:{d.get('cpu265_threads','auto')}")
        else:
            info = (f"libx264 {d['cpu_preset']} | CRF:{d['cpu_crf']} | "
                    f"Res:{d['cpu_res']} | T:{d['cpu_threads']}")
    batch_status = f"📦 Batch: {len(d['batch']['videos'])} videos" if d['batch']['videos'] else ""
    await message.reply_text(
        f"📊 **Status** | {ENV_NAME}\n"
        f"⚙️ **{m}** — {info}\n"
        f"🖋️ {d['font']} | ⚡ {pw}x | Queue: {qs} | {proc}\n"
        f"{batch_status}"
    )

# ════════════════════════════════════════════════════════════
# 📁  FILE UPLOAD HANDLER
# ════════════════════════════════════════════════════════════
@app.on_message(filters.document | filters.video)
async def handle_uploads(client, message):
    if not is_admin(message.from_user.id): return
    chat_id   = message.chat.id
    d         = get_data(chat_id)
    file_name = (
        getattr(message.document, "file_name", None) or
        getattr(message.video,    "file_name", None) or "file"
    )
    fl = file_name.lower()

    # ── Skip if waiting for rename input ─────────────────
    if d.get('status') == 'waiting_rename': return

    # ── JSON Import ───────────────────────────────────────
    if fl.endswith(".json"):
        raw       = await message.download(in_memory=True)
        raw_bytes = bytes(raw.getbuffer()) if hasattr(raw, 'getbuffer') else raw.read()
        import_type = d.get('pending_import', None)
        ok, msg   = import_settings(chat_id, raw_bytes, import_type)
        d['pending_import'] = None
        await message.reply_text(msg, reply_markup=main_menu(chat_id))
        return

    # ── Font Install ──────────────────────────────────────
    if fl.endswith(".ttf"):
        path = await message.download(file_name=f"fonts/{file_name}")
        fd   = os.path.expanduser("~/.fonts"); os.makedirs(fd, exist_ok=True)
        os.system(f"cp '{path}' '{fd}/' && fc-cache -f -v 2>/dev/null")
        font_name = os.path.splitext(file_name)[0]
        d['font'] = font_name
        await message.reply_text(
            f"✅ Font **{font_name}** installed!\n🖋️ Active as current font.",
            reply_markup=main_menu(chat_id)
        )
        return

    # ── Subtitle Conversion (pending_sub_cmd) ─────────────
    if d.get('pending_sub_cmd') and fl.endswith(('.srt', '.ass', '.vtt')):
        cmd = d['pending_sub_cmd']
        ext_map = {'crtoass': '.ass', 'ctosrt': '.srt', 'ctovtt': '.vtt'}
        out_ext  = ext_map[cmd]
        src_path = await message.download(file_name=f"downloads/conv_src_{chat_id}{os.path.splitext(fl)[1]}")
        out_path = f"downloads/conv_out_{chat_id}{out_ext}"
        prog = await message.reply_text(f"🔄 Converting to `{out_ext}`...")
        try:
            ret = subprocess.run(['ffmpeg', '-y', '-i', src_path, out_path], capture_output=True)
            if ret.returncode == 0 and os.path.exists(out_path):
                orig_base = os.path.splitext(file_name)[0]
                out_fname = f"{orig_base}{out_ext}"
                await client.send_document(chat_id, out_path,
                    caption=f"✅ **Converted!**\n📄 `{out_fname}`",
                    file_name=out_fname)
                os.remove(out_path)
            else:
                await prog.edit_text(f"❌ Convert fail!\n`{ret.stderr.decode(errors='replace')[-300:]}`")
        except Exception as e:
            await prog.edit_text(f"❌ Error: `{e}`")
        finally:
            if os.path.exists(src_path): os.remove(src_path)
            d['pending_sub_cmd'] = None
            await prog.delete()
        return

    # ── Extract Subtitles (pending_extract) ──────────────
    if d.get('pending_extract') and (message.video or fl.endswith(('.mp4', '.mkv', '.avi', '.mov', '.ts'))):
        d['pending_extract'] = False
        prog = await message.reply_text(f"🔍 Downloading `{file_name}` for extraction...")
        v_path = await message.download(file_name=f"downloads/ext_{chat_id}.tmp")
        try:
            probe = subprocess.run(
                ['ffprobe', '-v', 'quiet', '-print_format', 'json',
                 '-show_streams', '-select_streams', 's', v_path],
                capture_output=True, text=True
            )
            data = json.loads(probe.stdout or '{}')
            streams = data.get('streams', [])
            if not streams:
                await prog.edit_text("⚠️ Koi subtitle track nahi mila is video mein.")
                os.remove(v_path); return

            await prog.edit_text(f"✅ {len(streams)} subtitle track(s) mili!\n🔄 Extracting...")
            base_name = os.path.splitext(file_name)[0]
            sent_count = 0
            for i, s in enumerate(streams):
                codec = s.get('codec_name', 'ass')
                ext   = {'subrip': '.srt', 'ass': '.ass', 'ssa': '.ass',
                         'webvtt': '.vtt', 'hdmv_pgs_subtitle': '.sup'}.get(codec, '.ass')
                lang  = s.get('tags', {}).get('language', f'track{i}')
                title = s.get('tags', {}).get('title', '')
                out_sub = f"downloads/sub_{chat_id}_{i}{ext}"
                ret = subprocess.run(
                    ['ffmpeg', '-y', '-i', v_path, '-map', f'0:s:{i}', out_sub],
                    capture_output=True
                )
                if ret.returncode == 0 and os.path.exists(out_sub):
                    fname_out = f"{base_name}_sub_{lang}_{title}{ext}".replace(' ','_')
                    await client.send_document(chat_id, out_sub,
                        caption=f"📄 Track {i+1} | `{lang}` | {codec.upper()}{' — '+title if title else ''}",
                        file_name=fname_out)
                    os.remove(out_sub)
                    sent_count += 1
            await prog.edit_text(f"✅ **{sent_count}/{len(streams)} tracks extracted!**")
        except Exception as e:
            await prog.edit_text(f"❌ Extract error: `{e}`")
        finally:
            if os.path.exists(v_path): os.remove(v_path)
        return

    # ── Rename & Re-upload raw video ──────────────────────
    if d.get('pending_rename_raw') and (message.video or fl.endswith(('.mp4', '.mkv', '.avi', '.mov', '.ts'))):
        d['pending_rename_raw'] = False
        d['video']          = message
        d['original_fname'] = file_name
        d['status']         = 'waiting_rename_fresh'
        await message.reply_text(
            f"📺 Video ready: `{file_name}`\n\n"
            f"✏️ Naya naam type karein (bina extension ke):\n"
            f"`/cancel_custom` se cancel"
        )
        return

    # ── BATCH MODE: Video collection ──────────────────────
    if d['batch']['active'] and (message.video or fl.endswith(('.mp4', '.mkv', '.avi', '.mov', '.ts'))):
        idx = len(d['batch']['videos'])
        d['batch']['videos'].append({
            'msg'           : message,
            'fname'         : file_name,
            'original_fname': file_name,
            'name_confirmed': False,
            'subtitle'      : None,
            'sub_ext'       : None,
        })
        videos = d['batch']['videos']
        panel_id = d['batch'].get('rename_panel_msg_id')
        if panel_id:
            await _refresh_rename_panel(client, chat_id)
        else:
            sent = await client.send_message(
                chat_id,
                _rename_panel_text(videos),
                reply_markup=_rename_panel_kb(videos)
            )
            d['batch']['rename_panel_msg_id'] = sent.id
        return

    # ── BATCH MODE: Subtitle for selected file (waiting_sub_for) ──
    if d['batch']['waiting_sub_for'] is not None and fl.endswith(('.srt', '.ass', '.vtt')):
        idx    = d['batch']['waiting_sub_for']
        videos = d['batch']['videos']
        if 0 <= idx < len(videos):
            videos[idx]['subtitle'] = message
            videos[idx]['sub_ext']  = os.path.splitext(fl)[1]
            d['batch']['waiting_sub_for'] = None
            ext   = os.path.splitext(fl)[1].upper()
            fname = videos[idx]['fname']
            ready = sum(1 for v in videos if v['subtitle'])
            total = len(videos)
            await message.reply_text(
                f"✅ **File {idx+1} sub linked!** [{ext}]\n"
                f"📁 `{fname}`\n"
                f"📊 {ready}/{total} done"
            )
            await _refresh_batch_panel(client, chat_id)
        return

    # ── REPLY-TO-VIDEO: Auto-assign subtitle ─────────────
    if fl.endswith(('.srt', '.ass', '.vtt')) and message.reply_to_message:
        ref = message.reply_to_message
        ref_fname = (
            getattr(ref.document, "file_name", None) or
            getattr(ref.video,    "file_name", None) or ""
        ).lower()
        if ref_fname.endswith(('.mp4', '.mkv', '.avi', '.mov', '.ts')):
            for i, v in enumerate(d['batch']['videos']):
                if v['msg'].id == ref.id:
                    v['subtitle'] = message
                    v['sub_ext']  = os.path.splitext(fl)[1]
                    if d['batch']['waiting_sub_for'] == i:
                        d['batch']['waiting_sub_for'] = None
                    ready = sum(1 for vv in d['batch']['videos'] if vv['subtitle'])
                    total = len(d['batch']['videos'])
                    ext   = os.path.splitext(fl)[1].upper()
                    await message.reply_text(
                        f"✅ **Auto-assigned!** [{ext}]\n"
                        f"📦 File {i+1}: `{v['fname']}`\n"
                        f"📊 {ready}/{total} done"
                    )
                    await _refresh_batch_panel(client, chat_id)
                    return
            # Single mode auto-assign
            d['video']          = ref
            d['original_fname'] = ref_fname
            d['subtitle']       = message
            d['subtitle_ext']   = os.path.splitext(fl)[1]
            ext  = os.path.splitext(fl)[1].upper()
            orig = ref_fname
            await message.reply_text(
                f"✅ **Auto-Linked!** [{ext}]\n"
                f"📺 `{orig}`\n📄 `{file_name}`\n\n"
                f"Queue mein dalein?",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🚀 Add to Queue", callback_data="add_queue"),
                    InlineKeyboardButton("🗑️ Clear Files",  callback_data="cancel_files"),
                ]])
            )
            return

    # ── SINGLE MODE: Video ────────────────────────────────
    if message.video or fl.endswith(('.mp4', '.mkv', '.avi', '.mov', '.ts')):
        d['video']          = message
        d['original_fname'] = file_name
        d.pop('subtitle', None); d.pop('subtitle_ext', None)
        await message.reply_text(
            f"📺 **Video saved!**\n`{file_name}`\n\n"
            f"Ab subtitle bhejein (.srt/.vtt/.ass)\n"
            f"💡 Ya subtitle file ko **is video ka reply** karo — auto-link hoga!\n\n"
            f"✏️ `/changesub` — baad mein sub change karne ke liye"
        )
        return

    # ── SINGLE MODE: Subtitle ────────────────────────────
    if fl.endswith(('.srt', '.ass', '.vtt')):
        if 'video' not in d:
            await message.reply_text("❌ Pehle video upload karein!"); return
        d['subtitle']     = message
        d['subtitle_ext'] = os.path.splitext(fl)[1]
        ext  = os.path.splitext(fl)[1].upper()
        orig = d.get('original_fname', 'video.mkv')
        await message.reply_text(
            f"✅ **{ext} Subtitle received!**\n"
            f"📺 `{orig}` ✓\n\n"
            f"Queue mein dalein?\n"
            f"✏️ Galat sub? `/changesub` se change karo",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🚀 Add to Queue", callback_data="add_queue"),
                InlineKeyboardButton("🗑️ Clear Files",  callback_data="cancel_files"),
            ]])
        )
        return

# ════════════════════════════════════════════════════════════
# ✏️  TEXT INPUT HANDLER
# ════════════════════════════════════════════════════════════
HANDLED_CMDS = [
    "start","settings","cancel","status","hsubm","end","rename","extract",
    "crtoass","ctosrt","ctovtt","hardsub","hsub","htu","changesub", "c1080", "c720", "c480"
]

@app.on_message(filters.text & ~filters.command(HANDLED_CMDS))
async def handle_text_input(client, message):
    if not is_admin(message.from_user.id): return
    chat_id = message.chat.id
    d       = get_data(chat_id)

    if message.text.strip() in ("/cancel_custom",):
        d['custom_field'] = None; d['custom_msg_id'] = None
        if d.get('status') == 'waiting_rename_fresh':
            d['status'] = 'idle'
            d.pop('video', None)
        if d['batch'].get('rename_awaiting_custom'):
            d['batch']['rename_awaiting_custom'] = False
            d['batch']['rename_pending_idx']     = None
            await _refresh_rename_panel(client, chat_id)
        await message.reply_text("↩️ Cancelled."); return

    # ── Batch custom rename text input ────────────────────
    if d['batch'].get('rename_awaiting_custom') and d['batch'].get('rename_pending_idx') is not None:
        idx    = d['batch']['rename_pending_idx']
        videos = d['batch']['videos']
        if 0 <= idx < len(videos):
            name     = message.text.strip()
            orig_ext = os.path.splitext(videos[idx]['original_fname'])[1] or '.mkv'
            if not any(name.lower().endswith(e) for e in ['.mp4', '.mkv', '.avi', '.mov']):
                name += orig_ext
            videos[idx]['fname']          = name
            videos[idx]['name_confirmed'] = True
            d['batch']['rename_awaiting_custom'] = False
            d['batch']['rename_pending_idx']     = None
            await _refresh_rename_panel(client, chat_id)
        return

    # ── Settings custom input ─────────────────────────────
    if d.get('custom_field'):
        field  = d['custom_field']
        msg_id = d.get('custom_msg_id')
        side   = 'gpu' if 'gpu' in field else 'cpu'
        cleaned, err = validate_custom(field, message.text)
        if err:
            await message.reply_text(f"{err}\n\nDobara try karein ya /cancel_custom:"); return
        d[field] = cleaned; d['custom_field'] = None; d['custom_msg_id'] = None
        await message.reply_text(f"✅ **{field}** → `{cleaned}`")
        try:
            fn = gpu_settings_menu if side == 'gpu' else cpu_settings_menu
            await client.edit_message_reply_markup(chat_id, msg_id, fn(chat_id))
        except: pass
        return

    # ── Rename encoded output ─────────────────────────────
    if d.get('status') == 'waiting_rename':
        name = message.text.strip()
        if not name.lower().endswith(".mkv"): name += ".mkv"
        await message.reply_text(f"📝 Renaming to: **{name}**...")
        await upload_final_video(client, chat_id, name)
        return

    # ── Rename & Re-upload raw video ──────────────────────
    if d.get('status') == 'waiting_rename_fresh':
        name = message.text.strip()
        if not name.lower().endswith(".mkv"): name += ".mkv"
        d['status'] = 'idle'
        prog = await message.reply_text(f"⬇️ Downloading original video...")
        try:
            v_path = await d['video'].download(file_name=f"downloads/rename_{chat_id}.tmp")
            final  = f"downloads/{name}"
            os.rename(v_path, final)
            await prog.edit_text(f"☁️ Uploading `{name}`...")
            await client.send_document(chat_id, final, caption=f"**{name}**", file_name=name)
            os.remove(final)
            await prog.delete()
        except Exception as e:
            await prog.edit_text(f"❌ Error: `{e}`")
        finally:
            d.pop('video', None); d.pop('original_fname', None)
        return

# ════════════════════════════════════════════════════════════
# 🔘  CALLBACK ROUTER
# ════════════════════════════════════════════════════════════
CUSTOM_PROMPTS = {
    "custom_gpu_preset"    : ("gpu_preset",     "gpu",   "🎮 GPU H.264 Preset",     "p1–p7 (e.g. p3)"),
    "custom_gpu_cq"        : ("gpu_cq",         "gpu",   "🎮 GPU H.264 CQ",         "0–51, lower=better"),
    "custom_gpu_threads"   : ("gpu_threads",    "gpu",   "🎮 GPU H.264 Threads",    "number ya 'auto'"),
    "custom_gpu_res"       : ("gpu_res",        "gpu",   "🎮 GPU H.264 Resolution", "W:H ya 'original'"),
    "custom_gpu_maxrate"   : ("gpu_maxrate",    "gpu",   "🎮 GPU H.264 Maxrate",    "'none' ya '4M','500K'"),
    "custom_gpu265_preset" : ("gpu265_preset",  "gpu",   "🎮 GPU H.265 Preset",     "p1–p7"),
    "custom_gpu265_cq"     : ("gpu265_cq",      "gpu",   "🎮 GPU H.265 CQ",         "0–51"),
    "custom_gpu265_threads": ("gpu265_threads", "gpu",   "🎮 GPU H.265 Threads",    "number ya 'auto'"),
    "custom_gpu265_res"    : ("gpu265_res",     "gpu",   "🎮 GPU H.265 Resolution", "W:H ya 'original'"),
    "custom_gpu265_maxrate": ("gpu265_maxrate", "gpu",   "🎮 GPU H.265 Maxrate",    "'none' ya '4M'"),
    "custom_cpu_preset"    : ("cpu_preset",     "cpu",   "🖥️ CPU H.264 Preset",     "ultrafast/.../slow"),
    "custom_cpu_crf"       : ("cpu_crf",        "cpu",   "🖥️ CPU H.264 CRF",        "0–51"),
    "custom_cpu_threads"   : ("cpu_threads",    "cpu",   "🖥️ CPU H.264 Threads",    "number ya 'auto'"),
    "custom_cpu_res"       : ("cpu_res",        "cpu",   "🖥️ CPU H.264 Resolution", "W:H ya 'original'"),
    "custom_cpu_maxrate"   : ("cpu_maxrate",    "cpu",   "🖥️ CPU H.264 Maxrate",    "'none' ya '4M'"),
    "custom_cpu265_preset" : ("cpu265_preset",  "cpu",   "🖥️ CPU H.265 Preset",     "ultrafast/.../slow"),
    "custom_cpu265_crf"    : ("cpu265_crf",     "cpu",   "🖥️ CPU H.265 CRF",        "0–51"),
    "custom_cpu265_threads": ("cpu265_threads", "cpu",   "🖥️ CPU H.265 Threads",    "number ya 'auto'"),
    "custom_cpu265_res"    : ("cpu265_res",     "cpu",   "🖥️ CPU H.265 Resolution", "W:H ya 'original'"),
    "custom_cpu265_maxrate": ("cpu265_maxrate", "cpu",   "🖥️ CPU H.265 Maxrate",    "'none' ya '4M'"),
}

@app.on_callback_query()
async def cb_handler(client, query):
    global is_processing, current_proc

    if not is_admin(query.from_user.id):
        await query.answer("❌ Access Denied!", show_alert=True); return

    chat_id = query.message.chat.id
    cb      = query.data
    d       = get_data(chat_id)

    if cb == "noop": await query.answer(); return

    # ── Interactive Audio Menu Handlers ───────────────────
    if cb.startswith("del_aud_"):
        parts = cb.split("_")
        task_id = int(parts[2])
        idx = int(parts[3])
        if task_id in pending_audios:
            if idx in pending_audios[task_id]['deleted']:
                pending_audios[task_id]['deleted'].remove(idx)
            else:
                pending_audios[task_id]['deleted'].add(idx)
            await query.message.edit_reply_markup(_build_audio_kb(task_id))
        await query.answer()
        return

    if cb.startswith("cont_aud_"):
        task_id = int(cb.split("_")[2])
        if task_id in pending_audios:
            pending_audios[task_id]['event'].set()
        await query.answer("Continuing...")
        return

    # ── Navigation ─────────────────────────────────────────
    if cb in ("back_main", "refresh_main"):
        await query.message.edit_reply_markup(main_menu(chat_id))
        await query.answer(); return

    if cb in ("set_gpu", "set_cpu"):
        d['mode'] = cb.split("_")[1]
        await query.message.edit_reply_markup(main_menu(chat_id))
        await query.answer(f"✅ {d['mode'].upper()} Mode"); return

    if cb == "menu_gpu":
        await query.message.edit_reply_markup(gpu_settings_menu(chat_id))
        await query.answer(); return

    if cb == "menu_cpu":
        await query.message.edit_reply_markup(cpu_settings_menu(chat_id))
        await query.answer(); return

    if cb == "menu_fonts":
        kb, text = fonts_menu(chat_id)
        await query.message.edit_text(text, reply_markup=kb); return

    if cb == "menu_parallel":
        await query.message.edit_reply_markup(parallel_menu(chat_id))
        await query.answer(); return

    # ── Parallel Workers ──────────────────────────────────
    if cb.startswith("parallel_"):
        n = int(cb.split("_")[1])
        d['parallel_workers'] = n
        await query.message.edit_reply_markup(parallel_menu(chat_id))
        await query.answer(f"✅ Parallel Workers: {n}x"); return

    # ── Codec Switches ────────────────────────────────────
    if cb == "gpu_codec_h264":
        d['gpu_codec'] = 'h264'
        await query.message.edit_reply_markup(gpu_settings_menu(chat_id)); await query.answer("✅ H.264 NVENC"); return
    if cb == "gpu_codec_h265":
        d['gpu_codec'] = 'h265'
        await query.message.edit_reply_markup(gpu_settings_menu(chat_id)); await query.answer("✅ H.265 HEVC"); return
    if cb == "cpu_codec_h264":
        d['cpu_codec'] = 'h264'
        await query.message.edit_reply_markup(cpu_settings_menu(chat_id)); await query.answer("✅ H.264 x264"); return
    if cb == "cpu_codec_h265":
        d['cpu_codec'] = 'h265'
        await query.message.edit_reply_markup(cpu_settings_menu(chat_id)); await query.answer("✅ H.265 x265"); return

    # ── Export / Import ───────────────────────────────────
    if cb == "export_gpu":
        bio = io.BytesIO(export_settings(chat_id, 'gpu')); bio.name = "encoder_gpu_settings.json"
        await client.send_document(chat_id, bio, caption="🎮 **GPU Settings**")
        await query.answer("📤 GPU Exported!"); return
    if cb == "export_cpu":
        bio = io.BytesIO(export_settings(chat_id, 'cpu')); bio.name = "encoder_cpu_settings.json"
        await client.send_document(chat_id, bio, caption="🖥️ **CPU Settings**")
        await query.answer("📤 CPU Exported!"); return
    if cb == "import_gpu_prompt":
        d['pending_import'] = 'gpu'
        await query.message.reply_text("📥 **GPU Import** — `encoder_gpu_settings.json` bhejein!")
        await query.answer(); return
    if cb == "import_cpu_prompt":
        d['pending_import'] = 'cpu'
        await query.message.reply_text("📥 **CPU Import** — `encoder_cpu_settings.json` bhejein!")
        await query.answer(); return

    # ── GPU H.264 setting callbacks ───────────────────────
    for pfx in ['gpu']:
        if cb.startswith(f"{pfx}_preset_"):
            d[f'{pfx}_preset'] = cb.replace(f"{pfx}_preset_", "")
            await query.message.edit_reply_markup(gpu_settings_menu(chat_id))
            await query.answer(f"✅ Preset: {d[f'{pfx}_preset'].upper()}"); return
        if cb.startswith(f"{pfx}_cq_"):
            d[f'{pfx}_cq'] = cb.replace(f"{pfx}_cq_", "")
            await query.message.edit_reply_markup(gpu_settings_menu(chat_id))
            await query.answer(f"✅ CQ: {d[f'{pfx}_cq']}"); return
        if cb.startswith(f"{pfx}_res_"):
            d[f'{pfx}_res'] = cb.replace(f"{pfx}_res_", "")
            await query.message.edit_reply_markup(gpu_settings_menu(chat_id))
            await query.answer(f"✅ Res: {d[f'{pfx}_res']}"); return
        if cb.startswith(f"{pfx}_threads_"):
            d[f'{pfx}_threads'] = cb.replace(f"{pfx}_threads_", "")
            await query.message.edit_reply_markup(gpu_settings_menu(chat_id))
            await query.answer(f"✅ Threads: {d[f'{pfx}_threads']}"); return
        if cb.startswith(f"{pfx}_maxrate_"):
            d[f'{pfx}_maxrate'] = cb.replace(f"{pfx}_maxrate_", "")
            await query.message.edit_reply_markup(gpu_settings_menu(chat_id))
            await query.answer(f"✅ Maxrate: {d[f'{pfx}_maxrate']}"); return
        if cb.startswith(f"{pfx}_tune_"):
            d[f'{pfx}_tune'] = cb.replace(f"{pfx}_tune_", "")
            await query.message.edit_reply_markup(gpu_settings_menu(chat_id))
            await query.answer(f"✅ Tune: {d[f'{pfx}_tune']}"); return
        if cb.startswith(f"{pfx}_pix_"):
            d[f'{pfx}_pix_fmt'] = cb.replace(f"{pfx}_pix_", "")
            await query.message.edit_reply_markup(gpu_settings_menu(chat_id))
            await query.answer(f"✅ Pix: {d[f'{pfx}_pix_fmt']}"); return

    # ── GPU H.265 setting callbacks ───────────────────────
    if cb.startswith("gpu265_preset_"):
        d['gpu265_preset'] = cb.replace("gpu265_preset_", "")
        await query.message.edit_reply_markup(gpu_settings_menu(chat_id)); await query.answer(f"✅ H.265 Preset: {d['gpu265_preset'].upper()}"); return
    if cb.startswith("gpu265_cq_"):
        d['gpu265_cq'] = cb.replace("gpu265_cq_", "")
        await query.message.edit_reply_markup(gpu_settings_menu(chat_id)); await query.answer(f"✅ H.265 CQ: {d['gpu265_cq']}"); return
    if cb.startswith("gpu265_res_"):
        d['gpu265_res'] = cb.replace("gpu265_res_", "")
        await query.message.edit_reply_markup(gpu_settings_menu(chat_id)); await query.answer(f"✅ H.265 Res: {d['gpu265_res']}"); return
    if cb.startswith("gpu265_threads_"):
        d['gpu265_threads'] = cb.replace("gpu265_threads_", "")
        await query.message.edit_reply_markup(gpu_settings_menu(chat_id)); await query.answer(f"✅ H.265 Threads: {d['gpu265_threads']}"); return
    if cb.startswith("gpu265_maxrate_"):
        d['gpu265_maxrate'] = cb.replace("gpu265_maxrate_", "")
        await query.message.edit_reply_markup(gpu_settings_menu(chat_id)); await query.answer(f"✅ H.265 Maxrate: {d['gpu265_maxrate']}"); return
    if cb.startswith("gpu265_tune_"):
        d['gpu265_tune'] = cb.replace("gpu265_tune_", "")
        await query.message.edit_reply_markup(gpu_settings_menu(chat_id)); await query.answer(f"✅ H.265 Tune: {d['gpu265_tune']}"); return
    if cb.startswith("gpu265_pix_"):
        d['gpu265_pix_fmt'] = cb.replace("gpu265_pix_", "")
        await query.message.edit_reply_markup(gpu_settings_menu(chat_id)); await query.answer(f"✅ H.265 Pix: {d['gpu265_pix_fmt']}"); return

    # ── CPU H.264 setting callbacks ───────────────────────
    if cb.startswith("cpu_preset_"):
        d['cpu_preset'] = cb.replace("cpu_preset_", "")
        await query.message.edit_reply_markup(cpu_settings_menu(chat_id)); await query.answer(f"✅ CPU Preset: {d['cpu_preset']}"); return
    if cb.startswith("cpu_crf_"):
        d['cpu_crf'] = cb.replace("cpu_crf_", "")
        await query.message.edit_reply_markup(cpu_settings_menu(chat_id)); await query.answer(f"✅ CRF: {d['cpu_crf']}"); return
    if cb.startswith("cpu_res_"):
        d['cpu_res'] = cb.replace("cpu_res_", "")
        await query.message.edit_reply_markup(cpu_settings_menu(chat_id)); await query.answer(f"✅ Res: {d['cpu_res']}"); return
    if cb.startswith("cpu_threads_"):
        d['cpu_threads'] = cb.replace("cpu_threads_", "")
        await query.message.edit_reply_markup(cpu_settings_menu(chat_id)); await query.answer(f"✅ Threads: {d['cpu_threads']}"); return
    if cb.startswith("cpu_maxrate_"):
        d['cpu_maxrate'] = cb.replace("cpu_maxrate_", "")
        await query.message.edit_reply_markup(cpu_settings_menu(chat_id)); await query.answer(f"✅ Maxrate: {d['cpu_maxrate']}"); return
    if cb.startswith("cpu_tune_"):
        d['cpu_tune'] = cb.replace("cpu_tune_", "")
        await query.message.edit_reply_markup(cpu_settings_menu(chat_id)); await query.answer(f"✅ Tune: {d['cpu_tune']}"); return
    if cb.startswith("cpu_pix_"):
        d['cpu_pix_fmt'] = cb.replace("cpu_pix_", "")
        await query.message.edit_reply_markup(cpu_settings_menu(chat_id)); await query.answer(f"✅ Pix: {d['cpu_pix_fmt']}"); return

    # ── CPU H.265 setting callbacks ───────────────────────
    if cb.startswith("cpu265_preset_"):
        d['cpu265_preset'] = cb.replace("cpu265_preset_", "")
        await query.message.edit_reply_markup(cpu_settings_menu(chat_id)); await query.answer(f"✅ H.265 Preset: {d['cpu265_preset']}"); return
    if cb.startswith("cpu265_crf_"):
        d['cpu265_crf'] = cb.replace("cpu265_crf_", "")
        await query.message.edit_reply_markup(cpu_settings_menu(chat_id)); await query.answer(f"✅ H.265 CRF: {d['cpu265_crf']}"); return
    if cb.startswith("cpu265_res_"):
        d['cpu265_res'] = cb.replace("cpu265_res_", "")
        await query.message.edit_reply_markup(cpu_settings_menu(chat_id)); await query.answer(f"✅ H.265 Res: {d['cpu265_res']}"); return
    if cb.startswith("cpu265_threads_"):
        d['cpu265_threads'] = cb.replace("cpu265_threads_", "")
        await query.message.edit_reply_markup(cpu_settings_menu(chat_id)); await query.answer(f"✅ H.265 Threads: {d['cpu265_threads']}"); return
    if cb.startswith("cpu265_maxrate_"):
        d['cpu265_maxrate'] = cb.replace("cpu265_maxrate_", "")
        await query.message.edit_reply_markup(cpu_settings_menu(chat_id)); await query.answer(f"✅ H.265 Maxrate: {d['cpu265_maxrate']}"); return
    if cb.startswith("cpu265_tune_"):
        d['cpu265_tune'] = cb.replace("cpu265_tune_", "")
        await query.message.edit_reply_markup(cpu_settings_menu(chat_id)); await query.answer(f"✅ H.265 Tune: {d['cpu265_tune']}"); return
    if cb.startswith("cpu265_pix_"):
        d['cpu265_pix_fmt'] = cb.replace("cpu265_pix_", "")
        await query.message.edit_reply_markup(cpu_settings_menu(chat_id)); await query.answer(f"✅ H.265 Pix: {d['cpu265_pix_fmt']}"); return

    # ── Font ──────────────────────────────────────────────
    if cb.startswith("use_font_"):
        font_name = cb.replace("use_font_", "")
        d['font'] = font_name
        kb, text = fonts_menu(chat_id)
        await query.message.edit_text(text, reply_markup=kb)
        await query.answer(f"✅ Font: {font_name}"); return

    # ── Custom Input Prompts ──────────────────────────────
    if cb in CUSTOM_PROMPTS:
        field, side, label, hint = CUSTOM_PROMPTS[cb]
        d['custom_field']  = field
        d['custom_msg_id'] = query.message.id
        await query.message.reply_text(
            f"✏️ **{label}**\n📌 {hint}\nCurrent: `{d.get(field,'—')}`\n\nType karein ya /cancel_custom:"
        )
        await query.answer("✏️ Type karein!"); return

    # ── Clear Files ───────────────────────────────────────
    if cb == "cancel_files":
        for k in ['video','subtitle','original_fname','subtitle_ext']: d.pop(k, None)
        await query.message.edit_text("🗑️ Files cleared. Naya video bhejein.")
        await query.answer(); return

    # ── Add Single to Queue ───────────────────────────────
    if cb == "add_queue":
        if 'video' not in d or 'subtitle' not in d:
            await query.answer("❌ Video ya Subtitle missing!", show_alert=True); return
        task = _build_task(chat_id, d, d['video'], d['subtitle'],
                           d.get('original_fname','video.mkv'), is_batch=False)
        await task_queue.put(task)
        pos = task_queue.qsize()
        m   = task['mode']
        codec_disp = _codec_display(task)
        pw  = task.get('parallel_workers', 1)
        await query.message.edit_text(
            f"✅ **Queue mein add!** #{pos}\n"
            f"⚙️ {m.upper()} [{codec_disp}] | ⚡{pw}x\n"
            f"📁 `{task['original_fname']}`"
        )
        if not is_processing:
            asyncio.create_task(process_queue(client))
        await query.answer("🚀 Added!"); return

    # ── Keep Original Name ────────────────────────────────
    if cb == "keep_original_name":
        orig = d.get('_last_orig', d.get('original_fname', 'output.mkv'))
        if not orig.lower().endswith('.mkv'):
            orig = os.path.splitext(orig)[0] + '.mkv'
        await upload_final_video(client, chat_id, orig); return

    # ── Prompt Custom Rename ──────────────────────────────
    if cb == "prompt_rename":
        orig = d.get('_last_orig', 'output.mkv')
        await query.message.edit_text(
            f"✏️ **Custom Naam Type Karein**\n\n"
            f"📁 Original: `{orig}`\n"
            f"`.mkv` auto add hoga\n\n"
            f"Type karein ya `/cancel_custom`:"
        )
        await query.answer("✏️ Naam type karein!"); return

    # ── Rename callbacks ──────────────────────────────────
    if cb == "rename_encoded":
        if not d.get('temp_file') or not os.path.exists(d.get('temp_file','')):
            await query.answer("❌ File nahi mili!", show_alert=True); return
        d['status'] = 'waiting_rename'
        await query.message.edit_text(
            f"✏️ **Encoded File Rename**\n"
            f"📁 `{d.get('_last_orig', 'output.mkv')}`\n\n"
            f"Naya naam type karein (.mkv auto):"); return

    if cb == "rename_uploaded":
        if 'video' not in d:
            await query.answer("❌ Uploaded video nahi mili!", show_alert=True); return
        d['status'] = 'waiting_rename_fresh'
        await query.message.edit_text(
            f"✏️ **Upload Video Rename**\n"
            f"📺 `{d.get('original_fname','video.mkv')}`\n\n"
            f"Naya naam type karein (.mkv auto):\n/cancel_custom se cancel"); return

    if cb == "rename_cancel":
        await query.message.edit_text("↩️ Rename cancelled."); return

    # ── BATCH Rename Panel: Back to main list ─────────────
    if cb == "brp":
        d['batch']['rename_pending_idx']     = None
        d['batch']['rename_awaiting_custom'] = False
        videos = d['batch']['videos']
        panel_id = d['batch'].get('rename_panel_msg_id')
        if panel_id:
            try:
                await client.edit_message_text(
                    chat_id, panel_id,
                    _rename_panel_text(videos),
                    reply_markup=_rename_panel_kb(videos)
                )
            except Exception: pass
        await query.answer(); return

    # ── BATCH Rename Panel: File button tapped ────────────
    if cb.startswith("brfile_"):
        idx    = int(cb[7:])
        videos = d['batch']['videos']
        if idx >= len(videos): await query.answer("❌ Invalid!"); return
        d['batch']['rename_pending_idx']     = idx
        d['batch']['rename_awaiting_custom'] = False
        v = videos[idx]
        panel_id = d['batch'].get('rename_panel_msg_id')
        if panel_id:
            try:
                await client.edit_message_text(
                    chat_id, panel_id,
                    _rename_file_menu_text(idx, v),
                    reply_markup=_rename_file_menu_kb(idx)
                )
            except Exception: pass
        await query.answer(); return

    # ── BATCH Rename Panel: Original selected → confirm ───
    if cb.startswith("bro_"):
        idx    = int(cb[4:])
        videos = d['batch']['videos']
        if idx >= len(videos): await query.answer("❌ Invalid!"); return
        v = videos[idx]
        panel_id = d['batch'].get('rename_panel_msg_id')
        if panel_id:
            try:
                await client.edit_message_text(
                    chat_id, panel_id,
                    _rename_confirm_text(idx, v),
                    reply_markup=_rename_confirm_kb(idx)
                )
            except Exception: pass
        await query.answer(); return

    # ── BATCH Rename Panel: Original confirmed ─────────────
    if cb.startswith("broc_"):
        idx    = int(cb[5:])
        videos = d['batch']['videos']
        if idx >= len(videos): await query.answer("❌ Invalid!"); return
        videos[idx]['fname']          = videos[idx]['original_fname']
        videos[idx]['name_confirmed'] = True
        d['batch']['rename_pending_idx']     = None
        d['batch']['rename_awaiting_custom'] = False
        panel_id = d['batch'].get('rename_panel_msg_id')
        if panel_id:
            try:
                await client.edit_message_text(
                    chat_id, panel_id,
                    _rename_panel_text(videos),
                    reply_markup=_rename_panel_kb(videos)
                )
            except Exception: pass
        await query.answer("✅ Original naam set!"); return

    # ── BATCH Rename Panel: Custom naam prompt ─────────────
    if cb.startswith("brc_"):
        idx    = int(cb[4:])
        videos = d['batch']['videos']
        if idx >= len(videos): await query.answer("❌ Invalid!"); return
        d['batch']['rename_pending_idx']     = idx
        d['batch']['rename_awaiting_custom'] = True
        v = videos[idx]
        panel_id = d['batch'].get('rename_panel_msg_id')
        if panel_id:
            try:
                await client.edit_message_text(
                    chat_id, panel_id,
                    f"✏️ **Custom Naam — File {idx+1}**\n\n"
                    f"📁 Current: `{v['fname']}`\n"
                    f"Original: `{v['original_fname']}`\n\n"
                    f"Naya naam type karo (extension optional)\n"
                    f"`/cancel_custom` se cancel",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Back", callback_data=f"brfile_{idx}")
                    ]])
                )
            except Exception: pass
        await query.answer("✏️ Naam type karo!"); return

    # ── BATCH: Show file selector panel ───────────────────
    if cb == "batch_upload_subs":
        videos = d['batch']['videos']
        if not videos:
            await query.answer("❌ Koi video nahi!", show_alert=True); return
        text = (
            f"📋 **Subtitle Upload Panel**\n\n"
            f"{batch_summary_text(videos)}\n\n"
            f"💡 **Upload ke 2 tarike:**\n"
            f"1️⃣ **Reply method** — subtitle ko video message ka reply karo → auto-assign!\n"
            f"2️⃣ **Button method** — neeche file ka button dabao, phir sub bhejo\n\n"
            f"✏️ Galat sub? `/changesub <number>` ya `/changesub <filename>`\n"
            f"🛑 Cancel: `/cancel`"
        )
        sent = await query.message.edit_text(text, reply_markup=batch_file_selector_menu(chat_id))
        d['batch']['panel_msg_id'] = query.message.id
        await query.answer(); return

    # ── BATCH: Pick file for subtitle ─────────────────────
    if cb.startswith("batch_pick_"):
        idx = int(cb.replace("batch_pick_", ""))
        videos = d['batch']['videos']
        if idx >= len(videos):
            await query.answer("❌ Invalid file!"); return
        d['batch']['waiting_sub_for'] = idx
        fname   = videos[idx]['fname']
        has_sub = videos[idx]['subtitle'] is not None
        sub_note = "\n⚠️ Already has sub — naya bhejne se replace ho jaayega" if has_sub else ""
        await query.message.reply_text(
            f"📤 **File {idx+1} ke liye subtitle bhejo:**{sub_note}\n"
            f"📁 `{fname}`\n\n"
            f"SRT / ASS / VTT — koi bhi format chalega!\n"
            f"💡 Ya is video ka message dhundh ke usse **reply** karo sub se\n"
            f"🛑 Cancel: `/cancel`"
        )
        await query.answer(f"📂 File {idx+1} selected!"); return

    # ── BATCH: Add to queue ───────────────────────────────
    # ✅ FIX 2: Naam confirm check — sab original ya rename karo
    if cb == "batch_add_queue":
        videos = d['batch']['videos']
        ready  = [v for v in videos if v['subtitle']]
        if not ready:
            await query.answer("❌ Kisi video ka subtitle nahi!", show_alert=True); return

        # Check: kisi ka naam confirm nahi hua?
        unconfirmed = [v for v in ready if not v.get('name_confirmed')]
        if unconfirmed:
            await query.message.edit_text(
                f"📁 **Naam Confirm Karo**\n\n"
                f"⚠️ {len(unconfirmed)}/{len(ready)} files ka naam confirm nahi hua.\n\n"
                f"**Sab original naam use karo** ya pehle rename panel se naam set karo.",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ Sab Original Naam", callback_data="batch_confirm_original_all"),
                        InlineKeyboardButton("✏️ Naam Set Karo",     callback_data="batch_upload_subs"),
                    ],
                    [InlineKeyboardButton("❌ Cancel", callback_data="batch_cancel")],
                ])
            )
            await query.answer(); return

        # Sab confirmed — queue mein dalo
        added = 0
        for v in ready:
            task = _build_task(chat_id, d, v['msg'], v['subtitle'],
                               v['fname'], is_batch=True)
            await task_queue.put(task)
            added += 1
        d['batch']['videos'] = []
        d['batch']['waiting_sub_for'] = None
        d['batch']['panel_msg_id']    = None
        await query.message.edit_text(
            f"✅ **{added} video(s) queue mein add!**\n"
            f"⚡ Parallel: {d.get('parallel_workers',1)}x\n"
            f"Encoding shuru hogi shortly..."
        )
        if not is_processing:
            asyncio.create_task(process_queue(client))
        await query.answer(f"🚀 {added} tasks added!"); return

    # ── BATCH: Confirm all original names → queue ─────────
    # ✅ FIX 2: Sab unconfirmed ko original naam se confirm karke queue mein dalo
    if cb == "batch_confirm_original_all":
        videos = d['batch']['videos']
        ready  = [v for v in videos if v['subtitle']]
        for v in ready:
            if not v.get('name_confirmed'):
                v['fname']          = v['original_fname']
                v['name_confirmed'] = True
        added = 0
        for v in ready:
            task = _build_task(chat_id, d, v['msg'], v['subtitle'],
                               v['fname'], is_batch=True)
            await task_queue.put(task)
            added += 1
        d['batch']['videos'] = []
        d['batch']['waiting_sub_for'] = None
        d['batch']['panel_msg_id']    = None
        await query.message.edit_text(
            f"✅ **{added} video(s) queue mein add!**\n"
            f"⚡ Parallel: {d.get('parallel_workers',1)}x\n"
            f"Encoding shuru hogi shortly..."
        )
        if not is_processing:
            asyncio.create_task(process_queue(client))
        await query.answer(f"🚀 {added} tasks added!"); return

    # ── BATCH: Cancel ─────────────────────────────────────
    if cb == "batch_cancel":
        d['batch']['active']               = False
        d['batch']['videos']               = []
        d['batch']['waiting_sub_for']      = None
        d['batch']['panel_msg_id']         = None
        d['batch']['rename_panel_msg_id']  = None
        d['batch']['rename_pending_idx']   = None
        d['batch']['rename_awaiting_custom'] = False
        await query.message.edit_text("🗑️ Batch cancelled. `/hsubm` se dobara start karo.")
        await query.answer(); return

# ════════════════════════════════════════════════════════════
# 🛠️  TASK BUILDER HELPER
# ════════════════════════════════════════════════════════════
def _build_task(chat_id, d, video_msg, subtitle_msg, original_fname, is_batch=False) -> dict:
    return {
        'task_id'        : next_tid(),
        'chat_id'        : chat_id,
        'video'          : video_msg,
        'subtitle'       : subtitle_msg,
        'original_fname' : original_fname,
        'font'           : d.get('font', 'Arial'),
        'mode'           : d.get('mode', 'gpu'),
        'is_batch'       : is_batch,
        'parallel_workers': d.get('parallel_workers', 1),
        # GPU H.264
        'gpu_codec'     : d.get('gpu_codec', 'h264'),
        'gpu_preset'    : d.get('gpu_preset', 'p4'),
        'gpu_cq'        : d.get('gpu_cq', '21'),
        'gpu_res'       : d.get('gpu_res', 'original'),
        'gpu_threads'   : d.get('gpu_threads', 'auto'),
        'gpu_maxrate'   : d.get('gpu_maxrate', 'none'),
        'gpu_tune'      : d.get('gpu_tune', 'none'),
        'gpu_pix_fmt'   : d.get('gpu_pix_fmt', 'yuv420p'),
        # GPU H.265
        'gpu265_preset' : d.get('gpu265_preset', 'p4'),
        'gpu265_cq'     : d.get('gpu265_cq', '24'),
        'gpu265_res'    : d.get('gpu265_res', 'original'),
        'gpu265_threads': d.get('gpu265_threads', 'auto'),
        'gpu265_maxrate': d.get('gpu265_maxrate', 'none'),
        'gpu265_tune'   : d.get('gpu265_tune', 'none'),
        'gpu265_pix_fmt': d.get('gpu265_pix_fmt', 'yuv420p'),
        # CPU H.264
        'cpu_codec'     : d.get('cpu_codec', 'h264'),
        'cpu_preset'    : d.get('cpu_preset', 'faster'),
        'cpu_crf'       : d.get('cpu_crf', '23'),
        'cpu_res'       : d.get('cpu_res', 'original'),
        'cpu_threads'   : d.get('cpu_threads', 'auto'),
        'cpu_maxrate'   : d.get('cpu_maxrate', 'none'),
        'cpu_tune'      : d.get('cpu_tune', 'none'),
        'cpu_pix_fmt'   : d.get('cpu_pix_fmt', 'yuv420p'),
        # CPU H.265
        'cpu265_preset' : d.get('cpu265_preset', 'faster'),
        'cpu265_crf'    : d.get('cpu265_crf', '28'),
        'cpu265_res'    : d.get('cpu265_res', 'original'),
        'cpu265_threads': d.get('cpu265_threads', 'auto'),
        'cpu265_maxrate': d.get('cpu265_maxrate', 'none'),
        'cpu265_tune'   : d.get('cpu265_tune', 'none'),
        'cpu265_pix_fmt': d.get('cpu265_pix_fmt', 'yuv420p'),
    }

def _codec_display(task: dict) -> str:
    m = task['mode']
    if m == 'gpu':
        return "H.265 HEVC" if task.get('gpu_codec') == 'h265' else "H.264"
    return "H.265 x265" if task.get('cpu_codec') == 'h265' else "H.264 x264"

# ════════════════════════════════════════════════════════════
# ⚙️  SINGLE TASK ENCODER
# ════════════════════════════════════════════════════════════
async def encode_single_task(client, task):
    global current_proc, active_tasks
    active_tasks += 1
    chat_id    = task['chat_id']
    task_id    = task['task_id']
    is_batch   = task.get('is_batch', False)
    codec_disp = _codec_display(task)
    mode       = task['mode']
    out_path   = f"downloads/out_{chat_id}_{task_id}.mkv"
    v_path = s_raw = ass_tmp = None
    keep_out = False

    status_msg = await client.send_message(
        chat_id,
        f"🔥 **Encoding Initializing...**\n"
        f"📁 `{task.get('original_fname','video.mkv')}`\n⏳ Downloading resources..."
    )

    try:
        v_path = await task['video'].download(
            file_name=f"downloads/v_{chat_id}_{task_id}.tmp"
        )
        
        # Audio Probing and Selection
        audio_streams = _get_audio_streams(v_path)
        keep_audios = list(range(len(audio_streams)))

        if len(audio_streams) > 1 and not is_batch:
            ev = asyncio.Event()
            pending_audios[task_id] = {'event': ev, 'streams': audio_streams, 'deleted': set()}
            kb = _build_audio_kb(task_id)
            aud_msg = await client.send_message(
                chat_id,
                "🎵 **There are multiple audios available.**\nIf you want to delete, click on that button. List will auto update.",
                reply_markup=kb
            )
            await ev.wait()
            
            deleted = pending_audios[task_id]['deleted']
            keep_audios = [i for i in range(len(audio_streams)) if i not in deleted]
            task['keep_audios'] = keep_audios
            
            try:
                await aud_msg.delete()
            except:
                pass
            if task_id in pending_audios: del pending_audios[task_id]
        elif len(audio_streams) > 0:
            task['keep_audios'] = keep_audios

        # Subtitle Handling
        if task.get('subtitle'):
            sub_doc   = task['subtitle'].document
            sub_fname = (sub_doc.file_name if sub_doc else None) or "sub.srt"
            sub_ext   = os.path.splitext(sub_fname)[1].lower()
            s_raw     = await task['subtitle'].download(
                file_name=f"downloads/s_{chat_id}_{task_id}{sub_ext}"
            )
        else:
            s_raw = None

        cmd, ass_tmp = build_ffmpeg_cmd(task, v_path, s_raw, out_path)
        proc = await asyncio.create_subprocess_exec(*cmd)
        if not is_batch:
            current_proc = proc

        timer = 0
        while proc.returncode is None:
            await asyncio.sleep(8); timer += 8
            mins, secs = divmod(timer, 60)
            try:
                await status_msg.edit_text(
                    f"🔥 **Encoding** {'📦' if is_batch else '🎬'} "
                    f"[{mode.upper()} · {codec_disp}]\n"
                    f"📁 `{task.get('original_fname','')}` | "
                    f"⏳ {mins:02d}:{secs:02d} | /cancel"
                )
            except: pass

        mins, secs = divmod(timer, 60)

        if proc.returncode == 0:
            orig = task.get('original_fname', f'output_{task_id}.mkv')
            if not orig.lower().endswith('.mkv'):
                orig = os.path.splitext(orig)[0] + '.mkv'

            if is_batch:
                await status_msg.edit_text(
                    f"✅ **Done!** ({mins:02d}:{secs:02d}) [{codec_disp}]\n"
                    f"📦 Batch | 📁 `{orig}`\n☁️ Uploading..."
                )
                await client.send_document(chat_id, out_path,
                    caption=f"**{orig}**", file_name=orig)
                await status_msg.delete()
            else:
                dl = get_data(chat_id)
                dl['status']     = 'waiting_rename'
                dl['temp_file']  = out_path
                dl['_last_orig'] = orig
                keep_out = True
                if not is_batch: current_proc = None
                await status_msg.edit_text(
                    f"✅ **Done!** ({mins:02d}:{secs:02d}) [{codec_disp}]\n\n"
                    f"📁 Original: `{orig}`\n"
                    f"📝 Naam choose karein:",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("📁 Original", callback_data="keep_original_name"),
                        InlineKeyboardButton("✏️ Custom Naam", callback_data="prompt_rename"),
                    ]])
                )
        else:
            await status_msg.edit_text(
                f"❌ **FFmpeg Failed!** (Task #{task_id})\n"
                f"Logs check karein. /cancel"
            )

    except Exception as e:
        try: await status_msg.edit_text(f"❌ **Error:** `{e}`")
        except: await client.send_message(chat_id, f"❌ **Error:** `{e}`")
    finally:
        active_tasks -= 1
        if not is_batch: current_proc = None
        cleanup = [v_path, s_raw, ass_tmp]
        if not keep_out: cleanup.append(out_path)
        for fp in cleanup:
            if fp and os.path.exists(fp):
                try: os.remove(fp)
                except: pass
        task_queue.task_done()

# ════════════════════════════════════════════════════════════
# ⚙️  QUEUE PROCESSOR — Parallel support
# ════════════════════════════════════════════════════════════
async def process_queue(client):
    global is_processing
    is_processing = True
    running: set = set()

    while not task_queue.empty() or running:
        running = {t for t in running if not t.done()}

        if task_queue.empty():
            if running: await asyncio.sleep(0.5)
            continue

        task = await task_queue.get()
        pw   = task.get('parallel_workers', 1)

        while len(running) >= pw:
            await asyncio.sleep(0.5)
            running = {t for t in running if not t.done()}

        t = asyncio.create_task(encode_single_task(client, task))
        running.add(t)

    if running:
        await asyncio.gather(*running, return_exceptions=True)

    is_processing = False

# ════════════════════════════════════════════════════════════
# ☁️  UPLOAD FINAL (Single mode rename + upload)
# ════════════════════════════════════════════════════════════
async def upload_final_video(client, chat_id: int, final_name: str):
    d    = get_data(chat_id)
    temp = d.get('temp_file')
    if not temp or not os.path.exists(temp):
        await client.send_message(chat_id, "❌ Encoded file nahi mila!"); return
    try:
        os.rename(temp, final_name)
        prog = await client.send_message(chat_id, f"☁️ Uploading `{final_name}`...")
        await client.send_document(chat_id, final_name,
            caption=f"**{final_name}**", file_name=final_name)
        await prog.delete()
        if os.path.exists(final_name): os.remove(final_name)
    except Exception as e:
        await client.send_message(chat_id, f"❌ Upload error: `{e}`")
    finally:
        d['status'] = 'idle'
        for k in ['video','subtitle','temp_file','original_fname','subtitle_ext','_last_orig']:
            d.pop(k, None)

# ════════════════════════════════════════════════════════════
# 🚀  LAUNCH
# ════════════════════════════════════════════════════════════
async def start_bot():
    try:
        await app.start()
        print(f"🚀 BOT IS LIVE — {ENV_NAME}")
        from pyrogram import idle
        await idle()
    except Exception as e:
        print(f"❌ Launch error: {e}")
    finally:
        await app.stop()

try:
    asyncio.get_event_loop().run_until_complete(start_bot())
except:
    pass
