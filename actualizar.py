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
    'arg.1': date(2026, 1, 22),
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
        salida.append({'nombre': g.get('name', '') if hay_zonas else '', 'filas': filas})
    return salida


def actualizar(slug, inicio, historial):
    archivo = f'datos/{slug}.json'
    anterior = {}
    if os.path.exists(archivo):
        with open(archivo, encoding='utf-8') as f:
            anterior = json.load(f)
    partidos = anterior.get('partidos', [])

    hoy = date.today()
    desde = inicio if historial else hoy - timedelta(days=3)
    hasta = hoy + timedelta(days=30 if historial else 14)

    dias = errores = 0
    dia = desde
    while dia <= hasta:
        dias += 1
        try:
            nuevos = partidos_del_dia(slug, dia)
            partidos = [p for p in partidos if p['dia'] != dia.isoformat()] + nuevos
        except Exception as err:
            errores += 1
            print(f'  {dia}: {err}')
        dia += timedelta(days=1)
        time.sleep(0.3)
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
        }, f, ensure_ascii=False)
    print(f'{slug}: {len(partidos)} partidos, {errores} días con error')


if __name__ == '__main__':
    historial = '--historial' in sys.argv
    for slug, inicio in LIGAS.items():
        actualizar(slug, inicio, historial)
