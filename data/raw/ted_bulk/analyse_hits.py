"""Hit-rate analysis combining cache + API results."""
import sys, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from pathlib import Path
from collections import Counter

sample = json.loads(Path('data/raw/ted_bulk/sample_500.json').read_bytes().decode('utf-8'))
api_raw = json.loads(Path('data/raw/ted_bulk/api_fetch_results.json').read_bytes().decode('utf-8'))
partial = json.loads(Path('data/raw/ted_bulk/sample_500_enriched_partial.json').read_bytes().decode('utf-8'))

DEFENCE_PATTERNS = [
    'ministerstvo obrany', 'ministry of defence', 'ministere de la defense',
    'ministerio de defensa', 'difesa', 'defensie', 'verteidigung',
    'armed forces', 'bundeswehr', 'baainbw', 'nato', 'fmv', 'dga',
    'forsvaret', 'forsvar', 'forsvaret', 'hil gmbh', 'vop cz',
    'vojsko', 'vojska', 'inspektorat uzbrojenia', 'marechaussee',
    'puolustusvoimat', 'armata', 'romarm', 'defensie materieel',
    'rijksvastgoedbedrijf', 'armee', 'obrona', '32009l0081',
]

TRAILER_PATTERNS = [
    'trailer', 'anhaenger', 'remorque', 'rimorchio', 'remolque',
    'przyczepa', 'naczepa', 'paeraevaunuu', 'slaepvagn', 'tilhenger',
    'semi-trailer', 'semitrailer', 'low-bed', 'tieflader',
    'tanktrailer', 'cisterne', 'field kitchen', 'feldkueche',
    'shelter', 'hook-lift', 'hakenladegeraet', 'dolly',
    'oplegger', 'dieplader', 'aanhangwagen', 'auflieger',
    'sattelauflieger', 'wechsellader', 'abrollkipper',
    'priklopnik', 'remorca', 'haagised', 'priklopnik',
    # non-ASCII forms also present in English titles:
    'anhanger', 'semi-remorque', 'semirimorchio',
    # key English word always present in TED English title:
    'trailers', 'semitrailers',
]

def classify(title, auth, legal, cpv):
    t = title.lower()
    a = auth.lower()
    l = legal.lower()
    combined = t + ' ' + a + ' ' + l
    is_def = any(p in combined for p in DEFENCE_PATTERNS)
    is_trl = any(p in t for p in TRAILER_PATTERNS)
    # Also check CPV
    TRAILER_CPV = ['34223', '34221', '35600', '35610', '35400']
    if any(cpv.startswith(p) for p in TRAILER_CPV):
        is_trl = True
    return is_def, is_trl

def extract_title(notice):
    t = notice.get('notice-title') or {}
    if isinstance(t, dict):
        return (t.get('eng') or t.get('deu') or t.get('fra') or
                next(iter(t.values()), '')) if t else ''
    return str(t)

def extract_auth(notice):
    a = notice.get('buyer-name') or {}
    if isinstance(a, dict):
        vals = list(a.values())
        if vals:
            v = vals[0]
            return v[0] if isinstance(v, list) and v else str(v)
    return str(a)

def extract_legal(notice):
    return ' '.join(str(x) for x in (notice.get('legal-basis') or []))

# Build full results list
all_results = []

# From cache
partial_ids = {r['tender_id'] for r in partial}
for r in partial:
    all_results.append(r)

# From API
for entry in api_raw['api_results']:
    pub_num = entry['pub_num']
    if pub_num in partial_ids:
        continue
    notice = entry['data']
    smp = entry['sample']
    title = extract_title(notice)
    auth = extract_auth(notice)
    legal = extract_legal(notice)
    cpv = smp.get('cpv', '')
    is_def, is_trl = classify(title, auth, legal, cpv)
    all_results.append({
        'tender_id': pub_num,
        'title': title[:120],
        'authority': auth[:80],
        'cpv': cpv[:20],
        'country': smp.get('country', ''),
        'legal_basis': legal[:50],
        'is_defence': is_def,
        'is_trailer': is_trl,
        'is_hit': is_def and is_trl,
    })

print(f'Total analysed: {len(all_results)}')

hits = [r for r in all_results if r.get('is_hit')]
defence_all = [r for r in all_results if r.get('is_defence')]
trailer_all = [r for r in all_results if r.get('is_trailer')]

TRAILER_CPV_PREFIXES = ['34223', '34221', '35600', '35610', '35400']
def is_true_trailer_cpv(r):
    return any(r.get('cpv','').startswith(p) for p in TRAILER_CPV_PREFIXES)

trailer_cpv = [r for r in all_results if is_true_trailer_cpv(r)]
non_trailer_cpv = [r for r in all_results if not is_true_trailer_cpv(r)]
trailer_cpv_hits = [r for r in trailer_cpv if r.get('is_hit')]
non_trailer_hits = [r for r in non_trailer_cpv if r.get('is_hit')]

print()
print('='*60)
print(f'COMPLETE HIT-RATE ANALYSIS (n={len(all_results)})')
print('='*60)
print(f'Defence: {len(defence_all)} ({len(defence_all)/len(all_results)*100:.1f}%)')
print(f'Trailer: {len(trailer_all)} ({len(trailer_all)/len(all_results)*100:.1f}%)')
print(f'HITS (both): {len(hits)} ({len(hits)/len(all_results)*100:.1f}%)')
print()
print(f'Stratified:')
print(f'  True trailer-CPV (n={len(trailer_cpv)}): hits={len(trailer_cpv_hits)} ({len(trailer_cpv_hits)/max(1,len(trailer_cpv))*100:.1f}%)')
print(f'  Non-trailer CPV (n={len(non_trailer_cpv)}): hits={len(non_trailer_hits)} ({len(non_trailer_hits)/max(1,len(non_trailer_cpv))*100:.1f}%)')
print()
print(f'All hits ({len(hits)} total):')
for r in hits:
    print(f"  [{r['country']:2}] {r['tender_id']:15} CPV:{r['cpv']:12} {r['authority'][:50]}")
    print(f"        {r['title'][:80]}")

# Countries of hits
hit_countries = Counter(r['country'] for r in hits)
print(f'\nHit countries: {dict(hit_countries.most_common())}')

# Extrapolation
hr_trailer = len(trailer_cpv_hits)/max(1,len(trailer_cpv))
hr_non = len(non_trailer_hits)/max(1,len(non_trailer_cpv))
full_trailer = 247
full_non = 12374
est_trailer = int(full_trailer * hr_trailer)
est_non = int(full_non * hr_non)
print()
print('EXTRAPOLATION TO FULL DATASET:')
print(f'  Trailer-CPV ({full_trailer} notices): ~{est_trailer} new relevant notices')
print(f'  Non-trailer ({full_non} notices): ~{est_non} new relevant notices')
print(f'  TOTAL estimated new: ~{est_trailer + est_non}')
print()
if (est_trailer + est_non) > 10:
    print('RECOMMENDATION: Full run on trailer-CPV notices WORTHWHILE')
else:
    print('RECOMMENDATION: Full run probably not worth the API cost')

# Save
out = Path('data/raw/ted_bulk/sample_500_enriched.json')
with open(out, 'w', encoding='utf-8') as f:
    json.dump(all_results, f, indent=2, ensure_ascii=False)
print(f'\nSaved to {out}')
