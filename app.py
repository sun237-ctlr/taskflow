"""
TaskFlow Pro — Application Web SÉCURISÉE
Nouvelles fonctionnalités :
- Pause/reprise d'une tâche
- Emails automatiques à l'échéance (propriétaire + membres du projet)
"""
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect, generate_csrf
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, date, timedelta
import os, re, bleach, secrets, atexit

app = Flask(__name__)

# ═══════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)

db_url = os.environ.get('DATABASE_URL', 'sqlite:///taskflow.db')
if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['REMEMBER_COOKIE_HTTPONLY'] = True
app.config['REMEMBER_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production'
app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=14)
app.config['MAX_CONTENT_LENGTH'] = 1 * 1024 * 1024

# ── Configuration Email ──────────────────────────────────────
app.config['MAIL_SERVER']   = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT']     = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS']  = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_USERNAME', '')

db   = SQLAlchemy(app)
mail = Mail(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.session_protection = "strong"
csrf    = CSRFProtect(app)
limiter = Limiter(get_remote_address, app=app,
                  default_limits=["300 per hour", "60 per minute"],
                  storage_uri="memory://")

# ═══════════════════════════════════
# HEADERS DE SÉCURITÉ
# ═══════════════════════════════════
@app.after_request
def set_security_headers(response):
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
    if os.environ.get('FLASK_ENV') == 'production':
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none';"
    )
    return response

# ═══════════════════════════════════
# VALIDATION
# ═══════════════════════════════════
EMAIL_RE    = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
USERNAME_RE = re.compile(r'^[a-zA-Z0-9_\-\s]{2,40}$')

def clean_text(v, max_len=500):
    if not isinstance(v, str): return ''
    return bleach.clean(v.strip(), tags=[], strip=True)[:max_len]

def validate_email(e): return bool(EMAIL_RE.match(e or '')) and len(e) <= 120
def validate_username(u): return bool(USERNAME_RE.match(u or ''))
def validate_password(p):
    if not p or len(p) < 8: return False, "Minimum 8 caractères"
    if not re.search(r'[A-Za-z]', p) or not re.search(r'\d', p):
        return False, "Doit contenir au moins une lettre et un chiffre"
    if len(p) > 128: return False, "Mot de passe trop long"
    return True, ""
def validate_date(s):
    if not s: return True
    try: datetime.strptime(s, '%Y-%m-%d'); return True
    except: return False
def validate_priorite(p): return p in ('Urgente','Haute','Normale','Basse')
def validate_categorie(c): return c in ('General','Travail','Personnel','Etudes','Sante','Finance','Projet','Maison','Loisirs','Autre')
def validate_hex_color(c): return bool(re.match(r'^#[0-9A-Fa-f]{6}$', c or ''))

# ═══════════════════════════════════
# MODÈLES
# ═══════════════════════════════════
class User(UserMixin, db.Model):
    id              = db.Column(db.Integer, primary_key=True)
    username        = db.Column(db.String(40), unique=True, nullable=False)
    email           = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password        = db.Column(db.String(256), nullable=False)
    avatar          = db.Column(db.String(2), default='?')
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    failed_attempts = db.Column(db.Integer, default=0)
    locked_until    = db.Column(db.DateTime, nullable=True)
    taches  = db.relationship('Tache', backref='owner', lazy=True, foreign_keys='Tache.user_id')
    projets = db.relationship('Projet', backref='owner', lazy=True)

    def is_locked(self):
        return self.locked_until is not None and self.locked_until > datetime.utcnow()


class Projet(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    nom         = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, default='')
    couleur     = db.Column(db.String(10), default='#58A6FF')
    echeance    = db.Column(db.String(10), default='')
    archive     = db.Column(db.Boolean, default=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    user_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    taches      = db.relationship('Tache', backref='projet', lazy=True)
    membres     = db.relationship('MembreProjet', backref='projet', lazy=True, cascade='all, delete-orphan')


class MembreProjet(db.Model):
    id        = db.Column(db.Integer, primary_key=True)
    projet_id = db.Column(db.Integer, db.ForeignKey('projet.id'), nullable=False, index=True)
    user_id   = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    role      = db.Column(db.String(20), default='Membre')
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    user      = db.relationship('User', foreign_keys=[user_id])


class Tache(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    titre        = db.Column(db.String(200), nullable=False)
    description  = db.Column(db.Text, default='')
    priorite     = db.Column(db.String(20), default='Normale')
    categorie    = db.Column(db.String(50), default='General')
    echeance     = db.Column(db.String(10), default='')
    tags         = db.Column(db.String(200), default='')
    terminee     = db.Column(db.Boolean, default=False)
    epinglee     = db.Column(db.Boolean, default=False)
    # ── NOUVEAU : Pause ──────────────────────────────────────
    en_pause     = db.Column(db.Boolean, default=False)
    raison_pause = db.Column(db.String(300), default='')
    # ── NOUVEAU : Email de notification envoyé ───────────────
    notif_echeance_envoyee = db.Column(db.Boolean, default=False)
    # ─────────────────────────────────────────────────────────
    temps_passe  = db.Column(db.Integer, default=0)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    projet_id    = db.Column(db.Integer, db.ForeignKey('projet.id'), nullable=True, index=True)
    assigne_a    = db.Column(db.String(100), default='')
    sous_taches  = db.relationship('SousTache', backref='tache', lazy=True, cascade='all, delete-orphan')
    notes        = db.relationship('Note', backref='tache', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        statut, ech_txt = statut_echeance(self.echeance)
        return {
            'id': self.id, 'titre': self.titre, 'description': self.description,
            'priorite': self.priorite, 'categorie': self.categorie,
            'echeance': self.echeance, 'echeance_txt': ech_txt, 'echeance_statut': statut,
            'tags': [t for t in self.tags.split(',') if t] if self.tags else [],
            'terminee': self.terminee, 'epinglee': self.epinglee,
            'en_pause': self.en_pause, 'raison_pause': self.raison_pause or '',
            'temps_passe': self.temps_passe,
            'created_at': self.created_at.strftime('%d/%m/%Y'),
            'projet_id': self.projet_id,
            'projet_nom': self.projet.nom if self.projet else None,
            'projet_couleur': self.projet.couleur if self.projet else None,
            'assigne_a': self.assigne_a,
            'sous_taches': [st.to_dict() for st in self.sous_taches],
            'notes_count': len(self.notes),
        }


class SousTache(db.Model):
    id       = db.Column(db.Integer, primary_key=True)
    titre    = db.Column(db.String(200), nullable=False)
    terminee = db.Column(db.Boolean, default=False)
    tache_id = db.Column(db.Integer, db.ForeignKey('tache.id'), nullable=False, index=True)
    def to_dict(self): return {'id': self.id, 'titre': self.titre, 'terminee': self.terminee}


class Note(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    texte      = db.Column(db.Text, nullable=False)
    tache_id   = db.Column(db.Integer, db.ForeignKey('tache.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ═══════════════════════════════════
# UTILITAIRES
# ═══════════════════════════════════
def statut_echeance(s):
    if not s: return '', ''
    try:
        e = datetime.strptime(s, '%Y-%m-%d').date()
        d = (e - date.today()).days
        if d < 0:  return 'retard',  f'Retard {-d}j'
        if d == 0: return 'auj',     "Aujourd'hui"
        if d == 1: return 'demain',  'Demain'
        if d <= 3: return 'bientot', f'Dans {d}j'
        return 'ok', e.strftime('%d/%m/%Y')
    except: return '', ''

def get_stats(user_id):
    taches = Tache.query.filter_by(user_id=user_id).all()
    total     = len(taches)
    terminees = sum(1 for t in taches if t.terminee)
    en_cours  = sum(1 for t in taches if not t.terminee and not t.en_pause)
    en_pause  = sum(1 for t in taches if t.en_pause)
    en_retard = sum(1 for t in taches if not t.terminee and statut_echeance(t.echeance)[0] == 'retard')
    taux = round(terminees / total * 100) if total else 0
    return {'total': total, 'terminees': terminees, 'en_cours': en_cours,
            'en_pause': en_pause, 'en_retard': en_retard, 'taux': taux}

@login_manager.user_loader
def load_user(uid):
    try: return User.query.get(int(uid))
    except: return None

@login_manager.unauthorized_handler
def unauthorized():
    if request.path.startswith('/api/'):
        return jsonify({'ok': False, 'msg': 'Authentification requise'}), 401
    return redirect(url_for('login'))

def get_owned_tache_or_404(tid):
    return Tache.query.filter_by(id=tid, user_id=current_user.id).first_or_404()

def get_owned_projet_or_404(pid):
    return Projet.query.filter_by(id=pid, user_id=current_user.id).first_or_404()


# ═══════════════════════════════════
# EMAILS AUTOMATIQUES (APScheduler)
# ═══════════════════════════════════
def envoyer_email_echeance(tache, destinataires):
    """Envoie un email de rappel d'échéance pour une tâche."""
    if not app.config['MAIL_USERNAME']:
        print(f"[Email] MAIL_USERNAME non configuré — email non envoyé pour '{tache.titre}'")
        return False
    try:
        statut, ech_txt = statut_echeance(tache.echeance)
        sujet = f"⏰ TaskFlow Pro — Échéance : {tache.titre}"
        corps_html = f"""
        <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;background:#0D1117;color:#E6EDF3;border-radius:12px;overflow:hidden">
          <div style="background:#58A6FF;padding:24px;text-align:center">
            <h1 style="margin:0;color:#fff;font-size:24px">✦ TaskFlow Pro</h1>
            <p style="margin:8px 0 0;color:rgba(255,255,255,.8);font-size:14px">Rappel d'échéance</p>
          </div>
          <div style="padding:32px">
            <h2 style="color:#E6EDF3;font-size:20px;margin:0 0 16px">
              {'⚠️ Tâche en retard !' if statut == 'retard' else '📅 Échéance aujourd\'hui !'}
            </h2>
            <div style="background:#161B22;border:1px solid #30363D;border-left:4px solid #58A6FF;border-radius:8px;padding:20px;margin-bottom:20px">
              <h3 style="margin:0 0 8px;color:#58A6FF;font-size:16px">{tache.titre}</h3>
              {'<p style="margin:0 0 8px;color:#7D8590;font-size:14px">'+tache.description+'</p>' if tache.description else ''}
              <p style="margin:0;font-size:13px;color:#7D8590">
                📅 Échéance : <strong style="color:{'#F85149' if statut=='retard' else '#D29922'}">{ech_txt}</strong><br>
                🔴 Priorité : <strong>{tache.priorite}</strong><br>
                📁 Catégorie : {tache.categorie}
                {f'<br>🗂️ Projet : {tache.projet.nom}' if tache.projet else ''}
              </p>
            </div>
            <a href="https://taskflow-pro-4msa.onrender.com/dashboard"
               style="display:inline-block;background:#58A6FF;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;font-size:14px">
              Ouvrir TaskFlow Pro →
            </a>
          </div>
          <div style="padding:16px 32px;border-top:1px solid #30363D;font-size:11px;color:#7D8590;text-align:center">
            TaskFlow Pro · Ce message est automatique · Ne pas répondre
          </div>
        </div>
        """
        msg = Message(subject=sujet, recipients=destinataires, html=corps_html)
        with app.app_context():
            mail.send(msg)
        print(f"[Email] ✅ Envoyé à {destinataires} pour '{tache.titre}'")
        return True
    except Exception as e:
        print(f"[Email] ❌ Erreur : {e}")
        return False


def verifier_echeances():
    """
    Vérifie les tâches dont l'échéance est aujourd'hui ou dépassée.
    Envoie un email au propriétaire ET aux membres du projet.
    S'exécute automatiquement chaque matin à 8h.
    """
    print(f"[Scheduler] Vérification des échéances — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    with app.app_context():
        try:
            auj = date.today().strftime('%Y-%m-%d')
            # Tâches dues aujourd'hui ou en retard, non terminées, pas en pause, notif pas encore envoyée
            taches = Tache.query.filter(
                Tache.echeance <= auj,
                Tache.terminee == False,
                Tache.en_pause == False,
                Tache.notif_echeance_envoyee == False,
                Tache.echeance != ''
            ).all()

            print(f"[Scheduler] {len(taches)} tâche(s) à notifier")

            for t in taches:
                destinataires = set()
                # Propriétaire de la tâche
                owner = User.query.get(t.user_id)
                if owner and owner.email:
                    destinataires.add(owner.email)
                # Membres du projet si la tâche est dans un projet
                if t.projet_id and t.projet:
                    for m in t.projet.membres:
                        if m.user and m.user.email:
                            destinataires.add(m.user.email)

                if destinataires:
                    ok = envoyer_email_echeance(t, list(destinataires))
                    if ok:
                        t.notif_echeance_envoyee = True
                        db.session.commit()
        except Exception as e:
            print(f"[Scheduler] Erreur : {e}")


# Démarrage du scheduler (vérifie les échéances chaque jour à 8h)
scheduler = BackgroundScheduler()
scheduler.add_job(verifier_echeances, 'cron', hour=8, minute=0)
scheduler.start()
atexit.register(lambda: scheduler.shutdown())


# ═══════════════════════════════════
# ROUTES AUTH
# ═══════════════════════════════════
@app.route('/')
def index():
    if current_user.is_authenticated: return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        email    = clean_text(data.get('email', ''), 120).lower()
        password = data.get('password', '')
        if not email or not password:
            return jsonify({'ok': False, 'msg': 'Champs requis'}), 400
        user = User.query.filter_by(email=email).first()
        if user and user.is_locked():
            return jsonify({'ok': False, 'msg': 'Compte verrouillé 15 minutes (trop de tentatives)'}), 423
        if not user or not check_password_hash(user.password, password):
            if user:
                user.failed_attempts = (user.failed_attempts or 0) + 1
                if user.failed_attempts >= 5:
                    user.locked_until = datetime.utcnow() + timedelta(minutes=15)
                    user.failed_attempts = 0
                db.session.commit()
            return jsonify({'ok': False, 'msg': 'Email ou mot de passe incorrect'}), 401
        user.failed_attempts = 0; user.locked_until = None; db.session.commit()
        session.permanent = True; login_user(user, remember=True)
        return jsonify({'ok': True})
    return render_template('auth.html')

@app.route('/register', methods=['POST'])
@limiter.limit("5 per hour")
def register():
    data = request.get_json(silent=True) or {}
    username = clean_text(data.get('username', ''), 40)
    email    = clean_text(data.get('email', ''), 120).lower()
    password = data.get('password', '')
    if not username or not email or not password:
        return jsonify({'ok': False, 'msg': 'Tous les champs sont requis'}), 400
    if not validate_username(username):
        return jsonify({'ok': False, 'msg': "Nom d'utilisateur invalide"}), 400
    if not validate_email(email):
        return jsonify({'ok': False, 'msg': 'Email invalide'}), 400
    ok, msg = validate_password(password)
    if not ok: return jsonify({'ok': False, 'msg': msg}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({'ok': False, 'msg': 'Email déjà utilisé'}), 409
    if User.query.filter_by(username=username).first():
        return jsonify({'ok': False, 'msg': "Nom d'utilisateur déjà pris"}), 409
    user = User(username=username, email=email,
                password=generate_password_hash(password, method='pbkdf2:sha256', salt_length=16),
                avatar=(username[:2] or '??').upper())
    db.session.add(user); db.session.commit()
    session.permanent = True; login_user(user, remember=True)
    return jsonify({'ok': True})

@app.route('/logout')
@login_required
def logout():
    logout_user(); session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    stats = get_stats(current_user.id)
    return render_template('dashboard.html', stats=stats, user=current_user, csrf_token=generate_csrf())


# ═══════════════════════════════════
# API TÂCHES
# ═══════════════════════════════════
@app.route('/api/taches', methods=['GET'])
@login_required
def api_get_taches():
    vue  = request.args.get('vue', 'toutes')
    cat  = request.args.get('cat', '')
    pid  = request.args.get('projet_id', '')
    rech = clean_text(request.args.get('q', ''), 100).lower()
    tri  = request.args.get('tri', 'priorite')

    q = Tache.query.filter_by(user_id=current_user.id)
    if vue == 'terminees':  q = q.filter_by(terminee=True)
    elif vue == 'encours':  q = q.filter_by(terminee=False, en_pause=False)
    elif vue == 'pause':    q = q.filter_by(en_pause=True, terminee=False)
    elif vue == 'epinglees': q = q.filter_by(epinglee=True, terminee=False)
    if cat and validate_categorie(cat): q = q.filter_by(categorie=cat)
    if pid:
        try:
            pid_int = int(pid)
            if Projet.query.filter_by(id=pid_int, user_id=current_user.id).first():
                q = q.filter_by(projet_id=pid_int)
            else: return jsonify([])
        except ValueError: return jsonify({'msg': 'projet_id invalide'}), 400

    taches = q.all()
    if vue == 'retard':
        taches = [t for t in taches if not t.terminee and statut_echeance(t.echeance)[0] == 'retard']
    elif vue == 'auj':
        taches = [t for t in taches if not t.terminee and statut_echeance(t.echeance)[0] == 'auj']
    elif vue == 'haute':
        taches = [t for t in taches if not t.terminee and t.priorite in ('Haute', 'Urgente')]
    if rech:
        taches = [t for t in taches if rech in t.titre.lower() or rech in (t.description or '').lower()
                  or any(rech in tg.strip().lower() for tg in t.tags.split(',') if tg.strip())]

    ordre = {'Urgente':0,'Haute':1,'Normale':2,'Basse':3}
    if tri == 'priorite':
        taches.sort(key=lambda t: (not t.epinglee, t.en_pause, t.terminee, ordre.get(t.priorite, 2)))
    elif tri == 'echeance': taches.sort(key=lambda t: t.echeance or '9999')
    elif tri == 'date':     taches.sort(key=lambda t: t.created_at, reverse=True)
    elif tri == 'alpha':    taches.sort(key=lambda t: t.titre.lower())
    return jsonify([t.to_dict() for t in taches])

@app.route('/api/taches', methods=['POST'])
@login_required
@limiter.limit("60 per minute")
def api_create_tache():
    d = request.get_json(silent=True) or {}
    titre = clean_text(d.get('titre', ''), 200)
    if not titre: return jsonify({'msg': 'Titre requis'}), 400
    priorite  = d.get('priorite', 'Normale') if validate_priorite(d.get('priorite','')) else 'Normale'
    categorie = d.get('categorie', 'General') if validate_categorie(d.get('categorie','')) else 'General'
    echeance  = clean_text(d.get('echeance', ''), 10)
    if not validate_date(echeance): return jsonify({'msg': 'Date invalide'}), 400
    tags_raw = d.get('tags', [])
    tags = ','.join(clean_text(str(t), 30) for t in (tags_raw if isinstance(tags_raw, list) else [])[:10] if str(t).strip())
    projet_id = None
    if d.get('projet_id'):
        try:
            pid = int(d['projet_id'])
            if Projet.query.filter_by(id=pid, user_id=current_user.id).first(): projet_id = pid
        except: pass
    t = Tache(titre=titre, description=clean_text(d.get('description',''),2000),
              priorite=priorite, categorie=categorie, echeance=echeance, tags=tags,
              projet_id=projet_id, assigne_a=clean_text(d.get('assigne_a',''),100),
              user_id=current_user.id)
    db.session.add(t); db.session.commit()
    return jsonify(t.to_dict()), 201

@app.route('/api/taches/<int:tid>', methods=['GET'])
@login_required
def api_get_tache(tid):
    t = get_owned_tache_or_404(tid)
    dd = t.to_dict()
    dd['notes'] = [{'id':n.id,'texte':n.texte,'date':n.created_at.strftime('%d/%m/%Y %H:%M')} for n in t.notes]
    return jsonify(dd)

@app.route('/api/taches/<int:tid>', methods=['PUT'])
@login_required
@limiter.limit("60 per minute")
def api_update_tache(tid):
    t = get_owned_tache_or_404(tid)
    d = request.get_json(silent=True) or {}
    if 'titre' in d:
        v = clean_text(d['titre'], 200)
        if v: t.titre = v
    if 'description' in d: t.description = clean_text(d['description'], 2000)
    if 'priorite'   in d and validate_priorite(d['priorite']): t.priorite = d['priorite']
    if 'categorie'  in d and validate_categorie(d['categorie']): t.categorie = d['categorie']
    if 'echeance'   in d:
        ech = clean_text(d['echeance'], 10)
        if validate_date(ech):
            t.echeance = ech
            # Si l'échéance change, on réinitialise la notif pour qu'elle soit renvoyée
            t.notif_echeance_envoyee = False
    if 'assigne_a'  in d: t.assigne_a = clean_text(d['assigne_a'], 100)
    if 'tags'       in d and isinstance(d['tags'], list):
        t.tags = ','.join(clean_text(str(tg),30) for tg in d['tags'][:10] if str(tg).strip())
    if 'projet_id'  in d:
        pid = d['projet_id']
        if pid:
            try:
                pid = int(pid)
                if Projet.query.filter_by(id=pid, user_id=current_user.id).first(): t.projet_id = pid
            except: pass
        else: t.projet_id = None
    if 'terminee' in d:
        t.terminee = bool(d['terminee'])
        t.completed_at = datetime.utcnow() if t.terminee else None
        if t.terminee: t.en_pause = False  # Si terminée, retire la pause
    if 'epinglee'     in d: t.epinglee = bool(d['epinglee'])
    if 'temps_passe'  in d:
        try:
            val = int(d['temps_passe'])
            if 0 <= val <= 86400*30: t.temps_passe = val
        except: pass
    db.session.commit()
    return jsonify(t.to_dict())

@app.route('/api/taches/<int:tid>', methods=['DELETE'])
@login_required
def api_delete_tache(tid):
    t = get_owned_tache_or_404(tid)
    db.session.delete(t); db.session.commit()
    return jsonify({'ok': True})

# ── NOUVELLE ROUTE : Pause / Reprise ────────────────────────
@app.route('/api/taches/<int:tid>/pause', methods=['POST'])
@login_required
@limiter.limit("60 per minute")
def api_toggle_pause(tid):
    t = get_owned_tache_or_404(tid)
    if t.terminee:
        return jsonify({'ok': False, 'msg': 'Impossible de mettre en pause une tâche terminée'}), 400
    d = request.get_json(silent=True) or {}
    t.en_pause    = not t.en_pause
    t.raison_pause = clean_text(d.get('raison', ''), 300) if t.en_pause else ''
    db.session.commit()
    etat = 'mise en pause' if t.en_pause else 'reprise'
    return jsonify({'ok': True, 'en_pause': t.en_pause, 'msg': f'Tâche {etat} !'})

# ── NOUVELLE ROUTE : Forcer l'envoi d'une notif email ───────
@app.route('/api/taches/<int:tid>/notifier', methods=['POST'])
@login_required
def api_notifier_manuellement(tid):
    t = get_owned_tache_or_404(tid)
    destinataires = set()
    owner = User.query.get(t.user_id)
    if owner and owner.email: destinataires.add(owner.email)
    if t.projet_id and t.projet:
        for m in t.projet.membres:
            if m.user and m.user.email: destinataires.add(m.user.email)
    if not destinataires:
        return jsonify({'ok': False, 'msg': 'Aucun destinataire trouvé'}), 400
    ok = envoyer_email_echeance(t, list(destinataires))
    if ok:
        t.notif_echeance_envoyee = True; db.session.commit()
        return jsonify({'ok': True, 'msg': f'Email envoyé à {len(destinataires)} destinataire(s)'})
    return jsonify({'ok': False, 'msg': 'Erreur envoi email — vérifie MAIL_USERNAME et MAIL_PASSWORD'}), 500


# ═══════════════════════════════════
# API SOUS-TÂCHES & NOTES
# ═══════════════════════════════════
@app.route('/api/taches/<int:tid>/sous_taches', methods=['POST'])
@login_required
@limiter.limit("60 per minute")
def api_add_sous_tache(tid):
    t = get_owned_tache_or_404(tid)
    d = request.get_json(silent=True) or {}
    titre = clean_text(d.get('titre',''), 200)
    if not titre: return jsonify({'msg':'Titre requis'}), 400
    if len(t.sous_taches) >= 50: return jsonify({'msg':'Limite 50 sous-tâches'}), 400
    st = SousTache(titre=titre, tache_id=t.id)
    db.session.add(st); db.session.commit()
    return jsonify(st.to_dict()), 201

@app.route('/api/sous_taches/<int:sid>', methods=['PUT','DELETE'])
@login_required
def api_update_sous_tache(sid):
    st = SousTache.query.join(Tache).filter(SousTache.id==sid, Tache.user_id==current_user.id).first_or_404()
    if request.method == 'DELETE':
        db.session.delete(st); db.session.commit()
        return jsonify({'ok': True})
    d = request.get_json(silent=True) or {}
    if 'terminee' in d: st.terminee = bool(d['terminee'])
    if 'titre' in d:
        v = clean_text(d['titre'], 200)
        if v: st.titre = v
    db.session.commit()
    return jsonify(st.to_dict())

@app.route('/api/taches/<int:tid>/notes', methods=['POST'])
@login_required
@limiter.limit("60 per minute")
def api_add_note(tid):
    t = get_owned_tache_or_404(tid)
    d = request.get_json(silent=True) or {}
    texte = clean_text(d.get('texte',''), 1000)
    if not texte: return jsonify({'msg':'Texte requis'}), 400
    if len(t.notes) >= 100: return jsonify({'msg':'Limite 100 notes'}), 400
    n = Note(texte=texte, tache_id=t.id)
    db.session.add(n); db.session.commit()
    return jsonify({'id':n.id,'texte':n.texte,'date':n.created_at.strftime('%d/%m/%Y %H:%M')}), 201


# ═══════════════════════════════════
# API PROJETS
# ═══════════════════════════════════
@app.route('/api/projets', methods=['GET'])
@login_required
def api_get_projets():
    projets = Projet.query.filter_by(user_id=current_user.id, archive=False).all()
    result = []
    for p in projets:
        total    = len(p.taches)
        termines = sum(1 for t in p.taches if t.terminee)
        taux     = round(termines/total*100) if total else 0
        result.append({'id':p.id,'nom':p.nom,'description':p.description,
            'couleur':p.couleur,'echeance':p.echeance,'total':total,'terminees':termines,'taux':taux,
            'membres':[{'id':m.user.id,'username':m.user.username,'avatar':m.user.avatar,'role':m.role} for m in p.membres]})
    return jsonify(result)

@app.route('/api/projets', methods=['POST'])
@login_required
@limiter.limit("20 per hour")
def api_create_projet():
    d = request.get_json(silent=True) or {}
    nom = clean_text(d.get('nom',''), 100)
    if not nom: return jsonify({'msg':'Nom requis'}), 400
    couleur = d.get('couleur','#58A6FF')
    if not validate_hex_color(couleur): couleur = '#58A6FF'
    echeance = clean_text(d.get('echeance',''), 10)
    if not validate_date(echeance): return jsonify({'msg':'Date invalide'}), 400
    if Projet.query.filter_by(user_id=current_user.id, archive=False).count() >= 30:
        return jsonify({'msg':'Limite 30 projets'}), 400
    p = Projet(nom=nom, description=clean_text(d.get('description',''),1000),
               couleur=couleur, echeance=echeance, user_id=current_user.id)
    db.session.add(p); db.session.commit()
    m = MembreProjet(projet_id=p.id, user_id=current_user.id, role='Proprietaire')
    db.session.add(m); db.session.commit()
    return jsonify({'id':p.id,'nom':p.nom,'couleur':p.couleur}), 201

@app.route('/api/projets/<int:pid>', methods=['PUT','DELETE'])
@login_required
def api_update_projet(pid):
    p = get_owned_projet_or_404(pid)
    if request.method == 'DELETE':
        p.archive = True; db.session.commit()
        return jsonify({'ok': True})
    d = request.get_json(silent=True) or {}
    if 'nom' in d:
        v = clean_text(d['nom'],100)
        if v: p.nom = v
    if 'description' in d: p.description = clean_text(d['description'],1000)
    if 'couleur' in d and validate_hex_color(d['couleur']): p.couleur = d['couleur']
    if 'echeance' in d:
        ech = clean_text(d['echeance'],10)
        if validate_date(ech): p.echeance = ech
    db.session.commit()
    return jsonify({'id':p.id,'nom':p.nom,'couleur':p.couleur})

@app.route('/api/projets/<int:pid>/membres', methods=['POST'])
@login_required
@limiter.limit("20 per hour")
def api_add_membre(pid):
    p = get_owned_projet_or_404(pid)
    d = request.get_json(silent=True) or {}
    email = clean_text(d.get('email',''),120).lower()
    if not validate_email(email): return jsonify({'ok':False,'msg':'Email invalide'}), 400
    role = d.get('role','Membre')
    if role not in ('Membre','Editeur','Observateur','Admin'): role = 'Membre'
    user = User.query.filter_by(email=email).first()
    if not user: return jsonify({'ok':False,'msg':'Utilisateur introuvable'}), 404
    if MembreProjet.query.filter_by(projet_id=pid, user_id=user.id).first():
        return jsonify({'ok':False,'msg':'Déjà membre'}), 409
    if len(p.membres) >= 50: return jsonify({'ok':False,'msg':'Limite 50 membres'}), 400
    m = MembreProjet(projet_id=pid, user_id=user.id, role=role)
    db.session.add(m); db.session.commit()
    return jsonify({'id':user.id,'username':user.username,'avatar':user.avatar,'role':m.role}), 201

@app.route('/api/projets/<int:pid>/membres/<int:uid>', methods=['DELETE'])
@login_required
def api_remove_membre(pid, uid):
    get_owned_projet_or_404(pid)
    m = MembreProjet.query.filter_by(projet_id=pid, user_id=uid).first_or_404()
    if m.role == 'Proprietaire': return jsonify({'ok':False,'msg':'Impossible de retirer le propriétaire'}), 403
    db.session.delete(m); db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/stats')
@login_required
def api_stats():
    return jsonify(get_stats(current_user.id))


# ═══════════════════════════════════
# GESTION ERREURS
# ═══════════════════════════════════
@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'): return jsonify({'msg':'Ressource introuvable'}), 404
    return render_template('error.html', code=404, message="Page introuvable"), 404

@app.errorhandler(403)
def forbidden(e):
    if request.path.startswith('/api/'): return jsonify({'msg':'Accès refusé'}), 403
    return render_template('error.html', code=403, message="Accès refusé"), 403

@app.errorhandler(429)
def too_many(e): return jsonify({'msg':'Trop de requêtes — réessaie plus tard'}), 429

@app.errorhandler(500)
def server_error(e):
    db.session.rollback()
    if request.path.startswith('/api/'): return jsonify({'msg':'Erreur serveur'}), 500
    return render_template('error.html', code=500, message="Erreur serveur"), 500

@app.errorhandler(413)
def too_large(e): return jsonify({'msg':'Requête trop volumineuse'}), 413


# ═══════════════════════════════════
# INIT BASE
# ═══════════════════════════════════
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=False, port=5000)
