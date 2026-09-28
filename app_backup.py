@app.route("/api/chats/<int:chat_id>/message", methods=["POST"])
@user_required
def message_api(chat_id):
    c = Chat.query.filter_by(
        id=chat_id,
        user_id=session["user_id"],
        deleted=False
    ).first_or_404()

    text = request.json.get("message", "").strip()

    if not text:
        return jsonify(error="Message required"), 400

    user_msg = ChatMessage(
        chat_id=c.id,
        role="user",
        content=text
    )
    db.session.add(user_msg)

    try:
        from google import genai

        key = os.getenv("GEMINI_API_KEY")

        if not key:
            raise RuntimeError("GEMINI_API_KEY is not configured")

        client = genai.Client(api_key=key)

        prompt = f"""
You are a general health education assistant.

Answer the user's health-related question in simple language.

Important:
- Do not give a definite diagnosis.
- Do not prescribe medicines or dangerous dosages.
- Do not tell users to start or stop prescription medicines.
- If symptoms are severe or there is an emergency, advise the user to seek immediate medical care.
- Give practical general health information.
- Mention that your answer is general information, not a medical diagnosis.

User question:
{text}
"""

        response = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            contents=prompt
        )

        answer = response.text

        if not answer:
            answer = "I could not generate a response. Please try again."

    except Exception as e:
        print("====================================")
        print("GEMINI ERROR:", repr(e))
        print("====================================")

        db.session.rollback()

        return jsonify(
            error="AI service is unavailable. Check the Gemini API configuration and try again."
        ), 503

    db.session.add(
        ChatMessage(
            chat_id=c.id,
            role="assistant",
            content=answer
        )
    )

    if c.title == "New Chat":
        c.title = text[:60]

    c.updated_at = datetime.utcnow()
    db.session.commit()

    return jsonify(answer=answer)