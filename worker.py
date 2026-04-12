
import os, json, asyncio, subprocess
from pyrogram import Client

payload = json.loads(os.environ.get("PAYLOAD", "{}"))
app = Client("worker", api_id=int(os.environ.get("API_ID")), api_hash=os.environ.get("API_HASH"), bot_token=os.environ.get("BOT_TOKEN"))

async def main():
    await app.start()
    chat_id = payload['chat_id']
    vid_id = payload['video_id']
    sub_id = payload['sub_id']
    orig_name = payload['file_name']
    font = payload['font']
    st = payload['settings']
    
    await app.send_message(chat_id, f"☁️ **GitHub Runner Started!**\nDownloading `{orig_name}`...")
    
    v_path = await app.download_media(vid_id, file_name="vid.tmp")
    s_path = await app.download_media(sub_id, file_name="sub.srt") if sub_id else None
    out_path = f"out_{orig_name}"
    
    cmd = ['ffmpeg', '-y']
    if st['threads'] != 'auto':
        cmd.extend(['-threads', str(st['threads'])])
    
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
    await app.send_message(chat_id, f"🔥 **Encoding on Cloud...**\nCodec: {codec_name} | Preset: {st['preset']} | CRF: {st['crf']}")
    subprocess.run(cmd)
    
    if os.path.exists(out_path):
        await app.send_document(chat_id, out_path, caption=f"✅ Cloud Encoded: {orig_name}")
    else:
        await app.send_message(chat_id, "❌ Encoding Failed on GitHub!")
        
    await app.stop()

asyncio.run(main())
    