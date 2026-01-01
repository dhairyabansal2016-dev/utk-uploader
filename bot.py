import os
import requests
import logging
from flask import Flask
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# --- FLASK HEARTBEAT SECTION ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is Online"

def run_flask():
    # Render automatically provides the PORT environment variable
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

# --- BOT LOGIC SECTION ---
# Use Env Var for token, fallback to your hardcoded one for now
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8420197585:AAFMuzgaetEsUA9zo2FQlOKZlY2E5__gYMo")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class SelectionWayBot:
    def __init__(self):
        self.base_headers = {
            "sec-ch-ua-platform": "\"Windows\"",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
            "content-type": "application/json",
            "accept": "*/*",
            "origin": "https://www.selectionway.com",
            "referer": "https://www.selectionway.com/",
            "accept-language": "en-US,en;q=0.9",
        }
        self.user_sessions = {}

    def clean_url(self, url):
        if not url: return ""
        return url.replace(" ", "%")

    async def get_all_batches(self):
        courses_url = "https://backend.multistreaming.site/api/courses/active?userId=1448640"
        try:
            response = requests.get(courses_url, headers=self.base_headers)
            response.raise_for_status()
            data = response.json()
            return (True, data["data"]) if data.get("state") == 200 else (False, "Failed to get batches")
        except Exception as e:
            return False, str(e)

    async def login_user(self, email, password, user_id):
        login_url = "https://selectionway.hranker.com/admin/api/user-login"
        login_data = {
            "email": email, "password": password,
            "mobile": "", "otp": "", "logged_in_via": "web", "customer_id": 561
        }
        try:
            session = requests.Session()
            response = session.post(login_url, headers=self.base_headers, json=login_data)
            res = response.json()
            if res.get("state") == 200:
                self.user_sessions[user_id] = {
                    'user_id': res["data"]["user_id"],
                    'token': res["data"]["token_id"],
                    'session': session
                }
                return True, "✅ Login successful!"
            return False, "❌ Invalid credentials"
        except Exception as e:
            return False, f"❌ Error: {str(e)}"

    async def get_my_batches(self, user_id):
        if user_id not in self.user_sessions: return False, "Please login first"
        user_data = self.user_sessions[user_id]
        url = "https://backend.multistreaming.site/api/courses/my-courses"
        try:
            response = user_data['session'].post(url, headers=self.base_headers, json={"userId": str(user_data['user_id'])})
            res = response.json()
            return (True, res["data"]) if res.get("state") == "200" else (False, "Failed to get courses")
        except Exception as e:
            return False, str(e)

    async def extract_course_data_without_login(self, course_id, course_name):
        url = f"https://backend.multistreaming.site/api/courses/{course_id}/classes?populate=full"
        try:
            response = requests.get(url, headers=self.base_headers)
            res = response.json()
            if res.get("state") == 200:
                return True, {"classes_data": res["data"], "pdf_url": "", "course_details": {"title": course_name}}
            return False, "Failed to get data"
        except Exception as e:
            return False, str(e)

    def extract_all_data(self, classes_data, pdf_url, course_details):
        video_links = []
        pdf_links = [f"Batch Info PDF : {pdf_url}"] if pdf_url else []
        if classes_data and "classes" in classes_data:
            for topic in classes_data["classes"]:
                for item in topic.get("classes", []):
                    title = item.get("title", "Video")
                    best_url = item.get("class_link", "")
                    recs = item.get("mp4Recordings", [])
                    qualities = ["720p", "480p", "360p"]
                    for q in qualities:
                        for r in recs:
                            if r.get("quality") == q:
                                best_url = r.get("url")
                                title = f"{title} ({q})"
                                break
                        if "720p" in title or "480p" in title: break
                    if best_url: video_links.append(f"{title} : {best_url}")
        return video_links, pdf_links

    def create_file(self, name, videos, pdfs):
        filename = f"{name.replace(' ', '_')}.txt"
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"🎯 {name}\n\n📄 PDFs:\n" + "\n".join(pdfs) + "\n\n🎥 VIDEOS:\n" + "\n".join(videos))
        return filename

bot = SelectionWayBot()

# --- HANDLERS ---
async def start(update, context):
    keyboard = [[InlineKeyboardButton("🔐 Login & Extract", callback_data="login_extract")],
                [InlineKeyboardButton("📚 List All Batches", callback_data="list_batches")]]
    await update.message.reply_text("🤖 *SelectionWay Extractor Bot*", 
                                  reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def button_handler(update, context):
    query = update.callback_query
    await query.answer()
    if query.data == "login_extract":
        context.user_data['awaiting_login'] = True
        await query.edit_message_text("🔐 Send credentials as `email:password`", parse_mode='Markdown')
    elif query.data == "list_batches":
        success, result = await bot.get_all_batches()
        if success:
            msg = "📚 *Available Batches*\n\n"
            batch_list = []
            for i, c in enumerate(result[:20], 1): # Limit to 20 for message length
                msg += f"{i}. {c.get('title')}\nID: `{c.get('id')}`\n\n"
                batch_list.append(c)
            context.user_data.update({'all_batches': batch_list, 'awaiting_batch_id': True})
            await query.edit_message_text(msg + "👉 Send *Batch ID* to extract", parse_mode='Markdown')

async def handle_message(update, context):
    text = update.message.text
    uid = update.message.from_user.id
    
    if context.user_data.get('awaiting_login'):
        if ":" in text:
            email, pw = text.split(":", 1)
            success, msg = await bot.login_user(email.strip(), pw.strip(), uid)
            if success:
                context.user_data['awaiting_login'] = False
                # Fetch user batches
                s, my_b = await bot.get_my_batches(uid)
                if s:
                    res_msg = "✅ Your Batches:\n\n"
                    b_list = []
                    # Simple flattening for my_batches
                    for group in my_b:
                        for c in group.get("liveCourses", []) + group.get("recordedCourses", []):
                            b_list.append(c)
                            res_msg += f"{len(b_list)}. {c.get('title')}\n"
                    context.user_data.update({'my_batches': b_list, 'awaiting_batch_selection': True})
                    await update.message.reply_text(res_msg + "👉 Reply with Batch Number")
            else: await update.message.reply_text(msg)

    elif context.user_data.get('awaiting_batch_id'):
        bid = text.strip()
        await update.message.reply_text("🔄 Extracting...")
        s, res = await bot.extract_course_data_without_login(bid, "Extracted Course")
        if s:
            v, p = bot.extract_all_data(res["classes_data"], res["pdf_url"], res["course_details"])
            fname = bot.create_file("Course", v, p)
            with open(fname, 'rb') as f:
                await update.message.reply_document(f, caption=f"✅ Extracted {len(v)} videos")
            os.remove(fname)

def main():
    keep_alive() # Start Flask
    app_tg = Application.builder().token(BOT_TOKEN).build()
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(CallbackQueryHandler(button_handler))
    app_tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🤖 Bot is running...")
    app_tg.run_polling()

if __name__ == '__main__':
    main()
