"""Entrées malveillantes / incohérentes : aucune ne doit provoquer d'erreur 500."""
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

BAD_QUERY = [
    {'page': '-1'}, {'page': '0'}, {'per_page': '0'}, {'per_page': '-3'}, {'per_page': '100000'},
    {'date_debut': 'zz', 'date_fin': '2026-13-45'}, {'year': '-5'}, {'year': '0'}, {'year': '99999'},
    {'status': "x' OR 1=1--"}, {'sort': 'x', 'order': 'x'}, {'type': '<script>'}, {'member_id': 'abc'},
    {'reveal': 'abc'}, {'t': '../../etc'}, {'search': '%' * 50}, {'pool_amount': 'NaN'}, {'pool_amount': '-1'},
    {'pool_amount': 'Infinity'}, {'include_sanctions': 'on', 'pool_amount': '1e400'},
]
BAD_VALUES = ['abc', '-5', 'NaN', 'Infinity', '-Infinity', '1e400', '', '0', '9' * 30, '1,5', ' 12 ']
NUMERIC_FIELDS = ['amount', 'bid_amount', 'pool_amount', 'custom_amount', 'frequency_days', 'presence_amount',
                  'fonds_caisse_amount', 'loan_interest_rate', 'max_aid_per_member', 'guarantee_threshold',
                  'guarantors_min', 'duration_months', 'display_order', 'participant_id', 'guarantor_id',
                  'option_id', 'member_id', 'contribution_type_id', 'year']

with app.app_context():
    users = [(u.id, u.role, u.tontine_id) for u in md.User.query.filter_by(is_active=True).all()
             if u.role in ('PRESIDENT', 'TRESORIER', 'SUPERADMIN', 'MEMBRE')]
    samples = {}
    for param, model in {'member_id': md.Member, 'transaction_id': md.Transaction, 'loan_id': md.Loan,
                         'sanction_id': md.Sanction, 'meeting_id': md.Announcement, 'annonce_id': md.Announcement,
                         'cycle_id': md.TontineCycleDetail, 'aide_id': md.Aide, 'poll_id': md.Poll,
                         'guarantee_id': md.LoanGuarantor, 'seance_id': md.Seance, 'photo_id': md.GalleryPhoto,
                         'rubrique_id': md.ContributionType, 'tontine_id': md.Tontine}.items():
        samples[param] = {getattr(r, 'tontine_id', None): r.id for r in model.query.all()}

rules = [r for r in app.url_map.iter_rules() if r.endpoint not in ('static', 'logout')]
problems, count = [], 0


def url_for_rule(rule, tid):
    values = {}
    for arg in rule.arguments:
        if arg == 'token':
            values[arg] = 'x'
        elif arg == 'slug':
            values[arg] = 'jsb'
        elif arg in samples and samples[arg]:
            values[arg] = samples[arg].get(tid, next(iter(samples[arg].values())))
        else:
            return None
    with app.test_request_context():
        return m.url_for(rule.endpoint, **values)


for uid, role, tid in users:
    for rule in rules:
        url = url_for_rule(rule, tid)
        if not url:
            continue
        cases = []
        if 'GET' in rule.methods:
            cases += [('GET', url, q, None) for q in BAD_QUERY]
        if 'POST' in rule.methods:
            for v in BAD_VALUES:
                cases.append(('POST', url, None, {f: v for f in NUMERIC_FIELDS} | {'action': 'execute', 'mode': 'ENCHERE'}))
        for method, u, query, data in cases:
            client = app.test_client()
            with client.session_transaction() as sess:
                sess['_user_id'] = str(uid)
                sess['_fresh'] = True
            count += 1
            try:
                r = client.open(u, method=method, query_string=query, data=data)
                if r.status_code >= 500:
                    problems.append((role, method, u, query or data.get('amount'), r.status_code))
            except Exception as exc:
                problems.append((role, method, u, query or data.get('amount'),
                                 ''.join(traceback.format_exception_only(type(exc), exc)).strip()[:160]))

print(f'{count} requêtes piégées')
print('ERREURS:', len(problems))
seen = set()
for role, method, u, payload, err in problems:
    key = (method, u.split('?')[0], str(err)[:60])
    if key in seen:
        continue
    seen.add(key)
    print(f'  {method} {u} {payload} [{role}] -> {err}')
