"""
Minimal bilingual (Arabic / English) message catalogue.

Usage:
    t("welcome", lang, name="Ali")
"""

from __future__ import annotations

TEXTS: dict[str, dict[str, str]] = {
    "welcome": {
        "en": (
            "👋 Welcome, <b>{name}</b>!\n\n"
            "I turn your text descriptions into short AI‑generated videos.\n\n"
            "• /generate — create a new video\n"
            "• /status — check your current job\n"
            "• /cancel — cancel the current job\n"
            "• /lang — switch language\n"
            "• /help — detailed help\n\n"
            "Limit: <b>{limit}</b> videos per hour."
        ),
        "ar": (
            "👋 أهلاً بك، <b>{name}</b>!\n\n"
            "أحوّل وصفك النصي إلى فيديو قصير مولّد بالذكاء الاصطناعي.\n\n"
            "• /generate — إنشاء فيديو جديد\n"
            "• /status — حالة طلبك الحالي\n"
            "• /cancel — إلغاء الطلب الحالي\n"
            "• /lang — تغيير اللغة\n"
            "• /help — شرح مفصّل\n\n"
            "الحد: <b>{limit}</b> فيديوهات في الساعة."
        ),
    },
    "help": {
        "en": (
            "📖 <b>How it works</b>\n\n"
            "1️⃣ Send /generate\n"
            "2️⃣ Describe the scene in detail (5–{max_len} characters). Example:\n"
            "<i>A golden retriever running through autumn leaves, cinematic lighting, slow motion</i>\n"
            "3️⃣ Choose aspect ratio, duration and style\n"
            "4️⃣ Wait — rendering usually takes 1–5 minutes\n\n"
            "💡 <b>Tips</b>: mention camera movement, lighting, mood and subject.\n"
            "⚠️ Prohibited: violent, sexual or hateful content.\n\n"
            "Providers: {providers}"
        ),
        "ar": (
            "📖 <b>طريقة الاستخدام</b>\n\n"
            "1️⃣ أرسل /generate\n"
            "2️⃣ صف المشهد بالتفصيل (5–{max_len} حرف). مثال:\n"
            "<i>كلب ذهبي يركض بين أوراق الخريف، إضاءة سينمائية، حركة بطيئة</i>\n"
            "3️⃣ اختر نسبة الأبعاد والمدة والنمط\n"
            "4️⃣ انتظر — التوليد يستغرق عادةً من دقيقة إلى 5 دقائق\n\n"
            "💡 <b>نصائح</b>: اذكر حركة الكاميرا، الإضاءة، الجو العام والموضوع.\n"
            "⚠️ ممنوع: المحتوى العنيف أو الجنسي أو المسيء.\n\n"
            "المزوّدون: {providers}"
        ),
    },
    "ask_prompt": {
        "en": "✍️ Send me a description of the video you want (or /cancel to abort):",
        "ar": "✍️ أرسل لي وصف الفيديو الذي تريده (أو /cancel للإلغاء):",
    },
    "ask_aspect": {
        "en": "📐 Choose the aspect ratio:",
        "ar": "📐 اختر نسبة الأبعاد:",
    },
    "ask_duration": {
        "en": "⏱ Choose the duration:",
        "ar": "⏱ اختر مدة الفيديو:",
    },
    "ask_style": {
        "en": "🎨 Choose an artistic style:",
        "ar": "🎨 اختر النمط الفني:",
    },
    "confirm": {
        "en": (
            "🔎 <b>Review your request</b>\n\n"
            "📝 Prompt: <i>{prompt}</i>\n"
            "📐 Aspect: {aspect}\n"
            "⏱ Duration: {duration}s\n"
            "🎨 Style: {style}\n\n"
            "Start generation?"
        ),
        "ar": (
            "🔎 <b>راجع طلبك</b>\n\n"
            "📝 الوصف: <i>{prompt}</i>\n"
            "📐 الأبعاد: {aspect}\n"
            "⏱ المدة: {duration} ثانية\n"
            "🎨 النمط: {style}\n\n"
            "هل نبدأ التوليد؟"
        ),
    },
    "queued": {
        "en": "✅ Job <b>#{job_id}</b> queued (position {pos}). I'll notify you when it's ready.",
        "ar": "✅ تمت إضافة الطلب <b>#{job_id}</b> إلى الطابور (الترتيب {pos}). سأخبرك عند الجاهزية.",
    },
    "started": {
        "en": "🎬 Job <b>#{job_id}</b> is now rendering… this may take a few minutes.",
        "ar": "🎬 بدأ توليد الطلب <b>#{job_id}</b>… قد يستغرق بضع دقائق.",
    },
    "fallback": {
        "en": "🔁 Primary provider failed, retrying with <b>{provider}</b>…",
        "ar": "🔁 فشل المزوّد الأساسي، أعيد المحاولة عبر <b>{provider}</b>…",
    },
    "done_caption": {
        "en": "🎥 <b>Your video is ready!</b>\n\n📝 {prompt}\n📐 {aspect} • ⏱ {duration}s • 🎨 {style}\n⚙️ {provider}",
        "ar": "🎥 <b>فيديوك جاهز!</b>\n\n📝 {prompt}\n📐 {aspect} • ⏱ {duration} ث • 🎨 {style}\n⚙️ {provider}",
    },
    "done_link": {
        "en": "📎 The file is too large for Telegram upload, download it here:\n{url}",
        "ar": "📎 الملف أكبر من حد الرفع في تيليغرام، حمّله من هنا:\n{url}",
    },
    "failed": {
        "en": "❌ Sorry, job <b>#{job_id}</b> failed on all providers.\n<code>{error}</code>\n\nYour quota was not consumed — try again with a different prompt.",
        "ar": "❌ عذراً، فشل الطلب <b>#{job_id}</b> لدى جميع المزوّدين.\n<code>{error}</code>\n\nلم يُحتسب من حصتك — جرّب مجدداً بوصف مختلف.",
    },
    "status_none": {
        "en": "ℹ️ You have no active job. Use /generate to start one.",
        "ar": "ℹ️ لا يوجد لديك طلب نشط. استخدم /generate للبدء.",
    },
    "status": {
        "en": (
            "📊 <b>Job #{job_id}</b>\n"
            "Status: <b>{status}</b>\n"
            "Prompt: <i>{prompt}</i>\n"
            "Provider: {provider}\n"
            "Elapsed: {elapsed}s\n"
            "Queue size: {queue}"
        ),
        "ar": (
            "📊 <b>الطلب #{job_id}</b>\n"
            "الحالة: <b>{status}</b>\n"
            "الوصف: <i>{prompt}</i>\n"
            "المزوّد: {provider}\n"
            "الوقت المنقضي: {elapsed} ث\n"
            "حجم الطابور: {queue}"
        ),
    },
    "cancelled": {
        "en": "🛑 Job <b>#{job_id}</b> cancelled.",
        "ar": "🛑 تم إلغاء الطلب <b>#{job_id}</b>.",
    },
    "cancel_none": {
        "en": "ℹ️ Nothing to cancel.",
        "ar": "ℹ️ لا يوجد ما يمكن إلغاؤه.",
    },
    "flow_cancelled": {
        "en": "↩️ Operation cancelled.",
        "ar": "↩️ تم إلغاء العملية.",
    },
    "rate_limited": {
        "en": "⏳ You've used {used}/{limit} videos this hour. Try again in <b>{minutes} min</b>.",
        "ar": "⏳ استخدمت {used}/{limit} فيديوهات هذه الساعة. حاول مجدداً بعد <b>{minutes} دقيقة</b>.",
    },
    "already_active": {
        "en": "⚠️ You already have job <b>#{job_id}</b> in progress. Use /status or /cancel.",
        "ar": "⚠️ لديك بالفعل الطلب <b>#{job_id}</b> قيد التنفيذ. استخدم /status أو /cancel.",
    },
    "prompt_too_short": {
        "en": "⚠️ Prompt is too short (min {n} characters). Try again:",
        "ar": "⚠️ الوصف قصير جداً (الحد الأدنى {n} حرف). حاول مجدداً:",
    },
    "prompt_too_long": {
        "en": "⚠️ Prompt is too long (max {n} characters). Try again:",
        "ar": "⚠️ الوصف طويل جداً (الحد الأقصى {n} حرف). حاول مجدداً:",
    },
    "prompt_banned": {
        "en": "🚫 Your prompt contains prohibited content. Please rephrase:",
        "ar": "🚫 يحتوي وصفك على محتوى محظور. أعد الصياغة من فضلك:",
    },
    "banned": {
        "en": "🚫 You are not allowed to use this bot.",
        "ar": "🚫 غير مسموح لك باستخدام هذا البوت.",
    },
    "queue_full": {
        "en": "😓 The queue is full right now. Please try again in a few minutes.",
        "ar": "😓 الطابور ممتلئ حالياً. حاول مجدداً بعد بضع دقائق.",
    },
    "admin_only": {
        "en": "⛔ Admins only.",
        "ar": "⛔ للمشرفين فقط.",
    },
    "lang_choose": {
        "en": "🌐 Choose your language:",
        "ar": "🌐 اختر لغتك:",
    },
    "lang_set": {
        "en": "✅ Language set to English.",
        "ar": "✅ تم ضبط اللغة إلى العربية.",
    },
    "unknown": {
        "en": "🤔 I didn't understand that. Use /generate to create a video or /help.",
        "ar": "🤔 لم أفهم ذلك. استخدم /generate لإنشاء فيديو أو /help.",
    },
    "error_generic": {
        "en": "⚠️ Something went wrong. Please try again later.",
        "ar": "⚠️ حدث خطأ ما. حاول مجدداً لاحقاً.",
    },
    # Buttons
    "btn_confirm": {"en": "🚀 Generate", "ar": "🚀 توليد"},
    "btn_cancel": {"en": "✖️ Cancel", "ar": "✖️ إلغاء"},
    "btn_skip": {"en": "⏭ Default", "ar": "⏭ افتراضي"},
    "style_none": {"en": "None", "ar": "بدون"},
    "style_cinematic": {"en": "🎬 Cinematic", "ar": "🎬 سينمائي"},
    "style_anime": {"en": "🌸 Anime", "ar": "🌸 أنمي"},
    "style_3d": {"en": "🧊 3D Render", "ar": "🧊 ثلاثي الأبعاد"},
    "style_realistic": {"en": "📷 Realistic", "ar": "📷 واقعي"},
    "style_watercolor": {"en": "🖌 Watercolor", "ar": "🖌 ألوان مائية"},
    "status_queued": {"en": "queued", "ar": "في الطابور"},
    "status_running": {"en": "rendering", "ar": "قيد التوليد"},
    "status_done": {"en": "done", "ar": "مكتمل"},
    "status_failed": {"en": "failed", "ar": "فشل"},
    "status_cancelled": {"en": "cancelled", "ar": "ملغى"},
}

SUPPORTED_LANGS = ("en", "ar")


def normalize_lang(code: str | None, default: str = "en") -> str:
    """Map a Telegram language_code to a supported language."""
    if not code:
        return default
    code = code.lower().split("-")[0]
    return code if code in SUPPORTED_LANGS else default


def t(key: str, lang: str, **kwargs: object) -> str:
    """Translate `key` into `lang` (falls back to English) and format it."""
    entry = TEXTS.get(key, {})
    template = entry.get(lang) or entry.get("en") or key
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template
