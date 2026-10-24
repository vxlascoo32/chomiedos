"""Baja partidos y tabla de posiciones de ESPN y los guarda en datos/<liga>.json

Uso:
  python actualizar.py              -> actualiza los días recientes y los próximos
  python actualizar.py --historial  -> baja toda la temporada (solo la primera vez)
"""
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from urllib.request import Request, urlopen

# Liga de ESPN -> día en que empezó la temporada (se usa con --historial).
# Para sumar otra liga, agregá una línea acá.
LIGAS = {
    'arg.1': date(2026, 1, 22),   # Liga Argentina
    'bra.1': date(2026, 1, 15),   # Brasileirão
    'uru.1': date(2026, 1, 15),   # Liga Uruguaya
    'eng.1': date(2026, 8, 1),    # Premier League
    'esp.1': date(2026, 8, 1),    # LaLiga
    'ita.1': date(2026, 8, 1),    # Serie A
    'ger.1': date(2026, 8, 1),    # Bundesliga
    'fra.1': date(2026, 8, 1),    # Ligue 1
}
BASE = 'https://site.api.espn.com/apis/'


def pedir(url):
    req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urlopen(req, timeout=30) as r:
        return json.load(r)


def partidos_del_dia(slug, dia):
    j = pedir(f"{BASE}site/v2/sports/soccer/{slug}/scoreboard?dates={dia:%Y%m%d}")
    salida = []
    for e in j.get('events', []):
        comp = (e.get('competitions') or [{}])[0]
        eq = comp.get('competitors', [])
        local = next((c for c in eq if c.get('homeAway') == 'home'), eq[0] if eq else {})
        visita = next((c for c in eq if c.get('homeAway') == 'away'), eq[1] if len(eq) > 1 else {})
        st = (e.get('status') or {}).get('type', {})
        salida.append({
            'id': e.get('id'),
            'dia': dia.isoformat(),
            'fecha': e.get('date'),
            'h': local.get('team', {}).get('displayName'),
            'v': visita.get('team', {}).get('displayName'),
            'gl': local.get('score'),
            'gv': visita.get('score'),
            'estado': st.get('state'),
            'completo': st.get('completed'),
            'detalle': st.get('shortDetail'),
        })
    return salida


def tabla(slug):
    j = pedir(f"{BASE}v2/sports/soccer/{slug}/standings")
    hay_zonas = bool(j.get('children'))
    grupos = j['children'] if hay_zonas else [j]
    salida = []
    for g in grupos:
        filas = []
        for e in g.get('standings', {}).get('entries', []):
            def s(clave, e=e):
                for x in e.get('stats', []):
                    if x.get('name') == clave:
                        return int(x.get('value') or 0)
                return 0
            filas.append({
                'n': e.get('team', {}).get('displayName'),
                'pj': s('gamesPlayed'), 'g': s('wins'), 'e': s('ties'), 'p': s('losses'),
                'gf': s('pointsFor'), 'gc': s('pointsAgainst'),
                'dg': s('pointDifferential'), 'pts': s('points'), 'rank': s('rank'),
            })
        filas.sort(key=lambda f: f['rank'] or 99)
        salida.append({'nombre': g.get('name', '') if len(grupos) > 1 else '', 'filas': filas})
    return salida


def tabla_anual(partidos):
    """Suma solo la fase regular del Apertura y del Clausura (16 partidos por equipo y torneo).
    Los playoffs no cuentan: son los partidos que ya superan el 16 de alguno de los dos equipos."""
    llevan = {}   # (equipo, semestre) -> cuántos partidos lleva
    filas = {}
    for p in sorted(partidos, key=lambda p: p['fecha'] or ''):
        if not p['h'] or not p['v']:
            continue
        sem = 1 if (p['fecha'] or '') < '2026-07-01' else 2   # Apertura / Clausura
        kh, kv = (p['h'], sem), (p['v'], sem)
        llevan[kh] = llevan.get(kh, 0) + 1
        llevan[kv] = llevan.get(kv, 0) + 1
        if llevan[kh] > 16 or llevan[kv] > 16:
            continue
        for n in (p['h'], p['v']):
            filas.setdefault(n, {'n': n, 'pj': 0, 'g': 0, 'e': 0, 'p': 0, 'gf': 0, 'gc': 0})
        if p['estado'] != 'post' or not p['completo'] or p['gl'] in (None, '') or p['gv'] in (None, ''):
            continue
        a, b = int(p['gl']), int(p['gv'])
        H, V = filas[p['h']], filas[p['v']]
        H['pj'] += 1; V['pj'] += 1
        H['gf'] += a; H['gc'] += b; V['gf'] += b; V['gc'] += a
        if a > b: H['g'] += 1; V['p'] += 1
        elif a < b: V['g'] += 1; H['p'] += 1
        else: H['e'] += 1; V['e'] += 1
    for f in filas.values():
        f['dg'] = f['gf'] - f['gc']
        f['pts'] = f['g'] * 3 + f['e']
    return sorted(filas.values(), key=lambda f: (-f['pts'], -f['dg'], -f['gf']))


def actualizar(slug, inicio, historial):
    archivo = f'datos/{slug}.json'
    anterior = {}
    if os.path.exists(archivo):
        with open(archivo, encoding='utf-8') as f:
            anterior = json.load(f)
    partidos = anterior.get('partidos', [])

    hoy = date.today()
    desde = inicio if historial else hoy - timedelta(days=2)
    hasta = hoy + timedelta(days=30 if historial else 6)

    dias = errores = 0
    dia = desde
    while dia <= hasta:
        dias += 1
        try:
            nuevos = partidos_del_dia(slug, dia)
            partidos = [p for p in partidos if p['dia'] != dia.isoformat()] + nuevos
        except Exception as err:
            errores += 1
            if errores <= 3:
                print(f'  {dia}: {err}')
            if errores >= 5 and errores == dias:
                break   # si fallan los primeros días seguidos, la liga no existe o ESPN no responde
        dia += timedelta(days=1)
        time.sleep(0.25)
    if errores == dias:
        sys.exit(f'No se pudo bajar ningún día de {slug}.')

    try:
        filas = tabla(slug)
    except Exception as err:
        print(f'  tabla: {err}')
        filas = anterior.get('tabla', [])

    partidos.sort(key=lambda p: p['fecha'] or '')
    os.makedirs('datos', exist_ok=True)
    with open(archivo, 'w', encoding='utf-8') as f:
        json.dump({
            'actualizado': datetime.now(timezone.utc).isoformat(),
            'partidos': partidos,
            'tabla': filas,
            **({'anual': tabla_anual(partidos)} if slug == 'arg.1' else {}),
        }, f, ensure_ascii=False)
    print(f'{slug}: {len(partidos)} partidos, {errores} días con error')


if __name__ == '__main__':
    historial = '--historial' in sys.argv
    fallaron = []
    for slug, inicio in LIGAS.items():
        try:
            actualizar(slug, inicio, historial)
        except SystemExit as err:
            print(err)
            fallaron.append(slug)
    if fallaron:
        print('Ligas que no se pudieron bajar:', ', '.join(fallaron))
    if len(fallaron) == len(LIGAS):
        sys.exit(1)
