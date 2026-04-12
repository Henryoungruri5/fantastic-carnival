
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
    settings = payload['settings']
    
    await app.send_message(chat_id, f"☁️ **GitHub Runner Started!**\nDownloading `{orig_name}`...")
    
    v_path = await app.download_media(vid_id, file_name="vid.tmp")
    s_path = await app.download_media(sub_id, file_name="sub.srt") if sub_id else None
    
    out_path = f"out_{orig_name}"
    cmd = ['ffmpeg', '-y', '-i', v_path]
    
    if s_path:
        cmd.extend(['-vf', f"subtitles={s_path}:force_style='Fontname={font}'"])
        
    cmd.extend([
        '-c:v', 'libx264', '-preset', settings['preset'], '-crf', settings['crf'],
        '-c:a', 'copy', out_path
    ])
    
    await app.send_message(chat_id, f"🔥 **Encoding on GitHub...**\nPreset: {settings['preset']} | CRF: {settings['crf']}")
    subprocess.run(cmd)
    
    if os.path.exists(out_path):
        await app.send_document(chat_id, out_path, caption=f"✅ Cloud Encoded: {orig_name}")
    else:
        await app.send_message(chat_id, "❌ Encoding Failed on GitHub!")
        
    await app.stop()

asyncio.run(main())
    