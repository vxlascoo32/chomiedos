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
import unicodedata
from datetime import date, datetime, timedelta, timezone
from urllib.request import Request, urlopen

# Liga de ESPN -> día en que empezó la temporada (se usa con --historial).
# Para sumar otra liga, agregá una línea acá (y la misma en index.html).
LIGAS = {
    'arg.1': date(2026, 1, 22),   # Liga Profesional de Fútbol
    'arg.2': date(2026, 1, 20),   # Primera Nacional
    'arg.copa': date(2026, 1, 20),  # Copa Argentina
    'bra.1': date(2026, 1, 15),   # Brasileirão
    'bra.copa_do_brazil': date(2026, 2, 1),  # Copa de Brasil
    'uru.1': date(2026, 1, 15),   # Liga AUF Uruguaya
    'uru.copa_auf_uruguay': date(2026, 1, 20),  # Copa AUF Uruguay
    'col.1': date(2026, 1, 15),   # Liga BetPlay Dimayor
    'chi.1': date(2026, 1, 20),   # Liga de Primera
    'eng.1': date(2026, 8, 1),    # Premier League
    'esp.1': date(2026, 8, 1),    # LaLiga
    'ita.1': date(2026, 8, 1),    # Serie A
    'ger.1': date(2026, 8, 1),    # Bundesliga
    'fra.1': date(2026, 8, 1),    # Ligue 1
    'conmebol.libertadores': date(2026, 2, 1),  # CONMEBOL Libertadores
    'conmebol.sudamericana': date(2026, 2, 1),  # CONMEBOL Sudamericana
}
BASE = 'https://site.api.espn.com/apis/'

# Marcas de posiciones para las tablas que ESPN no marca: (desde, hasta, texto, color).
# Los números negativos cuentan desde el final (-1 = último).
REGLAS = {
    'arg.1': {
        'apertura': [(1, 1, 'Ganador del Torneo Apertura', '#2fa866'),
                     (2, 8, 'Playoffs', '#e3a21a')],
        'clausura': [(1, 1, 'Ganador del Torneo Clausura', '#2fa866'),
                     (2, 8, 'Playoffs', '#e3a21a')],
        'anual': [(1, 3, 'Copa Libertadores', '#2b7bd6'),
                  (4, 8, 'Copa Sudamericana', '#e3a21a')],
        'promedios': [(-1, -1, 'Descenso', '#d64545')],
    },
    'arg.2': {
        'torneo': [(1, 1, 'Final por el primer ascenso', '#2fa866'),
                   (2, 8, 'Reducido por el segundo ascenso', '#e3a21a')],
    },
    'bra.1': {
        'torneo': [(1, 6, 'Copa Libertadores', '#2b7bd6'),
                   (7, 12, 'Copa Sudamericana', '#e3a21a'),
                   (-4, -1, 'Descenso', '#d64545')],
    },
    'uru.1': {
        'apertura': [(1, 1, 'Campeón del Apertura', '#2fa866')],
        'intermedio': [(1, 1, 'Campeón del Torneo Intermedio', '#2fa866')],
        'clausura': [(1, 1, 'Campeón del Clausura', '#2fa866')],
        'anual': [(1, 3, 'Copa Libertadores', '#2b7bd6'),
                  (4, 6, 'Copa Sudamericana', '#e3a21a')],
        'promedios': [(-3, -1, 'Descenso', '#d64545')],
    },
    'col.1': {
        'torneo': [(1, 2, 'Copa Libertadores', '#2b7bd6'),
                   (3, 4, 'Copa Sudamericana', '#e3a21a'),
                   (-2, -1, 'Descenso', '#d64545')],
    },
    'chi.1': {
        'torneo': [(1, 2, 'Copa Libertadores', '#2b7bd6'),
                   (3, 5, 'Copa Sudamericana', '#e3a21a'),
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


def ronda_slug(e):
    texto = (e.get('season') or {}).get('slug', '')
    traducciones = {
        'round-of-64': 'Treintaidosavos de final', 'round-of-32': 'Dieciseisavos de final',
        'round-of-16': 'Octavos de final', 'quarterfinals': 'Cuartos de final',
        'semifinals': 'Semifinal', 'final': 'Final',
    }
    return traducciones.get(texto, texto.replace('-', ' ').title() if texto else '')


def partidos_del_dia(slug, dia):
    j = pedir(f"{BASE}site/v2/sports/soccer/{slug}/scoreboard?dates={dia:%Y%m%d}")
    salida = []
    for e in j.get('events', []):
        comp = (e.get('competitions') or [{}])[0]
        eq = comp.get('competitors', [])
        local = next((c for c in eq if c.get('homeAway') == 'home'), eq[0] if eq else {})
        visita = next((c for c in eq if c.get('homeAway') == 'away'), eq[1] if len(eq) > 1 else {})
        st = (e.get('status') or {}).get('type', {})
        pen_l, pen_v = local.get('shootoutScore'), visita.get('shootoutScore')
        partido = {
            'id': e.get('id'),
            'dia': dia.isoformat(),
            'fecha': e.get('date'),
            'ronda': ronda_slug(e),
            'h': local.get('team', {}).get('displayName'),
            'v': visita.get('team', {}).get('displayName'),
            'gl': local.get('score'),
            'gv': visita.get('score'),
            'estado': st.get('state'),
            'completo': st.get('completed'),
            'detalle': st.get('shortDetail'),
            'goles': goles_de(comp, local, visita),
        }
        if pen_l is not None and pen_v is not None:
            partido['pl'], partido['pv'] = pen_l, pen_v
        salida.append(partido)
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


def tabla_periodo(partidos, desde=None, hasta=None, limite_por_equipo=None, slug=None):
    """Suma una tabla por fechas. límite_por_equipo excluye playoffs posteriores al torneo regular."""
    llevan = {}
    filas = {}
    for p in sorted(partidos, key=lambda p: p['fecha'] or ''):
        fecha = p['fecha'] or ''
        if not p['h'] or not p['v'] or (desde and fecha < desde) or (hasta and fecha >= hasta):
            continue
        for n in (p['h'], p['v']):
            filas.setdefault(n, {'n': n, 'pj': 0, 'g': 0, 'e': 0, 'p': 0, 'gf': 0, 'gc': 0})
        if limite_por_equipo:
            kh, kv = (p['h'], desde), (p['v'], desde)
            llevan[kh] = llevan.get(kh, 0) + 1
            llevan[kv] = llevan.get(kv, 0) + 1
            if llevan[kh] > limite_por_equipo or llevan[kv] > limite_por_equipo:
                continue
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
    if slug:
        marcar(orden, REGLAS.get(slug, {}).get('anual', []))
    return orden

def tablas_por_zonas(partidos, grupos, slug, desde=None, hasta=None, limite_por_equipo=None):
    salida = []
    for grupo in grupos:
        equipos = {f['n'] for f in grupo.get('filas', [])}
        filas = tabla_periodo(
            [p for p in partidos if p.get('h') in equipos and p.get('v') in equipos],
            desde, hasta, limite_por_equipo=limite_por_equipo
        )
        reglas = REGLAS.get(slug, {}).get('apertura' if hasta else 'clausura', [])
        if not reglas:
            reglas = REGLAS.get(slug, {}).get('torneo', [])
        marcar(filas, reglas)
        nombre = grupo.get('nombre') or 'Zona'
        if slug == 'arg.1':
            nombre = re.sub(r'^Group ', 'Zona ', nombre)
        salida.append({'nombre': nombre, 'filas': filas})
    return salida


def tabla_anual(partidos, slug):
    if slug == 'arg.1':
        filas = {}
        for f in (tabla_periodo(partidos, hasta='2026-07-01T00:00:00Z', limite_por_equipo=16) +
                  tabla_periodo(partidos, desde='2026-07-01T00:00:00Z', limite_por_equipo=16)):
            t = filas.setdefault(f['n'], {'n': f['n'], 'pj': 0, 'g': 0, 'e': 0, 'p': 0, 'gf': 0, 'gc': 0})
            for k in ('pj', 'g', 'e', 'p', 'gf', 'gc'):
                t[k] += f[k]
        orden = sorted(filas.values(), key=lambda f: (-(f['g'] * 3 + f['e']), -(f['gf'] - f['gc']), -f['gf']))
        for f in orden:
            f['dg'] = f['gf'] - f['gc']
            f['pts'] = f['g'] * 3 + f['e']
        marcar(orden, REGLAS.get(slug, {}).get('anual', []))
        return orden
    return tabla_periodo(partidos, desde='2026-01-01T00:00:00Z', slug=slug)


def tabla_promedios(partidos, slug):
    filas = tabla_periodo(partidos, desde='2026-01-01T00:00:00Z')
    for fila in filas:
        fila['prom'] = round(fila['pts'] / fila['pj'], 3) if fila['pj'] else 0
    filas.sort(key=lambda f: (-f['prom'], -f['pts'], -f['dg'], -f['gf']))
    marcar(filas, REGLAS.get(slug, {}).get('promedios', []))
    return filas


# ===== Liga uruguaya: Apertura, Intermedio (dos zonas), Clausura y Tabla Anual =====
# Cada torneo tiene su ventana de fechas (en UTC, mismo formato que ESPN). Adentro de cada ventana cada
# cruce cuenta una sola vez: así no entran las finales ni los desempates, y el Intermedio solo cuenta
# los partidos dentro de cada zona. La misma lógica está en index.html (si cambiás una, cambiá la otra).
URU_VENTANAS = {
    'apertura': ('2026-01-01T00:00Z', '2026-05-13T00:00Z'),     # 15 fechas, hasta el 11 de mayo
    'intermedio': ('2026-05-13T00:00Z', '2026-08-06T12:00Z'),   # del 15 de mayo al 5 de agosto (final incluida)
    'clausura': ('2026-08-06T12:00Z', None),                    # desde el 7 de agosto
}
URU_NOMBRES = {
    'penarol': 'Peñarol', 'cerro_largo': 'Cerro Largo', 'racing': 'Racing', 'liverpool': 'Liverpool',
    'central_espanol': 'Central Español', 'cerro': 'Cerro', 'defensor': 'Defensor Sp.', 'boston_river': 'Boston River',
    'wanderers': 'Wanderers', 'nacional': 'Nacional', 'maldonado': 'Deportivo Maldonado', 'city_torque': 'City Torque',
    'juventud': 'Juventud', 'albion': 'Albion', 'progreso': 'Progreso', 'danubio': 'Danubio',
}
URU_CLAVES = [(k, re.compile(r)) for k, r in [
    ('cerro_largo', r'cerro largo'), ('central_espanol', r'central espanol'), ('cerro', r'\bcerro\b'),
    ('penarol', r'penarol'), ('nacional', r'nacional'), ('defensor', r'defensor'), ('danubio', r'danubio'),
    ('wanderers', r'wanderers'), ('liverpool', r'liverpool'), ('racing', r'racing'), ('boston_river', r'boston'),
    ('city_torque', r'torque'), ('maldonado', r'maldonado'), ('juventud', r'juventud'),
    ('albion', r'albion'), ('progreso', r'progreso'),
]]
URU_GRUPOS = {
    'Grupo A': ['penarol', 'cerro_largo', 'racing', 'liverpool', 'central_espanol', 'cerro', 'defensor', 'boston_river'],
    'Grupo B': ['wanderers', 'nacional', 'maldonado', 'city_torque', 'juventud', 'albion', 'progreso', 'danubio'],
}
# Puntos de menos por decisión de la Federación (la anual lo descuenta una sola vez).
URU_AJUSTES = {
    'intermedio': {'cerro': (-1, 'Decisión de la Federación')},
    'anual': {'cerro': (-1, 'Decisión de la Federación')},
}


def clave_uru(nombre):
    t = unicodedata.normalize('NFD', nombre or '')
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn').lower()
    return next((k for k, r in URU_CLAVES if r.search(t)), t)


def grupo_uru(k):
    return next((g for g, ks in URU_GRUPOS.items() if k in ks), None)


def terminado(p):
    return (p['estado'] == 'post' and p['completo'] and p['h'] and p['v']
            and p['gl'] not in (None, '') and p['gv'] not in (None, ''))


def forma_uru(partidos):
    """Últimos 5 resultados de cada equipo en la liga (V, E o D), del más viejo al más nuevo."""
    por = {}
    for p in sorted((p for p in partidos if terminado(p)), key=lambda p: p['fecha'] or ''):
        a, b = int(p['gl']), int(p['gv'])
        for nombre, gf, gc in ((p['h'], a, b), (p['v'], b, a)):
            por.setdefault(clave_uru(nombre), []).append('V' if gf > gc else 'D' if gf < gc else 'E')
    return {k: v[-5:] for k, v in por.items()}


def tabla_uru(partidos, torneo, ajustar=True):
    desde, hasta = URU_VENTANAS[torneo]
    filas = {k: {'k': k, 'n': n, 'pj': 0, 'g': 0, 'e': 0, 'p': 0, 'gf': 0, 'gc': 0} for k, n in URU_NOMBRES.items()}
    vistos = set()
    for p in sorted(partidos, key=lambda p: p['fecha'] or ''):
        f = p['fecha'] or ''
        if not p['h'] or not p['v'] or f < desde or (hasta and f >= hasta):
            continue
        kh, kv = clave_uru(p['h']), clave_uru(p['v'])
        if kh == kv:
            continue
        if torneo == 'intermedio' and (grupo_uru(kh) is None or grupo_uru(kh) != grupo_uru(kv)):
            continue
        if p['estado'] == 'post' and not p['completo']:
            continue   # suspendido o postergado: cuenta cuando se juegue
        par = tuple(sorted((kh, kv)))
        if par in vistos:
            continue   # un solo partido por cruce en cada torneo
        vistos.add(par)
        H = filas.setdefault(kh, {'k': kh, 'n': p['h'], 'pj': 0, 'g': 0, 'e': 0, 'p': 0, 'gf': 0, 'gc': 0})
        V = filas.setdefault(kv, {'k': kv, 'n': p['v'], 'pj': 0, 'g': 0, 'e': 0, 'p': 0, 'gf': 0, 'gc': 0})
        if not terminado(p):
            continue
        a, b = int(p['gl']), int(p['gv'])
        H['pj'] += 1; V['pj'] += 1; H['gf'] += a; H['gc'] += b; V['gf'] += b; V['gc'] += a
        if a > b: H['g'] += 1; V['p'] += 1
        elif a < b: V['g'] += 1; H['p'] += 1
        else: H['e'] += 1; V['e'] += 1
    forma = forma_uru(partidos)
    for f in filas.values():
        aj = URU_AJUSTES.get(torneo, {}).get(f['k']) if ajustar else None
        f['dg'] = f['gf'] - f['gc']
        f['pts'] = f['g'] * 3 + f['e'] + (aj[0] if aj else 0)
        if aj:
            f['aj'] = {'p': aj[0], 'm': aj[1]}
        f['ult'] = forma.get(f['k'], [])
    return sorted(filas.values(), key=lambda f: (-f['pts'], -f['dg'], -f['gf'], f['n']))


def marcar_campeon(filas, nombre):
    if filas and filas[0]['pj'] > 0:
        completo = all(f['pj'] >= 15 for f in filas)
        filas[0]['nota'] = {'d': ('Campeón del ' if completo else 'Líder del ') + nombre, 'c': '#2fa866'}


def anual_uru(partidos):
    total = {}
    for torneo in ('apertura', 'intermedio', 'clausura'):
        for f in tabla_uru(partidos, torneo, ajustar=False):
            t = total.setdefault(f['k'], {'k': f['k'], 'n': f['n'], 'pj': 0, 'g': 0, 'e': 0, 'p': 0, 'gf': 0, 'gc': 0, 'ult': f['ult']})
            for c in ('pj', 'g', 'e', 'p', 'gf', 'gc'):
                t[c] += f[c]
    for t in total.values():
        aj = URU_AJUSTES['anual'].get(t['k'])
        t['dg'] = t['gf'] - t['gc']
        t['pts'] = t['g'] * 3 + t['e'] + (aj[0] if aj else 0)
        if aj:
            t['aj'] = {'p': aj[0], 'm': aj[1]}
    orden = sorted(total.values(), key=lambda f: (-f['pts'], -f['dg'], -f['gf'], f['n']))
    marcar(orden, REGLAS['uru.1']['anual'])
    return orden


def datos_uru(partidos):
    apertura, clausura = tabla_uru(partidos, 'apertura'), tabla_uru(partidos, 'clausura')
    marcar_campeon(apertura, 'Apertura')
    marcar_campeon(clausura, 'Clausura')
    filas = tabla_uru(partidos, 'intermedio')
    grupos = []
    for nombre, ks in URU_GRUPOS.items():
        fs = [f for f in filas if f['k'] in ks]
        if fs and fs[0]['pj'] > 0:
            fs[0]['nota'] = {'d': 'Final', 'c': '#1aa3e8'}
        grupos.append({'nombre': nombre, 'filas': fs})
    return {'apertura': apertura, 'intermedio': grupos, 'clausura': clausura, 'anual': anual_uru(partidos)}



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
    unicos = {}
    for p in partidos:   # si un id aparece dos veces (partido postergado), queda el de fecha más nueva
        unicos[p['id'] or f"sin-id-{len(unicos)}"] = p
    partidos = list(unicos.values())
    nuevo = {'partidos': partidos, 'tabla': filas}
    if slug == 'arg.1':
        nuevo['apertura'] = tablas_por_zonas(partidos, filas, slug, hasta='2026-07-01T00:00:00Z', limite_por_equipo=16)
        nuevo['clausura'] = tablas_por_zonas(partidos, filas, slug, desde='2026-07-01T00:00:00Z', limite_por_equipo=16)
        nuevo['anual'] = tabla_anual(partidos, slug)
        nuevo['promedios'] = tabla_promedios(partidos, slug)
    if slug == 'uru.1':
        nuevo.update(datos_uru(partidos))

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
