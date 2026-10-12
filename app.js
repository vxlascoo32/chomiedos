const $=s=>document.querySelector(s),J=u=>fetch(u).then(r=>r.ok?r.json():null).catch(()=>null);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const logo=u=>u?`<img src="${esc(u)}" alt="" loading="lazy">`:'';
let L=[],H={};
const TABS=[['partidos','Partidos'],['posiciones','Posiciones'],['equipos','Equipos'],['stats','Estadísticas'],['palmares','Palmarés']];
function nav(cur){let g='',h='';for(const l of L){if(l.group!==g){g=l.group;h+=`<h4>${esc(g)}</h4>`}
h+=`<a href="#/${l.slug}" class="${l.slug===cur?'on':''}">${esc(l.name)}</a>`}$('#nav').innerHTML=h}
const fmt=d=>new Date(d).toLocaleDateString('es-AR',{weekday:'long',day:'numeric',month:'long'});
const hr=d=>new Date(d).toLocaleTimeString('es-AR',{hour:'2-digit',minute:'2-digit'});
function matches(ms){if(!ms?.length)return'<p class="empty">Sin partidos cargados.</p>';let day='',h='';
for(const m of [...ms].sort((a,b)=>a.date.localeCompare(b.date))){const d=fmt(m.date);if(d!==day){day=d;h+=`<div class="day">${esc(d)}</div>`}
const done=m.hg!=null,live=['1H','2H','HT','ET','P','LIVE'].includes(m.status);
h+=`<div class="m"><span class="st ${live?'live':''}">${live?esc(m.status):done?'Fin':hr(m.date)}</span><span class="h">${esc(m.home)} ${logo(m.homeLogo)}</span><span class="s">${done?`${m.hg} - ${m.ag}`:'-'}</span><span>${logo(m.awayLogo)}${esc(m.away)}</span></div>`}return h}
function standings(s){if(!s?.length)return'<p class="empty">Sin tabla (¿es una copa?).</p>';
return`<table><tr><th>#</th><th class="l">Equipo</th><th>PJ</th><th>G</th><th>E</th><th>P</th><th>DG</th><th>Pts</th></tr>`+s.map(r=>`<tr><td>${r.rank}</td><td class="l">${logo(r.logo)}${esc(r.team)}</td><td>${r.pj}</td><td>${r.g}</td><td>${r.e}</td><td>${r.p}</td><td>${r.dg}</td><td><b>${r.pts}</b></td></tr>`).join('')+'</table>'}
const rank=(t,a)=>`<div><h3>${t}</h3>${a?.length?`<table>${a.slice(0,10).map((p,i)=>`<tr><td>${i+1}</td><td class="l">${esc(p.name)}<br><span class="st">${esc(p.team)}</span></td><td><b>${p.value??0}</b></td></tr>`).join('')}</table>`:'<p class="empty">Sin datos.</p>'}</div>`;
async function view(){const [slug,tab='partidos']=location.hash.slice(2).split('/');nav(slug);const m=$('#main');
if(!slug){const all=(await Promise.all(L.map(l=>J(`data/l/${l.slug}.json`)))).filter(Boolean);const t=new Date().toISOString().slice(0,10);
m.innerHTML=`<h2>Hoy</h2>`+all.map(d=>{const ms=d.matches.filter(x=>x.date.startsWith(t));return ms.length?`<h3>${esc(d.name)}</h3>`+matches(ms):''}).join('')||'<p class="empty">Elegí una liga.</p>';return}
const l=L.find(x=>x.slug===slug);if(!l){m.innerHTML='<p class="empty">Liga no encontrada.</p>';return}
const d=await J(`data/l/${slug}.json`);
let h=`<h2>${esc(l.name)} <span class="st">${esc(l.group)}</span></h2><div class="tabs">${TABS.map(([k,n])=>`<a href="#/${slug}/${k}" class="${k===tab?'on':''}">${n}</a>`).join('')}</div>`;
if(tab==='palmares'){const p=H[slug];h+=p?`<table><tr><th class="l">Equipo</th><th>Títulos</th></tr>${p.map(r=>`<tr><td class="l">${esc(r.team)}</td><td>${r.titles}</td></tr>`).join('')}</table>`:'<p class="empty">Cargá el palmarés en data/honours.json.</p>'}
else if(!d)h+='<p class="empty">Todavía no hay datos. Corré el workflow “Actualizar datos”.</p>';
else if(tab==='partidos')h+=matches(d.matches);
else if(tab==='posiciones')h+=standings(d.standings);
else if(tab==='equipos')h+=d.teams?.length?`<div class="teams">${d.teams.map(t=>`<div>${logo(t.logo)}${esc(t.name)}</div>`).join('')}</div>`:'<p class="empty">Sin equipos.</p>';
else h+=`<div class="stats">${rank('Goleadores',d.scorers)}${rank('Asistidores',d.assists)}${rank('Más amarillas',d.yellows)}${rank('Más rojas',d.reds)}</div>`;
m.innerHTML=h;if(d)$('#upd').textContent='Actualizado: '+new Date(d.updated).toLocaleString('es-AR')}
(async()=>{L=await J('data/leagues.json')||[];H=await J('data/honours.json')||{};addEventListener('hashchange',view);view()})();
