"""Baja partidos y tabla de posiciones de ESPN y los guarda en datos/<liga>.json

Uso:
  python actualizar.py              -> modo normal (lo que corre cada 5 minutos)
  python actualizar.py --historial  -> baja toda la temporada (solo la primera vez)
  python actualizar.py --forzar     -> revisa todo ahora, aunque no haya partidos
"""
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from urllib.request import Request, urlopen

# Liga de ESPN -> día en que empezó la temporada (se usa con --historial).
# Para sumar otra liga, agregá una línea acá (y la misma en index.html).
LIGAS = {
    'arg.1': date(2026, 1, 22),   # Liga Argentina
    'arg.2': date(2026, 1, 20),   # Primera Nacional
    'bra.1': date(2026, 1, 15),   # Brasileirão
    'uru.1': date(2026, 1, 15),   # Liga Uruguaya
    'eng.1': date(2026, 8, 1),    # Premier League
    'esp.1': date(2026, 8, 1),    # LaLiga
    'ita.1': date(2026, 8, 1),    # Serie A
    'ger.1': date(2026, 8, 1),    # Bundesliga
    'fra.1': date(2026, 8, 1),    # Ligue 1
}
BASE = 'https://site.api.espn.com/apis/'

# Marcas de posiciones para las tablas que ESPN no marca: (desde, hasta, texto, color).
# Los números negativos cuentan desde el final (-1 = último).
REGLAS = {
    'arg.1': {
        'torneo': [(1, 8, 'Playoffs', '#2fa866')],
        'anual': [(1, 3, 'Copa Libertadores*', '#2b7bd6'),
                  (4, 9, 'Copa Sudamericana*', '#e3a21a'),
                  (-1, -1, 'Descenso', '#d64545')],
    },
}
HEX = re.compile(r'#?[0-9a-fA-F]{6}')


def pedir(url):
    ultimo = None
    for _ in range(2):
        try:
            req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urlopen(req, timeout=20) as r:
                return json.load(r)
        except Exception as err:
            ultimo = err
            time.sleep(1)
    raise ultimo


def goles_de(comp, local, visita):
    """Goles del partido: lado ('h' local, 'v' visita), jugador, minuto y tipo (p = penal, e = en contra)."""
    lados = {local.get('team', {}).get('id'): 'h', visita.get('team', {}).get('id'): 'v'}
    salida = []
    for d in comp.get('details') or []:
        if not d.get('scoringPlay'):
            continue
        if 'shootout' in str((d.get('type') or {}).get('text', '')).lower():
            continue
        lado = lados.get((d.get('team') or {}).get('id'))
        if not lado:
            continue
        jugadores = d.get('athletesInvolved') or [{}]
        salida.append({
            'l': lado,
            'n': jugadores[0].get('displayName') or jugadores[0].get('shortName') or '',
            'm': (d.get('clock') or {}).get('displayValue', ''),
            't': 'p' if d.get('penaltyKick') else 'e' if d.get('ownGoal') else '',
        })
    return salida


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
            'goles': goles_de(comp, local, visita),
        })
    return salida


def marcar(filas, reglas):
    """Pone la marca (clasificación, descenso, etc.) a las filas que no la traen de ESPN."""
    n = len(filas)
    for i, f in enumerate(filas, 1):
        if f.get('nota'):
            continue
        for a, b, texto, color in reglas:
            desde = a if a > 0 else n + a + 1
            hasta = b if b > 0 else n + b + 1
            if desde <= i <= hasta:
                f['nota'] = {'d': texto, 'c': color}
                break


def tabla(slug):
    j = pedir(f"{BASE}v2/sports/soccer/{slug}/standings")
    grupos = j['children'] if j.get('children') else [j]
    salida = []
    for g in grupos:
        filas = []
        for e in g.get('standings', {}).get('entries', []):
            def s(clave, e=e):
                for x in e.get('stats', []):
                    if x.get('name') == clave:
                        return int(x.get('value') or 0)
                return 0
            fila = {
                'n': e.get('team', {}).get('displayName'),
                'pj': s('gamesPlayed'), 'g': s('wins'), 'e': s('ties'), 'p': s('losses'),
                'gf': s('pointsFor'), 'gc': s('pointsAgainst'),
                'dg': s('pointDifferential'), 'pts': s('points'), 'rank': s('rank'),
            }
            nota = e.get('note') or {}
            if nota.get('description'):
                c = nota.get('color') or ''
                c = c if c.startswith('#') else '#' + c
                fila['nota'] = {'d': nota['description'], 'c': c if HEX.fullmatch(c) else '#888888'}
            filas.append(fila)
        filas.sort(key=lambda f: f['rank'] or 99)
        marcar(filas, REGLAS.get(slug, {}).get('torneo', []))
        salida.append({'nombre': g.get('name', '') if len(grupos) > 1 else '', 'filas': filas})
    return salida


def tabla_anual(partidos, slug):
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
    orden = sorted(filas.values(), key=lambda f: (-f['pts'], -f['dg'], -f['gf']))
    marcar(orden, REGLAS.get(slug, {}).get('anual', []))
    return orden


def hay_actividad(partidos):
    """True si hay un partido en juego, por empezar (15 min) o que terminó hace menos de 3 horas."""
    ahora = datetime.now(timezone.utc)
    for p in partidos:
        if p.get('estado') == 'in':
            return True
        try:
            f = datetime.fromisoformat(p['fecha'].replace('Z', '+00:00'))
        except Exception:
            continue
        if ahora - timedelta(hours=3) <= f <= ahora + timedelta(minutes=15):
            return True
    return False


def actualizar(slug, inicio, historial, forzar):
    archivo = f'datos/{slug}.json'
    anterior = {}
    if os.path.exists(archivo):
        with open(archivo, encoding='utf-8') as f:
            anterior = json.load(f)
    partidos = anterior.get('partidos', [])

    ahora = datetime.now(timezone.utc)
    revision_completa = historial or forzar or not anterior or ahora.minute < 10   # una vez por hora
    activa = hay_actividad(partidos)
    if not (revision_completa or activa):
        print(f'{slug}: sin partidos activos, se salta')
        return

    hoy = date.today()
    if historial:
        desde, hasta = inicio, hoy + timedelta(days=30)
    elif revision_completa:
        desde, hasta = hoy - timedelta(days=2), hoy + timedelta(days=6)
    else:
        desde, hasta = hoy - timedelta(days=1), hoy + timedelta(days=1)   # rápido: solo hoy y alrededores

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

    partidos.sort(key=lambda p: (p['fecha'] or '', p['id'] or ''))
    nuevo = {'partidos': partidos, 'tabla': filas}
    if slug == 'arg.1':
        nuevo['anual'] = tabla_anual(partidos, slug)

    previo = {k: v for k, v in anterior.items() if k != 'actualizado'}
    if nuevo == previo:
        print(f'{slug}: sin cambios')
        return   # no se escribe nada, así GitHub no registra cambios de más
    os.makedirs('datos', exist_ok=True)
    with open(archivo, 'w', encoding='utf-8') as f:
        json.dump({'actualizado': ahora.isoformat(), **nuevo}, f, ensure_ascii=False)
    print(f'{slug}: {len(partidos)} partidos, {errores} días con error')


if __name__ == '__main__':
    historial = '--historial' in sys.argv
    forzar = '--forzar' in sys.argv
    fallaron = []
    for slug, inicio in LIGAS.items():
        try:
            actualizar(slug, inicio, historial, forzar)
        except SystemExit as err:
            print(err)
            fallaron.append(slug)
    if fallaron:
        print('Ligas que no se pudieron bajar:', ', '.join(fallaron))
    if len(fallaron) == len(LIGAS):
        sys.exit(1)
