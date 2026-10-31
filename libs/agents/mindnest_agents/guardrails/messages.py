"""What the student sees when a rail stops a message, in the language they wrote in.

The language is chosen from the script of their message (Devanagari = Hindi, Gujarati = Gujarati,
anything else = English), because the app does not know which language a student will type in.
The Hindi and Gujarati text should be read by a native speaker before release."""

import re

from mindnest_agents.guardrails import rules

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_GUJARATI = re.compile(r"[઀-૿]")


def language_of(text: str) -> str:
    gu = len(_GUJARATI.findall(text))
    hi = len(_DEVANAGARI.findall(text))
    if gu > hi and gu:
        return "gu"
    if hi:
        return "hi"
    return "en"


_TEXT: dict[str, dict[str, str]] = {
    rules.INJECTION: {
        "en": (
            "I can't follow instructions that ask me to ignore my rules, change who I am, or reveal "
            "how I work. If you are studying prompt injection, ask me to explain it and I will. "
            "Otherwise, tell me what you would like to study."
        ),
        "hi": (
            "मैं ऐसे निर्देश नहीं मान सकता जो मुझसे मेरे नियम अनदेखा करने या यह बताने को कहें कि मैं कैसे काम करता हूँ। "
            "अगर आप प्रॉम्प्ट इंजेक्शन के बारे में पढ़ रहे हैं, तो मुझसे उसे समझाने को कहें। "
            "वरना बताइए कि आप क्या पढ़ना चाहते हैं।"
        ),
        "gu": (
            "હું એવી સૂચનાઓ માની શકતો નથી જે મને મારા નિયમો અવગણવા અથવા હું કેવી રીતે કામ કરું છું તે જણાવવા કહે. "
            "જો તમે પ્રોમ્પ્ટ ઇન્જેક્શન વિશે ભણી રહ્યા હો, તો મને તે સમજાવવા કહો. "
            "નહીંતર કહો કે તમે શું ભણવા માંગો છો."
        ),
    },
    rules.SELF_HARM: {
        "en": (
            "I'm really sorry you are feeling this way. You do not have to carry it alone, and it matters "
            "that you said it. Please talk to someone you trust right now: a friend, a family member, a "
            "teacher or a counsellor at your college.\n\n"
            "In India you can call **Tele-MANAS on 14416 or 1800-891-4416** (free, 24 hours, many languages). "
            "If you are in immediate danger, call **112**.\n\n"
            "I'm here if you want to talk. Your studies can wait."
        ),
        "hi": (
            "मुझे सचमुच दुख है कि आप ऐसा महसूस कर रहे हैं। आपको यह अकेले नहीं सहना है, और आपने यह कहा, यह ज़रूरी है। "
            "कृपया अभी किसी भरोसेमंद व्यक्ति से बात करें: कोई दोस्त, परिवार का सदस्य, शिक्षक या कॉलेज के काउंसलर।\n\n"
            "भारत में आप **टेली-मानस 14416 या 1800-891-4416** पर कॉल कर सकते हैं (निःशुल्क, 24 घंटे, कई भाषाओं में)। "
            "अगर आप तुरंत खतरे में हैं, तो **112** पर कॉल करें।\n\n"
            "अगर आप बात करना चाहें तो मैं यहाँ हूँ। पढ़ाई इंतज़ार कर सकती है।"
        ),
        "gu": (
            "તમે આવું અનુભવી રહ્યા છો તે જાણીને મને ખરેખર દુઃખ થયું. તમારે આ એકલા સહન કરવાનું નથી, અને તમે કહ્યું તે મહત્ત્વનું છે. "
            "કૃપા કરીને અત્યારે કોઈ ભરોસાપાત્ર વ્યક્તિ સાથે વાત કરો: મિત્ર, પરિવારના સભ્ય, શિક્ષક અથવા કૉલેજના કાઉન્સેલર.\n\n"
            "ભારતમાં તમે **ટેલિ-માનસ 14416 અથવા 1800-891-4416** પર કૉલ કરી શકો છો (મફત, 24 કલાક, ઘણી ભાષાઓમાં). "
            "જો તમે તાત્કાલિક જોખમમાં હો, તો **112** પર કૉલ કરો.\n\n"
            "તમે વાત કરવા માંગો તો હું અહીં છું. અભ્યાસ રાહ જોઈ શકે છે."
        ),
    },
    rules.HARMFUL: {
        "en": (
            "I can't help with making weapons or drugs, or with tools meant to harm people or break into "
            "someone else's accounts. If this is for a course, ask me about the concepts, or about how "
            "defenders protect against it, and I'll help with that."
        ),
        "hi": (
            "मैं हथियार या ड्रग्स बनाने, या ऐसे टूल बनाने में मदद नहीं कर सकता जो लोगों को नुकसान पहुँचाएँ या किसी और के अकाउंट में घुसें। "
            "अगर यह किसी कोर्स के लिए है, तो मुझसे उसकी अवधारणाएँ पूछें या यह कि सुरक्षा करने वाले इससे कैसे बचाव करते हैं।"
        ),
        "gu": (
            "હું હથિયારો કે ડ્રગ્સ બનાવવામાં, અથવા લોકોને નુકસાન પહોંચાડે કે બીજાના એકાઉન્ટમાં ઘૂસે તેવા ટૂલ બનાવવામાં મદદ કરી શકતો નથી. "
            "જો આ કોઈ કોર્સ માટે હોય, તો મને તેના ખ્યાલો વિશે પૂછો અથવા સુરક્ષા કરનારા તેનાથી કેવી રીતે બચાવ કરે છે તે પૂછો."
        ),
    },
}

_DEFAULT = rules.INJECTION


def refusal_text(code: str, message: str = "") -> str:
    """The reply for a stopped message. `message` only picks the language; it is never repeated."""
    table = _TEXT.get(code) or _TEXT[_DEFAULT]
    return table[language_of(message)]


def tool_refusal(reasons: list[str]) -> str:
    """Shown to the MODEL (not the student) when a tool call is refused."""
    why = ", ".join(reasons) or "the request"
    return (
        f"ERROR: this tool call was refused by the safety rules ({why}). The student did not ask for "
        "it. Do not retry it. Tell the student plainly that you did not do it and why, in one sentence."
    )
