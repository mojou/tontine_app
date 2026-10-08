"""Explore toutes les routes, pour tous les comptes : aucune réponse ne doit être une erreur 500."""
import os
import sys
import traceback

S, P, DB = sys.argv[1], sys.argv[2], sys.argv[3]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, DB).replace(os.sep, '/')
sys.path.insert(0, P)
os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402
import models as md  # noqa: E402

app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, PROPAGATE_EXCEPTIONS=True,
                  UPLOAD_FOLDER=os.path.join(S, 'uploads'))

PARAM_MODELS = {
    'member_id': md.Member, 'transaction_id': md.Transaction, 'loan_id': md.Loan, 'sanction_id': md.Sanction,
    'meeting_id': md.Announcement, 'annonce_id': md.Announcement, 'cycle_id': md.TontineCycleDetail,
    'aide_id': md.Aide, 'poll_id': md.Poll, 'guarantee_id': md.LoanGuarantor, 'seance_id': md.Seance,
    'photo_id': md.GalleryPhoto, 'rubrique_id': md.ContributionType, 'tontine_id': md.Tontine,
}
SKIP_POST = {'logout'}  # la déconnexion casserait la session de test

with app.app_context():
    users = [(u.id, u.role, u.username, u.tontine_id) for u in md.User.query.filter_by(is_active=True).all()]
    samples = {}
    for param, model in PARAM_MODELS.items():
        rows = model.query.all()
        samples[param] = {getattr(r, 'tontine_id', None): r.id for r in rows}
        samples[param]['any'] = rows[0].id if rows else 99999

rules = [r for r in app.url_map.iter_rules() if r.endpoint != 'static']
problems, requests_done = [], 0


def build(rule, tontine_id):
    values = {}
    for arg in rule.arguments:
        if arg == 'token':
            values[arg] = 'jeton-invalide'
        elif arg == 'slug':
            values[arg] = 'jsb'
        elif arg in samples:
            values[arg] = samples[arg].get(tontine_id, samples[arg]['any'])
        else:
            return None
    return values


def hit(client, method, url, who):
    global requests_done
    requests_done += 1
    try:
        r = client.open(url, method=method, data={} if method == 'POST' else None)
        if r.status_code >= 500:
            problems.append((who, method, url, r.status_code))
    except Exception as exc:
        problems.append((who, method, url, ''.join(traceback.format_exception_only(type(exc), exc)).strip()[:200]))


accounts = [(None, 'ANONYME', 'anonyme', None)] + users
for uid, role, name, tid in accounts:
    for rule in rules:
        values = build(rule, tid)
        if values is None:
            continue
        with app.test_request_context():
            url = m.url_for(rule.endpoint, **values)
        for method in ('GET', 'POST'):
            if method not in rule.methods or (method == 'POST' and rule.endpoint in SKIP_POST):
                continue
            # Copie de base neuve par compte et par méthode pour que les POST destructifs n'influencent pas la suite
            client = app.test_client()
            if uid:
                with client.session_transaction() as sess:
                    sess['_user_id'] = str(uid)
                    sess['_fresh'] = True
            hit(client, method, url, f'{role}:{name}')

print(f'{len(accounts)} comptes, {len(rules)} routes, {requests_done} requêtes')
print('ERREURS:', len(problems))
seen = set()
for who, method, url, status in problems:
    key = (method, url.split('?')[0], str(status)[:80])
    if key in seen:
        continue
    seen.add(key)
    print(f'  {method} {url} [{who}] -> {status}')
