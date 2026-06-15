"""
TaskFlow Pro - Application Web
Flask + SQLite + déployable sur Railway/Render/Heroku
"""
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date
import os, json

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'taskflow-secret-2024-change-me')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///taskflow.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ═══════════════════════════════════════════════════════════
# MODÈLES
# ═══════════════════════════════════════════════════════════

class User(UserMixin, db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    username   = db.Column(db.String(80), unique=True, nullable=False)
    email      = db.Column(db.String(120), unique=True, nullable=False)
    password   = db.Column(db.String(256), nullable=False)
    avatar     = db.Column(db.String(2), default='?')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    taches     = db.relationship('Tache', backref='owner', lazy=True,
                                  foreign_keys='Tache.user_id')
    projets    = db.relationship('Projet', backref='owner', lazy=True)


class Projet(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    nom         = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, default='')
    couleur     = db.Column(db.String(10), default='#58A6FF')
    echeance    = db.Column(db.String(10), default='')
    archive     = db.Column(db.Boolean, default=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    user_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    taches      = db.relationship('Tache', backref='projet', lazy=True)
    membres     = db.relationship('MembreProjet', backref='projet', lazy=True, cascade='all, delete-orphan')


class MembreProjet(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    projet_id  = db.Column(db.Integer, db.ForeignKey('projet.id'), nullable=False)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    role       = db.Column(db.String(20), default='Membre')
    joined_at  = db.Column(db.DateTime, default=datetime.utcnow)
    user       = db.relationship('User', foreign_keys=[user_id])


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
    temps_passe  = db.Column(db.Integer, default=0)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    projet_id    = db.Column(db.Integer, db.ForeignKey('projet.id'), nullable=True)
    assigne_a    = db.Column(db.String(100), default='')
    sous_taches  = db.relationship('SousTache', backref='tache', lazy=True, cascade='all, delete-orphan')
    notes        = db.relationship('Note', backref='tache', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        statut, ech_txt = statut_echeance(self.echeance)
        return {
            'id': self.id,
            'titre': self.titre,
            'description': self.description,
            'priorite': self.priorite,
            'categorie': self.categorie,
            'echeance': self.echeance,
            'echeance_txt': ech_txt,
            'echeance_statut': statut,
            'tags': self.tags.split(',') if self.tags else [],
            'terminee': self.terminee,
            'epinglee': self.epinglee,
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
    id        = db.Column(db.Integer, primary_key=True)
    titre     = db.Column(db.String(200), nullable=False)
    terminee  = db.Column(db.Boolean, default=False)
    tache_id  = db.Column(db.Integer, db.ForeignKey('tache.id'), nullable=False)

    def to_dict(self):
        return {'id': self.id, 'titre': self.titre, 'terminee': self.terminee}


class Note(db.Model):
    id        = db.Column(db.Integer, primary_key=True)
    texte     = db.Column(db.Text, nullable=False)
    tache_id  = db.Column(db.Integer, db.ForeignKey('tache.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ═══════════════════════════════════════════════════════════
# UTILITAIRES
# ═══════════════════════════════════════════════════════════

def statut_echeance(s):
    if not s: return '', ''
    try:
        e = datetime.strptime(s, '%Y-%m-%d').date()
        d = (e - date.today()).days
        if d < 0:  return 'retard',   f'Retard {-d}j'
        if d == 0: return 'auj',      "Aujourd'hui"
        if d == 1: return 'demain',   'Demain'
        if d <= 3: return 'bientot',  f'Dans {d}j'
        return 'ok', e.strftime('%d/%m/%Y')
    except: return '', ''


def get_stats(user_id):
    taches = Tache.query.filter_by(user_id=user_id).all()
    total     = len(taches)
    terminees = sum(1 for t in taches if t.terminee)
    en_cours  = total - terminees
    en_retard = sum(1 for t in taches if not t.terminee and statut_echeance(t.echeance)[0] == 'retard')
    taux = round(terminees / total * 100) if total else 0
    return {'total': total, 'terminees': terminees, 'en_cours': en_cours, 'en_retard': en_retard, 'taux': taux}


@login_manager.user_loader
def load_user(uid):
    return User.query.get(int(uid))


# ═══════════════════════════════════════════════════════════
# ROUTES AUTH
# ═══════════════════════════════════════════════════════════

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        data = request.get_json() or request.form
        user = User.query.filter_by(email=data.get('email', '').strip()).first()
        if user and check_password_hash(user.password, data.get('password', '')):
            login_user(user, remember=True)
            return jsonify({'ok': True}) if request.is_json else redirect(url_for('dashboard'))
        return jsonify({'ok': False, 'msg': 'Email ou mot de passe incorrect'}) if request.is_json else render_template('auth.html', error='Identifiants invalides')
    return render_template('auth.html')


@app.route('/register', methods=['POST'])
def register():
    data = request.get_json() or request.form
    username = data.get('username', '').strip()
    email    = data.get('email', '').strip()
    password = data.get('password', '')
    if not username or not email or not password:
        return jsonify({'ok': False, 'msg': 'Tous les champs sont requis'})
    if User.query.filter_by(email=email).first():
        return jsonify({'ok': False, 'msg': 'Email déjà utilisé'})
    if User.query.filter_by(username=username).first():
        return jsonify({'ok': False, 'msg': 'Nom d\'utilisateur déjà pris'})
    avatar = username[:2].upper()
    user = User(username=username, email=email,
                password=generate_password_hash(password), avatar=avatar)
    db.session.add(user); db.session.commit()
    login_user(user)
    return jsonify({'ok': True})


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# ═══════════════════════════════════════════════════════════
# ROUTES PRINCIPALES
# ═══════════════════════════════════════════════════════════

@app.route('/dashboard')
@login_required
def dashboard():
    stats   = get_stats(current_user.id)
    projets = Projet.query.filter_by(user_id=current_user.id, archive=False).all()
    return render_template('dashboard.html', stats=stats, projets=projets, user=current_user)


# ═══════════════════════════════════════════════════════════
# API TÂCHES
# ═══════════════════════════════════════════════════════════

@app.route('/api/taches', methods=['GET'])
@login_required
def api_get_taches():
    vue      = request.args.get('vue', 'toutes')
    cat      = request.args.get('cat', '')
    pid      = request.args.get('projet_id', '')
    rech     = request.args.get('q', '').strip().lower()
    tri      = request.args.get('tri', 'priorite')
    corbeille = request.args.get('corbeille', '0') == '1'

    q = Tache.query.filter_by(user_id=current_user.id)

    if vue == 'terminees':    q = q.filter_by(terminee=True)
    elif vue == 'encours':    q = q.filter_by(terminee=False)
    elif vue == 'epinglees':  q = q.filter_by(epinglee=True, terminee=False)

    if cat:  q = q.filter_by(categorie=cat)
    if pid:  q = q.filter_by(projet_id=int(pid))

    taches = q.all()

    # Filtres post-query
    if vue == 'retard':
        taches = [t for t in taches if not t.terminee and statut_echeance(t.echeance)[0] == 'retard']
    elif vue == 'auj':
        taches = [t for t in taches if not t.terminee and statut_echeance(t.echeance)[0] == 'auj']
    elif vue == 'haute':
        taches = [t for t in taches if not t.terminee and t.priorite in ('Haute', 'Urgente')]

    if rech:
        taches = [t for t in taches if rech in t.titre.lower() or rech in t.description.lower()
                  or any(rech in tg.strip().lower() for tg in t.tags.split(',') if tg.strip())]

    # Tri
    ordre = {'Urgente': 0, 'Haute': 1, 'Normale': 2, 'Basse': 3}
    if tri == 'priorite':
        taches.sort(key=lambda t: (not t.epinglee, t.terminee, ordre.get(t.priorite, 2)))
    elif tri == 'echeance':
        taches.sort(key=lambda t: t.echeance or '9999')
    elif tri == 'date':
        taches.sort(key=lambda t: t.created_at, reverse=True)
    elif tri == 'alpha':
        taches.sort(key=lambda t: t.titre.lower())

    return jsonify([t.to_dict() for t in taches])


@app.route('/api/taches', methods=['POST'])
@login_required
def api_create_tache():
    d = request.get_json()
    t = Tache(
        titre       = d.get('titre', '').strip(),
        description = d.get('description', ''),
        priorite    = d.get('priorite', 'Normale'),
        categorie   = d.get('categorie', 'General'),
        echeance    = d.get('echeance', ''),
        tags        = ','.join(d.get('tags', [])),
        projet_id   = d.get('projet_id') or None,
        assigne_a   = d.get('assigne_a', ''),
        user_id     = current_user.id,
    )
    db.session.add(t); db.session.commit()
    return jsonify(t.to_dict()), 201


@app.route('/api/taches/<int:tid>', methods=['GET'])
@login_required
def api_get_tache(tid):
    t = Tache.query.filter_by(id=tid, user_id=current_user.id).first_or_404()
    d = t.to_dict()
    d['notes'] = [{'id': n.id, 'texte': n.texte, 'date': n.created_at.strftime('%d/%m/%Y %H:%M')} for n in t.notes]
    return jsonify(d)


@app.route('/api/taches/<int:tid>', methods=['PUT'])
@login_required
def api_update_tache(tid):
    t = Tache.query.filter_by(id=tid, user_id=current_user.id).first_or_404()
    d = request.get_json()
    for field in ('titre', 'description', 'priorite', 'categorie', 'echeance', 'assigne_a'):
        if field in d: setattr(t, field, d[field])
    if 'tags' in d: t.tags = ','.join(d['tags'])
    if 'projet_id' in d: t.projet_id = d['projet_id'] or None
    if 'terminee' in d:
        t.terminee = d['terminee']
        t.completed_at = datetime.utcnow() if d['terminee'] else None
    if 'epinglee' in d: t.epinglee = d['epinglee']
    if 'temps_passe' in d: t.temps_passe = d['temps_passe']
    db.session.commit()
    return jsonify(t.to_dict())


@app.route('/api/taches/<int:tid>', methods=['DELETE'])
@login_required
def api_delete_tache(tid):
    t = Tache.query.filter_by(id=tid, user_id=current_user.id).first_or_404()
    db.session.delete(t); db.session.commit()
    return jsonify({'ok': True})


# ═══════════════════════════════════════════════════════════
# API SOUS-TÂCHES & NOTES
# ═══════════════════════════════════════════════════════════

@app.route('/api/taches/<int:tid>/sous_taches', methods=['POST'])
@login_required
def api_add_sous_tache(tid):
    t = Tache.query.filter_by(id=tid, user_id=current_user.id).first_or_404()
    d = request.get_json()
    st = SousTache(titre=d.get('titre', '').strip(), tache_id=tid)
    db.session.add(st); db.session.commit()
    return jsonify(st.to_dict()), 201


@app.route('/api/sous_taches/<int:sid>', methods=['PUT', 'DELETE'])
@login_required
def api_update_sous_tache(sid):
    st = SousTache.query.get_or_404(sid)
    if request.method == 'DELETE':
        db.session.delete(st); db.session.commit()
        return jsonify({'ok': True})
    d = request.get_json()
    if 'terminee' in d: st.terminee = d['terminee']
    if 'titre' in d: st.titre = d['titre']
    db.session.commit()
    return jsonify(st.to_dict())


@app.route('/api/taches/<int:tid>/notes', methods=['POST'])
@login_required
def api_add_note(tid):
    t = Tache.query.filter_by(id=tid, user_id=current_user.id).first_or_404()
    d = request.get_json()
    n = Note(texte=d.get('texte', '').strip(), tache_id=tid)
    db.session.add(n); db.session.commit()
    return jsonify({'id': n.id, 'texte': n.texte, 'date': n.created_at.strftime('%d/%m/%Y %H:%M')}), 201


# ═══════════════════════════════════════════════════════════
# API PROJETS
# ═══════════════════════════════════════════════════════════

@app.route('/api/projets', methods=['GET'])
@login_required
def api_get_projets():
    projets = Projet.query.filter_by(user_id=current_user.id, archive=False).all()
    result = []
    for p in projets:
        total    = len(p.taches)
        termines = sum(1 for t in p.taches if t.terminee)
        taux     = round(termines / total * 100) if total else 0
        result.append({
            'id': p.id, 'nom': p.nom, 'description': p.description,
            'couleur': p.couleur, 'echeance': p.echeance,
            'total': total, 'terminees': termines, 'taux': taux,
            'membres': [{'id': m.user.id, 'username': m.user.username,
                         'avatar': m.user.avatar, 'role': m.role} for m in p.membres],
        })
    return jsonify(result)


@app.route('/api/projets', methods=['POST'])
@login_required
def api_create_projet():
    d = request.get_json()
    p = Projet(nom=d.get('nom', '').strip(), description=d.get('description', ''),
               couleur=d.get('couleur', '#58A6FF'), echeance=d.get('echeance', ''),
               user_id=current_user.id)
    db.session.add(p); db.session.commit()
    # Ajoute le créateur comme propriétaire
    m = MembreProjet(projet_id=p.id, user_id=current_user.id, role='Proprietaire')
    db.session.add(m); db.session.commit()
    return jsonify({'id': p.id, 'nom': p.nom, 'couleur': p.couleur}), 201


@app.route('/api/projets/<int:pid>', methods=['PUT', 'DELETE'])
@login_required
def api_update_projet(pid):
    p = Projet.query.filter_by(id=pid, user_id=current_user.id).first_or_404()
    if request.method == 'DELETE':
        p.archive = True; db.session.commit()
        return jsonify({'ok': True})
    d = request.get_json()
    for field in ('nom', 'description', 'couleur', 'echeance'):
        if field in d: setattr(p, field, d[field])
    db.session.commit()
    return jsonify({'id': p.id, 'nom': p.nom, 'couleur': p.couleur})


@app.route('/api/projets/<int:pid>/membres', methods=['POST'])
@login_required
def api_add_membre(pid):
    p = Projet.query.filter_by(id=pid, user_id=current_user.id).first_or_404()
    d = request.get_json()
    email = d.get('email', '').strip()
    user  = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({'ok': False, 'msg': 'Utilisateur introuvable'}), 404
    if MembreProjet.query.filter_by(projet_id=pid, user_id=user.id).first():
        return jsonify({'ok': False, 'msg': 'Déjà membre'}), 409
    m = MembreProjet(projet_id=pid, user_id=user.id, role=d.get('role', 'Membre'))
    db.session.add(m); db.session.commit()
    return jsonify({'id': user.id, 'username': user.username, 'avatar': user.avatar, 'role': m.role}), 201


@app.route('/api/projets/<int:pid>/membres/<int:uid>', methods=['DELETE'])
@login_required
def api_remove_membre(pid, uid):
    m = MembreProjet.query.filter_by(projet_id=pid, user_id=uid).first_or_404()
    if m.role == 'Proprietaire':
        return jsonify({'ok': False, 'msg': 'Impossible de retirer le propriétaire'}), 403
    db.session.delete(m); db.session.commit()
    return jsonify({'ok': True})


# ═══════════════════════════════════════════════════════════
# API STATS
# ═══════════════════════════════════════════════════════════

@app.route('/api/stats')
@login_required
def api_stats():
    return jsonify(get_stats(current_user.id))


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5000)

# migration route added
