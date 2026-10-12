# Chomiedos
Sitio estático (GitHub Pages) + GitHub Action que baja datos de API-Football y los guarda como JSON en `data/l/`.

## Puesta en marcha
1. Subí la carpeta a un repo de GitHub.
2. Settings → Pages → Deploy from branch → `main` / root.
3. Creá cuenta en https://www.api-football.com (plan gratis: 100 pedidos/día), copiá la key.
4. Settings → Secrets and variables → Actions → `API_KEY`.
5. Actions → "Actualizar datos" → Run workflow.

## Notas
- Cada liga usa 7 pedidos. `MAX_CALLS` (90 por defecto) limita cada corrida y el script actualiza primero las ligas más viejas. Con el plan gratis tocá el cron a cada 2-3 horas.
- Ligas nuevas (copas de Uruguay, Paraguay, Chile, Colombia): buscá el id en `/leagues?country=...` y agregá una línea en `data/leagues.json`.
- Torneos de selecciones: cambiá `season` en `data/leagues.json` cuando empiece una edición nueva.
- Palmarés: se carga a mano en `data/honours.json` (`{"slug":[{"team":"X","titles":N}]}`); hoy sólo trae el Mundial.
- Colores: variables al inicio de `style.css`.
