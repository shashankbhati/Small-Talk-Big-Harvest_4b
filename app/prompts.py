"""Fixed phrases the system can say. Each key can have a recorded clip at
static/audio/<key>.mp3 (recorded by a native speaker). If the clip is missing,
Twilio reads the English text instead (fine for testing, not for the real demo)."""

PROMPTS = {
    "welcome_consent": (
        "Welcome to the coffee helpline. Describe what you see on your coffee plants and we will "
        "tell you the likely problem and what to do. Your voice is not stored. "
        "Press 1 to continue. Press 9 to delete your data."
    ),
    "consent_improve": (
        "May we keep your answers, without your name, to improve advice for farmers near you? "
        "Press 1 for yes. Press 2 for no."
    ),
    "describe": (
        "After the beep, describe the problem. For example the colour of the spots, where they are on the leaf, "
        "and if leaves or berries are damaged. Press the hash key when you are done."
    ),
    "please_wait": "Thank you. Please wait a moment while I check.",
    "goodbye": "Thank you for calling. Goodbye.",
    "no_consent": "No problem. You can call again any time. Goodbye.",
    "deleted": "Your data has been deleted. Goodbye.",
    "error": "Sorry, something went wrong. Your report was sent to the extension officer. Goodbye.",
}
