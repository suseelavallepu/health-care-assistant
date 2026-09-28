import os, re, secrets, smtplib, ssl
import time
from datetime import datetime, timedelta
from email.message import EmailMessage
from functools import wraps
from io import BytesIO

from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file, abort
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

load_dotenv()

BASE = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__, instance_relative_config=True)
app.config.update(
    SECRET_KEY=os.getenv("SECRET_KEY", "dev-change-me"),
    SQLALCHEMY_DATABASE_URI="sqlite:///" + os.path.join(BASE, "instance", "healthcare.db"),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    WTF_CSRF_TIME_LIMIT=None,
    RESET_TOKEN_MINUTES=int(os.getenv("RESET_TOKEN_MINUTES", "30")),
)
os.makedirs(app.instance_path, exist_ok=True)
db = SQLAlchemy(app)
csrf = CSRFProtect(app)

# ---------------- Models ----------------
mapping_table = db.Table(
    "symptom_condition",
    db.Column("symptom_id", db.Integer, db.ForeignKey("symptom.id"), primary_key=True),
    db.Column("condition_id", db.Integer, db.ForeignKey("condition.id"), primary_key=True),
)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    age = db.Column(db.Integer)
    gender = db.Column(db.String(40))
    height = db.Column(db.Float)
    weight = db.Column(db.Float)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    symptom_checks = db.relationship("SymptomCheck", backref="user", cascade="all, delete-orphan")
    chats = db.relationship("Chat", backref="user", cascade="all, delete-orphan")
    feedback = db.relationship("Feedback", backref="user", cascade="all, delete-orphan")

    @property
    def bmi(self):
        if self.height and self.weight and self.height > 0:
            return round(self.weight / ((self.height/100) ** 2), 1)
        return None

class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, default="Administrator")
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Symptom(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, default="")
    conditions = db.relationship("Condition", secondary=mapping_table, back_populates="symptoms")

class Condition(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), unique=True, nullable=False, index=True)
    guidance = db.Column(db.Text, default="")
    medicine_info = db.Column(db.Text, default="")
    precautions = db.Column(db.Text, default="")
    symptoms = db.relationship("Symptom", secondary=mapping_table, back_populates="conditions")

class SymptomCheck(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    raw_symptoms = db.Column(db.Text, nullable=False)
    duration = db.Column(db.String(80))
    severity = db.Column(db.String(40))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    results = db.relationship("SymptomCheckResult", backref="check", cascade="all, delete-orphan")

class SymptomCheckResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    check_id = db.Column(db.Integer, db.ForeignKey("symptom_check.id"), nullable=False)
    condition_id = db.Column(db.Integer, db.ForeignKey("condition.id"), nullable=False)
    score = db.Column(db.Float, nullable=False)
    condition = db.relationship("Condition")

class Chat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(200), default="New Chat")
    deleted = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    messages = db.relationship("ChatMessage", backref="chat", cascade="all, delete-orphan", order_by="ChatMessage.created_at")

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey("chat.id"), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Medicine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), unique=True, nullable=False, index=True)
    generic_name = db.Column(db.String(160), default="")
    category = db.Column(db.String(100), default="")
    uses = db.Column(db.Text, default="")
    precautions = db.Column(db.Text, default="")
    side_effects = db.Column(db.Text, default="")
    warnings = db.Column(db.Text, default="")
    interactions = db.Column(db.Text, default="")
    storage = db.Column(db.Text, default="")

class Feedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    feature = db.Column(db.String(100), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey("admin.id"))
    action = db.Column(db.String(160), nullable=False)
    target = db.Column(db.String(255), default="")
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    admin = db.relationship("Admin")

class PasswordResetToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False)
    token_hash = db.Column(db.String(128), nullable=False, unique=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)

# ---------------- Helpers ----------------
def user_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        uid = session.get("user_id")
        if not uid:
            flash("Please log in to continue.", "info")
            return redirect(url_for("login", next=request.path))
        u = db.session.get(User, uid)
        if not u or not u.is_active:
            session.clear()
            flash("Your account is inactive. Please contact support.", "error")
            return redirect(url_for("login"))
        return fn(*a, **kw)
    return wrapper

def admin_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        aid = session.get("admin_id")
        if not aid:
            flash("Admin login required.", "info")
            return redirect(url_for("admin_login"))
        aobj = db.session.get(Admin, aid)
        if not aobj or not aobj.is_active:
            session.clear()
            return redirect(url_for("admin_login"))
        return fn(*a, **kw)
    return wrapper

def admin_log(action, target=""):
    aid = session.get("admin_id")
    db.session.add(ActivityLog(admin_id=aid, action=action, target=target))
    db.session.commit()

def normalize(text):
    return set(re.findall(r"[a-zA-Z0-9]+", text.lower()))

def send_reset_email(email, token, role):
    host = request.host_url.rstrip("/")
    link = f"{host}/reset-password/{token}?role={role}"
    msg = EmailMessage()
    msg["Subject"] = "Healthcare Assistant password reset"
    msg["From"] = os.getenv("MAIL_FROM") or os.getenv("SMTP_USERNAME")
    msg["To"] = email
    msg.set_content(f"""Hello,

Use this link to reset your Healthcare Assistant password:
{link}

This link expires in {app.config['RESET_TOKEN_MINUTES']} minutes and can be used only once.

If you did not request this, ignore this email.
""")
    host_s, port = os.getenv("SMTP_HOST"), int(os.getenv("SMTP_PORT", "587"))
    username, password = os.getenv("SMTP_USERNAME"), os.getenv("SMTP_PASSWORD")
    if not all([host_s, username, password, msg["From"]]):
        raise RuntimeError("SMTP is not configured in .env")
    with smtplib.SMTP(host_s, port, timeout=15) as server:
        server.starttls(context=ssl.create_default_context())
        server.login(username, password)
        server.send_message(msg)

def make_token(email, role):
    raw = secrets.token_urlsafe(32)
    import hashlib
    h = hashlib.sha256(raw.encode()).hexdigest()
    db.session.add(PasswordResetToken(email=email, role=role, token_hash=h,
        expires_at=datetime.utcnow()+timedelta(minutes=app.config["RESET_TOKEN_MINUTES"])))
    db.session.commit()
    return raw

def check_token(raw, role):
    import hashlib
    h = hashlib.sha256(raw.encode()).hexdigest()
    obj = PasswordResetToken.query.filter_by(token_hash=h, role=role, used=False).first()
    if not obj or obj.expires_at < datetime.utcnow():
        return None
    return obj

def seed():
    if not Symptom.query.first():
        symptom_names = ["fever","cough","headache","fatigue","nausea","sore throat","runny nose","body ache","vomiting","diarrhea","shortness of breath","chest pain"]
        for n in symptom_names: db.session.add(Symptom(name=n))
    if not Condition.query.first():
        conditions = [
            ("Common cold","Often improves with rest and fluids. Consider professional advice if symptoms are severe or persistent.","No personalized prescription is provided.","Seek care for breathing difficulty or worsening symptoms."),
            ("Flu-like illness","Rest, fluids and monitoring may be appropriate. Seek professional advice when symptoms are significant.","Medicine information is general only.","Urgent care may be needed for severe breathing problems or chest pain."),
            ("Gastrointestinal illness","Hydration is important. Consider medical advice if vomiting/diarrhea is severe or persistent.","Medicine information is general only.","Seek care for dehydration, blood in stool/vomit, or severe pain."),
        ]
        for n,g,m,p in conditions: db.session.add(Condition(name=n,guidance=g,medicine_info=m,precautions=p))
        db.session.flush()
        def link(cname, names):
            c=Condition.query.filter_by(name=cname).first()
            for n in names:
                s=Symptom.query.filter_by(name=n).first()
                if s: c.symptoms.append(s)
        link("Common cold",["cough","sore throat","runny nose","headache","fatigue"])
        link("Flu-like illness",["fever","cough","headache","fatigue","body ache","sore throat"])
        link("Gastrointestinal illness",["nausea","vomiting","diarrhea","fatigue"])
    if not Medicine.query.first():
        db.session.add_all([
            Medicine(name="Paracetamol",generic_name="Acetaminophen",category="Pain/Fever",
                     uses="General information about pain and fever relief.",
                     precautions="Follow the product label and ask a pharmacist/doctor if unsure.",
                     side_effects="May cause side effects in some people.",
                     warnings="Avoid duplicate products containing the same active ingredient.",
                     interactions="Ask a pharmacist about interactions with your medicines.",
                     storage="Store according to the package instructions."),
            Medicine(name="Oral Rehydration Solution",generic_name="ORS",category="Hydration",
                     uses="Used to help replace fluids and electrolytes.",
                     precautions="Follow preparation instructions on the product.",
                     side_effects="Usually well tolerated when prepared correctly.",
                     warnings="Severe dehydration needs professional care.",
                     interactions="Ask a professional if you have medical conditions affecting fluid balance.",
                     storage="Follow package storage instructions.")
        ])
    admin_email=os.getenv("ADMIN_EMAIL")
    admin_password=os.getenv("ADMIN_PASSWORD")
    if admin_email and admin_password and not Admin.query.filter_by(email=admin_email.lower()).first():
        db.session.add(Admin(name="Administrator", email=admin_email.lower(), password_hash=generate_password_hash(admin_password)))
    db.session.commit()

with app.app_context():
    db.create_all()
    seed()

@app.context_processor
def globals():
    return {"current_user": db.session.get(User, session.get("user_id")) if session.get("user_id") else None,
            "current_admin": db.session.get(Admin, session.get("admin_id")) if session.get("admin_id") else None}

# ---------------- Public/Auth ----------------
@app.route("/")
def home(): return render_template("home.html")

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method=="POST":
        name=request.form.get("name","").strip()
        email=request.form.get("email","").strip().lower()
        pw=request.form.get("password","")
        cpw=request.form.get("confirm_password","")
        if not name or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$",email): flash("Enter a valid name and email.","error")
        elif len(pw)<8: flash("Password must be at least 8 characters.","error")
        elif pw!=cpw: flash("Passwords do not match.","error")
        elif User.query.filter_by(email=email).first(): flash("An account with that email already exists.","error")
        else:
            u=User(name=name,email=email,password_hash=generate_password_hash(pw))
            db.session.add(u); db.session.commit()
            session.clear(); session["user_id"]=u.id
            return redirect(url_for("user_home"))
    return render_template("register.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        email=request.form.get("email","").strip().lower(); pw=request.form.get("password","")
        u=User.query.filter_by(email=email).first()
        if u and u.is_active and check_password_hash(u.password_hash,pw):
            session.clear(); session["user_id"]=u.id
            return redirect(url_for("user_home"))
        flash("Invalid email or password.","error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("home"))

@app.route("/forgot-password", methods=["GET","POST"])
def forgot_password():
    if request.method=="POST":
        email=request.form.get("email","").strip().lower()
        u=User.query.filter_by(email=email).first()
        if u:
            try: send_reset_email(email, make_token(email,"user"), "user")
            except Exception as e: flash("Email could not be sent. Check SMTP configuration.","error")
            else: flash("If that email is registered, a reset link has been sent.","success")
        else: flash("If that email is registered, a reset link has been sent.","success")
    return render_template("forgot_password.html", role="user")

@app.route("/reset-password/<token>", methods=["GET","POST"])
def reset_password(token):
    role=request.args.get("role","user")
    obj=check_token(token,role)
    if not obj: return render_template("reset_password.html", valid=False, role=role)
    if request.method=="POST":
        pw=request.form.get("password",""); cpw=request.form.get("confirm_password","")
        if len(pw)<8: flash("Password must be at least 8 characters.","error")
        elif pw!=cpw: flash("Passwords do not match.","error")
        else:
            account=User.query.filter_by(email=obj.email).first() if role=="user" else Admin.query.filter_by(email=obj.email).first()
            if not account: abort(404)
            account.password_hash=generate_password_hash(pw); obj.used=True; db.session.commit()
            flash("Password updated. Please log in.","success")
            return redirect(url_for("login" if role=="user" else "admin_login"))
    return render_template("reset_password.html", valid=True, role=role)

# ---------------- User ----------------
@app.route("/app")
@user_required
def user_home(): return render_template("user_home.html")

@app.route("/profile", methods=["GET","POST"])
@user_required
def profile():
    u=db.session.get(User,session["user_id"])
    if request.method=="POST":
        try:
            u.name=request.form["name"].strip(); u.age=int(request.form["age"]) if request.form.get("age") else None
            u.gender=request.form.get("gender",""); u.height=float(request.form["height"]) if request.form.get("height") else None
            u.weight=float(request.form["weight"]) if request.form.get("weight") else None
            if u.age is not None and not 0<u.age<130: raise ValueError
            if u.height is not None and not 30<u.height<250: raise ValueError
            if u.weight is not None and not 1<u.weight<500: raise ValueError
            db.session.commit(); flash("Profile saved.","success")
        except (ValueError, KeyError): db.session.rollback(); flash("Please enter valid profile values.","error")
    return render_template("profile.html", user=u)

@app.route("/symptom-checker", methods=["GET","POST"])
@user_required
def symptom_checker():
    u=db.session.get(User,session["user_id"])
    symptoms=Symptom.query.order_by(Symptom.name).all()
    if request.method=="POST":
        selected=request.form.getlist("symptoms")
        manual=request.form.get("manual_symptoms","")
        raw=", ".join(selected + ([manual.strip()] if manual.strip() else []))
        duration=request.form.get("duration",""); severity=request.form.get("severity","")
        tokens=normalize(raw)
        matched=[]
        for s in symptoms:
            sn=normalize(s.name)
            if sn and (sn <= tokens or s.name.lower() in manual.lower()):
                matched.append(s)
        if not matched:
            flash("No recognizable symptoms were matched. Try selecting symptoms or using simple symptom names.","info")
            return render_template("symptom_checker.html", symptoms=symptoms, history=SymptomCheck.query.filter_by(user_id=u.id).order_by(SymptomCheck.created_at.desc()).limit(10).all())
        check=SymptomCheck(user_id=u.id,raw_symptoms=raw,duration=duration,severity=severity); db.session.add(check); db.session.flush()
        scores={}
        for s in matched:
            for c in s.conditions: scores[c.id]=scores.get(c.id,0)+1
        ranked=sorted(scores.items(), key=lambda x:x[1], reverse=True)[:5]
        for cid,score in ranked: db.session.add(SymptomCheckResult(check_id=check.id,condition_id=cid,score=score/len(matched)))
        db.session.commit()
        return render_template("symptom_result.html", check=check, results=check.results, matched=matched)
    return render_template("symptom_checker.html", symptoms=symptoms, history=SymptomCheck.query.filter_by(user_id=u.id).order_by(SymptomCheck.created_at.desc()).limit(10).all())

@app.route("/symptom-checker/history/<int:check_id>")
@user_required
def symptom_history(check_id):
    check=SymptomCheck.query.filter_by(id=check_id,user_id=session["user_id"]).first_or_404()
    return render_template("symptom_result.html", check=check, results=check.results, matched=[])

@app.route("/assistant")
@user_required
def assistant(): return render_template("ai_assistant.html")

@csrf.exempt
@app.route("/api/chats", methods=["GET","POST"])
@user_required
def chats_api():
    uid=session["user_id"]
    if request.method=="POST":
        c=Chat(user_id=uid,title="New Chat"); db.session.add(c); db.session.commit()
        return jsonify(id=c.id,title=c.title)
    q=request.args.get("q","").strip()
    query=Chat.query.filter_by(user_id=uid,deleted=False)
    if q:
        query=query.filter(Chat.title.ilike(f"%{q}%"))
    return jsonify([{"id":c.id,"title":c.title,"updated_at":c.updated_at.isoformat()} for c in query.order_by(Chat.updated_at.desc()).all()])

@csrf.exempt
@app.route("/api/chats/<int:chat_id>", methods=["GET","DELETE"])
@user_required
def chat_api(chat_id):
    c=Chat.query.filter_by(id=chat_id,user_id=session["user_id"],deleted=False).first_or_404()
    if request.method=="DELETE":
        c.deleted=True; db.session.commit(); return jsonify(ok=True)
    return jsonify({"id":c.id,"title":c.title,"messages":[{"role":m.role,"content":m.content} for m in c.messages]})

@csrf.exempt
@app.route("/api/chats/<int:chat_id>/message", methods=["POST"])
@user_required
def message_api(chat_id):
    c=Chat.query.filter_by(id=chat_id,user_id=session["user_id"],deleted=False).first_or_404()
    text=request.json.get("message","").strip()
    if not text: return jsonify(error="Message required"),400
    user_msg=ChatMessage(chat_id=c.id,role="user",content=text); db.session.add(user_msg)
    try:
        from google import genai
        key=os.getenv("GEMINI_API_KEY")
        if not key: raise RuntimeError("GEMINI_API_KEY is not configured")
        client=genai.Client(api_key=key)
        history=[{"role":m.role,"content":m.content} for m in c.messages[-12:]]
        prompt=("You are a cautious general-health educational assistant. "
                "Do not diagnose with certainty, prescribe, recommend dangerous doses, or tell users to start/stop prescription drugs. "
                "For emergencies advise immediate professional/emergency care. "
                "Answer clearly and briefly. User question:\n"+text)
        resp=client.models.generate_content(model=os.getenv("GEMINI_MODEL","gemini-3.6-flash"),
                                            contents=prompt)
        answer=resp.text or "I could not generate a response."
    except Exception as e:
         
        db.session.rollback()
        print("GEMINI ERROR:", e)
        return jsonify(error="AI service is unavailable. Check the Gemini API configuration and try again."),503
    db.session.add(ChatMessage(chat_id=c.id,role="assistant",content=answer))
    if c.title=="New Chat": c.title=text[:60]
    c.updated_at=datetime.utcnow(); db.session.commit()
    return jsonify(answer=answer)

@app.route("/dashboard")
@user_required
def dashboard():
    u=db.session.get(User,session["user_id"])
    checks=SymptomCheck.query.filter_by(user_id=u.id).count()
    chats=Chat.query.filter_by(user_id=u.id,deleted=False).count()
    reports=checks # each saved check can contribute to personal health summary
    return render_template("dashboard.html",user=u,checks=checks,chats=chats,reports=reports)

@app.route("/medkit")
@user_required
def medkit():
    q=request.args.get("q","").strip(); category=request.args.get("category","").strip()
    query=Medicine.query
    if q: query=query.filter((Medicine.name.ilike(f"%{q}%"))|(Medicine.generic_name.ilike(f"%{q}%")))
    if category: query=query.filter_by(category=category)
    medicines=query.order_by(Medicine.name).all()
    cats=[x[0] for x in db.session.query(Medicine.category).distinct().all() if x[0]]
    return render_template("medkit.html",medicines=medicines,categories=cats,q=q,category=category)

@app.route("/medkit/<int:medicine_id>")
@user_required
def medicine_detail(medicine_id):
    return render_template("medicine_detail.html",medicine=db.session.get(Medicine,medicine_id) or abort(404))

@app.route("/report")
@user_required
def report():
    u=db.session.get(User,session["user_id"])
    checks=SymptomCheck.query.filter_by(user_id=u.id).order_by(SymptomCheck.created_at.desc()).limit(10).all()
    return render_template("health_report.html",user=u,checks=checks)

@app.route("/report/pdf")
@user_required
def report_pdf():
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    u=db.session.get(User,session["user_id"])
    checks=SymptomCheck.query.filter_by(user_id=u.id).order_by(SymptomCheck.created_at.desc()).limit(10).all()
    buf=BytesIO(); doc=SimpleDocTemplate(buf,pagesize=A4,rightMargin=42,leftMargin=42,topMargin=42,bottomMargin=42)
    styles=getSampleStyleSheet(); story=[Paragraph("Healthcare Assistant — Personal Health Summary",styles["Title"]),Spacer(1,12)]
    data=[["Name",u.name],["Email",u.email],["Age",str(u.age or "Not provided")],["Gender",u.gender or "Not provided"],["Height",f"{u.height} cm" if u.height else "Not provided"],["Weight",f"{u.weight} kg" if u.weight else "Not provided"],["BMI",str(u.bmi or "Not available")]]
    t=Table(data,colWidths=[120,350]); t.setStyle(TableStyle([("GRID",(0,0),(-1,-1),0.5,colors.grey),("BACKGROUND",(0,0),(0,-1),colors.whitesmoke),("VALIGN",(0,0),(-1,-1),"TOP")]))
    story += [t,Spacer(1,18),Paragraph("Recent saved symptom checks",styles["Heading2"])]
    for c in checks:
        story += [Paragraph(f"{c.created_at:%d %b %Y %H:%M} — {c.raw_symptoms}",styles["BodyText"])]
        if c.results:
            story.append(Paragraph("Possible matches: "+", ".join(r.condition.name for r in c.results),styles["BodyText"]))
        story.append(Spacer(1,8))
    story += [Spacer(1,10),Paragraph("Medical safety notice: This report provides general educational information. It is not a diagnosis and does not replace professional medical care.",styles["BodyText"])]
    doc.build(story); buf.seek(0)
    return send_file(buf,as_attachment=True,download_name="healthcare_health_report.pdf",mimetype="application/pdf")

@app.route("/feedback", methods=["GET","POST"])
@user_required
def feedback():
    if request.method=="POST":
        try: rating=int(request.form["rating"])
        except: rating=0
        if rating not in range(1,6): flash("Choose a rating from 1 to 5.","error")
        else:
            db.session.add(Feedback(user_id=session["user_id"],feature=request.form.get("feature","Overall Website"),rating=rating,comment=request.form.get("comment","").strip()))
            db.session.commit(); flash("Thank you. Your feedback was saved.","success")
    return render_template("feedback.html")

# ---------------- Admin ----------------
@app.route("/admin", methods=["GET","POST"])
def admin_login():
    if request.method=="POST":
        email=request.form.get("email","").strip().lower(); pw=request.form.get("password","")
        a=Admin.query.filter_by(email=email).first()
        if a and a.is_active and check_password_hash(a.password_hash,pw):
            session.clear(); session["admin_id"]=a.id; return redirect(url_for("admin_home"))
        flash("Invalid admin credentials.","error")
    return render_template("admin_login.html")

@app.route("/admin/forgot-password", methods=["GET","POST"])
def admin_forgot():
    if request.method=="POST":
        email=request.form.get("email","").strip().lower(); a=Admin.query.filter_by(email=email).first()
        if a:
            try: send_reset_email(email,make_token(email,"admin"),"admin")
            except: pass
        flash("If the admin email is registered, a reset link has been sent.","success")
    return render_template("forgot_password.html",role="admin")

@app.route("/admin/logout")
def admin_logout():
    session.clear(); return redirect(url_for("home"))

@app.route("/admin/home")
@admin_required
def admin_home(): return render_template("admin_home.html")

@app.route("/admin/users")
@admin_required
def admin_users():
    q=request.args.get("q","").strip(); query=User.query
    if q: query=query.filter((User.name.ilike(f"%{q}%"))|(User.email.ilike(f"%{q}%")))
    return render_template("admin_users.html",users=query.order_by(User.created_at.desc()).all(),q=q)

@app.route("/admin/users/<int:user_id>/toggle",methods=["POST"])
@admin_required
def admin_user_toggle(user_id):
    u=db.session.get(User,user_id) or abort(404); u.is_active=not u.is_active; db.session.commit()
    admin_log("user status changed",u.email); return redirect(url_for("admin_users"))

@app.route("/admin/users/<int:user_id>/delete",methods=["POST"])
@admin_required
def admin_user_delete(user_id):
    u=db.session.get(User,user_id) or abort(404); email=u.email; db.session.delete(u); db.session.commit()
    admin_log("user deleted",email); return redirect(url_for("admin_users"))

def crud_page(model, title, endpoint, fields):
    q=request.args.get("q","").strip(); query=model.query
    if q and hasattr(model,"name"): query=query.filter(model.name.ilike(f"%{q}%"))
    return render_template("admin_crud.html",title=title,endpoint=endpoint,items=query.order_by(model.id.desc()).all(),fields=fields,q=q,model=model)

@app.route("/admin/symptoms",methods=["GET","POST"])
@admin_required
def admin_symptoms():
    if request.method=="POST":
        name=request.form.get("name","").strip().lower()
        if name and not Symptom.query.filter_by(name=name).first(): db.session.add(Symptom(name=name,description=request.form.get("description",""))); db.session.commit(); admin_log("symptom added",name)
        else: flash("Symptom already exists or is invalid.","error")
    return crud_page(Symptom,"Symptoms","admin_symptoms",["name","description"])

@app.route("/admin/symptoms/<int:item_id>/delete",methods=["POST"])
@admin_required
def admin_symptom_delete(item_id):
    x=db.session.get(Symptom,item_id) or abort(404); n=x.name; db.session.delete(x); db.session.commit(); admin_log("symptom deleted",n); return redirect(url_for("admin_symptoms"))

@app.route("/admin/conditions",methods=["GET","POST"])
@admin_required
def admin_conditions():
    if request.method=="POST":
        name=request.form.get("name","").strip()
        if name and not Condition.query.filter_by(name=name).first():
            db.session.add(Condition(name=name,guidance=request.form.get("guidance",""),medicine_info=request.form.get("medicine_info",""),precautions=request.form.get("precautions",""))); db.session.commit(); admin_log("condition added",name)
    return crud_page(Condition,"Conditions","admin_conditions",["name","guidance","medicine_info","precautions"])

@app.route("/admin/conditions/<int:item_id>/delete",methods=["POST"])
@admin_required
def admin_condition_delete(item_id):
    x=db.session.get(Condition,item_id) or abort(404); n=x.name; db.session.delete(x); db.session.commit(); admin_log("condition deleted",n); return redirect(url_for("admin_conditions"))

@app.route("/admin/mapping",methods=["GET","POST"])
@admin_required
def admin_mapping():
    if request.method=="POST":
        s=db.session.get(Symptom,int(request.form["symptom_id"])); c=db.session.get(Condition,int(request.form["condition_id"]))
        if s and c and c not in s.conditions: s.conditions.append(c); db.session.commit(); admin_log("symptom-condition mapping added",f"{s.name} ↔ {c.name}")
    mappings=[]
    for s in Symptom.query.order_by(Symptom.name).all():
        for c in s.conditions: mappings.append((s,c))
    return render_template("admin_mapping.html",symptoms=Symptom.query.all(),conditions=Condition.query.all(),mappings=mappings)

@app.route("/admin/mapping/delete",methods=["POST"])
@admin_required
def admin_mapping_delete():
    s=db.session.get(Symptom,int(request.form["symptom_id"])); c=db.session.get(Condition,int(request.form["condition_id"]))
    if s and c and c in s.conditions: s.conditions.remove(c); db.session.commit(); admin_log("symptom-condition mapping deleted",f"{s.name} ↔ {c.name}")
    return redirect(url_for("admin_mapping"))

@app.route("/admin/medicines",methods=["GET","POST"])
@admin_required
def admin_medicines():
    if request.method=="POST":
        m=Medicine(name=request.form.get("name","").strip(),generic_name=request.form.get("generic_name",""),category=request.form.get("category",""),uses=request.form.get("uses",""),precautions=request.form.get("precautions",""),side_effects=request.form.get("side_effects",""),warnings=request.form.get("warnings",""),interactions=request.form.get("interactions",""),storage=request.form.get("storage",""))
        if m.name and not Medicine.query.filter_by(name=m.name).first(): db.session.add(m); db.session.commit(); admin_log("medicine added",m.name)
        else: flash("Medicine name is required and must be unique.","error")
    q=request.args.get("q","").strip(); meds=Medicine.query.filter(Medicine.name.ilike(f"%{q}%")).order_by(Medicine.name).all() if q else Medicine.query.order_by(Medicine.name).all()
    return render_template("admin_medicines.html",medicines=meds,q=q)

@app.route("/admin/medicines/<int:item_id>/delete",methods=["POST"])
@admin_required
def admin_medicine_delete(item_id):
    x=db.session.get(Medicine,item_id) or abort(404); n=x.name; db.session.delete(x); db.session.commit(); admin_log("medicine deleted",n); return redirect(url_for("admin_medicines"))

@app.route("/admin/feedback")
@admin_required
def admin_feedback():
    q=request.args.get("q","").strip(); query=Feedback.query
    if q: query=query.join(User).filter((User.name.ilike(f"%{q}%"))|(Feedback.feature.ilike(f"%{q}%")))
    return render_template("admin_feedback.html",feedback=query.order_by(Feedback.created_at.desc()).all(),q=q)

@app.route("/admin/overview")
@admin_required
def admin_overview():
    return render_template("admin_overview.html",stats={"users":User.query.count(),"symptoms":Symptom.query.count(),"conditions":Condition.query.count(),"medicines":Medicine.query.count(),"feedback":Feedback.query.count()})

@app.route("/admin/activity")
@admin_required
def admin_activity(): return render_template("admin_activity.html",logs=ActivityLog.query.order_by(ActivityLog.timestamp.desc()).limit(200).all())

@app.route("/admin/profile",methods=["GET","POST"])
@admin_required
def admin_profile():
    a=db.session.get(Admin,session["admin_id"])
    if request.method=="POST":
        a.name=request.form.get("name",a.name).strip()
        if request.form.get("new_password"):
            if len(request.form["new_password"])<8: flash("Password must be at least 8 characters.","error")
            else: a.password_hash=generate_password_hash(request.form["new_password"])
        db.session.commit(); flash("Admin profile updated.","success")
    return render_template("admin_profile.html",admin=a)

@app.errorhandler(403)
def forbidden(e): return render_template("error.html",code=403,message="You are not authorized to access this page."),403
@app.errorhandler(404)
def not_found(e): return render_template("error.html",code=404,message="The page you requested was not found."),404
@app.errorhandler(500)
def server_error(e): return render_template("error.html",code=500,message="Something went wrong. Please try again."),500

if __name__=="__main__":
    app.run(debug=True)
