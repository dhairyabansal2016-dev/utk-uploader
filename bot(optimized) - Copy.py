import os, re, requests, yt_dlp, asyncio, time, shutil, json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler

# --- CONFIGURATION ---
BOT_TOKEN = os.getenv("BOT_TOKEN") 
GET_FILE, GET_QUALITY, GET_NAME = range(3)
DB_FILE = "resume_data.json"

# --- HEALTH CHECK SERVER (For UptimeRobot) ---
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"ALIVE")

def run_server():
    port = int(os.getenv("PORT", 8080))
    HTTPServer(('0.0.0.0', port), HealthHandler).serve_forever()

# --- DATABASE & PARSER ---
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r') as f: return json.load(f)
        except: return {}
    return {}

def save_db(f_name, idx, h_id=None):
    db = load_db()
    db[f_name] = {"idx": idx, "h_id": h_id or db.get(f_name, {}).get("h_id")}
    with open(DB_FILE, 'w') as f: json.dump(db, f)

def parse_txt(path):
    out, curr = [], "General"
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line: continue
            tm = re.match(r"^\[(.*?)\]", line)
            if tm: curr = tm.group(1); line = line[tm.end():].strip()
            if " : " in line:
                p = line.split(" : ", 1)
                out.append({"topic": curr, "title": p[0].strip(), "url": p[1].strip()})
    return out

# --- CONVERSATION FLOW ---
async def start_upload(u, c):
    await u.message.reply_text("📂 **UPLOAD TXT FILE:**")
    return GET_FILE

async def receive_file(u, c):
    doc = u.message.document
    if not doc.file_name.endswith(".txt"):
        await u.message.reply_text("❌ Send a .txt file!"); return GET_FILE
    c.user_data['f_id'], c.user_data['f_name'] = doc.file_id, doc.file_name
    kb = [[InlineKeyboardButton("480p", callback_data='480'), InlineKeyboardButton("720p", callback_data='720')]]
    await u.message.reply_text("🎬 **QUALITY:**", reply_markup=InlineKeyboardMarkup(kb))
    return GET_QUALITY

async def receive_quality(u, c):
    q = u.callback_query; await q.answer(); c.user_data['q'] = q.data
    await q.edit_message_text(f"✅ {q.data}p selected.\n👤 **ENTER EXTRACTOR NAME:**")
    return GET_NAME

async def receive_name(u, c):
    ex_name = u.message.text
    qual, f_name = c.user_data['q'], c.user_data['f_name']
    batch = f_name.replace(".txt", "")
    
    file = await c.bot.get_file(c.user_data['f_id'])
    await file.download_to_drive(f_name)
    content = parse_txt(f_name)
    
    db = load_db().get(f_name, {"idx": 0, "h_id": None})
    last_idx, h_id = db["idx"], db["h_id"]

    if not h_id:
        msg = await c.bot.send_message(u.effective_chat.id, f"📦 **BATCH: {batch}**\n👤 By: {ex_name}\n🎬 Qual: {qual}p\n📊 Total: {len(content)}")
        h_id = msg.message_id
        try: await c.bot.pin_chat_message(u.effective_chat.id, h_id)
        except: pass
        save_db(f_name, 0, h_id)

    status = await u.message.reply_text("🚀 Starting sequence...")
    
    for i, item in enumerate(content, 1):
        if i <= last_idx: continue
        if i % 20 == 0: await asyncio.sleep(30) # Flood Protection

        try:
            work_dir = os.path.abspath("work")
            if os.path.exists(work_dir): shutil.rmtree(work_dir)
            os.makedirs(work_dir, exist_ok=True)
            v_path, t_path = os.path.join(work_dir, "v.mp4"), os.path.join(work_dir, "t.jpg")
            
            # Download
            with yt_dlp.YoutubeDL({'format': f'bestvideo[height<={qual}]+bestaudio/best', 'outtmpl': v_path, 'quiet': True}) as ydl:
                ydl.download([item['url']])
            
            # Thumbnail
            os.system(f'ffmpeg -i "{v_path}" -ss 00:00:05 -vframes 1 "{t_path}" -y -loglevel quiet')
            
            # Upload
            cap = f"Index: {i}\nTitle: {item['title']}\nTopic: {item['topic']}\nBatch: {batch}"
            with open(v_path, 'rb') as video_file, open(t_path, 'rb') as thumb_file:
                await c.bot.send_video(u.effective_chat.id, video=video_file, thumbnail=thumb_file, caption=cap, supports_streaming=True, write_timeout=120)
            
            save_db(f_name, i)
            await status.edit_text(f"✅ Progress: {i}/{len(content)}")
        except Exception as e:
            await u.message.reply_text(f"⚠️ Skip {i}: {str(e)[:100]}")

    await c.bot.edit_message_text(f"📂 **BATCH: {batch}**", u.effective_chat.id, h_id)
    await u.message.reply_text("🏁 **BATCH COMPLETED SUCCESSFULLY!**")
    return ConversationHandler.END

# --- MAIN ---
if __name__ == '__main__':
    Thread(target=run_server, daemon=True).start()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("upload", start_upload)],
        states={GET_FILE: [MessageHandler(filters.Document.ALL, receive_file)],
                GET_QUALITY: [CallbackQueryHandler(receive_quality)],
                GET_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_name)]},
        fallbacks=[CommandHandler("cancel", lambda u,c: ConversationHandler.END)]
    ))
    app.run_polling()