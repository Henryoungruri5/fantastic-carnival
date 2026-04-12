
import os, json, asyncio, time, sys
from pyrogram import Client

payload = json.loads(os.environ.get("PAYLOAD", "{}"))
app = Client("worker", api_id=int(os.environ.get("API_ID")), api_hash=os.environ.get("API_HASH"), bot_token=os.environ.get("BOT_TOKEN"))

last_edit_time = 0

def make_progress_bar(current, total):
    percent = current * 100 / total
    filled = int(percent / 5)
    bar = '█' * filled + '░' * (20 - filled)
    return f"[{bar}] {percent:.1f}%"

async def prog_cb(current, total, msg, action):
    global last_edit_time
    if time.time() - last_edit_time > 3:
        try:
            curr_mb = current / (1024 * 1024)
            tot_mb = total / (1024 * 1024)
            text = f"☁️ **{action}**\n{make_progress_bar(current, total)}\n{curr_mb:.1f} MB / {tot_mb:.1f} MB"
            await msg.edit_text(text)
            last_edit_time = time.time()
        except: pass

async def main():
    await app.start()
    chat_id = payload['chat_id']
    vid_id = payload['video_id']
    sub_id = payload['sub_id']
    orig_name = payload['file_name']
    font = payload['font']
    st = payload['settings']
    
    status_msg = await app.send_message(chat_id, "☁️ **GitHub Runner Started!**\nPreparing to download...")
    
    async def dl_prog(c, t): await prog_cb(c, t, status_msg, "Downloading Video...")
    v_path = await app.download_media(vid_id, file_name="vid.tmp", progress=dl_prog)
    
    s_path = None
    if sub_id:
        async def sub_prog(c, t): await prog_cb(c, t, status_msg, "Downloading Subtitle...")
        s_path = await app.download_media(sub_id, file_name="sub.srt", progress=sub_prog)
        
    out_path = f"out_{orig_name}"
    
    cmd = ['ffmpeg', '-y']
    if st['threads'] != 'auto': cmd.extend(['-threads', str(st['threads'])])
    cmd.extend(['-i', v_path])
    
    vf = ""
    res_map = {'1080p': '1920:1080', '720p': '1280:720', '480p': '854:480', '360p': '640:360', '144p': '256:144'}
    res = res_map.get(st['res'])
    if res: vf += f"scale={res},"
    if s_path: vf += f"subtitles={s_path}:force_style='Fontname={font}'"
    vf = vf.rstrip(',')
    if vf: cmd.extend(['-vf', vf])
    
    cmd.extend(['-c:v', st['codec'], '-preset', st['preset'], '-crf', str(st['crf']), '-pix_fmt', st['pix_fmt']])
    
    if st['maxrate'] != 'none':
        try:
            num = float(st['maxrate'].replace('M', '').replace('K', '').replace('m', '').replace('k', ''))
            unit = st['maxrate'][-1].upper()
            buf = f"{int(num*2)}{unit}"
            cmd.extend(['-maxrate', st['maxrate'].upper(), '-bufsize', buf])
        except: pass
        
    if st['tune'] != 'none':
        if st['codec'] == 'libx265': cmd.extend(['-x265-params', f"tune={st['tune']}"])
        else: cmd.extend(['-tune', st['tune']])
        
    cmd.extend(['-c:a', 'copy', out_path])
    
    codec_name = "H.265" if st['codec'] == "libx265" else "H.264"
    await status_msg.edit_text(f"🔥 **Encoding on Cloud...**\nCodec: {codec_name} | Preset: {st['preset']} | CRF: {st['crf']}")
    
    process = await asyncio.create_subprocess_exec(*cmd)
    await process.communicate()
    
    if os.path.exists(out_path):
        async def ul_prog(c, t): await prog_cb(c, t, status_msg, "Uploading Encoded Video...")
        await app.send_document(chat_id, out_path, caption=f"✅ Cloud Encoded: {orig_name}", progress=ul_prog)
        await status_msg.delete()
    else:
        await status_msg.edit_text("❌ Encoding Failed on GitHub!")
        
    await app.stop()
    sys.exit(0)

asyncio.run(main())
    