"""Lokalt MVP. Start: python -B web_app.py. Ingen eksterne dataforespørsler."""
import sqlite3
import re
import secrets
import hashlib
import base64
import json
import os
import ssl
import smtplib
import tempfile
from copy import deepcopy
from pathlib import Path
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from html import escape
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit, quote, urljoin
from email.message import EmailMessage

from demand_features import calculate_features, calculate_detail_region, MISSING_REGION
from market_analysis import DATABASE, EPOCH, load_observations, period_bounds
from nav_monthly_cache import CACHE as MONTHLY_CACHE, read_month
from nav_database import initialize_database
from job_navigator import load_active_jobs
from job_search import find_jobs, normalize

CSS = """
:root{--ink:#163e3a;--muted:#5f716d;--paper:#f5f6f2;--line:#dce3dd}*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.6 system-ui,sans-serif}
main{max-width:1180px;margin:auto;padding:32px 28px 70px}header{display:flex;justify-content:space-between;border-bottom:1px solid var(--line);padding-bottom:20px}
a{color:var(--ink);text-underline-offset:4px}header a{text-decoration:none;font-weight:700;letter-spacing:.06em}
.eyebrow,small{color:var(--muted);font-size:13px}.hero{max-width:850px;padding:70px 0 36px}h1{font-size:clamp(36px,5vw,64px);line-height:1.12;letter-spacing:-.045em;font-weight:600;margin:16px 0 24px}h2{font-size:30px;line-height:1.2;font-weight:600}h3{font-size:23px;margin:0 0 18px}.intro{font-size:20px;color:var(--muted);max-width:740px}
form{max-width:800px;margin:0 0 40px}label{display:block;font-weight:600;margin-bottom:10px}.search{display:flex;gap:12px}input{flex:1;min-width:0;border:1px solid #a5b6ad;background:white;padding:18px;border-radius:12px;font:inherit}button,.button{display:inline-block;background:var(--ink);color:white;padding:17px 24px;border:0;border-radius:12px;font:inherit;text-decoration:none;cursor:pointer}a:focus-visible,input:focus-visible,button:focus-visible,summary:focus-visible{outline:3px solid #6c9d89;outline-offset:4px}
.note{background:#e8eee7;border-radius:16px;padding:22px 26px;margin:24px 0}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:22px}.card{background:white;border:1px solid var(--line);border-radius:20px;padding:28px}.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:22px 0}.metric b{display:block;font-size:28px;font-weight:600}.metric span{font-size:13px;color:var(--muted)}.badge{display:inline-block;background:#edf1ec;padding:5px 11px;border-radius:30px;font-size:13px}.context{border-top:1px solid var(--line);padding-top:16px;color:var(--muted);font-size:14px}details{margin:16px 0}summary{cursor:pointer}.job{margin:20px 0}.job h3{margin-bottom:8px}.empty{padding:30px;background:white;border-radius:16px}footer{margin-top:48px;border-top:1px solid var(--line);padding-top:20px;color:var(--muted);font-size:13px}
.result-search{margin:22px 0}.result-search input{padding:10px 14px}.result-search button{padding:10px 20px}
.region{padding:20px 24px}.card-head{display:flex;align-items:center;justify-content:space-between;gap:12px}.card-head h3{margin:0;font-size:21px}.region .metrics{margin:14px 0}.region .metric b{font-size:25px}.region .button{padding:8px 16px;font-size:14px}.disclosure{border-top:1px solid var(--line);padding:16px 0;margin:8px 0}.disclosure summary{font-weight:600}.disclosure .grid{margin-top:20px}.grid{gap:16px}
@media(max-width:700px){main{padding:22px 18px}.hero{padding-top:36px}.grid{grid-template-columns:1fr}.search{flex-direction:column}.card{padding:22px}header small{max-width:125px;text-align:right}.metric b{font-size:24px}}
/* Presentation only: five compact rows, with the same values and ordering. */
:root{--ink:#203b35;--muted:#65716a;--paper:#f7f6f1;--line:#e0e4db}
main{max-width:1440px;padding:20px 36px 32px}header{align-items:center;min-height:48px;padding-bottom:16px}
header nav{display:flex;gap:28px}header nav a{font-size:14px;font-weight:500;letter-spacing:0;color:var(--muted)}
.hero{padding:48px 0 20px;max-width:800px}h1{font-size:clamp(34px,4vw,52px);line-height:1.15;margin:12px 0 20px}h2{font-size:29px;letter-spacing:-.025em;margin:18px 0 8px}.intro{font-size:19px}
form{max-width:880px;margin-bottom:28px}.search{padding:6px;background:#fff;border:1px solid #cfd8ce;border-radius:16px;box-shadow:0 6px 24px #203b3508;gap:8px}input{border:0;background:transparent;padding:14px 16px}button{border-radius:11px;padding:14px 24px;font-weight:600}
.result-search{max-width:740px;margin:18px 0 22px}.result-search label{font-size:13px;margin-bottom:5px}.result-search input{padding:8px 12px}.result-search button{padding:8px 20px}
.grid{grid-template-columns:1fr;gap:9px}.region{display:grid;grid-template-columns:minmax(200px,1.1fr) minmax(420px,2.5fr) 190px 145px;align-items:center;gap:20px;padding:16px 22px;min-height:94px;border-radius:14px;box-shadow:0 2px 10px #203b3503}
.region:hover{border-color:#b8cabc;box-shadow:0 5px 18px #203b3508}.card-head{justify-content:flex-start;gap:14px}.card-head h3{font-size:20px;letter-spacing:-.02em}.top-five{counter-reset:region}.top-five .card-head:before{counter-increment:region;content:counter(region,decimal-leading-zero);font-size:14px;font-variant-numeric:tabular-nums;color:#829185}
.region .metrics{margin:0;gap:20px;grid-template-columns:repeat(3,minmax(0,1fr))}.region .metric b{font-size:25px;line-height:1.3;font-variant-numeric:tabular-nums}.region .metric span{font-size:12px;line-height:1.35;display:block;margin-top:4px}.region .badge{font-size:12px;background:#eaf0e4;text-align:center;padding:6px 10px;justify-self:start}.region .button{padding:8px 0;background:transparent;color:var(--ink);font-size:14px;font-weight:600;white-space:nowrap;justify-self:end}
button,.button,.region,header a{transition:background .18s ease,border-color .18s ease,box-shadow .18s ease,color .18s ease}button:hover{background:#34584a}.region .button:hover{color:#547b53;text-decoration:underline}.disclosure{padding:12px 0;margin:4px 0}.disclosure summary{font-size:14px}.job{max-width:1000px}
@media(max-width:1100px){.region{grid-template-columns:minmax(150px,1fr) minmax(350px,2fr);gap:14px}.region .badge{grid-column:1}.region .button{grid-column:2}.top-five .card-head:before{font-size:12px}}
@media(max-width:700px){main{padding:18px}.hero{padding:32px 0 16px}header{gap:16px}header a{font-size:13px}header nav{gap:14px}header nav a{font-size:12px}.region{display:flex;flex-direction:column;align-items:stretch;padding:20px;gap:16px}.region .metrics{gap:12px}.region .badge{align-self:flex-start}.region .button{align-self:flex-end}.region .metric b{font-size:23px}.search{gap:4px}button{width:100%}.result-search{margin-top:20px}}
/* Final polish: shared result surface and compact working space. */
main{padding:16px 28px 24px}header{background:#fff;border:1px solid var(--line);border-radius:18px;padding:12px 20px;box-shadow:0 3px 14px #203b3504;min-height:58px}.brand{display:flex;align-items:center;gap:11px;font-size:14px}.logo-mark{display:inline-flex;align-items:flex-end;gap:3px;width:26px;height:26px;padding:6px;background:#eaf0e4;border-radius:8px}.logo-mark:before,.logo-mark:after{content:"";width:6px;background:#50785c;border-radius:2px}.logo-mark:before{height:11px}.logo-mark:after{height:17px}header nav a{padding:5px 9px;border-radius:8px}header nav a:hover{background:#f0f3eb}
form,.result-search{max-width:850px;margin:14px 0 18px}label,.result-search label{font-size:13px;margin-bottom:4px}.search{padding:4px;border-radius:12px;box-shadow:0 2px 10px #203b3504}input,.result-search input{padding:8px 12px}button,.result-search button{padding:8px 18px;border-radius:9px;font-size:14px}h2{font-size:26px;margin:14px 0 5px}h2+p{margin:0 0 14px;color:var(--muted);font-size:15px}.hero{padding:24px 0 14px}.hero h1{font-size:clamp(32px,3.5vw,46px)}
.top-five{background:white;border:1px solid var(--line);border-radius:16px;gap:0;box-shadow:0 4px 20px #203b3504;overflow:hidden}.top-five .region{border:0;border-bottom:1px solid var(--line);border-radius:0;box-shadow:none;min-height:78px;padding:12px 20px}.top-five .region:last-child{border-bottom:0}.top-five .region:hover{background:#f8faf5;box-shadow:none}.region .metric b{font-size:23px}.region .metric span{margin-top:2px}.card-head h3{font-size:18px}.disclosure{padding:9px 0;margin:3px 0}.disclosure summary{line-height:1.5}.region{grid-template-columns:minmax(170px,1fr) minmax(360px,2.3fr) 175px 130px;gap:16px}
@media(min-width:1000px) and (max-width:1200px){main{padding-left:18px;padding-right:18px}.region{grid-template-columns:165px minmax(300px,1fr) 160px 118px;gap:10px}.region .badge,.region .button{grid-column:auto}.region .metrics{gap:8px}.region .badge{font-size:11px}.region .button{font-size:13px}}
@media(min-width:701px) and (max-width:999px){.region{grid-template-columns:180px 1fr;gap:8px}.top-five .region{padding:10px 16px;min-height:108px}.region .badge{grid-column:1}.region .button{grid-column:2}}
@media(max-width:700px){main{padding:12px}.brand{font-size:12px;gap:7px}header{padding:10px;gap:8px}header nav{gap:2px}header nav a{padding:5px;font-size:11px}.logo-mark{width:24px;height:24px;padding:4px}.top-five{background:transparent;border:0;box-shadow:none;overflow:visible;gap:12px}.top-five .region{border:1px solid var(--line);border-radius:14px;padding:18px;background:white}.top-five .region:last-child{border-bottom:1px solid var(--line)}.region{gap:14px}.region .metric span{font-size:12px}form,.result-search{margin:16px 0}.hero{padding-top:20px}}
"""


CSS += """
button:disabled{cursor:wait;opacity:.8}.spinner{display:inline-block;width:14px;height:14px;border:2px solid #ffffff55;border-top-color:white;border-radius:50%;animation:spin .8s linear infinite;margin-right:8px;vertical-align:-2px}@keyframes spin{to{transform:rotate(360deg)}}
.job-list{background:white;border:1px solid var(--line);border-radius:15px;overflow:hidden}.job-list:empty{display:none}.job-row{display:flex;align-items:center;justify-content:space-between;gap:22px;padding:16px 22px;border-bottom:1px solid var(--line);border-left:3px solid transparent;min-height:104px}.job-row:last-child{border-bottom:0}.job-row:hover{background:#f8faf5;border-left-color:#98b98f}.job-copy{min-width:0}.job-copy h3{font-size:18px;line-height:1.35;margin:0 0 4px}.job-copy p{font-size:14px;color:var(--muted);margin:0 0 2px}.job-copy small{font-size:12px}.job-link{font-size:14px;font-weight:600;white-space:nowrap;text-decoration:none}.job-link:hover{text-decoration:underline}.share-label{cursor:help;text-decoration:underline dotted;text-underline-offset:3px}
@media(max-width:700px){.job-row{align-items:flex-start;flex-direction:column;gap:12px;padding:18px}.job-link{align-self:flex-end}}
@media(prefers-reduced-motion:reduce){.spinner{animation:none}}
"""

CSS += """.search{position:relative}.search input{border:0!important;outline:0;background:transparent;box-shadow:none}.search:focus-within{border-color:#6c9d89;box-shadow:0 0 0 3px #6c9d8930}.autocomplete-list{position:absolute;z-index:20;top:calc(100% + 5px);left:0;right:0;overflow:hidden;border:1px solid #dce6e0;border-radius:12px;background:#fff;box-shadow:0 10px 24px #183e3818}.autocomplete-option{display:block;width:100%;min-height:38px;padding:8px 13px;border:0;border-bottom:1px solid #edf1ed;border-radius:0;background:#fff;color:var(--ink);text-align:left;font-size:14px}.autocomplete-option:last-child{border-bottom:0}.autocomplete-option:hover,.autocomplete-option.selected{background:#edf6f1;color:#174f45}@media(max-width:700px){.autocomplete-option{min-height:44px;padding:10px 13px}.autocomplete-list{left:-1px;right:-1px}}"""

SCRIPT = """const form = document.querySelector('form');
if (form && form.querySelector('input[name="q"]')) {
  const input = form.querySelector('input[name="q"]');
  const button = form.querySelector('button');
  const original = button.textContent;
  form.addEventListener('submit', event => {
    if (form.dataset.busy) { event.preventDefault(); return; }
    const value = document.createElement('input');
    value.type = 'hidden'; value.name = input.name; value.value = input.value;
    value.dataset.submittedQuery = 'true'; form.append(value);
    form.dataset.busy = 'true'; form.setAttribute('aria-busy', 'true');
    button.innerHTML = '<span class="spinner" aria-hidden="true"></span>' + (button.dataset.loadingLabel || original);
    button.disabled = true; input.disabled = true;
  });
  window.addEventListener('pageshow', () => {
    delete form.dataset.busy; form.removeAttribute('aria-busy');
    input.disabled = false; button.disabled = false; button.textContent = original;
    form.querySelectorAll('[data-submitted-query]').forEach(node => node.remove());
  });
}
const exploreStarts = new WeakSet();
document.addEventListener('click', event => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = event.target.closest('a[href]');
    if (!link || link.target && link.target !== '_self' || link.hasAttribute('download')) return;
    if (new URL(window.location.href).searchParams.get('mode') === 'explore') return;
    const destination = new URL(link.href, window.location.href);
    if (destination.origin !== window.location.origin || destination.pathname !== '/' || destination.searchParams.get('mode') !== 'explore') return;
    if (typeof gtag !== 'function') return;
    if (exploreStarts.has(link)) { event.preventDefault(); return; }
    exploreStarts.add(link);
    event.preventDefault();
    const continueNavigation = () => window.location.assign(destination.href);
    gtag('event', 'explore_start', {event_callback: continueNavigation, event_timeout: 300});
}, {capture: true});
if (document.querySelector('[data-analytics-event="vakt_verified"]') && typeof gtag === 'function') {
    gtag('event', 'vakt_verified');
}
document.querySelectorAll('[data-autocomplete]').forEach(input => {
  const container = input.closest('.search');
  if (!container) return;
  const list = document.createElement('div');
  list.className = 'autocomplete-list'; list.setAttribute('role', 'listbox');
  list.hidden = true; container.append(list);
  let choices = [], selected = -1, request = 0;
  const close = () => { choices = []; selected = -1; list.hidden = true; list.replaceChildren(); };
  const choose = value => { input.value = value; close(); input.focus(); };
  const paint = () => {
    list.replaceChildren();
    choices.forEach((value, index) => {
      const option = document.createElement('button'); option.type = 'button';
      option.className = 'autocomplete-option' + (index === selected ? ' selected' : '');
      option.setAttribute('role', 'option'); option.setAttribute('aria-selected', index === selected ? 'true' : 'false');
      option.textContent = value;
      option.addEventListener('mousedown', event => { event.preventDefault(); choose(value); });
      list.append(option);
    });
    list.hidden = !choices.length;
  };
  input.addEventListener('input', () => {
    const query = input.value.trim();
    if (query.length < 2) { close(); return; }
    const current = ++request;
    const municipality = input.dataset.autocomplete === 'municipality';
    const mode = municipality ? 'municipality_suggestions' : 'suggestions';
    const parameter = municipality ? 'kommune' : 'q';
    fetch('/?mode=' + mode + '&' + parameter + '=' + encodeURIComponent(query), {headers: {'Accept': 'application/json'}})
      .then(response => response.ok ? response.json() : [])
      .then(values => { if (current === request && input.value.trim() === query) { choices = Array.isArray(values) ? values : []; selected = -1; paint(); } })
      .catch(() => { if (current === request) close(); });
  });
  input.addEventListener('keydown', event => {
    if (event.key === 'Escape') { close(); return; }
    if (!choices.length) return;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault(); selected = event.key === 'ArrowDown' ? (selected + 1) % choices.length : (selected + choices.length - 1) % choices.length; paint();
    } else if (event.key === 'Enter' && selected >= 0) { event.preventDefault(); choose(choices[selected]); }
  });
  input.addEventListener('blur', () => setTimeout(close, 120));
});
document.querySelectorAll('.all-jobs-filter').forEach(form => {
    form.addEventListener('submit', event => {
        event.preventDefault();
        if (form.dataset.searchEventSent === 'true') return;
        form.dataset.searchEventSent = 'true';
        const submitForm = () => HTMLFormElement.prototype.submit.call(form);
        if (typeof gtag !== 'function') { submitForm(); return; }
        const params = {};
        const term = form.elements.namedItem('q')?.value.trim() || '';
        const emailLike = /[^\\s@]+@[^\\s@]+\\.[^\\s@]+/.test(term);
        const digitCount = (term.match(/\\d/g) || []).length;
        if (term && !emailLike && digitCount < 7) params.search_term = term;
        const fylke = form.elements.namedItem('fylke')?.value.trim() || '';
        const kommune = form.elements.namedItem('kommune')?.value.trim() || '';
        if (fylke) params.fylke = fylke;
        if (kommune) params.kommune = kommune;
        params.event_callback = submitForm;
        params.event_timeout = 300;
        gtag('event', 'search', params);
    }, {capture: true});
});
document.querySelectorAll('[data-jobs-filter]').forEach(select => select.addEventListener('change', () => {
    if (select.form?.matches('.all-jobs-filter')) select.form.requestSubmit();
    else select.form.submit();
}));
document.querySelectorAll('[data-jobs-tip]').forEach(row => row.addEventListener('click', () => {
  const search = document.querySelector('#profession');
  const county = document.querySelector('#all-jobs-county');
  if (row.dataset.jobsTip === 'county' && county) {
    county.focus();
    try { county.showPicker?.(); } catch (_) {}
  } else if (search) {
    document.querySelector('.all-jobs-filter')?.scrollIntoView({behavior: 'smooth', block: 'center'});
    search.focus({preventScroll: true});
  }
}));"""
SCRIPT_HASH = base64.b64encode(hashlib.sha256(SCRIPT.encode('utf-8')).digest()).decode('ascii')


BRAND = '''<span class="peil-mark" aria-hidden="true"><svg viewBox="0 0 40 40" width="34" height="34" fill="none"><path d="M10 31V10h10a8 8 0 0 1 0 16H10" stroke="currentColor" stroke-width="4" stroke-linejoin="round"/><path class="peil-arrow" d="M20 22L33 9M25 9h8v8" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg></span><span>JobbPeil</span>'''


TRANSLATIONS = {
    "no": {
        "nav.search":"S\u00f8k", "nav.explore":"Utforsk", "nav.about":"Om JobbPeil", "nav.open_menu":"\u00c5pne hovedmenyen", "nav.language":"Velg spr\u00e5k", "nav.norwegian":"Norsk", "nav.english":"English", "nav.menu":"Meny",
        "footer.contact":"Kontakt", "footer.privacy":"Personvern", "footer.data_source":"Data fra NAV / Arbeidsplassen", "footer.tagline":"Finn din retning",
        "home.title":"JobbPeil \u2013 Finn din retning", "home.eyebrow":"Finn din retning", "home.hero_title":"Finn ut hvor kompetansen din er etterspurt", "home.hero_intro":"Se hvor i Norge det finnes jobbmuligheter for yrket ditt \u2013 basert p\u00e5 faktiske stillingsannonser og arbeidsmarkedsdata.", "home.hero_intro_short":"Utforsk jobbmuligheter i Norge \u2013 basert p\u00e5 stillingsannonser og arbeidsmarkedsdata.", "home.sign.job":"Jobb", "home.sign.opportunities":"Muligheter", "home.sign.skills":"Kompetanse", "home.sign.place":"Sted", "home.search_label":"Hva jobber du med?", "home.search_placeholder":"f.eks. sykepleier", "home.search_cta":"Se jobbmuligheter", "home.searching":"S\u00f8ker...", "home.signpost_alt":"Treveiviser med Jobb, Muligheter, Kompetanse og Sted", "home.choice_search_title":"Jeg vet hva jeg vil jobbe med", "home.choice_search_copy":"S\u00f8k etter yrke og utforsk fylkene.", "home.choice_search_cta":"Finn jobbmuligheter", "home.choice_explore_title":"Jeg er usikker p\u00e5 hva jeg kan jobbe med", "home.choice_explore_copy":"Svar p\u00e5 fem sp\u00f8rsm\u00e5l og utforsk mulige retninger.", "home.choice_explore_cta":"Utforsk muligheter", "home.fact_region_title":"Regionfokus", "home.fact_region_copy":"Utforsk annonser fordelt p\u00e5 fylke.", "home.fact_people_title":"For mennesker", "home.fact_people_copy":"To veier inn, ut fra hvor du er n\u00e5.", "home.fact_data_title":"Fakta med forklaring", "home.fact_data_copy":"Lagrede NAV-data med synlige perioder og begrensninger.", "home.data_title":"Om datagrunnlaget", "home.data_copy_1":"Lokalt NAV-utvalg. Ingen eksterne data lastes ned. Originalannonser \u00e5pnes bare n\u00e5r du velger lenken.", "home.data_copy_2":"Datagrunnlaget er et lagret utvalg av aktive annonser fra NAV / Arbeidsplassen.", "home.data_copy_3":"Tallene er veiledende og kan endre seg n\u00e5r annonser oppdateres eller fjernes.", "home.data_copy_4":"Les alltid kravene i originalannonsen f\u00f8r du s\u00f8ker.",
        "about.title":"Om JobbPeil", "about.page_title":"Om JobbPeil", "about.lead":"Mer enn en jobbs\u00f8ker. En veiviser i arbeidslivet.", "about.intro":"JobbPeil hjelper deg \u00e5 finne reelle stillinger, forst\u00e5 hvor mulighetene er st\u00f8rst og oppdage nye retninger som kan passe deg i arbeidsmarkedet.", "about.explore_cta":"Utforsk mulige jobber", "about.search_cta":"S\u00f8k etter stillinger", "about.note":"Flere muligheter.<br>Klokere valg.<br>En lysere fremtid.", "about.how_title":"Slik fungerer det", "about.how_intro":"Tre enkle steg p\u00e5 veien til nye muligheter.", "about.step_search_title":"S\u00f8k etter stillinger", "about.step_search_copy":"S\u00f8k etter yrke, bransje eller sted og se relevante stillinger fra NAV.", "about.step_search_cta":"G\u00e5 til s\u00f8k", "about.step_explore_title":"Utforsk muligheter", "about.step_explore_copy":"Svar p\u00e5 fem enkle sp\u00f8rsm\u00e5l og f\u00e5 forslag til retninger og reelle stillinger.", "about.step_explore_cta":"Start Utforsk", "about.step_insight_title":"Innsikt, ikke bare stillinger", "about.step_insight_copy":"Se hvor det finnes muligheter n\u00e5, og hvilke retninger du kan unders\u00f8ke videre.", "about.data_title":"Datagrunnlag", "about.data_intro":"JobbPeil bruker p\u00e5litelige og offentlige kilder.", "about.nav_source_title":"NAV / Arbeidsplassen", "about.active_source":"Aktiv kilde", "about.nav_source_copy":"Reelle stillingsannonser i JobbPeil hentes fra NAV / Arbeidsplassen og vises fra det aktive utvalget.", "about.nav_source_link":"Arbeidsplassen", "about.ssb_title":"Statistisk sentralbyr\u00e5 (SSB)", "about.coming_soon":"Kommer senere", "about.ssb_copy":"Arbeidsmarkedsstatistikk er planlagt som en fremtidig kilde til mer innsikt.", "about.why_title":"Hvorfor JobbPeil?", "about.why_intro":"Vi gir deg et bredere bilde.", "about.benefit_1":"Reelle stillinger fra NAV / Arbeidsplassen", "about.benefit_2":"Oversikt over muligheter p\u00e5 tvers av regioner", "about.benefit_3":"Hjelp til \u00e5 utforske nye retninger", "about.benefit_4":"Et enkelt og oversiktlig grensesnitt", "about.benefit_5":"Gratis \u00e5 bruke", "about.mission":"M\u00e5let er \u00e5 gj\u00f8re det enklere \u00e5 finne neste steg i arbeidslivet \u2013 med reelle annonser og tydeligere oversikt.", "about.contact_title":"Kontakt", "about.contact_copy":"Har du sp\u00f8rsm\u00e5l eller forslag? Vi h\u00f8rer gjerne fra deg.", "about.privacy_title":"Personvern", "about.privacy_copy":"JobbPeil behandler kun offentlige data og samler ikke inn personlige opplysninger.", "about.future_title":"Videre utvikling", "about.future_copy":"JobbPeil utvikles videre med flere forklaringer og bedre innsikt i mulighetene.",
        "privacy.title":"Personvern", "privacy.page_title":"Personvern | JobbPeil", "privacy.lead":"JobbPeil skal v\u00e6re enkelt \u00e5 bruke og tydelig p\u00e5 hvordan data h\u00e5ndteres.", "privacy.uses_title":"Hva JobbPeil bruker", "privacy.uses_copy_1":"JobbPeil bruker stillingsdata fra offentlige kilder, blant annet NAV / Arbeidsplassen, for \u00e5 vise ledige stillinger og gi oversikt over muligheter i arbeidsmarkedet.", "privacy.uses_copy_2":"N\u00e5r du bruker s\u00f8k eller Utforsk, behandles valgene dine for \u00e5 vise relevante resultater.", "privacy.no_storage_title":"Dette lagrer vi ikke n\u00e5", "privacy.no_storage_intro":"JobbPeil har forel\u00f8pig ingen brukerkontoer.", "privacy.no_storage_lead":"Vi lagrer ikke:", "privacy.cv":"CV", "privacy.applications":"jobbs\u00f8knader", "privacy.profiles":"personlige profiler", "privacy.passwords":"passord", "privacy.payment":"betalingsinformasjon", "privacy.external_title":"Eksterne lenker", "privacy.external_copy_1":"Noen stillinger kan sende deg videre til arbeidsgiverens nettside eller Arbeidsplassen.", "privacy.external_copy_2":"N\u00e5r du forlater JobbPeil, gjelder personvernreglene til den eksterne tjenesten du bes\u00f8ker.", "privacy.technical_title":"Tekniske data", "privacy.technical_copy_1":"Som andre nettsteder kan JobbPeil behandle n\u00f8dvendige tekniske foresp\u00f8rsler for at siden skal fungere, for eksempel sidevisninger, URL-parametere og serverforesp\u00f8rsler.", "privacy.technical_copy_2":"JobbPeil bruker forel\u00f8pig ikke brukerkontoer eller personlig profilering.", "privacy.sources_title":"Datakilder", "privacy.sources_copy_1":"Stillingsdata kommer fra NAV / Arbeidsplassen.", "privacy.sources_copy_2":"SSB kan bli brukt som statistikkilde i fremtiden.", "privacy.contact_title":"Kontakt om personvern", "privacy.contact_copy":"Har du sp\u00f8rsm\u00e5l om personvern i JobbPeil, kan du kontakte oss p\u00e5:", "privacy.updated":"Sist oppdatert: september 2026",
        "contact.title":"Kontakt", "contact.page_title":"Kontakt | JobbPeil", "contact.copy_1":"Har du sp\u00f8rsm\u00e5l, tilbakemeldinger eller forslag til JobbPeil?", "contact.copy_2":"Send oss gjerne en e-post.", "contact.cta":"Send e-post", "error.data_title":"Lokale data er ikke tilgjengelige", "error.data_copy":"Kontroller datafilene og pr\u00f8v igjen.", "error.home":"Til forsiden"
    },
    "en": {
        "nav.search":"Search", "nav.explore":"Explore", "nav.about":"About JobbPeil", "nav.open_menu":"Open main menu", "nav.language":"Choose language", "nav.norwegian":"Norsk", "nav.english":"English", "nav.menu":"Menu", "footer.contact":"Contact", "footer.privacy":"Privacy", "footer.data_source":"Data from NAV / Arbeidsplassen", "footer.tagline":"Find your direction",
        "home.title":"JobbPeil - Find your direction", "home.eyebrow":"Find your direction", "home.hero_title":"Find out where your skills are in demand", "home.hero_intro":"See where in Norway there are job opportunities for your profession, based on real job advertisements and labour-market data.", "home.hero_intro_short":"Explore job opportunities in Norway, based on job advertisements and labour-market data.", "home.sign.job":"Jobs", "home.sign.opportunities":"Opportunities", "home.sign.skills":"Skills", "home.sign.place":"Location", "home.search_label":"What do you do?", "home.search_placeholder":"e.g. nurse", "home.search_cta":"View job opportunities", "home.searching":"Searching...", "home.signpost_alt":"Signpost with Jobs, Opportunities, Skills and Location", "home.choice_search_title":"I know what I want to do", "home.choice_search_copy":"Search for a profession and explore counties.", "home.choice_search_cta":"Find job opportunities", "home.choice_explore_title":"I am unsure what I can do", "home.choice_explore_copy":"Answer five questions and explore possible directions.", "home.choice_explore_cta":"Explore opportunities", "home.fact_region_title":"Regional focus", "home.fact_region_copy":"Explore advertisements by county.", "home.fact_people_title":"For people", "home.fact_people_copy":"Two ways in, based on where you are now.", "home.fact_data_title":"Facts with context", "home.fact_data_copy":"Saved NAV data with visible time periods and limitations.", "home.data_title":"About the data", "home.data_copy_1":"Local NAV selection. No external data is downloaded. Original advertisements open only when you choose the link.", "home.data_copy_2":"The data source is a saved selection of active vacancies from NAV / Arbeidsplassen.", "home.data_copy_3":"The figures are indicative and may change when advertisements are updated or removed.", "home.data_copy_4":"Always read the requirements in the original advertisement before applying.",
        "about.title":"About JobbPeil", "about.page_title":"About JobbPeil", "about.lead":"More than a job search. A guide to working life.", "about.intro":"JobbPeil helps you find real vacancies, understand where opportunities are greatest, and discover new directions that may suit you in the labour market.", "about.explore_cta":"Explore possible jobs", "about.search_cta":"Search for jobs", "about.note":"More opportunities.<br>Smarter choices.<br>A brighter future.", "about.how_title":"How it works", "about.how_intro":"Three simple steps towards new opportunities.", "about.step_search_title":"Search for jobs", "about.step_search_copy":"Search by profession, industry or place and see relevant vacancies from NAV.", "about.step_search_cta":"Go to search", "about.step_explore_title":"Explore opportunities", "about.step_explore_copy":"Answer five simple questions and get suggestions for directions and real vacancies.", "about.step_explore_cta":"Start exploring", "about.step_insight_title":"Insights, not just vacancies", "about.step_insight_copy":"See where opportunities are available now and which directions you can explore further.", "about.data_title":"Data sources", "about.data_intro":"JobbPeil uses reliable public sources.", "about.nav_source_title":"NAV / Arbeidsplassen", "about.active_source":"Active source", "about.nav_source_copy":"Real job advertisements in JobbPeil come from NAV / Arbeidsplassen and are shown from the active selection.", "about.nav_source_link":"Arbeidsplassen", "about.ssb_title":"Statistics Norway (SSB)", "about.coming_soon":"Coming later", "about.ssb_copy":"Labour-market statistics are planned as a future source of further insight.", "about.why_title":"Why JobbPeil?", "about.why_intro":"We give you a broader picture.", "about.benefit_1":"Real vacancies from NAV / Arbeidsplassen", "about.benefit_2":"An overview of opportunities across regions", "about.benefit_3":"Help to explore new directions", "about.benefit_4":"A simple, clear interface", "about.benefit_5":"Free to use", "about.mission":"The goal is to make it easier to find the next step in working life, with real advertisements and clearer context.", "about.contact_title":"Contact", "about.contact_copy":"Do you have questions or suggestions? We would be happy to hear from you.", "about.privacy_title":"Privacy", "about.privacy_copy":"JobbPeil uses public data only and does not collect personal information.", "about.future_title":"Further development", "about.future_copy":"JobbPeil is being developed with more explanations and better insight into opportunities.",
        "privacy.title":"Privacy", "privacy.page_title":"Privacy | JobbPeil", "privacy.lead":"JobbPeil should be easy to use and clear about how data is handled.", "privacy.uses_title":"What JobbPeil uses", "privacy.uses_copy_1":"JobbPeil uses job data from public sources, including NAV / Arbeidsplassen, to show vacancies and provide an overview of opportunities in the labour market.", "privacy.uses_copy_2":"When you use Search or Explore, your choices are processed to show relevant results.", "privacy.no_storage_title":"What we do not store now", "privacy.no_storage_intro":"JobbPeil currently has no user accounts.", "privacy.no_storage_lead":"We do not store:", "privacy.cv":"CV", "privacy.applications":"job applications", "privacy.profiles":"personal profiles", "privacy.passwords":"passwords", "privacy.payment":"payment information", "privacy.external_title":"External links", "privacy.external_copy_1":"Some vacancies may take you to an employer's website or Arbeidsplassen.", "privacy.external_copy_2":"When you leave JobbPeil, the privacy policy of the external service you visit applies.", "privacy.technical_title":"Technical data", "privacy.technical_copy_1":"Like other websites, JobbPeil may process the technical requests needed for the site to work, such as page views, URL parameters and server requests.", "privacy.technical_copy_2":"JobbPeil currently does not use user accounts or personal profiling.", "privacy.sources_title":"Data sources", "privacy.sources_copy_1":"Job data comes from NAV / Arbeidsplassen.", "privacy.sources_copy_2":"SSB may be used as a statistical source in the future.", "privacy.contact_title":"Privacy contact", "privacy.contact_copy":"If you have questions about privacy in JobbPeil, you can contact us at:", "privacy.updated":"Last updated: September 2026",
        "contact.title":"Contact", "contact.page_title":"Contact | JobbPeil", "contact.copy_1":"Do you have questions, feedback or suggestions for JobbPeil?", "contact.copy_2":"Feel free to email us.", "contact.cta":"Send email", "error.data_title":"Local data is unavailable", "error.data_copy":"Check the data files and try again.", "error.home":"Back to home"
    }
}

TRANSLATIONS["no"].update({
    "vakt.title":"JobbPeil Vakt", "vakt.page_title":"JobbPeil Vakt | JobbPeil", "vakt.badge":"AI-assistent", "vakt.promo_copy":"F\u00e5 relevante jobbvarsler p\u00e5 e-post", "vakt.try":"Pr\u00f8v n\u00e5", "vakt.back":"Tilbake til forsiden", "vakt.lead":"F\u00e5 relevante jobber rett til e-post", "vakt.intro":"Fortell oss hva slags jobb du ser etter, s\u00e5 sier vi fra n\u00e5r noe passer deg. Du slipper \u00e5 lete \u2013 vi holder \u00f8ye for deg.", "vakt.benefit_1_title":"Spar tid", "vakt.benefit_1_copy":"Vi finner nye jobber for deg.", "vakt.benefit_2_title":"Relevante forslag", "vakt.benefit_2_copy":"Du f\u00e5r kun jobber som passer s\u00f8ket ditt.", "vakt.benefit_3_title":"Rett til e-post", "vakt.benefit_3_copy":"Enkelt, gratis og uforpliktende.", "vakt.form_title":"Start din JobbPeil Vakt", "vakt.form_helper":"Fyll ut informasjonen under, s\u00e5 varsler vi deg n\u00e5r det kommer nye, relevante jobber.", "vakt.profession":"Yrke / stillingstittel", "vakt.profession_placeholder":"For eksempel: renholder, butikkmedarbeider, sj\u00e5f\u00f8r ...", "vakt.explore_help":"Usikker p\u00e5 yrke? Utforsk muligheter", "vakt.county":"Fylke", "vakt.county_placeholder":"Velg fylke", "vakt.email":"E-postadresse", "vakt.email_placeholder":"din@epost.no", "vakt.submit":"Start JobbPeil Vakt", "vakt.free_note":"Det er gratis, og du kan n\u00e5r som helst melde deg av.", "vakt.robot_speech":"Jeg holder \u00f8ye med nye muligheter for deg!", "vakt.alerts_title":"Eksempler p\u00e5 varsler du kan f\u00e5:", "vakt.alert_1":"Ny jobb: Renholder i Agder", "vakt.alert_2":"Ny jobb: Butikkmedarbeider i Oslo", "vakt.alert_3":"Ny jobb: Servicemedarbeider i Rogaland", "vakt.steps_title":"Slik fungerer det", "vakt.step_1_title":"Fyll ut dine \u00f8nsker", "vakt.step_1_copy":"Fortell oss hvilken jobb du ser etter, og hvor du vil jobbe.", "vakt.step_2_title":"Vi holder \u00f8ye", "vakt.step_2_copy":"Vi ser jevnlig etter nye, relevante stillinger.", "vakt.step_3_title":"Du f\u00e5r varsel", "vakt.step_3_copy":"N\u00e5r det kommer noe som passer, f\u00e5r du en e-post."
})
TRANSLATIONS["en"].update({
    "vakt.title":"JobbPeil Vakt", "vakt.page_title":"JobbPeil Vakt | JobbPeil", "vakt.badge":"AI assistant", "vakt.promo_copy":"Get relevant job alerts by email", "vakt.try":"Try now", "vakt.back":"Back to home", "vakt.lead":"Get relevant jobs by email", "vakt.intro":"Tell us what kind of job you are looking for and we will let you know when something suits you. You do not need to keep searching \u2013 we will keep an eye out for you.", "vakt.benefit_1_title":"Save time", "vakt.benefit_1_copy":"We find new jobs for you.", "vakt.benefit_2_title":"Relevant suggestions", "vakt.benefit_2_copy":"You receive jobs that match your search.", "vakt.benefit_3_title":"Straight to email", "vakt.benefit_3_copy":"Simple, free and without obligation.", "vakt.form_title":"Start your JobbPeil Vakt", "vakt.form_helper":"Complete the information below and we will alert you when new relevant jobs appear.", "vakt.profession":"Job title / profession", "vakt.profession_placeholder":"For example: cleaner, shop assistant, driver ...", "vakt.explore_help":"Unsure about a profession? Explore opportunities", "vakt.county":"County", "vakt.county_placeholder":"Choose county", "vakt.email":"Email address", "vakt.email_placeholder":"you@email.com", "vakt.submit":"Start JobbPeil Vakt", "vakt.free_note":"It is free, and you can unsubscribe at any time.", "vakt.robot_speech":"I keep an eye on new opportunities for you!", "vakt.alerts_title":"Examples of alerts you can receive:", "vakt.alert_1":"New job: Cleaner in Agder", "vakt.alert_2":"New job: Shop assistant in Oslo", "vakt.alert_3":"New job: Service employee in Rogaland", "vakt.steps_title":"How it works", "vakt.step_1_title":"Tell us what you want", "vakt.step_1_copy":"Tell us what kind of job you are looking for and where you want to work.", "vakt.step_2_title":"We keep an eye out", "vakt.step_2_copy":"We regularly look for new relevant vacancies.", "vakt.step_3_title":"You receive an alert", "vakt.step_3_copy":"When something matches, you receive an email."
})

TRANSLATIONS["no"].update({
    "vakt.registered_title": "Vakten er registrert",
    "vakt.registered_copy": "Registreringen er lagret. E-postbekreftelse kobles på i neste backend-steg.",
    "vakt.error_invalid_email": "Skriv inn en gyldig e-postadresse.",
    "vakt.error_invalid_profession": "Skriv inn et yrke eller en stillingstittel.",
    "vakt.error_profession_too_long": "Yrke eller stillingstittel kan være maks 120 tegn.",
    "vakt.error_invalid_county": "Velg et gyldig fylke.",
    "vakt.error_invalid_form": "Kontroller feltene og prøv igjen.",
    "vakt.error_unavailable": "Vakten kunne ikke lagres akkurat nå. Prøv igjen senere."
})
TRANSLATIONS["en"].update({
    "vakt.registered_title": "Your alert is registered",
    "vakt.registered_copy": "The registration is saved. Email confirmation will be connected in the next backend step.",
    "vakt.error_invalid_email": "Enter a valid email address.",
    "vakt.error_invalid_profession": "Enter a profession or job title.",
    "vakt.error_profession_too_long": "The profession or job title can be no more than 120 characters.",
    "vakt.error_invalid_county": "Choose a valid county.",
    "vakt.error_invalid_form": "Check the fields and try again.",
    "vakt.error_unavailable": "The alert could not be saved right now. Please try again later."
})

TRANSLATIONS["no"].update({
    "vakt.confirmation_sent_title": "Sjekk e-posten din",
    "vakt.confirmation_sent_copy": "Vi har sendt en bekreftelseslenke til {email}.",
    "vakt.error_email_delivery": "Vi kunne ikke sende bekreftelses-e-posten akkurat n\u00e5. Pr\u00f8v igjen senere.",
})
TRANSLATIONS["en"].update({
    "vakt.confirmation_sent_title": "Check your email",
    "vakt.confirmation_sent_copy": "We sent a confirmation link to {email}.",
    "vakt.error_email_delivery": "We could not send the confirmation email right now. Please try again later.",
})


TRANSLATIONS["no"].update({
    "vakt.verify_success_title": "JobbPeil Vakt er aktivert",
    "vakt.verify_success_copy": "Vakten er aktiv. Du får e-post når JobbPeil finner nye relevante stillinger for deg.",
    "vakt.verify_invalid_title": "Bekreftelseslenken er ugyldig",
    "vakt.verify_invalid_copy": "Bekreftelseslenken er ugyldig eller ikke lenger aktiv.",
    "vakt.unsubscribe_success_title": "Varslingen er stoppet",
    "vakt.unsubscribe_success_copy": "Du vil ikke lenger motta varsler fra denne JobbPeil Vakten.",
    "vakt.unsubscribe_invalid_title": "Lenken er ugyldig",
    "vakt.unsubscribe_invalid_copy": "Avmeldingslenken er ugyldig eller ikke lenger tilgjengelig.",
    "vakt.lifecycle_home": "Til JobbPeil"
})
TRANSLATIONS["en"].update({
    "vakt.verify_success_title": "JobbPeil Vakt is activated",
    "vakt.verify_success_copy": "Your alert is now active and ready for when email delivery is connected.",
    "vakt.verify_invalid_title": "The confirmation link is invalid",
    "vakt.verify_invalid_copy": "The confirmation link is invalid or no longer active.",
    "vakt.unsubscribe_success_title": "Notifications are stopped",
    "vakt.unsubscribe_success_copy": "You will no longer receive notifications from this JobbPeil alert.",
    "vakt.unsubscribe_invalid_title": "The link is invalid",
    "vakt.unsubscribe_invalid_copy": "The unsubscribe link is invalid or no longer available.",
    "vakt.lifecycle_home": "Back to JobbPeil"
})

TRANSLATIONS["no"].update({
    "jobs.title": "Nye stillinger", "jobs.newest_first": "De nyeste stillingene f\u00f8rst",
    "jobs.all_counties": "Alle fylker", "jobs.county_label": "Fylke",
    "jobs.in_county": "Nye stillinger i {fylke}", "jobs.count": "{count} aktive stillinger i utvalget.",
    "jobs.empty": "Ingen aktive stillinger funnet i utvalget.", "jobs.about": "OM STILLINGENE",
    "jobs.about_copy": "Her ser du de nyeste aktive stillingene fra NAV / Arbeidsplassen.",
    "jobs.previous": "Forrige", "jobs.next": "Neste"
})
TRANSLATIONS["en"].update({
    "jobs.title": "New vacancies", "jobs.newest_first": "Newest vacancies first",
    "jobs.all_counties": "All counties", "jobs.county_label": "County",
    "jobs.in_county": "New vacancies in {fylke}", "jobs.count": "{count} active vacancies in the selection.",
    "jobs.empty": "No active vacancies found in the selection.", "jobs.about": "ABOUT THE VACANCIES",
    "jobs.about_copy": "Here are the newest active vacancies from NAV / Arbeidsplassen.",
    "jobs.previous": "Previous", "jobs.next": "Next"
})

TRANSLATIONS["no"].update({
    "jobs.showing": "Viser {start}\u2013{end} av {total}",
    "jobs.hero_title": "Finn raskere riktig jobb",
    "jobs.hero_copy": "Utforsk nye muligheter, velg fylke og finn stillinger som passer deg og dine m\u00e5l.",
    "jobs.help_search": "S\u00f8k p\u00e5 yrke", "jobs.help_search_copy": "Skriv inn en tittel eller bruk v\u00e5re forslag.",
    "jobs.help_county": "Velg fylke", "jobs.help_county_copy": "Se stillinger i din region eller i hele Norge.",
    "jobs.help_newest": "Se de nyeste stillingene", "jobs.help_newest_copy": "Vi viser alltid de mest nylig publiserte stillingene f\u00f8rst.",
    "jobs.more_title": "Flere muligheter i hele Norge",
    "jobs.more_copy": "Utforsk stillinger i alle fylker og finn ut hvor det er st\u00f8rst aktivitet akkurat n\u00e5.",
    "jobs.tips_title": "Tips for bedre resultater", "jobs.tip_words": "Pr\u00f8v ulike s\u00f8keord",
    "jobs.tip_county": "Velg fylke for \u00e5 f\u00e5 mer relevante stillinger",
    "jobs.tip_fresh": "Hold \u00f8ye med nye stillinger \u2013 vi oppdaterer jevnlig",
    "jobs.tip_vakt": "Lag en JobbPeil Vakt for \u00e5 f\u00e5 stillinger rett i innboksen"
})
TRANSLATIONS["en"].update({
    "jobs.showing": "Showing {start}\u2013{end} of {total}",
    "jobs.hero_title": "Find the right job faster",
    "jobs.hero_copy": "Explore new opportunities, choose a county and find vacancies that suit you and your goals.",
    "jobs.help_search": "Search by profession", "jobs.help_search_copy": "Enter a title or use our suggestions.",
    "jobs.help_county": "Choose county", "jobs.help_county_copy": "See vacancies in your region or across Norway.",
    "jobs.help_newest": "See the newest vacancies", "jobs.help_newest_copy": "We always show the most recently published vacancies first.",
    "jobs.more_title": "More opportunities across Norway",
    "jobs.more_copy": "Explore vacancies in every county and see where activity is greatest right now.",
    "jobs.tips_title": "Tips for better results", "jobs.tip_words": "Try different search terms",
    "jobs.tip_county": "Choose a county for more relevant vacancies",
    "jobs.tip_fresh": "Keep an eye on new vacancies \u2013 we update regularly",
    "jobs.tip_vakt": "Create a JobbPeil alert to get vacancies in your inbox"
})


TRANSLATIONS["no"].update({
    "jobs.more_copy": "Utforsk stillinger i ulike fylker og se hvor det er størst aktivitet akkurat nå.",
    "jobs.more_label": "NORGE RUNDT", "jobs.more_vacancies": "aktive stillinger",
    "jobs.more_insight_1": "Reell innsikt.", "jobs.more_insight_2": "Bedre valg.",
    "jobs.more_insight_copy": "JobbPeil hjelper deg å se mulighetene – der du er, og der du vil.",
    "jobs.more_all_counties": "Se alle fylker", "jobs.more_all_counties_copy": "Utforsk muligheter over hele Norge."
})
TRANSLATIONS["en"].update({
    "jobs.more_copy": "Explore vacancies in different counties and see where activity is greatest right now.",
    "jobs.more_label": "AROUND NORWAY", "jobs.more_vacancies": "active vacancies",
    "jobs.more_insight_1": "Real insight.", "jobs.more_insight_2": "Better choices.",
    "jobs.more_insight_copy": "JobbPeil helps you see the opportunities – where you are and where you want to go.",
    "jobs.more_all_counties": "See all counties", "jobs.more_all_counties_copy": "Explore opportunities across Norway."
})


TRANSLATIONS["no"].update({
    "jobs.tips_copy": "Enkle grep som hjelper deg å finne mer relevante stillinger.",
    "jobs.tips_search_title": "Bruk konkrete søkeord",
    "jobs.tips_search_copy": "Prøv for eksempel yrkestittel, bransje eller viktige ferdigheter.",
    "jobs.tips_county_title": "Velg sted eller fylke",
    "jobs.tips_county_copy": "Snevr inn søket for å få mer relevante resultater.",
    "jobs.tips_filters_title": "Bruk filtre",
    "jobs.tips_filters_copy": "Filtrer på stillingstype, arbeidstid eller publiseringsdato.",
    "jobs.tips_save_title": "Lagre søk",
    "jobs.tips_save_copy": "Få varsel når det kommer nye relevante stillinger."
})
TRANSLATIONS["en"].update({
    "jobs.tips_copy": "Simple steps that help you find more relevant vacancies.",
    "jobs.tips_search_title": "Use specific search terms",
    "jobs.tips_search_copy": "Try a job title, industry or important skills.",
    "jobs.tips_county_title": "Choose a place or county",
    "jobs.tips_county_copy": "Narrow your search for more relevant results.",
    "jobs.tips_filters_title": "Use filters",
    "jobs.tips_filters_copy": "Filter by job type, working hours or publication date.",
    "jobs.tips_save_title": "Save a search",
    "jobs.tips_save_copy": "Get an alert when new relevant vacancies appear."
})


def normalize_lang(value):
    value = value.casefold() if isinstance(value, str) else ""
    return value if value in TRANSLATIONS else "no"


def t(lang, key, **values):
    norwegian = TRANSLATIONS["no"]
    text = TRANSLATIONS.get(normalize_lang(lang), {}).get(key, norwegian.get(key))
    if text is None:
        raise KeyError(f"Unknown translation key: {key}")
    return text.format(**values)


def internal_url(params=None, *, fragment="", **changes):
    values = {}
    for key, value in (params or {}).items():
        if isinstance(value, (list, tuple)):
            if value:
                values[key] = value[-1]
        elif value is not None:
            values[key] = value
    for key, value in changes.items():
        if value is None:
            values.pop(key, None)
        else:
            values[key] = value
    if "lang" in values:
        values["lang"] = normalize_lang(values["lang"])
    return "/" + ("?" + urlencode(values) if values else "") + ("#" + fragment if fragment else "")


def language_change(params, lang):
    return internal_url(params, lang=normalize_lang(lang))


def local_nav_url(mode=None, lang="no", fragment="", include_lang=False):
    changes = {"lang": lang} if include_lang or lang == "en" else {}
    if mode:
        changes["mode"] = mode
    return internal_url({}, fragment=fragment, **changes)


def site_header(active, params=None, lang="no", homepage=False):
    params = params or {}
    lang = normalize_lang(lang)
    preserve_lang = lang == "en" or "lang" in params
    brand = '<a class="brand" href="/">' + BRAND + '</a>'
    brand = brand.replace('<span>JobbPeil</span>', '<span class="brand-name">JobbPeil<small>' + e(t(lang, "footer.tagline")) + '</small></span>')
    mark_start = brand.index('<span class="peil-mark"')
    mark_end = brand.index('</span>', mark_start) + len('</span>')
    brand = (brand[:mark_start]
             + '<svg class="home-logo" viewBox="0 0 48 52" aria-hidden="true"><path fill="currentColor" d="M12 3h19c13 0 17 8 13 20-3 9-10 13-20 13h-5l-5 14H2L13 17h12l-3 9h4c5 0 8-2 10-7 1-4-1-6-6-6H16Z"/><path class="peil-arrow" d="m13 32 15-15H18v-4h17v17h-4V20L16 35Z" fill="#e5faf1"/></svg>'
             + brand[mark_end:])
    def item(key, href, label):
        current = ' class="active" aria-current="page"' if active == key else ''
        return f'<a href="{e(href)}"{current}>{e(label)}</a>'
    other_lang = "en" if lang == "no" else "no"
    current_key = "nav.norwegian" if lang == "no" else "nav.english"
    other_key = "nav.english" if lang == "no" else "nav.norwegian"
    language_options = (f'<button type="button" aria-current="true">{e(t(lang, current_key))}</button>'
                        f'<a href="{e(language_change(params, other_lang))}">{e(t(lang, other_key))}</a>')
    language_menu = f'<details class="language-menu"><summary aria-label="{e(t(lang, "nav.language"))}"><span class="language-desktop">{lang.upper()} / {other_lang.upper()}</span><span class="language-mobile">{lang.upper()} / {other_lang.upper()}</span><span aria-hidden="true">&#9662;</span></summary><div class="language-options">{language_options}</div></details>'
    if homepage:
        nav = (item('contact', local_nav_url('kontakt', lang, include_lang=preserve_lang), t(lang, 'contact.title'))
               + item('about', local_nav_url('about', lang, include_lang=preserve_lang), t(lang, 'nav.about'))
               + language_menu)
    else:
        nav = (item('search', local_nav_url(lang=lang, fragment='profession', include_lang=preserve_lang), t(lang, 'nav.search'))
               + item('explore', local_nav_url('explore', lang, include_lang=preserve_lang), t(lang, 'nav.explore'))
               + item('vakt', local_nav_url('vakt', lang, include_lang=preserve_lang), 'JobbPeil Vakt')
               + item('about', local_nav_url('about', lang, include_lang=preserve_lang), t(lang, 'nav.about'))
               + language_menu)
    return ('<header>' + brand
            + f'<details class="site-menu"><summary aria-label="{e(t(lang, "nav.open_menu"))}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg><span>{e(t(lang, "nav.menu"))}</span></summary>'
            + f'</details><nav class="site-nav" aria-label="{e(t(lang, "nav.open_menu"))}">' + nav + '</nav></header>')


def site_footer(lang="no", params=None):
    params = params or {}
    lang = normalize_lang(lang)
    include_lang = lang == "en" or "lang" in params
    contact = local_nav_url('kontakt', lang, include_lang=include_lang)
    privacy = local_nav_url('personvern', lang, include_lang=include_lang)
    return (f'<footer class="site-footer"><span>&copy; 2026 JobbPeil &middot; <a href="{e(contact)}">{e(t(lang, "footer.contact"))}</a> &middot; <a href="{e(privacy)}">{e(t(lang, "footer.privacy"))}</a> &middot; {e(t(lang, "footer.data_source"))}</span>'
            f'<span class="site-footer-tagline">{e(t(lang, "footer.tagline"))}</span></footer>')

CSS += """
:root{--ink:#153e3b;--paper:#f7f7f1}.brand{font-size:22px;font-weight:650;letter-spacing:-.04em;gap:9px}.peil-mark{display:inline-flex;background:#e8eee3;border-radius:10px;padding:3px;color:#1c5750}.peil-arrow{transform-origin:26px 16px;animation:peil-point .7s ease-out both}
main>header{position:relative;z-index:10;overflow:visible}.site-menu{display:none;margin:0 0 0 auto}.site-nav{display:flex;align-items:center;gap:4px;margin-left:auto}.site-nav>a{position:relative;display:inline-flex;align-items:center;min-height:38px;padding:7px 10px;border-radius:9px;color:#5b706c;font-size:14px;font-weight:550;letter-spacing:0;text-decoration:none;transition:background .16s ease,color .16s ease}.site-nav>a:hover{background:#e8f4ed;color:#174f46}.site-nav>a.active{color:#174f46;font-weight:700}.site-nav>a.active:after{content:"";position:absolute;right:10px;bottom:3px;left:10px;height:2px;border-radius:2px;background:#27816e}.language-menu{position:relative;margin:0}.language-menu summary{display:inline-flex;align-items:center;gap:5px;min-height:38px;padding:7px 9px;border-radius:9px;color:#45645e;font-size:13px;font-weight:650;cursor:pointer;list-style:none}.language-menu summary::-webkit-details-marker{display:none}.language-menu summary:hover,.language-menu[open] summary{background:#e8f4ed;color:#174f46}.language-menu summary span:last-child{font-size:11px}.language-mobile{display:none}.language-options{position:absolute;z-index:21;top:calc(100% + 7px);right:0;display:grid;min-width:128px;padding:5px;background:#fff;border:1px solid #d8e6df;border-radius:11px;box-shadow:0 10px 24px #183e3820}.language-options button,.language-options a{width:100%;padding:7px 9px;border:0;border-radius:7px;background:transparent;color:#335b54;font:600 13px/1.3 inherit;text-align:left}.language-options button[aria-current="true"]{background:#edf7f1}.language-options a{display:block;text-decoration:none}.language-options button:disabled{cursor:default;color:#889691}
.site-footer{display:flex;align-items:center;justify-content:space-between;gap:14px;margin:20px 0 0;padding:10px 2px 0;border-top:1px solid #dbe5df;color:#73837e;font-size:12px;line-height:1.4}.site-footer a{color:inherit;text-underline-offset:3px}.site-footer-tagline{flex:none;color:#5b756e;font-weight:600;font-style:italic;white-space:nowrap}@media(max-width:700px){.site-footer{align-items:flex-start;flex-wrap:wrap;gap:3px 14px;margin-top:16px;padding-top:9px}.site-footer-tagline{width:100%}}
.hero{max-width:none;display:grid;grid-template-columns:minmax(0,1.6fr) minmax(260px,1fr);align-items:center;gap:48px;padding:48px 20px 32px;animation:peil-enter .55s ease-out both}.hero-copy{max-width:740px}.hero .eyebrow{color:#38655a;font-size:14px;letter-spacing:.12em;font-weight:600}.hero h1{font-size:clamp(36px,4vw,56px);letter-spacing:-.045em;max-width:680px}.hero .intro{max-width:650px;font-size:18px;line-height:1.65}
.signpost{position:relative;min-height:300px;max-width:380px;width:100%;margin:auto;display:flex;flex-direction:column;justify-content:center;gap:12px;padding:16px 26px 30px;background:radial-gradient(ellipse,#e9eee2 0%,transparent 70%)}.signpost:before{content:"";position:absolute;left:48%;top:20px;bottom:8px;width:15px;background:linear-gradient(90deg,#b1a080,#d4c4a4,#b3a183);border-radius:5px}.signboard{position:relative;width:90%;padding:11px 24px;color:#354c40;background:linear-gradient(105deg,#e3d5b9,#d5c4a2);clip-path:polygon(0 0,88% 0,100% 50%,88% 100%,0 100%);font-size:18px;font-weight:600;letter-spacing:.02em;transform-origin:55% 50%;animation:peil-board .65s ease-out both}.signboard:nth-child(2){margin-left:18px;animation-delay:.06s;background:linear-gradient(110deg,#d8c8a9,#e6d9c0)}.signboard:nth-child(3){animation-delay:.12s}.signboard:nth-child(4){margin-left:18px;animation-delay:.18s}.signboard:after{content:"";position:absolute;left:58%;top:50%;width:4px;height:4px;background:#9e9073;border-radius:50%}
.scenario-choices a{transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease}.scenario-choices a:hover{transform:translateY(-2px);box-shadow:0 6px 18px #153e3b08}button:hover{box-shadow:0 3px 10px #153e3b18}
@keyframes peil-enter{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}@keyframes peil-point{from{transform:rotate(-9deg) translate(-2px,2px)}to{transform:none}}@keyframes peil-board{from{opacity:0;transform:rotate(-3deg)}to{opacity:1;transform:none}}
@media(max-width:700px){.brand{font-size:20px}.peil-mark svg{width:28px;height:28px}main>header{position:relative}.site-menu{display:block}.site-menu summary{display:inline-flex;align-items:center;gap:5px;min-height:38px;padding:7px 9px;border-radius:10px;color:#315e56;font-size:12px;font-weight:650;cursor:pointer;list-style:none}.site-menu summary::-webkit-details-marker{display:none}.site-menu summary:hover,.site-menu[open] summary{background:#e1f2e9}.site-menu summary svg{width:19px;height:19px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round}.site-nav{display:none}.site-menu[open]+.site-nav{position:absolute;z-index:20;top:calc(100% + 8px);right:0;display:grid;width:min(280px,calc(100vw - 24px));gap:3px;padding:8px;background:#fff;border:1px solid #d8e6df;border-radius:14px;box-shadow:0 12px 30px #183e3820}.site-nav>a{width:100%;min-height:42px;padding:8px 10px}.site-nav>a.active:after{right:10px;bottom:4px;left:10px}.language-menu{width:100%}.language-menu summary{justify-content:space-between;width:100%;min-height:42px;padding:8px 10px}.language-desktop{display:none}.language-mobile{display:inline}.language-options{position:static;min-width:0;margin:3px 0 1px;box-shadow:none}.hero{grid-template-columns:1fr;gap:12px;padding:28px 4px 18px}.hero h1{font-size:36px}.signpost{min-height:235px;max-width:300px;gap:8px;padding:12px 22px 24px}.signboard{font-size:16px;padding:8px 20px}}
@media(prefers-reduced-motion:reduce){.hero,.peil-arrow,.signboard{animation:none}.scenario-choices a,button,.button,.region,header a{transition:none}.scenario-choices a:hover{transform:none}}
"""


def e(value):
    return escape(str(value), quote=True)


def number(value):
    return "Ikke tilgjengelig" if value is None else (f"{value:.2f}".replace(".", ",") if isinstance(value, float) else str(value))


CACHE_DIR = Path(__file__).resolve().parent / ".jobbpeil_cache"


def feature_source_version():
    try:
        stat = MONTHLY_CACHE.stat()
        monthly_version = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    except FileNotFoundError:
        monthly_version = None
    return active_jobs_source_version(), monthly_version


@lru_cache(maxsize=1)
def feature_code_version():
    digest = hashlib.sha256()
    for name in ("web_app.py", "demand_features.py", "profession_regions.py", "job_search.py",
                 "market_analysis.py", "nav_monthly_cache.py"):
        digest.update((Path(__file__).resolve().parent / name).read_bytes())
    return digest.hexdigest()


@lru_cache(maxsize=1)
def local_data(source_version):
    observations, metadata = load_observations(period_bounds("2026-08-14", "2026-09-11"))
    try:
        official = read_month("2026-08")
    except (OSError, ValueError, KeyError):
        official = None
    return observations, metadata, official


@lru_cache(maxsize=32)
def cached_features(query, version):
    cache_file = CACHE_DIR / (hashlib.sha256(query.encode("utf-8")).hexdigest() + ".json")
    try:
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
        if payload["query"] == query and payload["version"] == version:
            return payload["rows"], payload["summary"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    observations, _, official = local_data(feature_source_version())
    rows, summary = calculate_features(observations, query, official)
    temp_path = None
    try:
        CACHE_DIR.mkdir(exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=CACHE_DIR, delete=False) as temp:
            temp_path = Path(temp.name)
            json.dump(dict(query=query, version=version, rows=rows, summary=summary), temp, ensure_ascii=False)
        os.replace(temp_path, cache_file)
    except OSError:
        pass
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
    return rows, summary


def features(query):
    source_version = feature_source_version()
    version = hashlib.sha256(repr((source_version, feature_code_version())).encode("utf-8")).hexdigest()
    return cached_features(query, version)


@lru_cache(maxsize=16)
def cached_detail_region(query, county, source_version):
    observations, _ = load_observations(period_bounds("2026-08-14", "2026-09-11"),
                                        path=DATABASE, county=county)
    if not observations:
        return None
    try:
        official = read_month("2026-08")
    except (OSError, ValueError, KeyError):
        official = None
    return calculate_detail_region(observations, query, county, official)


def detail_region_data(query, county):
    return cached_detail_region(normalize(query), county.casefold(), feature_source_version())


def active_jobs_source_version():
    path = DATABASE.resolve()
    version = []
    for source in (path, Path(str(path) + "-wal")):
        try:
            stat = source.stat()
            version.append((stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
        except FileNotFoundError:
            version.append(None)
    return tuple(version)


@lru_cache(maxsize=1)
def cached_active_jobs(source_version):
    return load_active_jobs()


def active_matches(query, county):
    return cached_active_matches(normalize(query), county.strip().casefold(), active_jobs_source_version())


@lru_cache(maxsize=1)
def cached_active_published_dates(source_version):
    # Ð¡ÑƒÑ‰ÐµÑÑ‚Ð²ÑƒÑŽÑ‰Ð¸Ð¹ Ð·Ð°Ð³Ñ€ÑƒÐ·Ñ‡Ð¸Ðº Ð½Ðµ ÑÐºÑÐ¿Ð¾Ñ€Ñ‚Ð¸Ñ€ÑƒÐµÑ‚ published; Ñ‡Ð¸Ñ‚Ð°ÐµÐ¼ Ð´Ð°Ñ‚Ñƒ Ñ‚ÐµÐºÑƒÑ‰ÐµÐ¹ Ð²ÐµÑ€ÑÐ¸Ð¸ Ð¾Ñ‚Ð´ÐµÐ»ÑŒÐ½Ð¾.
    db = sqlite3.connect(DATABASE.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        db.execute("PRAGMA query_only=ON")
        return dict(db.execute("SELECT j.uuid,v.published FROM jobs j JOIN job_versions v "
                               "ON v.id=j.current_version_id AND v.job_uuid=j.uuid "
                               "WHERE j.status='ACTIVE' AND v.status='ACTIVE'"))
    finally:
        db.close()


@lru_cache(maxsize=32)
def cached_active_matches(query, county, source_version):
    matches = find_jobs(cached_active_jobs(source_version), query, county)
    return matches, cached_active_published_dates(source_version)


ALL_JOBS_PAGE_SIZE = 24


@lru_cache(maxsize=1)
def cached_active_titles(source_version):
    """One deduplicated, human-readable title index for the current ACTIVE snapshot."""
    titles = {}
    for ad in cached_active_jobs(source_version).values():
        title = " ".join(str(ad.get("title") or ad.get("jobtitle") or "").split())
        if title:
            titles.setdefault(title.casefold(), title)
    return tuple(sorted(titles.values(), key=str.casefold))


AUTOCOMPLETE_ADVERTISING_PATTERN = re.compile(
    r"\b(?:vi\s+s\u00f8ker|s\u00f8ker|s\u00f8kes|ledig\s+stilling|fast\s+stilling|vikariat|"
    r"deltid|heltid|tilkalling|mulighet\s+for|join\s+our|ready\s+to|our\s+team)\b|\b\d+\s*%", re.I)


def is_clean_autocomplete_title(title):
    words = title.split()
    punctuation = sum(not character.isalnum() and not character.isspace() and character not in "-/&" for character in title)
    return (len(title) <= 55 and len(words) <= 6 and punctuation <= 3
            and not AUTOCOMPLETE_ADVERTISING_PATTERN.search(title))


@lru_cache(maxsize=1)
def cached_autocomplete_titles(source_version):
    return tuple(title for title in cached_active_titles(source_version) if is_clean_autocomplete_title(title))


def autocomplete_suggestions(query, limit=5):
    if not isinstance(query, str):
        return []
    needle = query.strip().casefold()
    if len(needle) < 2:
        return []
    limit = min(max(int(limit), 1), 5)
    titles = cached_autocomplete_titles(active_jobs_source_version())
    rank = lambda title: (len(title.split()), len(title), title.casefold())
    prefix = sorted((title for title in titles if title.casefold().startswith(needle)), key=rank)
    contains = sorted((title for title in titles if needle in title.casefold() and not title.casefold().startswith(needle)), key=rank)
    return (prefix + contains)[:limit]


def canonical_fylke(value):
    key = " ".join(value.split()).casefold() if isinstance(value, str) else ""
    return next((county for county in FYLKE_OPTIONS if county.casefold() == key), None)


def location_municipality(location):
    if not isinstance(location, dict):
        return ""
    municipal = " ".join(str(location.get("municipal") or "").split())
    return municipal or " ".join(str(location.get("city") or "").split())


@lru_cache(maxsize=1)
def cached_active_municipalities(source_version):
    municipalities = {}
    for ad in cached_active_jobs(source_version).values():
        for location in ad.get("workLocations") or []:
            name = location_municipality(location)
            if name:
                municipalities.setdefault(name.casefold(), name.title() if name.isupper() else name)
    return tuple(sorted(municipalities.values(), key=str.casefold))


def canonical_active_municipality(value):
    key = " ".join(value.split()).casefold() if isinstance(value, str) else ""
    if not key:
        return ""
    municipalities = cached_active_municipalities(active_jobs_source_version())
    return next((name for name in municipalities if name.casefold() == key), None)


def municipality_suggestions(query, limit=5):
    if not isinstance(query, str):
        return []
    needle = query.strip().casefold()
    if len(needle) < 2:
        return []
    limit = min(max(int(limit), 1), 5)
    municipalities = cached_active_municipalities(active_jobs_source_version())
    prefix = [name for name in municipalities if name.casefold().startswith(needle)]
    contains = [name for name in municipalities
                if needle in name.casefold() and not name.casefold().startswith(needle)]
    return (prefix + contains)[:limit]


def all_active_vacancies(county="", page=1, page_size=ALL_JOBS_PAGE_SIZE,
                         profession="", municipality=""):
    """Current ACTIVE jobs, optionally for one canonical fylke, newest published first."""
    selected_county = canonical_fylke(county) if county else ""
    if county and selected_county is None:
        return [], 0, None
    source_version = active_jobs_source_version()
    selected_municipality = canonical_active_municipality(municipality) if municipality else ""
    if municipality and selected_municipality is None:
        return [], 0, selected_county
    dates = cached_active_published_dates(source_version)
    rows = []
    for vacancy_uuid, ad in cached_active_jobs(source_version).items():
        locations = ad.get("workLocations") or []
        if profession:
            title = " ".join(str(ad.get(key) or "") for key in ("title", "jobtitle")).casefold()
            if profession.casefold() not in title:
                continue
        if selected_county:
            locations = [location for location in locations if (location.get("county") or "").casefold() == selected_county.casefold()]
        if selected_municipality:
            locations = [location for location in locations
                         if location_municipality(location).casefold() == selected_municipality.casefold()]
        if locations or (not selected_county and not selected_municipality):
            rows.append((vacancy_uuid, ad, locations, dates.get(vacancy_uuid)))
    rows.sort(key=lambda row: (row[3] is None, -(row[3] or 0), row[0]))
    page = max(int(page), 1)
    start = (page - 1) * page_size
    return rows[start:start + page_size], len(rows), selected_county


@lru_cache(maxsize=1)
def cached_active_county_counts(source_version):
    """Active vacancy counts per canonical fylke from the current local snapshot."""
    counts = {county: 0 for county in FYLKE_OPTIONS}
    for ad in cached_active_jobs(source_version).values():
        counties = {
            canonical_fylke(location.get("county") or "")
            for location in (ad.get("workLocations") or [])
        }
        for county in counties:
            if county:
                counts[county] += 1
    return tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold())))


def active_county_leaders(limit=5):
    return cached_active_county_counts(active_jobs_source_version())[:limit]


def region_thumbnail_html(county):
    thumbnail = REGION_THUMBNAILS.get(county)
    if thumbnail:
        return (f'<span class="jobs-more-county-thumbnail" aria-hidden="true">'
                f'<img src="/static/regions/{thumbnail}" alt=""></span>')
    return '<span class="jobs-more-county-tile" aria-hidden="true"><i></i></span>'


def region_card(row, query, lang="no", preserve_lang=False):
    quality = row["quality"]
    badge = ("Begrenset datagrunnlag" if row["low_sample"] or quality is None or quality < 50
             else "Godt datagrunnlag" if quality >= 80 else "Middels datagrunnlag")
    link = internal_url({}, q=query, fylke=row["fylke"], lang=lang) if preserve_lang or lang == "en" else internal_url({}, q=query, fylke=row["fylke"])
    return f'''<article class="card region"><div class="card-head"><h3>{e(row['fylke'].title())}</h3></div>
    <div class="metrics"><div class="metric"><b>{row['strong']}</b><span>Relevante stillingsannonser</span></div>
    <div class="metric"><b>{number(row['positions'])}</b><span>Utlyste stillinger</span></div>
    <div class="metric"><b>{number(row['local_share'])}%</b><span class="share-label" tabindex="0" title="Viser hvor stor del av de analyserte annonsene i regionen som gjelder dette yrket.">Andel av annonser i regionen</span></div></div>
    <span class="badge">{badge}</span><a class="button" href="{e(link)}">Se stillinger →</a></article>'''


def result_regions(rows):
    visible = [r for r in rows if r["fylke"] != MISSING_REGION]
    order = lambda r: (-r["strong"], r["fylke"].casefold())
    areas = [r for r in visible if r["fylke"].casefold() in ("svalbard", "jan mayen")]
    counties = [r for r in visible if r not in areas]
    return sorted(counties, key=order), sorted(areas, key=order)


def data_details(rows):
    text = '''<details class="disclosure" id="datagrunnlag"><summary>Om datagrunnlaget</summary>
    <p>Lokalt NAV-utvalg. Ingen eksterne data lastes ned. Originalannonser åpnes bare når du velger lenken.</p>
    <p>Fylkene vises etter antall sterke treff, ikke etter andel eller en samlet vurdering.
    Relevante annonser er sterke treff i tittel eller yrkesfelt, også med lignende skrivemåter.
    Andelen er sterke treff delt på alle analyserbare lokale annonser i fylket.
    Den gjelder vårt analyserte utvalg i perioden, ikke sannsynligheten for å få jobb eller andelen av hele markedet.
    Utlyste stillinger summerer bare kjente arbeidsplasser med entydig fylke. Ukjente verdier er ikke null.</p>
    <p>Annonser: 14. august–11. september 2026 (Europe/Oslo). NAV-kontekst: august 2026.
    Historikken er delvis gjenopprettet, inkluderer historiske INACTIVE og dekker ikke hele markedet.
    Ulike perioder og dekning kan ikke blandes til en presis markedsandel. Annonsene var registrert som aktive ved siste lagring;
    vi har ikke kontrollert at de fortsatt er åpne. Se originalannonsen for oppdatert informasjon.</p>
    <p>Fullstendighet er andelen av alle treff med sterkt yrkestreff, STYRK/ESCO, kjent antall arbeidsplasser
    og entydig fylke. Visningsetiketter: Godt fra 80 %, Middels fra 50 %, ellers Begrenset.
    Færre enn 10 sterke treff gir alltid Begrenset datagrunnlag. Dette er enkle etiketter for datagrunnlaget,
    ikke statistisk sikkerhet eller en vurdering av jobbmulighetene. Svake treff påvirker ikke sterke antall,
    arbeidsplasser eller andelens teller.</p>'''
    for r in rows:
        text += f'''<p><strong>{e(r['fylke'].title())}</strong> · Fullstendighet: {number(r['quality'])}{'%' if r['quality'] is not None else ''} · Svake treff: {r['weak']}<br>
        NAV: helt ledige {number(r['nav_unemployed'])}; ledighet {number(r['nav_unemployment_rate'])}{'%' if r['nav_unemployment_rate'] is not None else ''};
        nye stillinger {number(r['nav_new_vacancies'])}; nye per 100 helt ledige {number(r['nav_per_100'])}.</p>'''
    return text + '</details>'


EMAIL_PATTERN = re.compile(r'(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w.-])', re.I)
PHONE_PATTERN = re.compile(r'(?<!\d)(?:\+47[ .-]?)?(?:\d{3}[ .-]\d{2}[ .-]\d{3}|\d{2}[ .-]\d{2}[ .-]\d{2}[ .-]\d{2}|\d{8})(?!\d)')
PHONE_CONTEXT_PATTERN = re.compile(r'\b(?:telefon|telefonnummer|tlf|mobil|sms|ring|kontakt)\b', re.I)


def contact_matches(text, context=''):
    matches = [('email', match.start(), match.end(), match.group(0)) for match in EMAIL_PATTERN.finditer(text)]
    for match in PHONE_PATTERN.finditer(text):
        nearby = context[-55:] + text[max(0, match.start() - 55):min(len(text), match.end() + 30)]
        if PHONE_CONTEXT_PATTERN.search(nearby):
            matches.append(('phone', match.start(), match.end(), match.group(0)))
    return sorted(matches, key=lambda item: (item[1], item[2]))


def linked_contact_text(text, context=''):
    parts, end = [], 0
    for kind, start, stop, value in contact_matches(text, context):
        if start < end:
            continue
        parts.append(e(text[end:start]))
        target = 'mailto:' + value if kind == 'email' else 'tel:' + (('+' if value.lstrip().startswith('+') else '') + ''.join(ch for ch in value if ch.isdigit()))
        parts.append(f'<a class="description-contact" href="{e(target)}">{e(value)}</a>')
        end = stop
    parts.append(e(text[end:]))
    return ''.join(parts)


class DescriptionHTML(HTMLParser):
    """Retain text structure, never execute markup or load external resources."""
    allowed = {'p', 'br', 'h2', 'h3', 'h4', 'ul', 'ol', 'li', 'strong', 'em', 'b', 'i', 'blockquote'}

    def __init__(self, linkify_contacts=False):
        super().__init__(convert_charrefs=True)
        self.parts, self.stack, self.text_parts, self.blocked = [], [], [], 0
        self.linkify_contacts = linkify_contacts

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'iframe', 'object'):
            self.blocked += 1
        if not self.blocked and tag in self.allowed:
            self.parts.append('<' + tag + '>')
            if tag != 'br':
                self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'iframe', 'object'):
            self.blocked = max(0, self.blocked - 1)
            return
        if not self.blocked and tag in self.stack:
            while self.stack:
                closing = self.stack.pop()
                self.parts.append('</' + closing + '>')
                if closing == tag:
                    break

    def handle_data(self, data):
        if not self.blocked:
            context = ' '.join(self.text_parts)[-55:]
            self.text_parts.append(data)
            self.parts.append(linked_contact_text(data, context) if self.linkify_contacts else e(data))

    def result(self):
        return ''.join(self.parts) + ''.join('</'+t+'>' for t in reversed(self.stack))


def description_markup(raw, linkify_contacts=False):
    # Remove only whole repeated section bodies, not individual repeated phrases.
    # A different heading alone must not turn an exact copy into new content.
    seen = set()
    def section(match):
        body = re.sub(r'^\s*<h[1-6]\b[^>]*>.*?</h[1-6]>', '', match.group(1), count=1, flags=re.S | re.I)
        key = re.sub(r'>\s+<', '><', body.strip())
        if key and key in seen:
            return ''
        if key:
            seen.add(key)
        return match.group(0)
    cleaned = re.sub(r'<section\b[^>]*>((?:(?!<section\b).)*?)</section>', section, raw, flags=re.S | re.I)
    parser = DescriptionHTML(linkify_contacts=linkify_contacts)
    parser.feed(cleaned)
    parser.close()
    return parser.result()


def description_contacts(raw):
    parser = DescriptionHTML()
    parser.feed(raw or '')
    parser.close()
    text = ' '.join(parser.text_parts)
    emails, phones = [], []
    for kind, _, _, value in contact_matches(text):
        values = emails if kind == 'email' else phones
        if value not in values:
            values.append(value)
    return emails, phones


def stored_contacts(raw):
    try:
        values = json.loads(raw or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(values, list):
        return []
    contacts, seen = [], set()
    for value in values:
        if not isinstance(value, dict):
            continue
        contact = {key: value.get(key).strip() if isinstance(value.get(key), str) else ''
                   for key in ('name', 'title', 'role', 'email', 'phone')}
        if not any(contact.values()):
            continue
        key = tuple(contact[field].casefold() for field in ('name', 'title', 'role', 'email', 'phone'))
        if key not in seen:
            contacts.append(contact)
            seen.add(key)
    return contacts


def description_contact_records(raw):
    """Expose only contact values already parsed from the saved description."""
    emails, phones = description_contacts(raw)
    parser = DescriptionHTML()
    parser.feed(raw or '')
    parser.close()
    parts = [re.sub(r'\s+', ' ', value).strip() for value in parser.text_parts if value.strip()]

    def part_index(value):
        return next((index for index, part in enumerate(parts) if value.casefold() in part.casefold()), -1)

    def looks_like_name(value):
        words = value.strip().split()
        return (1 <= len(words) <= 5 and all(word[:1].isupper() for word in words)
                and not re.search(r'\b(?:e-?post|telefon|kontakt|søknad)\b', value, re.I))

    def identity(index):
        if index < 0:
            return '', ''
        current = parts[index]
        fields = [field.strip(' :-') for field in current.split(',') if field.strip(' :-')]
        first_contact = next((position for position, field in enumerate(fields)
                              if EMAIL_PATTERN.search(field) or PHONE_PATTERN.search(field)), None)
        if first_contact is not None and first_contact and looks_like_name(fields[0]):
            return fields[0], fields[1] if first_contact > 1 else ''
        start = next((position for position in range(index - 1, max(-1, index - 8), -1)
                      if re.fullmatch(r'(?:søknad og kontakt|kontaktinformasjon|kontaktperson(?: for stillingen)?)',
                                      parts[position].strip(' :'), re.I)), None)
        if start is None:
            return '', ''
        between = parts[start + 1:index]
        if any(EMAIL_PATTERN.search(value) or PHONE_PATTERN.search(value) for value in between):
            return '', ''
        candidates = [value.strip(' :-') for value in between
                      if value.strip(' :-') and not re.fullmatch(r'(?:e-?post|telefon|tlf)', value.strip(' :'), re.I)]
        if candidates and looks_like_name(candidates[0]):
            return candidates[0], candidates[1] if len(candidates) > 1 else ''
        return '', ''

    # Some structured contact lines contain an unlabelled eight-digit phone.
    # Accept it only in the same text node as an already validated email.
    for email in emails:
        index = part_index(email)
        if index >= 0:
            for match in PHONE_PATTERN.finditer(parts[index]):
                value = match.group(0)
                if value not in phones:
                    phones.append(value)

    phone_positions = {value: part_index(value) for value in phones}
    unused_phones = set(phones)
    records = []
    for email in emails:
        index = part_index(email)
        nearby = min((value for value in unused_phones
                      if phone_positions[value] >= 0 and index >= 0 and abs(phone_positions[value] - index) <= 1),
                     key=lambda value: abs(phone_positions[value] - index), default='')
        if nearby:
            unused_phones.remove(nearby)
        name, title = identity(index)
        records.append(dict(name=name, title=title, role='', email=email, phone=nearby,
                            from_description=True))
    for phone in phones:
        if phone not in unused_phones:
            continue
        name, title = identity(phone_positions[phone])
        records.append(dict(name=name, title=title, role='', email='', phone=phone,
                            from_description=True))
    return records


def phone_target(value):
    prefix = '+' if value.lstrip().startswith('+') else ''
    digits = ''.join(character for character in value if character.isdigit())
    return prefix + digits if 7 <= len(digits) <= 15 else ''


APPLICATION_EMAIL_CONTEXT = re.compile(
    r'(?:send\s+(?:søknad(?:en)?(?:\s+og\s+cv)?|cv(?:\s+og\s+søknad)?)'
    r'|søknad(?:en)?[^@]{0,100}?sendes|søk(?:nad)?\s+via\s+e-?post)[^@]{0,100}$', re.I)


def description_application_email(raw):
    parser = DescriptionHTML()
    parser.feed(raw or '')
    parser.close()
    text = re.sub(r'\s+', ' ', ' '.join(parser.text_parts))
    for match in EMAIL_PATTERN.finditer(text):
        if APPLICATION_EMAIL_CONTEXT.search(text[max(0, match.start() - 160):match.start()]):
            return match.group(0)
    return None


def detail_contact_data(ad):
    """Shared, read-only contact and application choices for both detail views."""
    emails, phones = description_contacts(ad['description'])
    application_email = description_application_email(ad['description'])
    stored = stored_contacts(ad['contact_list_json'])
    contacts = stored or description_contact_records(ad['description'])
    application_candidate = ad['application_url'] if (
        ad['application_url'] and urlsplit(ad['application_url']).scheme in ('http', 'https')
        and urlsplit(ad['application_url']).netloc) else None
    application_parts = urlsplit(application_candidate) if application_candidate else None
    is_superrask = bool(application_parts and application_parts.hostname == 'arbeidsplassen.nav.no'
                        and application_parts.path.rstrip('/').endswith('/superrask-soknad'))
    application_link = application_candidate if (
        application_candidate and (application_parts.hostname != 'arbeidsplassen.nav.no' or is_superrask)) else None
    source_link = next((ad[key] for key in ('link', 'source_url', 'application_url')
                        if ad[key] and urlsplit(ad[key]).scheme in ('http', 'https')
                        and urlsplit(ad[key]).netloc
                        and urlsplit(ad[key]).hostname == 'arbeidsplassen.nav.no'
                        and not urlsplit(ad[key]).path.rstrip('/').endswith('/superrask-soknad')), None)
    contact_email = next((contact['email'] for contact in contacts
                          if contact['email'] and EMAIL_PATTERN.fullmatch(contact['email'])), None)
    contact_phone = next(((contact['phone'], phone_target(contact['phone'])) for contact in contacts
                          if contact['phone'] and phone_target(contact['phone'])), None)
    if stored and not application_link and not application_email:
        application_email = contact_email
    contact_link = ('mailto:' + contact_email if contact_email else
                    'tel:' + contact_phone[1] if contact_phone else None)
    return {
        'contacts': contacts,
        'description_email_keys': {value.casefold() for value in emails},
        'description_phone_keys': {phone_target(value) for value in phones if phone_target(value)},
        'application_email': application_email,
        'application_link': application_link,
        'contact_link': contact_link,
        'contact_kind': 'email' if contact_email else 'phone' if contact_phone else None,
        'contact_value': contact_email if contact_email else contact_phone[0] if contact_phone else None,
        'source_link': source_link,
        'primary_link': application_link or ('mailto:' + application_email if application_email else None) or contact_link,
    }


def detail_contact_section(data):
    rows = []
    for contact in data['contacts']:
        details = []
        from_description = contact.get('from_description', False)
        roles = [value for value in (contact['title'], contact['role']) if value]
        if roles:
            details.append('<span class="contact-role">' + e(' · '.join(dict.fromkeys(roles))) + '</span>')
        if (contact['email'] and (from_description or contact['email'].casefold() not in data['description_email_keys'])
                and EMAIL_PATTERN.fullmatch(contact['email'])):
            details.append(f'<a href="mailto:{e(contact["email"])}">{e(contact["email"])}</a>')
        target = phone_target(contact['phone'])
        if contact['phone'] and target and (from_description or target not in data['description_phone_keys']):
            details.append(f'<a href="tel:{e(target)}">{e(contact["phone"])}</a>')
        if contact['name'] or details:
            heading = f'<strong>{e(contact["name"])}</strong>' if contact['name'] else ''
            rows.append('<div class="regional-contact">' + heading + ''.join(details) + '</div>')
    if not rows:
        return ''
    named = sum(bool(contact['name']) for contact in data['contacts'])
    label = ('Kontaktperson for stillingen' if named == 1 else
             'Kontaktpersoner for stillingen' if named > 1 else 'Kontaktopplysninger')
    return f'<section class="explore-job-section regional-job-contacts"><h2>{label}</h2>' + ''.join(rows) + '</section>'


def detail_primary_action(data):
    if data['application_link']:
        return 'Søk hos arbeidsgiver →', ' target="_blank" rel="noopener noreferrer"'
    if data['application_email']:
        return 'Send søknad på e-post →', ''
    if data['contact_kind'] == 'email':
        return 'Kontakt via e-post →', ''
    if data['contact_kind'] == 'phone':
        return 'Ring kontaktperson →', ''
    return None, ''


def detail_primary_action_markup(data):
    label, external = detail_primary_action(data)
    if data['primary_link'] and label:
        return f'<a class="detail-primary-action" href="{e(data["primary_link"])}"{external}>{label}</a>'
    return ''


def detail_secondary_action_markup(data, compact=False):
    text = ''
    if data['application_link'] and data['application_email']:
        text += (f'<p class="detail-alternative">Alternativt kan du sende søknad på e-post: '
                 f'<a href="mailto:{e(data["application_email"])}">{e(data["application_email"])}</a></p>')
    elif data['application_link'] and compact and data['contact_link'] and data['contact_kind'] == 'email':
        text += (f'<p class="detail-alternative">Alternativt kan du sende søknad på e-post: '
                 f'<a href="{e(data["contact_link"])}">{e(data["contact_value"])}</a></p>')
    elif data['application_email']:
        text += f'<p><a href="mailto:{e(data["application_email"])}">{e(data["application_email"])}</a></p>'
    elif data['contact_link'] and data['contact_kind'] == 'email':
        text += f'<p><a href="{e(data["contact_link"])}">{e(data["contact_value"])}</a></p>'
    elif data['contact_link'] and data['contact_kind'] == 'phone':
        text += f'<p><a href="{e(data["contact_link"])}">{e(data["contact_value"])}</a></p>'
    if data['source_link']:
        text += (f'<p class="original-ad"><a href="{e(data["source_link"])}" target="_blank" '
                 'rel="noopener noreferrer">Se originalannonsen på Arbeidsplassen →</a></p>')
    return text


def detail_action_markup(data):
    return detail_primary_action_markup(data) + detail_secondary_action_markup(data)


def detail_application_status(timestamp=None, raw=''):
    date = None
    if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
        try:
            date = (EPOCH + timedelta(microseconds=timestamp)).astimezone()
        except (ValueError, OverflowError, OSError):
            pass
    if date is None and isinstance(raw, str) and raw.strip():
        try:
            date = datetime.fromisoformat(raw.strip().replace('Z', '+00:00')).astimezone()
        except ValueError:
            try:
                date = datetime.strptime(raw.strip(), '%d.%m.%Y')
            except ValueError:
                pass
    if date is None:
        return 'Søk snarest mulig'
    months = ('januar', 'februar', 'mars', 'april', 'mai', 'juni',
              'juli', 'august', 'september', 'oktober', 'november', 'desember')
    return f'Søk innen {date.day}. {months[date.month - 1]} {date.year}'


def detail_main_application_section(data, deadline_timestamp=None, deadline_raw=''):
    if not data['primary_link'] and not data['source_link']:
        return ''
    icon = ('<span class="detail-main-icon" aria-hidden="true"><svg viewBox="0 0 24 24">'
            '<path d="M5 12h14M13 6l6 6-6 6"/></svg></span>')
    return ('<section class="explore-job-section detail-application-main"><div class="detail-main-top">'
            '<div class="detail-main-heading">' + icon + '<div><h2>Søk på jobben</h2>'
            f'<p class="detail-main-status">{e(detail_application_status(deadline_timestamp, deadline_raw))}</p>'
            '</div></div><div class="detail-main-cta">' + detail_primary_action_markup(data)
            + '</div></div><div class="detail-main-meta">' + detail_secondary_action_markup(data, compact=True)
            + '</div></section>')


def detail_application_section(data, application_sections=()):
    if not application_sections and not data['primary_link'] and not data['source_link']:
        return ''
    text = '<section class="explore-job-card explore-job-apply"><h2>Slik søker du</h2>'
    if application_sections:
        text += ''.join(application_sections)
    return text + detail_action_markup(data) + '</section>'


def format_deadline(timestamp, raw):
    if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
        try:
            return (EPOCH + timedelta(microseconds=timestamp)).astimezone().strftime('%d.%m.%Y')
        except (ValueError, OverflowError, OSError):
            pass
    value = raw.strip() if isinstance(raw, str) else ''
    if value:
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00')).strftime('%d.%m.%Y')
        except ValueError:
            pass  # Preserve existing textual deadlines, e.g. "Snarest".
    return value


def load_detail_job(uid):
    """The existing indexed lookup, also used before ordinary-detail analytics."""
    with sqlite3.connect(DATABASE.resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        ad = db.execute("SELECT v.* FROM jobs j JOIN job_versions v ON v.id=j.current_version_id "
                        "AND v.job_uuid=j.uuid WHERE j.uuid=? AND j.status='ACTIVE' AND v.status='ACTIVE'", (uid,)).fetchone()
        locations = (db.execute('SELECT * FROM job_locations WHERE version_id=?', (ad['id'],)).fetchall()
                     if ad is not None else [])
    return ad, locations


def job_detail(query, county, uid, return_url=None, status=None, lang="no", preserve_lang=False, *, loaded=None):
    ad, locations = load_detail_job(uid) if loaded is None else loaded
    if ad is None:
        back = return_url or (internal_url({}, q=query, fylke=county, lang=lang) if preserve_lang or lang == 'en' else internal_url({}, q=query, fylke=county))
        return ('<section class="explore-job regional-job"><div class="explore-job-main">'
                + f'<p class="explore-job-back"><a href="{e(back)}">← Tilbake til stillingene</a></p>'
                + '<h1>Annonsen er ikke tilgjengelig</h1>'
                + '<section class="explore-job-section"><p>Annonsen er ikke lenger tilgjengelig i det lagrede utvalget.</p></section>'
                + '</div></section>')
    contact_data = detail_contact_data(ad)
    if return_url:
        places = list(dict.fromkeys(', '.join(v for v in (loc['kommune'], loc['fylke']) if v) for loc in locations))
        place = '; '.join(p for p in places if p)
        facts = []
        for label, value in (('Sted', place), ('Arbeidsgiver', ad['employer_name']),
                             ('Antall stillinger', ad['positioncount']),
                             ('Publisert', format_published_short(ad['published']) if ad['published'] else None),
                             ('Søknadsfrist', format_deadline(ad['application_due'], ad['application_due_raw']))):
            if value is not None and value != '':
                facts.append((label, value))
        text = '<section class="explore-job"><div class="explore-job-main">'
        text += f'<p class="explore-job-back"><a href="{e(return_url)}">← Tilbake til stillingene</a></p>'
        text += f'<h1>{e(ad["title"] or ad["jobtitle"] or "Stillingsannonse")}</h1>'
        if ad['employer_name']:
            text += f'<p class="explore-job-employer">{e(ad["employer_name"])}</p>'
        if place:
            text += f'<p class="explore-job-place">{e(place)}</p>'
        if status:
            text += f'<span class="badge">{e(status)}</span>'
        text += detail_main_application_section(
            contact_data, ad['application_due'], ad['application_due_raw'])
        markup = description_markup(ad['description'], linkify_contacts=True) if ad['description'] else ''
        headings = list(re.finditer(r'<h[23]>.*?</h[23]>|<p><strong>[^<]{1,80}:</strong></p>', markup, re.S))
        sections = []
        if headings:
            preface = markup[:headings[0].start()]
            if preface.strip():
                sections.append(('', preface))
            for index, heading in enumerate(headings):
                end = headings[index + 1].start() if index + 1 < len(headings) else len(markup)
                title = heading.group(0)
                if title.startswith('<p><strong>'):
                    title = '<h2>' + re.sub(r'<[^>]+>', '', title) + '</h2>'
                sections.append((title, markup[heading.end():end]))
        elif markup.strip():
            sections.append(('', markup))
        application_sections = []
        for heading, content in sections:
            if heading and content.strip() and re.search(
                    r'^(?:slik søker du|søknad|søknadsprosess|søknadsinformasjon|hvordan søke|send søknad)',
                    re.sub(r'<[^>]+>', '', heading).strip(), re.I):
                application_sections.append(content)
            else:
                text += '<section class="explore-job-section">' + heading + content + '</section>'
        text += detail_contact_section(contact_data)
        text += '</div><aside class="explore-job-sidebar"><section class="explore-job-card explore-job-facts"><h2>Kort om stillingen</h2>'
        if facts:
            fact_classes = {'Sted': 'place', 'Arbeidsgiver': 'employer', 'Antall stillinger': 'positions',
                            'Publisert': 'published', 'Søknadsfrist': 'deadline'}
            text += '<dl>' + ''.join(f'<div class="fact-{fact_classes[label]}"><dt>{e(label)}</dt><dd>{e(value)}</dd></div>'
                                      for label, value in facts) + '</dl>'
        text += '</section>'
        text += detail_application_section(contact_data, application_sections)
        text += '<section class="explore-job-card explore-job-insight"><h2>Jobbinnsikt</h2>'
        text += f'<p>Du utforsker {e(query)} i {e(county.title())}. Se annonsens innhold for å vurdere om oppgavene passer deg.</p>'
        text += '<p>Annonsen var registrert som aktiv ved siste lagring. Kontroller frist og tilgjengelighet hos arbeidsgiveren.</p>'
        return text + '</section></aside></section>'
    back = return_url or '/?' + urlencode(dict(q=query, fylke=county))
    places = list(dict.fromkeys(', '.join(v for v in (loc['kommune'], loc['fylke']) if v) for loc in locations))
    place = '; '.join(p for p in places if p)
    facts = []
    for label, value in (('Sted', place), ('Arbeidsgiver', ad['employer_name']),
                         ('Antall stillinger', ad['positioncount']),
                         ('Publisert', format_published_short(ad['published']) if ad['published'] else None)):
        if value is not None and value != '':
            facts.append((label, value))
    deadline = format_deadline(ad['application_due'], ad['application_due_raw'])
    if deadline:
        facts.append(('Søknadsfrist', deadline))
    text = '<section class="explore-job regional-job"><div class="explore-job-main">'
    text += f'<p class="explore-job-back"><a href="{e(back)}">← Tilbake til stillingene</a></p>'
    text += f'<h1>{e(ad["title"] or ad["jobtitle"] or "Stillingsannonse")}</h1>'
    if ad['employer_name']:
        text += f'<p class="explore-job-employer">{e(ad["employer_name"])}</p>'
    if place:
        text += f'<p class="explore-job-place">{e(place)}</p>'
    text += '<span class="badge">Bekreftet</span>'
    text += detail_main_application_section(
        contact_data, ad['application_due'], ad['application_due_raw'])
    if ad['description']:
        plain = '' if re.search(r'<(?:p|h[1-6]|ul|ol|li|section)\b', ad['description'], re.I) else ' plain-description'
        text += '<section class="explore-job-section regional-job-description"><div class="job-description' + plain + '">' + description_markup(ad['description'], linkify_contacts=True) + '</div></section>'
    text += detail_contact_section(contact_data)
    text += '</div><aside class="explore-job-sidebar"><section class="explore-job-card explore-job-facts"><h2>Kort om stillingen</h2>'
    fact_classes = {'Sted': 'place', 'Arbeidsgiver': 'employer', 'Antall stillinger': 'positions',
                    'Publisert': 'published', 'Søknadsfrist': 'deadline'}
    if facts:
        text += '<dl>' + ''.join(f'<div class="fact-{fact_classes[label]}"><dt>{e(label)}</dt><dd>{e(value)}</dd></div>' for label, value in facts) + '</dl>'
    text += '</section>'
    text += detail_application_section(contact_data)
    text += '<section class="explore-job-card explore-job-insight"><h2>Jobbinnsikt</h2>'
    text += f'<p>Du utforsker {e(query)} i {e(county.title())}. Se annonsens innhold for å vurdere om oppgavene passer deg.</p>'
    text += '<p>Annonsen var registrert som aktiv ved siste lagring. Kontroller frist og tilgjengelighet hos arbeidsgiveren.</p></section></aside></section>'
    matches = {} if return_url else active_matches(query, county)[0]
    related = [(key, item) for key, item in matches.items() if key != uid and item[3] >= 10][:3]
    if related:
        text += '<h2 class="related-heading">Flere relevante stillinger</h2><div class="job-list related-jobs">'
        for key, (other, _, _, _) in related:
            href = '/?' + urlencode(dict(q=query, fylke=county, job=key))
            text += f'<article class="job-row"><h3>{e(other.get("title") or other.get("jobtitle") or "Stillingsannonse")}</h3><a class="job-link" href="{e(href)}">Se hele stillingen →</a></article>'
        text += '</div>'
    return text


CSS += """.job-detail{max-width:980px;background:white;border:1px solid var(--line);border-radius:18px;padding:28px;margin:18px 0}.job-detail h1{font-size:clamp(26px,3vw,38px);line-height:1.2}.job-facts{display:flex;flex-wrap:wrap;gap:16px 36px;background:#f4f6ef;padding:16px;border-radius:12px}.job-facts dt{font-size:13px;color:var(--muted)}.job-facts dd{margin:2px 0 0;font-weight:600}.job-description{max-width:78ch;line-height:1.75;white-space:pre-line;overflow-wrap:anywhere;margin:24px 0}.job-description h2{font-size:24px}.job-description h3{font-size:20px}.job-description p{margin:12px 0}.job-description ul,.job-description ol{white-space:normal}.job-detail .note{margin-bottom:0}@media(max-width:700px){.job-detail{padding:20px}.job-facts{gap:16px}}"""


CSS += """.job-detail{padding:22px 26px;margin:12px 0}.job-detail h1{margin:0 0 12px}.job-detail .intro{margin:8px 0 12px;font-size:17px}.job-facts{padding:12px 14px;margin:12px 0;gap:12px 28px}.job-description{line-height:1.55;white-space:normal;margin:18px 0}.job-description.plain-description{white-space:pre-line}.job-description p{margin:7px 0}.job-description h2{margin:18px 0 8px;font-size:23px}.job-description h3,.job-description h4{margin:14px 0 6px}.job-description ul,.job-description ol{margin:8px 0;padding-left:24px}.job-description li{margin:3px 0}.job-description li p{margin:2px 0}.job-detail .note{padding:14px 18px;margin-top:18px}.job-detail .note h3{font-size:19px;margin:0 0 6px}.job-detail .note p{margin:6px 0;line-height:1.5}.related-heading{font-size:23px;margin:18px 0 10px}.related-jobs .job-row{min-height:64px;padding:12px 18px}.related-jobs h3{font-size:17px;margin:0}@media(max-width:700px){.job-detail{padding:18px}.job-description{line-height:1.6}.related-jobs .job-row{gap:8px}}"""


def vacancies(query, county, lang="no", preserve_lang=False):
    matches, dates = active_matches(query, county)
    primary, other = [], []
    months = ('januar', 'februar', 'mars', 'april', 'mai', 'juni', 'juli', 'august', 'september', 'oktober', 'november', 'desember')
    card_icons = (
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 4.5C12.5 4.5 6.2 8.2 4 16c4.4.4 8-1.1 10.7-4.3-1.6 3-4 5.3-7.3 6.9"/><path d="M4 20c1.2-4.3 4.2-7.7 8.8-10.1"/></svg>',
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 21V6h6v15M10 9h10v12M2 21h20"/><path d="M7 9v2m0 3v2m7-4v2m3-2v2m-3 3v2m3-2v2"/></svg>',
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2l1.5 5.3L19 9l-5.5 1.7L12 16l-1.5-5.3L5 9l5.5-1.7L12 2Z"/><path d="M19 15l.8 2.7L22 19l-2.2 1.3L19 23l-.8-2.7L16 19l2.2-1.3L19 15Z"/></svg>',
        '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="9" cy="8" r="3"/><circle cx="17" cy="9" r="2.5"/><path d="M3 20v-2a5 5 0 0 1 10 0v2m1-6a4 4 0 0 1 6 3.5V20"/></svg>',
    )
    meta_icons = {
        'employer': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 21V6h7v15M11 10h9v11M2 21h20"/><path d="M7 9v2m0 3v2m7-2v2m3-2v2"/></svg>',
        'place': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 10c0 6-8 11-8 11S4 16 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/></svg>',
        'date': '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4m10-4v4M3 10h18"/></svg>',
    }
    tag_rules = (
        ('Erfaring', r'erfaring'), ('Selvstendighet', r'selvstendig|selvstend'), ('Pålitelighet', r'pålitelig|punktlig'),
        ('Kveld', r'kveld'), ('Natt', r'natt'), ('Deltid', r'deltid|20-50|stilling(?:s)?prosent'),
        ('Vikariat', r'vikar|tilkalling'), ('Fleksibel', r'fleksibel'), ('Kundeservice', r'kunde|service'),
        ('Ekstrahjelp', r'ekstrahjelp|ekstra hjelp'),
    )
    for card_index, (uid, (ad, locations, reasons, score)) in enumerate(matches.items()):
        stamp = dates.get(uid)
        day = (EPOCH + timedelta(microseconds=stamp)).astimezone() if stamp is not None else None
        published = f"Publisert {day.day}. {months[day.month-1]} {day.year}" if day else "Publiseringsdato ikke oppgitt"
        municipalities = ", ".join(dict.fromkeys(loc.get("municipal") or "Ikke oppgitt" for loc in locations))
        snippet = ad_summary(ad)
        employer = (ad.get("employer") or {}).get("name") or "Arbeidsgiver ikke oppgitt"
        card = f'<article class="job-row"><span class="vacancy-icon">{card_icons[card_index % len(card_icons)]}</span><div class="job-copy"><h3>{e(ad.get("title") or ad.get("jobtitle") or "Uten tittel")}</h3>'
        card += '<p class="job-meta-line">'
        card += f'<span>{meta_icons["employer"]}{e(employer)}</span><span>{meta_icons["place"]}{e(municipalities)}</span>'
        card += f'</p><p class="job-date">{meta_icons["date"]}{e(published)}</p>'
        if snippet:
            card += f'<p class="job-snippet">{e(snippet)}</p>'
        haystack = ' '.join(str(v or '') for v in (ad.get('title'), ad.get('jobtitle'), snippet)).casefold()
        tags = []
        profession_tag = 'Renhold' if normalize(query) in ('renholder', 'renhold') else query[:1].upper() + query[1:]
        if profession_tag:
            tags.append(profession_tag)
        for label, pattern in tag_rules:
            if len(tags) >= 4:
                break
            if re.search(pattern, haystack, re.I) and label not in tags:
                tags.append(label)
        if tags:
            card += '<div class="job-tags">' + ''.join(f'<span>{e(tag)}</span>' for tag in tags) + '</div>'
        card += '</div>'
        internal = internal_url({}, q=query, fylke=county, job=uid, lang=lang) if preserve_lang or lang == 'en' else internal_url({}, q=query, fylke=county, job=uid)
        card += f'<a class="job-link" href="{e(internal)}">Se hele stillingen →</a>'
        card += '</article>'
        (primary if score >= 10 else other).append(card)
    title = f'{query[:1].upper()+query[1:]} i {county.title()}'
    content = f'<div class="vacancy-layout"><section class="vacancy-results"><h2>{e(title)}</h2><p>{len(primary)} relevante stillingsannonser i utvalget.</p><div class="job-list">' + ''.join(primary) + '</div>'
    if other:
        content += f'<details class="disclosure"><summary>Andre mulige treff ({len(other)})</summary><div class="job-list">' + ''.join(other) + '</div></details>'
    if not matches:
        content += '<p class="empty">Ingen annonser funnet i utvalget. Det betyr ikke at slike jobber ikke finnes i NAV.</p>'
    content += f'''</section><aside class="vacancy-sidebar"><section class="region-summary"><div><span class="region-pin" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M20 10c0 6-8 11-8 11S4 16 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/></svg></span><h2>{e(county.title())}</h2><p>{len(primary)} stillinger</p></div><span class="city-photo" role="img" aria-label="Oslo ved Operaen og vannkanten"></span></section>
    <section class="vacancy-info"><span class="eyebrow">OM STILLINGENE</span><h2>{e(title)}</h2><p>Her ser du stillinger som matcher søkekriteriene dine. Les mer om hver stilling for å se om den passer for deg.</p><ul>
    <li><span class="info-icon document" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M6 3h9l3 3v15H6zM9 10h6m-6 4h6m-6 4h4"/></svg></span><span>Reelle stillingsannonser<br>fra NAV / Arbeidsplassen</span></li>
    <li><span class="info-icon shield" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M12 3 5 6v5c0 4.6 2.8 8 7 10 4.2-2 7-5.4 7-10V6z"/><path d="m9 12 2 2 4-5"/></svg></span><span>Oppdatert informasjon</span></li>
    <li><span class="info-icon people" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="3"/><circle cx="17" cy="9" r="2.5"/><path d="M3 20v-2a5 5 0 0 1 10 0v2m1-6a4 4 0 0 1 6 3.5V20"/></svg></span><span>Ulike arbeidsgivere og<br>arbeidsplasser</span></li>
    <li><span class="info-icon location" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M20 10c0 6-8 11-8 11S4 16 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/></svg></span><span>Stillinger i {e(county.title())}</span></li></ul></section>
    <section class="vacancy-next"><span class="next-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M12 21V10m0 5c-5 0-7-3-7-7 5 0 7 3 7 7Zm0-4c0-4 2.5-7 7-7 0 4-2.5 7-7 7Z"/><path d="M7 21h10"/></svg></span><div><h2>Et steg nærmere<br>riktig retning</h2><p>Utforsk mulighetene, og finn<br>stillinger som passer din hverdag<br>og dine mål.</p></div><span class="next-landscape" aria-hidden="true"><i></i><b></b><em></em></span></section></aside></div>'''
    return content


def all_jobs_url(county="", page=1, lang="no", preserve_lang=False, job=None,
                 profession="", municipality=""):
    values = {"mode": "jobs", "page": page}
    if county:
        values["fylke"] = county
    if profession:
        values["q"] = profession
    if municipality:
        values["kommune"] = municipality
    if job:
        values["job"] = job
    if preserve_lang or lang == "en":
        values["lang"] = lang
    return internal_url(values)


def all_jobs_page(county="", page=1, lang="no", preserve_lang=False,
                  profession="", municipality=""):
    rows, total, selected_county = all_active_vacancies(
        county, page, profession=profession, municipality=municipality)
    tr = lambda key, **values: e(t(lang, key, **values))
    heading = tr("jobs.in_county", fylke=selected_county) if selected_county else tr("jobs.title")
    selected = selected_county or ""
    options = f'<option value="">{tr("jobs.all_counties")}</option>' + ''.join(
        f'<option value="{e(item)}"{" selected" if item == selected else ""}>{e(item)}</option>'
        for item in FYLKE_OPTIONS
    )
    lang_input = f'<input type="hidden" name="lang" value="{lang}">' if preserve_lang or lang == "en" else ""
    search_icon = '<svg class="search-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="10" cy="10" r="6.5"/><path d="m15 15 6 6"/></svg>'
    pin_icon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 10c0 6-8 11-8 11S4 16 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/></svg>'
    form = (f'<form class="result-search all-jobs-filter" method="get" action="/">{lang_input}'
            '<input type="hidden" name="mode" value="jobs">'
            f'<label class="visually-hidden" for="profession">{tr("home.search_label")}</label>'
            f'<div class="search all-jobs-query">{search_icon}<input id="profession" name="q" data-autocomplete autocomplete="off" placeholder="{tr("home.search_placeholder")}" value="{e(profession)}" maxlength="120"></div>'
            f'<div class="all-jobs-county">{pin_icon}<label class="visually-hidden" for="all-jobs-county">{tr("jobs.county_label")}</label><select id="all-jobs-county" name="fylke" data-jobs-filter>{options}</select></div>'
            f'<label class="visually-hidden" for="all-jobs-municipality">Kommune</label>'
            f'<div class="search all-jobs-municipality"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 10c0 6-8 11-8 11S4 16 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/></svg><input id="all-jobs-municipality" name="kommune" data-autocomplete="municipality" autocomplete="off" placeholder="Skriv kommune" value="{e(municipality)}" maxlength="120"></div>'
            f'<button data-loading-label="{tr("home.searching")}">{tr("home.search_cta")} <span aria-hidden="true">&rarr;</span></button></form>')
    cards = []
    card_icon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 21V6h7v15M11 10h9v11M2 21h20"/><path d="M7 9v2m0 3v2m7-2v2m3-2v2"/></svg>'
    employer_icon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 21V6h7v15M11 10h9v11M2 21h20"/><path d="M7 9v2m0 3v2m7-2v2m3-2v2"/></svg>'
    date_icon = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4m10-4v4M3 10h18"/></svg>'
    for vacancy_uuid, ad, locations, stamp in rows:
        municipalities = ", ".join(dict.fromkeys(location.get("municipal") or "Ikke oppgitt" for location in locations)) or "Ikke oppgitt"
        employer = (ad.get("employer") or {}).get("name") or "Arbeidsgiver ikke oppgitt"
        published = format_published_short(stamp) if stamp is not None else "Publiseringsdato ikke oppgitt"
        details = all_jobs_url(selected_county or "", page, lang, preserve_lang, vacancy_uuid,
                       profession, municipality)
        card = (f'<article class="job-row"><span class="vacancy-icon">{card_icon}</span><div class="job-copy">'
                f'<h3>{e(ad.get("title") or ad.get("jobtitle") or "Uten tittel")}</h3>'
                f'<p class="job-meta-line"><span>{employer_icon}{e(employer)}</span><span>{pin_icon}{e(municipalities)}</span></p>'
                f'<p class="job-date">{date_icon}{e(published)}</p>')
        snippet = ad_summary(ad)
        if snippet:
            card += f'<p class="job-snippet">{e(snippet)}</p>'
        cards.append(card + f'</div><a class="job-link" href="{e(details)}">Se hele stillingen &rarr;</a></article>')
    if not cards:
        cards.append(f'<p class="empty">{tr("jobs.empty")}</p>')
    page = max(int(page), 1)
    pages = max((total + ALL_JOBS_PAGE_SIZE - 1) // ALL_JOBS_PAGE_SIZE, 1)
    start = (page - 1) * ALL_JOBS_PAGE_SIZE + 1 if total else 0
    end = min(page * ALL_JOBS_PAGE_SIZE, total)
    pagination = '<nav class="all-jobs-pagination" aria-label="Pagination">'
    if page > 1:
        pagination += f'<a class="page-link" href="{e(all_jobs_url(selected_county or "", page - 1, lang, preserve_lang, profession=profession, municipality=municipality))}" aria-label="{tr("jobs.previous")}">&lsaquo;</a>'
    for number in range(1, min(pages, 5) + 1):
        current = ' class="page-link current" aria-current="page"' if number == page else ' class="page-link"'
        pagination += f'<a{current} href="{e(all_jobs_url(selected_county or "", number, lang, preserve_lang, profession=profession, municipality=municipality))}">{number}</a>'
    if pages > 5:
        pagination += '<span class="page-ellipsis">&hellip;</span>'
    if page < pages:
        pagination += f'<a class="page-link" href="{e(all_jobs_url(selected_county or "", page + 1, lang, preserve_lang, profession=profession, municipality=municipality))}" aria-label="{tr("jobs.next")}">&rsaquo;</a>'
    pagination += '</nav>'
    vakt_url = local_nav_url("vakt", lang, include_lang=preserve_lang)
    help_rows = (("jobs.help_search", "jobs.help_search_copy", "search"),
                 ("jobs.help_county", "jobs.help_county_copy", "pin"),
                 ("jobs.help_newest", "jobs.help_newest_copy", "star"))
    side_icons = {
        "search": search_icon, "pin": pin_icon,
        "star": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 2.6 5.3 5.9.9-4.3 4.2 1 5.9-5.2-2.8-5.2 2.8 1-5.9-4.3-4.2 5.9-.9Z"/></svg>'
    }
    help_html = ''.join(f'<div class="jobs-help-row {kind}"><span>{side_icons[kind]}</span><div><h3>{tr(title)}</h3><p>{tr(copy)}</p></div><i class="jobs-help-arrow" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="m9 5 7 7-7 7"/></svg></i></div>'
                        for title, copy, kind in help_rows)
    tip_icons = {
        "search": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10" cy="10" r="6.5"/><path d="m15 15 6 6"/></svg>',
        "pin": pin_icon,
        "filters": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h10m3 0h3M4 17h3m3 0h10"/><circle cx="15" cy="7" r="3"/><circle cx="9" cy="17" r="3"/></svg>',
        "save": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 8.5C20 14 12 20 12 20S4 14 4 8.5A4.5 4.5 0 0 1 12 5.7a4.5 4.5 0 0 1 8 2.8Z"/></svg>',
    }
    tips_chevron = '<i class="jobs-tips-arrow" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="m9 5 7 7-7 7"/></svg></i>'
    tip_rows = (("jobs.tips_search_title", "jobs.tips_search_copy", "search", "search"),
                ("jobs.tips_county_title", "jobs.tips_county_copy", "pin", "county"),
                ("jobs.tips_filters_title", "jobs.tips_filters_copy", "filters", "filters"))
    tips_html = ''.join(
        f'<button class="jobs-tips-row" type="button" data-jobs-tip="{action}"><span class="jobs-tips-icon">{tip_icons[kind]}</span><span class="jobs-tips-copy"><b>{tr(title)}</b><small>{tr(copy)}</small></span>{tips_chevron}</button>'
        for title, copy, kind, action in tip_rows
    )
    tips_html += (f'<a class="jobs-tips-row" href="{e(vakt_url)}"><span class="jobs-tips-icon">{tip_icons["save"]}</span>'
                  f'<span class="jobs-tips-copy"><b>{tr("jobs.tips_save_title")}</b><small>{tr("jobs.tips_save_copy")}</small></span>{tips_chevron}</a>')
    county_leaders_html = ''.join(
        f'<a class="jobs-more-county" href="{e(all_jobs_url(county, 1, lang, preserve_lang))}">'
        f'{region_thumbnail_html(county)}'
        f'<span class="jobs-more-county-copy"><b>{e(county)}</b><small>{count} {tr("jobs.more_vacancies")}</small></span>'
        '<span class="jobs-more-county-arrow" aria-hidden="true">&rsaquo;</span></a>'
        for county, count in active_county_leaders()
    )
    all_counties_url = all_jobs_url("", 1, lang, preserve_lang)
    sidebar = (f'<aside class="vacancy-sidebar all-jobs-sidebar"><section class="jobs-side-hero"><div class="jobs-side-hero-top"><img class="jobs-side-hero-image" src="/static/jobbpeil-sidebar-hero.png" alt=""><div class="jobs-side-hero-copy"><span class="jobs-side-kicker">JOBBPEIL</span><h2>{tr("jobs.hero_title")}</h2><p>{tr("jobs.hero_copy")}</p></div></div>{help_html}</section>'
               f'<section class="jobs-side-more"><div class="jobs-more-main"><img class="jobs-more-image" src="/static/jobbpeil-norway-opportunities.png" alt=""><div class="jobs-more-copy"><span class="jobs-more-kicker">{tr("jobs.more_label")}</span><h2>{tr("jobs.more_title")}</h2><p>{tr("jobs.more_copy")}</p><div class="jobs-more-counties">{county_leaders_html}</div></div></div><div class="jobs-more-insight"><strong>{tr("jobs.more_insight_1")}<br>{tr("jobs.more_insight_2")}</strong><p>{tr("jobs.more_insight_copy")}</p></div><a class="jobs-more-all" href="{e(all_counties_url)}"><span><b>{tr("jobs.more_all_counties")}</b><small>{tr("jobs.more_all_counties_copy")}</small></span><i aria-hidden="true">&rarr;</i></a></section>'
               f'<section class="jobs-side-tips"><div class="jobs-tips-head"><span class="jobs-tips-bulb" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M8.5 15.5c-1.5-1.2-2.5-3-2.5-5a6 6 0 1 1 12 0c0 2-1 3.8-2.5 5-.7.6-1 1.4-1 2.2H9.5c0-.8-.3-1.6-1-2.2Z"/><path d="M9.5 20h5m-4-2.3h3"/></svg></span><div><h2>{tr("jobs.tips_title")}</h2><p>{tr("jobs.tips_copy")}</p></div></div>{tips_html}</section></aside>')
    return (form + f'<div class="vacancy-layout all-jobs-layout"><section class="vacancy-results"><div class="all-jobs-heading"><div><h2>{heading}</h2>'
            f'<p>{tr("jobs.newest_first")} <span aria-hidden="true">&middot;</span> {tr("jobs.count", count=total)}</p></div><div class="all-jobs-pages"><p>{tr("jobs.showing", start=start, end=end, total=total)}</p>{pagination}</div></div><div class="job-list">'
            + ''.join(cards) + '</div></section>' + sidebar + '</div>')


def all_jobs_detail(vacancy_uuid, county="", page=1, lang="no", preserve_lang=False,
                    profession="", municipality=""):
    selected_county = canonical_fylke(county) if county else ""
    return_url = all_jobs_url(selected_county or "", page, lang, preserve_lang,
                              profession=profession, municipality=municipality)
    return job_detail(t(lang, "jobs.title"), selected_county or "Norge", vacancy_uuid,
                      return_url=return_url, lang=lang, preserve_lang=preserve_lang)



CSS += """.scenario-choices{display:grid;grid-template-columns:1fr 1fr;gap:14px;max-width:900px;margin:0 0 20px}.scenario-choices a{display:flex;flex-direction:column;gap:6px;padding:20px;background:white;border:1px solid var(--line);border-radius:14px;text-decoration:none}.scenario-choices a:hover{border-color:#8aa48b;background:#f4f7ef}.scenario-choices span{font-size:14px;color:var(--muted)}.explore-intro{max-width:700px}.explore-form{max-width:700px;background:white;border:1px solid var(--line);border-radius:14px;padding:18px}.explore-form fieldset{border:0;padding:0;margin:0 0 14px;display:grid;grid-template-columns:1fr 1fr;gap:12px 16px}.explore-form legend{font-weight:600;margin-bottom:12px}.explore-form p{margin:0}.explore-form p:last-child{grid-column:1/-1}.direction-card{padding:18px 22px;max-width:900px;margin:12px 0}.direction-card h2{font-size:23px;margin:0 0 8px}.direction-card p{margin:8px 0;font-size:15px}.direction-card .button{padding:10px 16px}@media(max-width:700px){.scenario-choices,.explore-form fieldset{grid-template-columns:1fr}.explore-form{padding:16px}.scenario-choices a{padding:16px}}"""


DIRECTIONS = {
    'butikk': ('Butikk og service', r'butikkmedarbeider|butikkassistent|kundeservice|servicemedarbeider'),
    'assistanse': ('Personlig assistanse', r'personlig assistent|brukerstyrt personlig|\bbpa\b'),
    'renhold': ('Renhold', r'renholder|renholdsmedarbeider|renholdsoperat'),
    'lager': ('Lager og logistikk', r'lagermedarbeider|lagerarbeider|terminalarbeider|logistikkmedarbeider'),
    'hotell': ('Hotell og servering', r'servitør|hotellmedarbeider|resepsjonist|kjøkkenassistent|oppvask'),
}
QUESTIONS = {
    'language': ('Norsknivå', [('basic', 'Nybegynner / nesten ingen norsk'), ('a1', 'A1'), ('a2', 'A2'), ('b1', 'B1'), ('b2', 'B2 eller høyere')]),
    'licence': ('Førerkort', [('none', 'Ingen'), ('b', 'Klasse B'), ('other', 'Andre klasser – må avklares')]),
    'experience': ('Arbeidserfaring', [('none', 'Ingen arbeidserfaring'), ('some', 'Noe arbeidserfaring'), ('long', 'Mye arbeidserfaring')]),
    'hours': ('Når kan du jobbe?', [('day', 'Bare vanlig dagtid'), ('flex', 'Også kveld, natt og helg')]),
    'training': ('Vil du vurdere jobber med opplæring eller uten erfaringskrav?', [('yes', 'Ja'), ('no', 'Nei, ikke prioriter dette')]),
}


def requirements(ad):
    """Conservative sentence-level signals with retained evidence, not keyword eligibility."""
    parser = DescriptionHTML()
    parser.feed(ad.get('description') or '')
    text = re.sub(r'<[^>]+>', '\n', parser.result())
    from html import unescape
    # Some NAV descriptions place an entire bullet list in one <p>.
    # Separate inline list items before classifying: a preference/negation in
    # the experience item must not negate the Norwegian requirement next to it.
    sentences = [s.strip() for s in re.split(
        r'[\n.!?;]+|\s+[-–•]\s*(?=[A-ZÆØÅ])', unescape(text)) if s.strip()]
    result = {k: {'state': 'unknown', 'evidence': []} for k in ('language', 'licence', 'experience', 'hours', 'training', 'qualification')}
    subjects = {'language': r'norsk', 'licence': r'førerkort', 'experience': r'erfaring',
                'hours': r'kveld|natt|helg', 'training': r'opplæring',
                'qualification': r'fagbrev|autorisasjon|bachelor|sertifikat|truckførerbevis'}
    for sentence in sentences:
        s = sentence.casefold()
        for key, subject in subjects.items():
            if not re.search(subject, s):
                continue
            state = None
            if re.search(r'ikke (?:et )?(?:krav|nødvendig)|ingen krav|trenger ikke|uten erfaring', s):
                state = 'not_required'
            elif key == 'training' and re.search(r'(?:du (?:får|vil få)|vi (?:gir|tilbyr)|(?:full|grundig|nødvendig) opplæring|opplæring (?:gis|vil bli gitt))', s):
                state = 'not_required'
            elif re.search(r'ønskelig|en fordel|gjerne|ønsker at', s):
                state = 'preferred'
            elif re.search(r'\bmå\b|krever|krav|påkrevd|forutsetning|du (?:har|behersker)|gode norskkunnskaper|snakke (?:godt |flytende )?norsk', s):
                state = 'required'
            elif key == 'hours' and re.search(r'arbeidstid|vaktene|arbeidet innebærer|jobbe|arbeide', s):
                state = 'required'
            if state:
                result[key]['evidence'].append((state, sentence))
    for item in result.values():
        states = {s for s, _ in item['evidence']}
        # Conflicting statements require a human reading, not silent acceptance.
        item['state'] = ('unknown' if 'required' in states and 'not_required' in states else
                         next((s for s in ('required', 'not_required', 'preferred') if s in states), 'unknown'))
    # A general Norwegian-language phrase does not establish a CEFR level.
    language = result['language']
    levels = []
    for sentence in sentences:
        s = sentence.casefold()
        if re.search(r'norsk', s) and re.search(r'\b(?:krav|må|minst|minimum|kreves|påkrevd)\b', s):
            found = re.findall(r'\b(?:a1|a2|b1|b2|c1|c2)\b', s)
            if len(set(found)) == 1 and not re.search(r'ikke|ønskelig|fordel|eller', s):
                levels.extend(found)
                if ('required', sentence) not in language['evidence']:
                    language['evidence'].append(('required', sentence))
    language['level'] = levels[0] if len(set(levels)) == 1 else None
    language['good_norwegian_required'] = False
    natural = (r'\b(?:flytende|godt?|gode)\s+norsk(?:kunnskaper|ferdigheter)?\b'
               r'|\bgode?\s+(?:(?:skriftlige?|muntlige?)\s+(?:og\s+(?:skriftlige?|muntlige?)\s+)?)?'
               r'(?:ferdigheter|kunnskaper|språkferdigheter)\s+i\s+norsk\b'
               r'|\b(?:behersk\w*|kommuniser\w*)\s+(?:godt\s+)?norsk\s+'
               r'(?:godt\s+)?(?:både\s+)?(?:skriftlig\s+og\s+muntlig|muntlig\s+og\s+skriftlig)\b'
               r'|\bkommuniser\w*\s+godt\s+på\s+(?:både\s+)?norsk\b'
               r'|\bbehersk\w*\s+norsk\s+godt\b')
    for sentence in sentences:
        # Separate contrasts so "erfaring er ikke et krav, men ..." does not
        # negate an explicit language requirement in the following clause.
        for clause in re.split(r'\bmen\b', sentence, flags=re.I):
            s = clause.casefold()
            if re.search(natural, s) and not re.search(
                    r'\bikke\b|\bingen\b|\buten\b|ønskelig|fordel|gjerne|\beller\b', s):
                language['good_norwegian_required'] = True
                evidence = ('required', clause.strip())
                if evidence not in language['evidence']:
                    language['evidence'].append(evidence)
    if language['level'] and language['state'] != 'not_required':
        language['state'] = 'required'
    elif language['good_norwegian_required']:
        language['state'] = 'required'
    elif language['state'] == 'required':
        language['state'] = 'unknown'
    language['other_languages'] = []
    for sentence in sentences:
        s = sentence.casefold()
        if re.search(r'engelsk|skandinavisk', s) and re.search(r'snakke|kommuniser|behersk|flytende|språk|krav|forståelse', s):
            language['other_languages'].append(sentence)
            if ('unknown', sentence) not in language['evidence']:
                language['evidence'].append(('unknown', sentence))
    return result


@lru_cache(maxsize=2048)
def cached_requirements(job_uuid, payload_hash, description):
    """Return parsed requirements for one immutable ACTIVE job payload."""
    return requirements({'description': description})


def explore_requirements(ad):
    """Use the per-payload cache without sharing mutable compatibility state."""
    job_uuid = ad.get('uuid')
    payload_hash = ad.get('payloadHash')
    if isinstance(job_uuid, str) and job_uuid and isinstance(payload_hash, str) and payload_hash:
        # explore_compatibility adds fields to the result, so each caller needs a copy.
        return deepcopy(cached_requirements(job_uuid, payload_hash, ad.get('description') or ''))
    return requirements(ad)


def explore_compatibility(req, answers):
    """Evidence coverage across all five questions; absence is never confirmation."""
    levels = {'basic': 0, 'a1': 1, 'a2': 2, 'b1': 3, 'b2': 4, 'c1': 5, 'c2': 6}
    status = {key: 'Må avklares' for key in QUESTIONS}
    for key in status:
        if req[key]['state'] == 'not_required':
            status[key] = 'Bekreftet'
    lang = req['language']
    level = lang.get('level')
    if answers['language'] == 'basic' and lang['good_norwegian_required']:
        status['language'] = 'Konflikt'
    elif lang['state'] == 'required' and level:
        if levels[answers['language']] >= levels[level]:
            status['language'] = 'Bekreftet'
        elif answers['language'] != 'b2':
            status['language'] = 'Konflikt'
    if lang.get('other_languages') and status['language'] != 'Konflikt':
        status['language'] = 'Må avklares'
    if req['licence']['state'] == 'required':
        evidence = ' '.join(q for state, q in req['licence']['evidence'] if state == 'required').casefold()
        if answers['licence'] == 'none':
            status['licence'] = 'Konflikt'
        elif answers['licence'] == 'b':
            if re.search(r'klasse\s*(?:c|d|be|ce)', evidence):
                status['licence'] = 'Konflikt'
            elif re.search(r'klasse\s+b\b', evidence) and not re.search(r'eller|\bog\b', evidence):
                status['licence'] = 'Bekreftet'
    if req['experience']['state'] == 'required' and answers['experience'] == 'none':
        status['experience'] = 'Konflikt'
    if req['hours']['state'] == 'required':
        status['hours'] = 'Bekreftet' if answers['hours'] == 'flex' else 'Konflikt'
    # This is the combined training/no-experience criterion, not a second
    # requirement to provide training when experience is explicitly optional.
    status['training'] = ('Bekreftet' if answers['training'] == 'yes' and
        (req['training']['state'] == 'not_required' or req['experience']['state'] == 'not_required')
        else 'Må avklares')
    for key, value in status.items():
        req[key]['compatibility'] = value
    overall = ('Konflikt' if 'Konflikt' in status.values() else
               'Bekreftet' if all(v == 'Bekreftet' or (
                   req[key]['state'] == 'unknown' and not req[key]['evidence'])
                   for key, v in status.items())
               and req['qualification']['state'] not in ('required', 'preferred') else 'Må avklares')
    return overall


def explore_candidates(answers, counts=None):
    groups = {key: [] for key in DIRECTIONS}
    if counts is not None:
        counts.update({key: {'analyzed': 0, 'Bekreftet': 0, 'Må avklares': 0, 'Konflikt': 0} for key in DIRECTIONS})
    for uid, ad in cached_active_jobs(active_jobs_source_version()).items():
        title = ' '.join(str(ad.get(k) or '') for k in ('title', 'jobtitle')).casefold()
        # Names select a display direction only; eligibility is checked per advertisement below.
        direction = next((key for key, (_, pattern) in DIRECTIONS.items() if re.search(pattern, title)), None)
        if not direction:
            continue
        req = explore_requirements(ad)
        status = explore_compatibility(req, answers)
        if counts is not None:
            counts[direction]['analyzed'] += 1
            counts[direction][status] += 1
        if status == 'Konflikt':
            continue
        levels = {'basic': 0, 'a1': 1, 'a2': 2, 'b1': 3, 'b2': 4, 'c1': 5, 'c2': 6}
        positive = req['training']['state'] == 'not_required' or req['experience']['state'] == 'not_required'
        unknown = sum(item['state'] == 'unknown' for item in req.values())
        groups[direction].append((uid, ad, req, positive, unknown))
    def confirmation_order(item):
        req = item[2]
        language = req['language']
        level = language.get('level')
        language_confirmed = language['state'] == 'not_required' or (
            language['state'] == 'required' and level is not None
            and levels[answers['language']] >= levels[level])
        # General experience and "other" licences do not confirm a specific
        # occupational requirement. Unknown/preferred is never confirmation.
        confirmed = sum(req[key]['state'] == 'not_required'
                        for key in ('licence', 'experience', 'hours'))
        if answers['hours'] == 'flex' and req['hours']['state'] == 'required':
            confirmed += 1
        # Lexicographic evidence ordering, not a suitability score. Language
        # confirmation precedes training, which says nothing about language.
        return (explore_compatibility(req, answers) != 'Bekreftet', not language_confirmed, -confirmed,
                not (answers['training'] == 'yes' and item[3]), item[4], item[0])

    for items in groups.values():
        items.sort(key=confirmation_order)
    return groups


@lru_cache(maxsize=4)
def cached_explore_candidates(source_version, answer_items):
    counts = {}
    groups = explore_candidates(dict(answer_items), counts)
    return groups, counts


CSS += """
main:is(.home,.results-page,.vacancy-list-page,.explore-entry) > header{background:#f3faf5f2}
"""


EXPLORE_FORM_STYLE = """
.explore-entry{font-family:"Segoe UI",Arial,sans-serif;max-width:1600px;padding:12px 20px 24px;background:radial-gradient(ellipse at 100% 30%,#e2f0f6 0,transparent 60%)}
.explore-entry header{padding:9px 24px;background:#fffffff2;box-shadow:0 5px 24px #183e3808;min-height:62px;border-radius:20px}.explore-entry .brand{gap:12px}.explore-entry .home-logo{width:45px;height:48px;flex:none;color:#148975}.explore-entry .brand-name{display:flex;flex-direction:column;font-size:28px;font-weight:750;letter-spacing:-.05em;line-height:1.15}.explore-entry .brand-name small{font-size:11px;font-weight:500;letter-spacing:.12em;margin-top:4px}
.explore-entry .explore-heading{padding:30px 28px 0}.explore-entry .eyebrow{color:#227969;font-size:13px;letter-spacing:.18em;font-weight:650;margin:0 0 10px}.explore-entry h1{font-size:clamp(32px,4vw,52px);font-weight:700;letter-spacing:-.045em;line-height:1.12;margin:0 0 14px;color:#142e36}.explore-entry .explore-intro{font-size:17px;line-height:1.5;max-width:770px;margin:0 0 22px;color:#536974}
.explore-entry .explore-workspace{padding:0 28px;display:grid;grid-template-columns:minmax(0,66fr) minmax(0,32fr);gap:26px}.explore-entry .explore-visual{margin-right:calc(-48px - max(0px, (100vw - 1600px) / 2));background-image:url('/static/jobbpeil-explore-bg.png');background-size:cover;background-position:calc(100% - 6px) bottom;background-repeat:no-repeat;min-width:0;mask-image:linear-gradient(90deg,transparent,#000 18%),linear-gradient(180deg,transparent,#000 12%,#000 90%,transparent);mask-composite:intersect;pointer-events:none}
.explore-entry .explore-form{max-width:none;width:100%;margin:0;padding:24px 28px;background:#ffffffeb;border:1px solid #ffffff;border-radius:24px;box-shadow:0 12px 35px #23483b0d}.explore-entry .explore-form fieldset{gap:22px 26px;margin:0 0 20px}.explore-entry .explore-form legend{font-size:22px;letter-spacing:-.025em;font-weight:650;margin-bottom:20px}.explore-entry .explore-form p{display:grid;grid-template-columns:48px minmax(0,1fr);gap:6px 14px;align-content:start}.explore-entry .question-icon{grid-column:1;grid-row:1/3;width:48px;height:48px;align-self:center;display:grid;place-items:center;border-radius:50%;color:#176f63;background:linear-gradient(135deg,#e5f5f1,#e3f1f5)}.explore-entry .question-icon svg{width:24px;height:24px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.explore-entry .explore-form label{grid-column:2;font-size:15px;font-weight:600;line-height:1.3;margin:0}.explore-entry .explore-form select{grid-column:2;padding:11px 12px;background:#fff;color:#183b3c;border-color:#dbe5e4;border-radius:11px;min-height:44px;font-size:15px}.explore-entry .explore-form select:focus-visible{outline:2px solid #318d7b;outline-offset:2px}.explore-entry .explore-form button{width:100%;padding:14px;font-family:inherit;font-size:17px;font-weight:600;border-radius:14px;background:linear-gradient(110deg,#173f40,#1b655c)}.explore-entry .explore-form button:after{content:' →';margin-left:16px}
.explore-entry>.disclosure{margin:18px 28px 0;padding:10px 0}.explore-entry .entry-facts{display:grid;grid-template-columns:repeat(3,1fr);margin:0 28px;padding:16px 0;gap:26px;border-top:1px solid #dfe8e5}.explore-entry .entry-facts strong{display:block;font-size:14px;color:#214d43}.explore-entry .entry-facts span{font-size:13px;color:#596e73}
@media(min-width:701px){
.explore-entry{padding-top:10px;padding-bottom:12px}.explore-entry header{min-height:54px;padding:6px 24px}.explore-entry .home-logo{width:38px;height:40px}.explore-entry .brand-name{font-size:25px}
.explore-entry .explore-heading{padding-top:18px}.explore-entry .eyebrow{margin-bottom:7px}.explore-entry h1{font-size:clamp(30px,3.3vw,43px);margin-bottom:10px}.explore-entry .explore-intro{margin-bottom:16px;line-height:1.4}
.explore-entry .explore-form{padding:18px 24px}.explore-entry .explore-form fieldset{gap:14px 24px;margin-bottom:14px}.explore-entry .explore-form legend{margin-bottom:14px}.explore-entry .explore-form p{grid-template-columns:40px minmax(0,1fr);gap:5px 12px}.explore-entry .question-icon{width:40px;height:40px}.explore-entry .question-icon svg{width:22px;height:22px}.explore-entry .explore-form select{padding:8px 12px;min-height:38px}.explore-entry .explore-form button{padding:10px}
.explore-entry>.disclosure{margin-top:10px;padding:7px 0}.explore-entry .entry-facts{padding:10px 0}
}
@media(max-width:1000px){.explore-entry .explore-workspace{grid-template-columns:1fr}.explore-entry .explore-visual{display:none}}
@media(max-width:700px){.explore-entry{padding:12px}.explore-entry header{padding:10px 12px}.explore-entry .home-logo{width:35px;height:39px}.explore-entry .brand-name{font-size:23px}.explore-entry .explore-heading{padding:24px 4px 0}.explore-entry .explore-workspace{padding:0}.explore-entry .explore-form{padding:20px 16px}.explore-entry .explore-form fieldset{grid-template-columns:1fr;gap:18px}.explore-entry .explore-form legend{font-size:20px}.explore-entry>.disclosure,.explore-entry .entry-facts{margin-left:4px;margin-right:4px}.explore-entry .entry-facts{grid-template-columns:1fr;gap:12px}}
"""


EXPLORE_FORM_STYLE += """
.explore-entry .explore-form fieldset p:nth-of-type(1) .question-icon{background:#e5f5ee;color:#287963}
.explore-entry .explore-form fieldset p:nth-of-type(2) .question-icon{background:#e8f2fa;color:#39728c}
.explore-entry .explore-form fieldset p:nth-of-type(3) .question-icon{background:#f0edfa;color:#70648e}
.explore-entry .explore-form fieldset p:nth-of-type(4) .question-icon{background:#f8f1e3;color:#846f45}
.explore-entry .explore-form fieldset p:nth-of-type(5) .question-icon{background:#faeeea;color:#956e65}
"""


EXPLORE_RESULTS_STYLE = """
.explore-results{padding:12px 24px;font-family:"Segoe UI",Arial,sans-serif;max-width:1500px}.explore-results>h1{font-size:36px;letter-spacing:-.035em;line-height:1.15;margin:18px 0 8px}.explore-results>.explore-intro{max-width:1000px;font-size:14px;line-height:1.45;margin:0 0 8px}.explore-results>p{margin:8px 0 12px;font-size:14px}.direction-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;align-items:start}.explore-results .direction-card{display:flex;flex-direction:column;max-width:none;margin:0;padding:18px;border-radius:20px;border:1px solid #dfe9e5;background:#ffffffed;box-shadow:0 5px 20px #244f4210;min-height:248px}.explore-results .direction-card h2{font-size:22px;line-height:1.2;letter-spacing:-.025em;margin:0 0 8px}.explore-results .direction-card p{font-size:13px;line-height:1.4;margin:5px 0}.explore-results .direction-counts{display:flex;flex-wrap:wrap;gap:6px}.explore-results .direction-counts span{border-radius:18px;padding:4px 9px;font-size:12px;background:#e8f4ec;color:#215b46}.explore-results .direction-counts span:last-child{background:#fff3d9;color:#66532c}.explore-results .reason-details{margin:9px 0 5px;font-size:13px;line-height:1.4}.explore-results .reason-details summary{cursor:pointer;font-weight:600}.explore-results .reason-preview{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;font-weight:400;margin-top:4px}.explore-results .reason-details[open] .reason-preview{display:none}.explore-results .direction-card .button{align-self:flex-start;margin-top:auto;padding:9px 13px;font-size:13px}.explore-results .direction-card .direction-regions{margin:6px 0 12px}.explore-results>.disclosure{margin:10px 0 0;padding:5px 0}
@media(max-width:1050px){.direction-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:700px){.direction-grid{grid-template-columns:1fr}.explore-results{padding:12px}.explore-results>h1{font-size:30px}.explore-results .direction-card{min-height:0}.explore-results .direction-card .button{margin-top:10px}}
"""


EXPLORE_RESULTS_STYLE += """
.explore-results>.results-eyebrow{font-size:12px;letter-spacing:.12em;color:#37776a;margin:12px 0 4px}.explore-results>h1{margin:0 0 6px;font-size:43px;font-weight:700;letter-spacing:-.045em;line-height:1.12}.explore-results>.explore-intro{font-size:17px;line-height:1.4;margin-bottom:5px}.explore-results>p{margin-top:5px;margin-bottom:8px}.explore-results .direction-grid{gap:12px;counter-reset:direction;align-items:stretch}.explore-results .direction-card{--tint:#cceee0;--ink:#17674e;position:relative;display:grid;grid-template-columns:54px minmax(0,1fr);column-gap:12px;row-gap:4px;align-content:start;min-height:0;padding:15px 17px;background:linear-gradient(135deg,#fff,#ffffffed);counter-increment:direction}.explore-results .direction-card:after{content:counter(direction,decimal-leading-zero);position:absolute;top:16px;right:14px;font-size:11px;color:#7c9695}.explore-results .direction-card:nth-child(2){--tint:#cce4f8;--ink:#205b8a}.explore-results .direction-card:nth-child(3){--tint:#fbdcde;--ink:#a24856}.explore-results .direction-card:nth-child(4){--tint:#e1dbfa;--ink:#63549b}.explore-results .direction-card:nth-child(5){--tint:#ffedbd;--ink:#8b691a}.explore-results .direction-card:nth-child(6){--tint:#d7eedb;--ink:#3d7852}.explore-results .direction-icon{width:54px;height:54px;border-radius:50%;display:grid;place-items:center;background:var(--tint);color:var(--ink);grid-column:1;grid-row:1/4}.explore-results .direction-icon svg{width:26px;height:26px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.explore-results .direction-card h2{grid-column:2;font-size:22px;margin:0;padding-right:18px;line-height:1.2;font-weight:700;letter-spacing:-.025em}.explore-results .direction-card>p:first-of-type{grid-column:2;margin:0;font-size:12px;font-weight:400;line-height:1.4}.explore-results .direction-counts{grid-column:2;gap:5px}.explore-results .direction-counts span{font-size:12px;padding:3px 7px;font-weight:650;letter-spacing:-.01em}.explore-results .reason-details{grid-column:1/-1;margin:5px 0 0;font-size:12px}.explore-results .reason-preview{margin-top:3px;line-height:1.4}.explore-results .direction-card .direction-regions{grid-column:1/-1;font-size:13px;margin:4px 0 7px;line-height:1.4;font-weight:300}.explore-results .direction-card .button{grid-column:1/-1;justify-self:start;background:var(--tint);color:#173e3b;border:1px solid transparent;font-size:14px;font-weight:600;letter-spacing:-.01em;padding:8px 12px;margin:0}.explore-results .direction-card .button:after{content:' →';margin-left:8px}.explore-results .direction-card .button:hover{filter:brightness(.96);border-color:var(--ink)}.explore-results .direction-facts{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;border-radius:14px;background:#e8f0eb;padding:10px 16px;margin-top:8px}.explore-results .direction-facts>div{display:grid;grid-template-columns:24px 1fr;gap:0 10px}.explore-results .direction-facts svg{width:23px;height:23px;grid-row:1/3;align-self:center;fill:none;stroke:#37776a;stroke-width:1.7}.explore-results .direction-facts strong{font-size:12px}.explore-results .direction-facts span{font-size:12px;color:#526e69}.explore-results>.disclosure{margin-top:5px;padding:3px 0}
@media(max-width:700px){.explore-results .direction-facts{grid-template-columns:1fr;gap:10px}.explore-results .direction-card{padding:18px}.explore-results>h1{font-size:30px}}
"""


EXPLORE_RESULTS_STYLE += """
.explore-results .direction-grid:before{content:attr(data-caption);grid-column:3;grid-row:1;display:grid;place-items:center;border-radius:24px;background:radial-gradient(ellipse,#dceee699,transparent 70%);font-family:"Segoe Print","Comic Sans MS",cursive;font-size:27px;color:#37776a;transform:rotate(-5deg)}.explore-results .direction-card:nth-child(3){grid-column:1;grid-row:2}.explore-results .direction-card:nth-child(4){grid-column:2;grid-row:2}.explore-results .direction-card:nth-child(5){grid-column:3;grid-row:2}
.explore-results .direction-card{padding:11px 15px;row-gap:2px}.explore-results .direction-card .direction-regions{margin:3px 0 5px;line-height:1.3}.explore-results .direction-regions:before{content:'⌖';color:#37776a;margin-right:5px}.explore-results .short-reasons{grid-column:1/-1;list-style:none;padding:0;margin:6px 0 2px;font-size:12px;line-height:1.35}.explore-results .short-reasons li{position:relative;padding-left:17px;margin:2px 0}.explore-results .short-reasons li:before{content:'✓';position:absolute;left:0;color:#278764}.explore-results .reason-details{margin:2px 0;font-size:13px;line-height:1.4}.explore-results .direction-card .button{padding:7px 12px}.explore-results .direction-card h2{line-height:1.15}.explore-results .direction-facts{padding:8px 16px}
@media(max-width:1050px){.explore-results .direction-grid:before{display:none}.explore-results .direction-card:nth-child(n){grid-column:auto;grid-row:auto}}
"""


EXPLORE_RESULTS_STYLE += """
.explore-results .direction-card .button{background:#174c46;color:#fff;border-color:#174c46;box-shadow:0 3px 10px #174c4618}
.explore-results .direction-card .button:hover{background:#21645a;border-color:#21645a;filter:none}
.explore-results .direction-grid:before{background:radial-gradient(ellipse at 50% 55%,#e1f2eabb 0%,#eaf4f4a0 40%,transparent 72%);color:#286d60}
"""



# Approved JobbPeil visual package — presentation only.
APPROVED_UI_STYLE = r"""
.home header,.results-page header,.vacancy-list-page header,.explore-entry header{background:#eef8f2f2;border-color:#dbe9e0}
.home .fact-strip{background:#e6f4ebf2;border-color:#d3e8da}
.results-page{background:#f7f8f4}.results-page:before{top:78px;left:18px;right:18px;height:190px;border-radius:24px;background-image:linear-gradient(90deg,#f7fbf8f2 0%,#f3faf6d8 43%,#e7f3ef99 72%,#edf5f4b8 100%),url('/static/jobbpeil-bg.png');background-size:cover;background-position:center 45%;box-shadow:inset 0 0 0 1px #ffffffa8;z-index:0}.results-page>*{position:relative;z-index:1}.results-page .top-five{margin-top:10px}
.explore-entry .explore-form fieldset p:nth-of-type(1) .question-icon{background:#cfeee2;color:#176b58}.explore-entry .explore-form fieldset p:nth-of-type(2) .question-icon{background:#d8ebf8;color:#2d6f91}.explore-entry .explore-form fieldset p:nth-of-type(3) .question-icon{background:#e5def6;color:#68548f}.explore-entry .explore-form fieldset p:nth-of-type(4) .question-icon{background:#f5e8c9;color:#80652c}.explore-entry .explore-form fieldset p:nth-of-type(5) .question-icon{background:#f5ddd7;color:#8d554d}
.explore-results{position:relative;isolation:isolate;overflow:hidden;background:#f7f8f4}.explore-results:before{content:"";position:absolute;z-index:-1;top:76px;left:0;right:0;bottom:0;background-image:linear-gradient(90deg,#f7f8f4 0%,#f7f8f4f4 34%,#f4f8f6bf 54%,#eef7f3a0 72%,#eef7f38f 100%),url('/static/jobbpeil-bg.png');background-size:cover;background-position:center 48%;background-repeat:no-repeat}.explore-results .direction-grid:before{content:attr(data-caption);position:relative;min-height:190px;border:0;box-shadow:none;background:none;border-radius:0;color:#246b5d;text-shadow:0 1px #fff;font-size:26px;place-items:center}.explore-results .direction-card .button{background:#174c46;color:#fff;border-color:#174c46}
.explore-vacancies{position:relative;font-family:"Segoe UI",Arial,sans-serif;max-width:1500px;padding:12px 24px 30px;background:#f7f8f4}.explore-vacancies:before{content:"";position:absolute;z-index:0;top:78px;left:18px;right:18px;height:210px;border-radius:24px;background-image:linear-gradient(90deg,#f7fbf8f5 0%,#f3faf6d5 48%,#e8f3ef86 78%,#eef6f4aa),url('/static/jobbpeil-bg.png');background-size:cover;background-position:center 48%}.explore-vacancies>*{position:relative;z-index:1}.explore-vacancies header{padding:7px 24px;min-height:58px;background:#eef8f2f2;border-radius:20px;box-shadow:0 5px 24px #183e3808}.explore-vacancies>h1{font-size:34px;margin:18px 0 5px}.explore-vacancies>.explore-intro{max-width:820px;font-size:14px}.explore-vacancies>p{margin:7px 0}.explore-vacancies>h2{font-size:30px;letter-spacing:-.035em;margin:12px 0 4px}.explore-vacancies .job-list{width:min(100%,980px);display:flex;flex-direction:column;gap:9px;border:0;background:transparent;overflow:visible;margin-top:12px}.explore-vacancies .job-row{display:flex;align-items:flex-start;justify-content:space-between;gap:22px;min-height:0;padding:14px 18px;border:1px solid #dce9e3;border-radius:17px;background:#fffffff3;box-shadow:0 4px 16px #244f4208}.explore-vacancies .job-row:hover{background:#fbfefc;border-color:#b9d9cd}.explore-vacancies .job-row h3{font-size:18px;line-height:1.25;margin:7px 0 3px}.explore-vacancies .job-row p{font-size:13px;color:#587571;margin:0 0 5px}.explore-vacancies .job-row details{margin:7px 0 0;font-size:12px;max-width:720px}.explore-vacancies .job-row details summary{font-weight:600;color:#315f57}.explore-vacancies .job-row blockquote{margin:6px 0;padding-left:12px;border-left:2px solid #cfe3db;color:#536d68}.explore-vacancies .job-link{align-self:center;flex:none;background:#174c46;color:#fff;padding:10px 14px;border-radius:11px;text-decoration:none}.explore-vacancies .job-link:hover{background:#21645a}.explore-vacancies .badge{background:#e3f2e8;color:#245d49;font-weight:600}.explore-vacancies:after{content:attr(data-caption);position:absolute;z-index:1;right:7%;top:190px;font-family:"Segoe Print","Comic Sans MS",cursive;font-size:24px;color:#2b7063;transform:rotate(-5deg)}
.job-detail{max-width:1180px;display:grid;grid-template-columns:minmax(0,1fr) 310px;column-gap:30px;align-items:start}.job-detail>h1,.job-detail>.intro,.job-detail>.job-facts,.job-detail>p,.job-detail>.job-description{grid-column:1}.job-detail>.note{grid-column:2;grid-row:1 / span 7;margin:0;position:sticky;top:18px;background:#edf7f1;border:1px solid #d8e9df;border-radius:18px;padding:20px}.job-detail>.note:before{content:'Kort om stillingen';display:block;font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:#397164;font-weight:700;margin-bottom:10px}.job-detail .job-facts{background:#f2f7f3}.job-detail .job-description{max-width:76ch}
@media(max-width:900px){.job-detail{grid-template-columns:1fr}.job-detail>h1,.job-detail>.intro,.job-detail>.job-facts,.job-detail>p,.job-detail>.job-description,.job-detail>.note{grid-column:1}.job-detail>.note{grid-row:auto;position:static;margin-top:12px}.explore-vacancies:after{display:none}}@media(max-width:700px){.results-page:before,.explore-vacancies:before{left:8px;right:8px;height:230px}.explore-vacancies{padding:12px}.explore-vacancies .job-row{flex-direction:column}.explore-vacancies .job-link{align-self:flex-end}}
"""

APPROVED_UI_STYLE += r"""
/* Keep generated autocomplete buttons independent from page CTA button rules. */
.results-page .result-search,.vacancy-list-page .all-jobs-filter{position:relative;overflow:visible}
.results-page .result-search:focus-within,.vacancy-list-page .all-jobs-filter:focus-within{z-index:30}
.results-page .search,.vacancy-list-page .all-jobs-query{position:relative;overflow:visible}
.results-page .autocomplete-list,.vacancy-list-page .autocomplete-list{z-index:100}
.results-page .autocomplete-option,.vacancy-list-page .autocomplete-option{display:block;width:100%;min-height:38px;padding:8px 13px;border:0;border-bottom:1px solid #edf1ed;border-radius:0;background:#fff;color:var(--ink);box-shadow:none;text-align:left;font:14px/1.35 inherit}
.results-page .autocomplete-option:last-child,.vacancy-list-page .autocomplete-option:last-child{border-bottom:0}
.results-page .autocomplete-option:hover,.results-page .autocomplete-option.selected,.vacancy-list-page .autocomplete-option:hover,.vacancy-list-page .autocomplete-option.selected{background:#edf6f1;color:#174f45;box-shadow:none}
@media(max-width:700px){.results-page .autocomplete-option,.vacancy-list-page .autocomplete-option{min-height:44px;padding:10px 13px}.results-page .autocomplete-list,.vacancy-list-page .autocomplete-list{left:-1px;right:-1px}}
.vakt-page .vakt-profession-search{height:52px;overflow:visible;border:1px solid #d7e3e2;border-radius:10px;background:#fff}.vakt-page .vakt-profession-search:focus-within{z-index:30;border-color:#6c9d89;box-shadow:0 0 0 3px #6c9d8930}.vakt-page .vakt-profession-search svg{top:50%;transform:translateY(-50%)}.vakt-page .vakt-profession-search input,.vakt-page .vakt-profession-search input:focus{display:block;height:50px;border:0!important;border-radius:inherit;background:transparent;box-shadow:none!important}.vakt-page .vakt-profession-search .autocomplete-list{z-index:100}.vakt-page .vakt-form-card .autocomplete-option{display:block;width:100%;min-height:38px;margin:0;padding:8px 13px;border:0;border-bottom:1px solid #edf1ed;border-radius:0;background:#fff;color:var(--ink);box-shadow:none;text-align:left;font:14px/1.35 inherit}.vakt-page .vakt-form-card .autocomplete-option:last-child{border-bottom:0}.vakt-page .vakt-form-card .autocomplete-option:hover,.vakt-page .vakt-form-card .autocomplete-option.selected{background:#edf6f1;color:#174f45;box-shadow:none}@media(max-width:700px){.vakt-page .vakt-form-card .autocomplete-option{min-height:44px;padding:10px 13px}.vakt-page .vakt-profession-search .autocomplete-list{left:-1px;right:-1px}}
"""


EXPLORE_PAGE_SIZE = 20


def explore_published_dates(job_uuids):
    """Published dates for the current page's active ads; presentation only."""
    job_uuids = tuple(dict.fromkeys(job_uuids))
    if not job_uuids:
        return {}
    placeholders = ','.join('?' for _ in job_uuids)
    db = sqlite3.connect(DATABASE.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        db.execute("PRAGMA query_only=ON")
        return dict(db.execute("SELECT j.uuid,v.published FROM jobs j JOIN job_versions v "
                               "ON v.id=j.current_version_id AND v.job_uuid=j.uuid "
                               "WHERE j.status='ACTIVE' AND v.status='ACTIVE' "
                               f"AND j.uuid IN ({placeholders})", job_uuids))
    finally:
        db.close()


def format_published_short(value):
    if not value:
        return ''
    try:
        dt = ((EPOCH + timedelta(microseconds=value)).astimezone()
              if isinstance(value, (int, float)) and not isinstance(value, bool)
              else datetime.fromisoformat(str(value).replace('Z', '+00:00')))
        months = ('jan.', 'feb.', 'mars', 'apr.', 'mai', 'juni', 'juli', 'aug.', 'sep.', 'okt.', 'nov.', 'des.')
        return f'{dt.day}. {months[dt.month-1]} {dt.year}'
    except (ValueError, TypeError, AttributeError, OverflowError):
        return str(value)[:10]


def ad_summary(ad, limit=175):
    from html import unescape
    raw = ad.get('description') or ''
    text = unescape(re.sub(r'<[^>]+>', ' ', raw))
    text = re.sub(r'\\s+', ' ', text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(' ', 1)[0]
    return cut.rstrip(' ,;:.-') + ' …'


def direction_tags(label, req):
    tags = [label]
    signals = (
        ('training', 'Opplæring'),
        ('experience', 'Uten erfaringskrav'),
        ('hours', 'Kveld / helg'),
        ('licence', 'Førerkort'),
        ('language', 'Norsk'),
        ('qualification', 'Fagkrav'),
    )
    for key, tag in signals:
        item = req.get(key, {})
        state = item.get('state')
        if key in ('training', 'experience'):
            include = state == 'not_required' or bool(item.get('evidence'))
        else:
            include = state in ('required', 'preferred')
        if include and tag not in tags:
            tags.append(tag)
        if len(tags) >= 4:
            break
    return tags


# Approved direction vacancy list — scoped to this page only.
DIRECTION_VACANCY_STYLE = r"""
.explore-vacancies{position:relative;isolation:isolate;overflow:hidden;max-width:1500px;padding:12px 24px 34px;background:#eef5f0;font-family:"Segoe UI",Arial,sans-serif}
/* One continuous, subdued JobbPeil landscape: readable on the left, greener/forest-like on the free right side. */
.explore-vacancies:before{content:"";position:absolute;z-index:-1;inset:76px 0 0 0;background-image:linear-gradient(90deg,rgba(247,250,247,.96) 0%,rgba(247,250,247,.91) 42%,rgba(238,246,241,.84) 70%,rgba(220,236,225,.76) 100%),linear-gradient(180deg,rgba(255,255,255,.05) 0%,rgba(238,247,241,.10) 52%,rgba(207,228,214,.20) 100%),url('/static/jobbpeil-bg.png');background-size:cover,cover,cover;background-position:center top,center top,center top;background-repeat:no-repeat,no-repeat,no-repeat;background-attachment:scroll,scroll,fixed}
.explore-vacancies header{padding:7px 24px;min-height:58px;background:#eef8f2f2;border-radius:20px;box-shadow:0 5px 24px #183e3808}
.explore-vacancies header .brand{gap:12px}.explore-vacancies header .home-logo{width:40px;height:44px;flex:none;color:#148975}.explore-vacancies header .brand-name{display:flex;flex-direction:column;font-size:27px;font-weight:750;letter-spacing:-.05em;line-height:1.15}.explore-vacancies header .brand-name small{font-size:11px;font-weight:500;letter-spacing:.12em;margin-top:4px}
.explore-vacancies .back-link{margin:17px 0 5px}.explore-vacancies .back-link a{font-weight:600}
.explore-vacancies .vacancy-direction-title{font-family:inherit;font-size:43px;line-height:1.12;letter-spacing:-.045em;margin:6px 0 6px;max-width:840px;font-weight:700}
.explore-vacancies>.explore-intro{max-width:820px;font-size:17px;line-height:1.4;margin:0 0 4px;color:#355b56;font-weight:400}
.explore-vacancies .result-count{font-size:13px;color:#637a76;margin:0 0 12px;font-weight:450}
.explore-vacancy-layout{display:grid;grid-template-columns:minmax(0,1fr) 285px;gap:24px;align-items:start}.explore-vacancy-results{min-width:0}.explore-vacancy-results .job-list{width:100%}.place-result-note{margin:0 0 10px;padding:8px 11px;border:1px solid #d8e9e2;border-radius:10px;background:#f7fcf8;color:#245d52;font-size:14px;font-weight:650;line-height:1.35}.explore-place-filter{position:static}.explore-place-filter>section{padding:16px;background:#f3faf6e8;border:1px solid #d8e9e2;border-radius:17px;box-shadow:0 5px 18px #244f4208}.explore-place-filter h2{display:flex;align-items:center;gap:8px;margin:0 0 3px;font-size:20px;line-height:1.2;letter-spacing:-.025em}.explore-place-filter h2:before{content:"";width:14px;height:14px;border:2px solid #257a68;border-radius:50% 50% 50% 0;transform:rotate(-45deg);box-sizing:border-box}.explore-place-filter>section>p{margin:0 0 10px;color:#55736d;font-size:12.5px;line-height:1.4}.explore-place-filter nav{display:grid;gap:3px}.explore-place-filter nav>a,.explore-place-filter .place-more>a{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:8px 9px;border-radius:9px;color:#204f47;font-size:14px;font-weight:600;text-decoration:none}.explore-place-filter nav>a:hover,.explore-place-filter .place-more>a:hover{background:#e4f4eb}.explore-place-filter nav>a.active,.explore-place-filter .place-more>a.active{background:#d9f0e5;color:#155f50}.explore-place-filter nav strong{font-size:13px;font-variant-numeric:tabular-nums}.place-more{display:grid;gap:3px;margin:4px 0 0}.place-more summary{padding:6px 9px;color:#247464;font-size:13px;font-weight:650;text-decoration:underline;text-underline-offset:3px}.place-more .less-label{display:none}.place-more[open] .more-label{display:none}.place-more[open] .less-label{display:inline}
.explore-vacancies .job-list{width:min(100%,1040px);display:flex;flex-direction:column;gap:10px;border:0;background:transparent;overflow:visible;margin-top:10px}
.explore-vacancies .job-row{display:grid;grid-template-columns:minmax(250px,.9fr) minmax(360px,1.25fr) 188px;align-items:center;gap:22px;min-height:118px;padding:14px 18px;border:1px solid #dce9e3;border-radius:17px;background:#fffffff4;box-shadow:0 4px 16px #244f4208}
.explore-vacancies .job-row:hover{background:#fbfefc;border-color:#b9d9cd}
.explore-vacancies .job-main{min-width:0;max-width:100%;overflow-wrap:anywhere}.explore-vacancies .job-main h3{max-width:100%;font-family:inherit;font-size:20px;line-height:1.2;letter-spacing:-.025em;margin:4px 0 3px;font-weight:650}.explore-vacancies .job-main p{font-size:13px;line-height:1.4;color:#587571;margin:0 0 5px;font-weight:400}
.explore-vacancies .job-meta{display:flex;gap:14px;flex-wrap:wrap;color:#4c6d68;font-size:12px;line-height:1.4;margin-top:8px;font-weight:400}.explore-vacancies .job-meta span{display:inline-flex;align-items:center;gap:5px}.explore-vacancies .job-meta svg{width:17px;height:17px;fill:none;stroke:#3b766c;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.explore-vacancies .job-middle{min-width:0;max-width:100%;overflow-wrap:anywhere}.explore-vacancies .job-state-line{display:flex;align-items:center;gap:14px;margin-bottom:5px}.explore-vacancies .badge{background:#e3f2e8;color:#245d49;font-weight:600;letter-spacing:-.005em}.explore-vacancies .badge.needs-check{background:#fff0c9;color:#72581c}
.explore-vacancies .why{margin:0;font-size:13px;line-height:1.4}.explore-vacancies .why summary{font-family:inherit;font-weight:650;color:#315f57;letter-spacing:-.005em}.explore-vacancies .why p,.explore-vacancies .why blockquote{font-size:12px}
.explore-vacancies .summary-snippet{font-size:13px;line-height:1.4;color:#41655f;margin:4px 0 7px;font-weight:400;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.explore-vacancies .job-tags{display:flex;flex-wrap:wrap;gap:6px}.explore-vacancies .job-tags span{display:inline-block;padding:4px 10px;border-radius:999px;background:#deeffb;color:#26688e;font-size:12px;line-height:1.2;font-weight:600}
.explore-vacancies .job-link{justify-self:end;align-self:center;background:#0f6a5d;color:white;padding:13px 18px;border-radius:11px;text-decoration:none;font-family:inherit;font-size:15px;font-weight:600;letter-spacing:-.01em;white-space:nowrap;box-shadow:0 4px 12px #0f6a5d14}.explore-vacancies .job-link:hover{background:#155e54}
.explore-vacancies:after{content:attr(data-caption);position:absolute;z-index:0;right:6%;top:122px;font-family:"Segoe Print","Comic Sans MS",cursive;font-size:27px;color:#197566;transform:rotate(-5deg);text-shadow:0 1px #fff}
@media(max-width:1180px){.explore-vacancy-layout{grid-template-columns:1fr}.explore-place-filter{max-width:420px}}@media(max-width:1050px){.explore-vacancies .job-list{width:100%}.explore-vacancies .job-row{grid-template-columns:minmax(230px,.9fr) minmax(300px,1.15fr) 170px}.explore-vacancies:after{display:none}}
@media(max-width:780px){.explore-vacancies{padding:12px}.explore-vacancies .vacancy-direction-title{font-size:31px}.explore-vacancies .job-row{grid-template-columns:1fr;gap:10px;padding:16px}.explore-vacancies .job-link{justify-self:end}.explore-vacancies:before{inset:74px 0 0 0}}
"""

DIRECTION_VACANCY_STYLE += """
.explore-vacancies .explore-pagination{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin:18px 0 0;font-size:14px}
.explore-pagination a,.explore-pagination .page-disabled{padding:8px 12px;border:1px solid var(--line);border-radius:10px;background:#fff;color:var(--ink);font-weight:600;text-decoration:none}
.explore-pagination a:hover{background:#edf6f1;border-color:#a5c6b7}.explore-pagination .page-disabled{opacity:.45}.explore-pagination .page-status{white-space:nowrap;color:var(--muted)}
"""


EXPLORE_DETAIL_STYLE = """
.explore-detail{font-family:"Segoe UI",Arial,sans-serif;max-width:1500px;padding:12px 24px 30px;background:#f7f8f4}.regional-detail{width:calc(100% - 48px)}
.explore-detail>header{display:flex;align-items:center;padding:7px 24px;min-height:58px;background:#eef8f2f2;border-radius:20px;box-shadow:0 5px 24px #183e3808}.explore-detail>header .brand{gap:12px}.explore-detail>header .home-logo{width:40px;height:44px;flex:none;color:#148975}.explore-detail>header .brand-name{display:flex;flex-direction:column;font-size:27px;font-weight:750;letter-spacing:-.05em;line-height:1.15}.explore-detail>header .brand-name small{font-size:11px;font-weight:500;letter-spacing:.12em;margin-top:4px}
.explore-job{display:grid;grid-template-columns:minmax(0,68fr) minmax(0,32fr);gap:24px;align-items:start;margin-top:18px}.explore-job-main,.explore-job-sidebar{min-width:0}.explore-job-sidebar{position:static;display:grid;gap:14px}.explore-job-back{margin:0 0 14px}.explore-job-back a{font-size:14px;font-weight:600}.explore-job-main>h1{font-size:clamp(30px,3.3vw,43px);line-height:1.12;letter-spacing:-.045em;font-weight:700;margin:0 0 5px}.explore-job-employer,.explore-job-place{font-size:16px;line-height:1.4;margin:2px 0}.explore-job-main>.badge{margin:8px 0 14px;background:#e3f2e8;color:#245d49;font-weight:600}
.explore-job-section,.explore-job-card{background:#fff;border:1px solid #dce9e3;border-radius:18px;box-shadow:0 6px 20px #244f420b;padding:18px 22px}.explore-job-section{margin:14px 0}.explore-job-section:first-of-type{margin-top:0}.explore-job-section h2,.explore-job-section h3,.explore-job-card h2{display:flex;align-items:center;gap:12px;font-size:21px;line-height:1.2;letter-spacing:-.025em;font-weight:650;margin:0 0 8px}.explore-job-section p,.explore-job-section li,.explore-job-card p,.explore-job-card li{font-size:15px;line-height:1.5}.explore-job-section p,.explore-job-card p{margin:7px 0}.explore-job-section ul,.explore-job-section ol,.explore-job-card ul,.explore-job-card ol{margin:8px 0;padding-left:22px}.explore-job-section li p,.explore-job-card li p{margin:2px 0}
.explore-job-section h2:before,.explore-job-section h3:before,.explore-job-card h2:before{display:grid;place-items:center;flex:none;width:42px;height:42px;border-radius:50%;font-size:22px;font-weight:500;letter-spacing:0}
.explore-job-section h2:before,.explore-job-section h3:before{content:"✦";background:#ddf5e9;color:#267564}.explore-job-section:nth-of-type(3n+2) h2:before,.explore-job-section:nth-of-type(3n+2) h3:before{content:"☷";background:#e2f0ff;color:#3973a2}.explore-job-section:nth-of-type(3n) h2:before,.explore-job-section:nth-of-type(3n) h3:before{content:"✧";background:#fff0d5;color:#927136}
.explore-job-facts h2:before{content:"ⓘ";background:#d8f3e6;color:#176f5e}.explore-job-apply h2:before{content:"▤";background:#ffedc9;color:#866527}.explore-job-insight h2:before{content:"▥";background:#dcecff;color:#286aa0}
.explore-job-facts dl>div:before{grid-column:1;display:grid;place-items:center;width:34px;height:34px;border-radius:50%;font-size:18px;background:#def3e8;color:#216d5f}.explore-job-facts .fact-place:before{content:"⌖"}.explore-job-facts .fact-employer:before{content:"▣"}.explore-job-facts .fact-positions:before{content:"◉";background:#e2f0ff;color:#3973a2}.explore-job-facts .fact-published:before,.explore-job-facts .fact-deadline:before{content:"▦";background:#e8efff;color:#416bab}
.explore-job-facts dl{margin:0 0 16px}.explore-job-facts dl>div{display:grid;grid-template-columns:34px 110px minmax(0,1fr);gap:10px;align-items:center;padding:8px 0;border-bottom:1px solid #e5eeea}.explore-job-facts dt{grid-column:2;font-size:13px;color:#587571}.explore-job-facts dd{grid-column:3;font-size:14px;font-weight:600;margin:0;overflow-wrap:anywhere}.explore-job-facts .button{display:block;text-align:center;font-size:15px;font-weight:600;background:#0f6a5d;color:#fff;padding:12px 18px;border-radius:11px}.explore-job-facts .button:hover{background:#155e54}.explore-job-facts{background:#f1faf5}.explore-job-apply{background:#fff9ed}.explore-job-insight{background:#eff7ff}.regional-detail .explore-job-facts .button{background:#2f6658}.regional-detail .explore-job-facts .button:hover{background:#28594e}.regional-job-description .job-description{max-width:none;margin:0;line-height:1.58}.regional-job-description .job-description h2{font-size:22px;margin:18px 0 8px}.regional-job-description .job-description h3{font-size:19px;margin:15px 0 6px}.regional-job-description .job-description p{margin:8px 0}.regional-job-description .job-description ul,.regional-job-description .job-description ol{margin:8px 0;padding-left:23px}.regional-job-description .description-contact,.regional-detail .explore-job-apply a{font-weight:600;overflow-wrap:anywhere}.regional-detail .explore-job-apply .original-ad{margin-top:12px;padding-top:10px;border-top:1px solid #eadfca;font-size:13px}.regional-job-contacts{padding-top:16px;padding-bottom:16px}.regional-job-contacts h2:before{content:"@";background:#e2f0ff;color:#3973a2}.regional-contact{display:grid;gap:2px;padding:9px 0;border-top:1px solid #e5eeea;overflow-wrap:anywhere}.regional-contact:first-of-type{border-top:0;padding-top:2px}.regional-contact strong{font-size:15px}.regional-contact .contact-role{font-size:14px;color:var(--muted)}.regional-contact a{font-size:14px;font-weight:600}
@media(max-width:1100px){.regional-job{grid-template-columns:1fr}}
@media(max-width:900px){.explore-job{grid-template-columns:1fr}.explore-job-sidebar{position:static}}
@media(max-width:700px){.explore-detail{padding:12px}.regional-detail{width:auto;max-width:100%}.explore-detail>header{padding:10px}.regional-detail>header{gap:8px}.regional-detail>header .brand{min-width:0;flex:none}.regional-detail>header nav{min-width:0;gap:2px 6px;flex-wrap:wrap;justify-content:flex-end}.regional-detail>header nav a{font-size:11px;padding:3px}.explore-detail>header .home-logo{width:32px;height:36px}.explore-detail>header .brand-name{font-size:22px}.regional-detail .explore-job-main,.regional-detail .explore-job-section{max-width:100%;overflow-wrap:anywhere}.explore-job-section,.explore-job-card{padding:16px}.explore-job-facts dl>div{grid-template-columns:32px 95px minmax(0,1fr);gap:8px}}
"""


EXPLORE_DETAIL_STYLE += """
.detail-application-main{margin-top:12px!important;padding:13px 16px 11px!important;border-color:#cfe4da;border-radius:15px;background:linear-gradient(135deg,#f1faf6,#eaf6f1);box-shadow:0 3px 12px #244f4208}.detail-main-top{display:flex;align-items:center;justify-content:space-between;gap:18px}.detail-main-heading{display:flex;align-items:center;min-width:0;gap:10px}.detail-main-icon{display:grid;place-items:center;flex:none;width:34px;height:34px;border-radius:50%;background:#d8eee4;color:#176b5b}.detail-main-icon svg{width:17px;height:17px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}.detail-application-main h2{display:block;margin:0;font-size:18px;line-height:1.15;letter-spacing:-.02em}.detail-application-main h2:before{display:none}.detail-main-status{margin:2px 0 0!important;color:#56706b;font-size:12.5px!important;line-height:1.3!important}.detail-main-cta{flex:none}.detail-primary-action{display:inline-flex;align-items:center;justify-content:center;max-width:100%;margin:5px 0 3px;padding:11px 16px;border-radius:10px;background:#176c5c;color:#fff;font-size:15px;font-weight:700;line-height:1.25;text-decoration:none;box-shadow:0 4px 12px #176c5c18}.detail-primary-action:hover{background:#145b4e;color:#fff}.detail-application-main .detail-primary-action{min-height:40px;margin:0;padding:9px 15px;border-radius:9px;box-shadow:0 2px 7px #176c5c14;white-space:nowrap}.detail-main-meta{display:grid;gap:4px;margin-top:8px;padding-top:7px;border-top:1px solid #d7e8e0}.detail-main-meta p{margin:0!important;font-size:12.5px!important;line-height:1.4!important}.detail-main-meta .original-ad{margin:0!important;padding:0!important;border:0!important;font-size:11.5px!important}.detail-main-meta .original-ad a{color:#5c746f!important;font-weight:550!important}.detail-alternative{margin-top:10px!important}.detail-application-main a:not(.detail-primary-action),.explore-job-apply a:not(.detail-primary-action){color:#176b5b;font-weight:650;overflow-wrap:anywhere}.explore-job-apply .original-ad{margin-top:12px!important;padding-top:10px;border-top:1px solid #dce9e3;font-size:13px!important}.explore-job-apply .detail-primary-action{width:100%}@media(max-width:700px){.detail-primary-action{width:100%}.detail-application-main{padding:12px 13px 10px!important}.detail-main-top{align-items:stretch;flex-direction:column;gap:9px}.detail-main-cta{width:100%}.detail-application-main .detail-primary-action{width:100%}.detail-main-meta{margin-top:7px;padding-top:7px}}
"""


ABOUT_STYLE = """
.about-page{max-width:1500px;margin:0 auto;padding:12px 18px 38px;background:#f7f9f6;font-family:"Segoe UI",Arial,sans-serif;color:#153d3a}.about-page header{padding:7px 24px;min-height:58px;background:#eef8f2f2;border-radius:20px;box-shadow:0 5px 24px #183e3808}.about-page .brand{gap:12px}.about-page .home-logo{width:40px;height:44px;flex:none;color:#148975}.about-page .brand-name{display:flex;flex-direction:column;font-size:27px;font-weight:750;letter-spacing:-.05em;line-height:1.15}.about-page .brand-name small{font-size:11px;font-weight:500;letter-spacing:.12em;margin-top:4px}.about-hero{position:relative;isolation:isolate;overflow:hidden;margin-top:12px;min-height:254px;padding:32px 36px;border:1px solid #dbe9e2;border-radius:22px;background:linear-gradient(90deg,#f8fcf9f5 0%,#f7fbf8e8 43%,#e8f4ef91 72%,#eef7f4a0 100%),url('/static/jobbpeil-bg.png') center 47%/cover no-repeat;box-shadow:0 8px 28px #244f420b}.about-hero>*{position:relative;z-index:1}.about-hero h1{margin:0 0 4px;font-size:clamp(39px,4vw,54px);line-height:1.08;letter-spacing:-.055em;font-weight:760}.about-hero .lead{margin:0 0 10px;font-size:21px;font-weight:680;line-height:1.35}.about-hero .intro{max-width:650px;margin:0;font-size:16px;line-height:1.52;color:#294e50}.about-hero-actions{display:flex;flex-wrap:wrap;gap:14px;margin-top:18px}.about-hero-actions .button{display:inline-flex;align-items:center;justify-content:center;min-width:206px;padding:13px 18px;border:1px solid #4b9586;border-radius:11px;background:#ffffffd9;color:#176455;font-size:15px;font-weight:700;box-shadow:0 3px 10px #244f4208}.about-hero-actions .button.primary{border-color:#176c5c;background:#176c5c;color:#fff}.about-hero-actions .button:hover{background:#e7f4ee}.about-hero-actions .button.primary:hover{background:#145b4e}.about-hero .about-hero-note{position:absolute;right:32px;bottom:27px;max-width:212px;padding:17px 18px 17px 70px;border:1px solid #ffffffcf;border-radius:17px;background:#ffffffdf;color:#193f3d;font-size:16px;font-weight:650;line-height:1.4;box-shadow:0 7px 20px #244f4214}.about-hero-note:before{content:'';position:absolute;left:18px;top:50%;width:36px;height:28px;transform:translateY(-50%);border-radius:12px 12px 8px 8px;background:linear-gradient(135deg,#bfead5 0 48%,#5fae82 49% 100%)}.about-section{margin-top:14px;padding:20px;background:#fffffff2;border:1px solid #dce9e3;border-radius:19px;box-shadow:0 5px 20px #244f4208}.about-section>h2,.about-section h3{margin:0;color:#163e3b;letter-spacing:-.035em}.about-section>h2{display:flex;align-items:center;gap:11px;font-size:25px}.about-section>.section-intro{margin:3px 0 14px 43px;color:#58736f;font-size:15px}.about-heading-icon,.about-card-icon{display:inline-grid;place-items:center;flex:none;width:38px;height:38px;border-radius:10px;background:#e1f4ea;color:#176b5b}.about-heading-icon svg,.about-card-icon svg{width:24px;height:24px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}.about-paths{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.about-path,.about-insight,.about-source,.about-small-card{min-width:0;border:1px solid #e0ece7;border-radius:15px;background:#fff}.about-path{position:relative;padding:18px 18px 15px 92px;min-height:148px;background:linear-gradient(135deg,#fcfefd,#f2faf6)}.about-path:nth-child(2){background:linear-gradient(135deg,#fcfdff,#f1f7fc)}.about-path:not(:last-child):after{content:'→';position:absolute;right:-23px;top:50%;z-index:2;display:grid;place-items:center;width:24px;height:24px;transform:translateY(-50%);border-radius:50%;background:#f7f9f6;color:#16806b;font-weight:800}.about-path .about-card-icon{position:absolute;top:20px;left:18px;width:58px;height:58px;border-radius:50%;background:#dff4e9}.about-path:nth-child(2) .about-card-icon{background:#e4f1fb;color:#2f6f9f}.about-insight .about-card-icon{background:#e9eefc;color:#506fa5}.about-path h3,.about-insight h3,.about-source h3,.about-small-card h3{font-size:17px;line-height:1.25}.about-path p,.about-insight p,.about-source p,.about-small-card p{margin:6px 0 12px;color:#496965;font-size:13px;line-height:1.45}.about-path .button{display:inline-block;padding:8px 11px;border-radius:9px;background:#e2f3eb;color:#175d51;font-size:12.5px;font-weight:700}.about-path:first-child .button{background:#e2f3eb;color:#175d51}.about-path:nth-child(2) .button{background:#e5f1fb;color:#29628b}.about-path .button:hover{background:#d5ede2}.about-path:nth-child(2) .button:hover{background:#d8eafa}.about-path:first-child .button:hover{background:#d5ede2}.about-insight:not(.about-path){padding:18px;background:#eff8f4}.about-path.about-insight{padding:18px 18px 15px 92px;background:#f1f4fb}.about-insight:not(.about-path) .about-card-icon{float:left;margin:0 13px 9px 0}.about-insight:not(.about-path) p{clear:both;margin-top:13px}.about-data-grid{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(350px,1fr);gap:14px;margin-top:14px}.about-data-grid .about-section{margin-top:0}.about-sources{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.about-source{position:relative;padding:17px;background:linear-gradient(135deg,#fff,#f4fbf8)}.about-source.soon{background:linear-gradient(135deg,#fff,#f5f7f6)}.about-source-mark{display:grid;place-items:center;width:55px;height:55px;margin-bottom:10px;border-radius:50%;font-size:19px;font-weight:800;letter-spacing:-.08em}.about-source-mark.nav{background:#d81f28;color:#fff}.about-source-mark.ssb{background:#1d2424;color:#fff;font-size:17px;letter-spacing:-.03em}.about-source .status{position:absolute;top:18px;right:14px;display:inline-block;padding:4px 9px;border-radius:999px;background:#2d9c67;color:#fff;font-size:11px;font-weight:700}.about-source.soon .status{background:#e9eeeb;color:#60736c}.about-source h3{font-size:17px}.about-source p{margin-bottom:10px}.about-source-link{font-size:13px;font-weight:700;color:#176b5b}.about-why{padding:20px}.about-benefits{display:grid;gap:8px;margin:15px 0 16px;padding:0;list-style:none}.about-benefits li{display:flex;gap:9px;align-items:flex-start;font-size:14px;line-height:1.35}.about-benefits li:before{content:'✓';display:grid;place-items:center;flex:none;width:19px;height:19px;border-radius:50%;background:#2ba96b;color:#fff;font-size:12px;font-weight:800}.about-why-copy{position:relative;margin:0;padding:15px 17px 15px 53px;border-radius:13px;background:#edf7f2;color:#315e56;font-size:14px;line-height:1.45}.about-why-copy:before{content:'“';position:absolute;left:17px;top:6px;color:#2eaa70;font-size:38px;font-weight:800}.about-small-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-top:14px}.about-small-card{min-height:114px;padding:16px 16px 14px 72px;background:#ffffffdf;position:relative}.about-small-card .about-card-icon{position:absolute;top:17px;left:17px;width:42px;height:42px;background:#f0f8f4}.about-small-card p{margin:5px 0 0;font-size:13px}.about-small-link{color:inherit;text-decoration:none}.about-small-link:hover{border-color:#b7d8cc;background:#fbfefc}.about-page a:focus-visible{outline:3px solid #6c9d89;outline-offset:3px}@media(max-width:1050px){.about-paths{grid-template-columns:repeat(2,minmax(0,1fr))}.about-path:nth-child(2):after{display:none}.about-insight{grid-column:1/-1}.about-data-grid{grid-template-columns:1fr}.about-hero .about-hero-note{display:none}}@media(max-width:700px){.about-page{padding:10px 12px 28px}.about-page header{padding:10px 12px}.about-page .home-logo{width:35px;height:39px}.about-page .brand-name{font-size:23px}.about-hero{min-height:auto;padding:25px 20px}.about-hero h1{font-size:36px}.about-hero .lead{font-size:19px}.about-hero-actions{gap:10px}.about-hero-actions .button{flex:1 1 100%;min-width:0}.about-section,.about-why{padding:17px}.about-section>h2{font-size:23px}.about-section>.section-intro{margin-left:0}.about-paths,.about-sources,.about-data-grid,.about-small-grid{grid-template-columns:1fr}.about-path:not(:last-child):after{display:none}.about-insight{grid-column:auto}.about-small-card{min-height:104px}}
"""


PRIVACY_STYLE = """
.privacy-page{max-width:1120px;margin:0 auto;padding:12px 18px 34px;background:#f7f9f6;font-family:"Segoe UI",Arial,sans-serif;color:#153d3a}.privacy-page header{padding:7px 24px;min-height:58px;background:#eef8f2f2;border-radius:20px;box-shadow:0 5px 24px #183e3808}.privacy-page .brand{gap:12px}.privacy-page .home-logo{width:40px;height:44px;flex:none;color:#148975}.privacy-page .brand-name{display:flex;flex-direction:column;font-size:27px;font-weight:750;letter-spacing:-.05em;line-height:1.15}.privacy-page .brand-name small{font-size:11px;font-weight:500;letter-spacing:.12em;margin-top:4px}.privacy-hero{margin-top:14px;padding:28px 32px;border:1px solid #dce9e3;border-radius:20px;background:linear-gradient(135deg,#f5fcf8,#edf7f3);box-shadow:0 6px 20px #244f4208}.privacy-hero h1{margin:0 0 7px;font-size:clamp(34px,4vw,48px);line-height:1.1;letter-spacing:-.05em}.privacy-hero p{max-width:630px;margin:0;color:#365c56;font-size:17px;line-height:1.5}.privacy-content{max-width:760px;margin:16px auto 0}.privacy-section{margin-top:13px;padding:20px 22px;border:1px solid #dce9e3;border-radius:17px;background:#fff;box-shadow:0 4px 16px #244f4208}.privacy-section h2{margin:0 0 8px;font-size:21px;line-height:1.25;letter-spacing:-.025em}.privacy-section p{margin:7px 0;color:#3c5f5a;line-height:1.58}.privacy-section ul{margin:8px 0 0;padding-left:21px;color:#3c5f5a;line-height:1.6}.privacy-section li+li{margin-top:3px}.privacy-cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px;margin-top:13px}.privacy-cards .privacy-section{margin:0;background:#f7fbf8}.privacy-cards .privacy-section:last-child{background:#f5f8fc}.privacy-section a{color:#176b5b;font-weight:650;overflow-wrap:anywhere}.privacy-updated{margin:15px 2px 0;color:#6b817c;font-size:13px}.privacy-page a:focus-visible{outline:3px solid #6c9d89;outline-offset:3px}@media(max-width:700px){.privacy-page{padding:10px 12px 28px}.privacy-page header{padding:10px 12px}.privacy-page .home-logo{width:35px;height:39px}.privacy-page .brand-name{font-size:23px}.privacy-hero{padding:24px 20px}.privacy-hero h1{font-size:35px}.privacy-section{padding:18px}.privacy-cards{grid-template-columns:1fr}}
"""


CONTACT_STYLE = """
.contact-page{max-width:1120px;margin:0 auto;padding:12px 18px 34px;background:#f7f9f6;font-family:"Segoe UI",Arial,sans-serif;color:#153d3a}.contact-page header{padding:7px 24px;min-height:58px;background:#eef8f2f2;border-radius:20px;box-shadow:0 5px 24px #183e3808}.contact-page .brand{gap:12px}.contact-page .home-logo{width:40px;height:44px;flex:none;color:#148975}.contact-page .brand-name{display:flex;flex-direction:column;font-size:27px;font-weight:750;letter-spacing:-.05em;line-height:1.15}.contact-page .brand-name small{font-size:11px;font-weight:500;letter-spacing:.12em;margin-top:4px}.contact-card{max-width:640px;margin:52px auto 0;padding:32px;border:1px solid #dce9e3;border-radius:20px;background:linear-gradient(135deg,#fff,#f3faf6);box-shadow:0 6px 20px #244f4208}.contact-icon{display:grid;place-items:center;width:48px;height:48px;margin-bottom:17px;border-radius:14px;background:#e1f4ea;color:#176b5b}.contact-icon svg{width:24px;height:24px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.contact-card h1{margin:0 0 8px;font-size:clamp(34px,4vw,46px);line-height:1.1;letter-spacing:-.05em}.contact-card p{margin:8px 0;color:#3c5f5a;font-size:17px;line-height:1.55}.contact-email{display:inline-block;margin-top:13px;color:#176b5b;font-size:18px;font-weight:700;overflow-wrap:anywhere}.contact-send{display:inline-block;margin-top:18px;padding:9px 13px;border-radius:9px;background:#e2f3eb;color:#175d51;font-size:14px;font-weight:700;text-decoration:none}.contact-send:hover{background:#d5ede2}.contact-page a:focus-visible{outline:3px solid #6c9d89;outline-offset:3px}@media(max-width:700px){.contact-page{padding:10px 12px 28px}.contact-page header{padding:10px 12px}.contact-page .home-logo{width:35px;height:39px}.contact-page .brand-name{font-size:23px}.contact-card{margin-top:24px;padding:24px 20px}.contact-card p{font-size:16px}}
"""

CONTACT_STYLE += """
.contact-page{position:relative;isolation:isolate;background:linear-gradient(135deg,#F3FAF6 0%,#F7FAF9 50%,#EAF5FB 100%)}
.contact-page:before,.contact-page:after{content:"";position:absolute;z-index:0;pointer-events:none;opacity:.58}
.contact-page:before{top:112px;right:20px;width:300px;height:380px;border-radius:64% 36% 58% 42% / 43% 57% 43% 57%;background:linear-gradient(145deg,#d9f1e6,#d9edf7)}
.contact-page:after{bottom:60px;left:18px;width:230px;height:270px;border-radius:42% 58% 39% 61% / 57% 42% 58% 43%;background:#dcefe6}
.contact-page>header,.contact-page>.contact-card,.contact-page>.site-footer{position:relative;z-index:1}
.contact-page .contact-card{box-shadow:0 10px 28px #244f4210}
@media(max-width:700px){.contact-page:before{top:100px;right:10px;width:180px;height:245px;opacity:.48}.contact-page:after{bottom:42px;left:8px;width:145px;height:180px;opacity:.42}}
"""



VAKT_STYLE = """
body{background:#f7faf9;font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif}.vakt-page{width:calc(100% - 64px);max-width:1540px;margin:0 auto;padding:0 0 28px;background:linear-gradient(180deg,#fbfdfc 0,#f7faf9 61%,#f9fbfb 100%);color:#102f36;font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif}.vakt-page,.vakt-page *{box-sizing:border-box}.vakt-product-header{display:flex;align-items:center;min-height:74px;padding:0 8px;background:#fff;border:0;border-bottom:1px solid #e6efec;border-radius:0;box-shadow:0 2px 12px #173f3908}.vakt-brand{display:flex;align-items:center;gap:10px;color:#123d3b;font-size:27px;font-weight:700;letter-spacing:-.05em;text-decoration:none}.vakt-brand .peil-mark{padding:0;background:transparent;color:#148975}.vakt-brand .peil-mark svg{width:42px;height:42px}.vakt-main-nav{display:flex;align-items:center;gap:27px;margin:0 auto 0 54px}.vakt-main-nav a,.vakt-main-nav span{position:relative;padding:26px 0 23px;color:#385b5a;font-size:14px;font-weight:500;line-height:1;text-decoration:none;white-space:nowrap}.vakt-main-nav a:hover{color:#0d6655}.vakt-main-nav .active{color:#087762;font-weight:700}.vakt-main-nav .active:after{content:"";position:absolute;right:0;bottom:15px;left:0;height:2px;border-radius:2px;background:#087762}.vakt-main-nav .vakt-nav-placeholder{color:#879793;cursor:default}.vakt-header-actions{display:flex;align-items:center;gap:11px}.vakt-header-icon{display:grid;place-items:center;width:34px;height:34px;border-radius:50%;color:#123d3b;text-decoration:none}.vakt-header-icon:hover{background:#edf8f4}.vakt-header-icon svg{width:19px;height:19px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}.vakt-language{position:relative}.vakt-language summary{display:flex;align-items:center;gap:5px;padding:7px 5px;color:#183f3e;font-size:14px;font-weight:650;cursor:pointer;list-style:none}.vakt-language summary::-webkit-details-marker{display:none}.vakt-language-options{position:absolute;z-index:25;top:calc(100% + 7px);right:0;display:grid;min-width:124px;padding:5px;border:1px solid #dcebe5;border-radius:10px;background:#fff;box-shadow:0 10px 24px #173f3920}.vakt-language-options a,.vakt-language-options span{padding:7px 9px;border-radius:7px;color:#244f4b;font-size:13px;text-decoration:none}.vakt-language-options span{background:#edf8f4;font-weight:650}.vakt-login{min-height:38px;padding:9px 17px;border:0;border-radius:999px;background:#087762;color:#fff;font:600 14px/1 Inter,system-ui,sans-serif;opacity:1}.vakt-login:disabled{cursor:default}.vakt-mobile-menu{display:none;margin-left:auto}.vakt-mobile-menu summary{display:flex;align-items:center;gap:6px;padding:8px;border-radius:9px;color:#244f4b;font-size:13px;font-weight:650;cursor:pointer;list-style:none}.vakt-mobile-menu summary::-webkit-details-marker{display:none}.vakt-mobile-menu summary svg{width:19px;height:19px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round}.vakt-mobile-links{display:none}.vakt-grid{display:grid;grid-template-columns:minmax(0,32fr) minmax(0,35fr) minmax(0,33fr);gap:20px;align-items:stretch;margin-top:20px}.vakt-intro,.vakt-form-card,.vakt-info{min-width:0;min-height:505px;border:1px solid #dcebe6;border-radius:22px;box-shadow:0 8px 24px #1a51460d}.vakt-intro{position:relative;display:flex;flex-direction:column;overflow:hidden;padding:23px 30px;background:linear-gradient(145deg,#effbf6 0,#e7f8f1 66%,#def4eb 100%)}.vakt-intro:before{content:"";position:absolute;right:-20px;bottom:-36px;width:126px;height:236px;border-radius:100% 0 100% 0;background:linear-gradient(145deg,#9edfc6,#d0f1e3);opacity:.30;transform:rotate(-24deg)}.vakt-intro:after{content:"";position:absolute;right:-65px;bottom:-104px;width:250px;height:300px;border:30px solid #9edfc6;border-radius:82% 18% 82% 18%;opacity:.30;transform:rotate(-22deg)}.vakt-badge{position:relative;z-index:1;display:inline-flex;align-items:center;align-self:flex-start;gap:7px;margin:0 0 14px;padding:6px 11px;border-radius:999px;background:#d5f3e5;color:#10735d;font-size:13px;font-weight:650;line-height:1}.vakt-badge svg{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round}.vakt-intro h1{position:relative;z-index:1;margin:0 0 7px;font-size:clamp(34px,2.8vw,44px);font-weight:700;letter-spacing:-.052em;line-height:1.08}.vakt-intro h2{position:relative;z-index:1;max-width:365px;margin:0 0 14px;font-size:clamp(25px,2.05vw,31px);font-weight:650;letter-spacing:-.04em;line-height:1.16}.vakt-intro>p{position:relative;z-index:1;max-width:365px;margin:0;color:#315c60;font-size:15px;font-weight:400;line-height:1.44}.vakt-benefits{position:relative;z-index:1;display:grid;gap:8px;margin-top:14px;padding-top:0}.vakt-benefit{display:grid;grid-template-columns:52px minmax(0,1fr);gap:11px;align-items:center}.vakt-benefit span{display:grid;place-items:center;width:52px;height:52px;border-radius:50%;background:#fffffff2;color:#087762;box-shadow:0 5px 14px #1b695417}.vakt-benefit svg{width:24px;height:24px;fill:none;stroke:currentColor;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round}.vakt-benefit strong,.vakt-benefit small{display:block}.vakt-benefit strong{font-size:16px;font-weight:650;letter-spacing:-.018em;line-height:1.22}.vakt-benefit small{margin-top:1px;color:#496e70;font-size:12.5px;font-weight:400;line-height:1.4}.vakt-form-card{display:flex;flex-direction:column;padding:24px 30px;background:#fff}.vakt-form-card h2{margin:0 0 6px;font-size:clamp(28px,2.35vw,35px);font-weight:700;letter-spacing:-.048em;line-height:1.12}.vakt-form-card>p{max-width:480px;margin:0 0 17px;color:#4c6670;font-size:15px;font-weight:400;line-height:1.44}.vakt-form-card form{display:flex;flex-direction:column;max-width:none;margin:0}.vakt-field{position:relative;margin:0 0 6px}.vakt-form-card label{display:block;margin:0 0 5px;color:#183c40;font-size:14px;font-weight:600;line-height:1.25}.vakt-field svg{position:absolute;z-index:1;top:41px;left:15px;width:20px;height:20px;color:#1d5f61;fill:none;stroke:currentColor;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round;pointer-events:none}.vakt-field .vakt-select-chevron{right:15px;left:auto;width:17px}.vakt-form-card input,.vakt-form-card select{width:100%;height:52px;margin:0;padding:12px 15px 12px 46px;border:1px solid #d7e3e2;border-radius:10px;background:#fff;color:#173e3f;font:400 14px/1.25 Inter,system-ui,sans-serif;outline:0}.vakt-form-card select{appearance:none;padding-right:44px}.vakt-form-card input::placeholder{color:#7b8e94}.vakt-form-card input:focus,.vakt-form-card select:focus{border-color:#4fa58e;box-shadow:0 0 0 3px #d9f2e8}.vakt-explore-link{display:inline-flex;align-self:flex-start;margin:-2px 0 8px;color:#087762;font-size:14px;font-weight:500;text-decoration-thickness:1px;text-underline-offset:4px}.vakt-form-card button{width:100%;min-height:54px;margin-top:4px;padding:13px 20px;border:0;border-radius:10px;background:linear-gradient(105deg,#087a61,#0a8067);color:#fff;font:650 17px/1.2 Inter,system-ui,sans-serif;box-shadow:0 7px 16px #08776224}.vakt-form-card button:hover{background:#086b57}.vakt-free-note{margin:5px 0 0!important;color:#687d87!important;font-size:13px!important;font-weight:400!important;line-height:1.35!important;text-align:center}.vakt-info{position:relative;display:flex;flex-direction:column;overflow:hidden;padding:15px 16px 12px;background:linear-gradient(155deg,#eaf6fc 0,#e7f6fc 58%,#eaf7fb 100%)}.vakt-info:before{content:"";position:absolute;z-index:0;top:28px;right:-24px;width:310px;height:310px;border-radius:50%;background:radial-gradient(circle at 45% 42%,#d9f2fc 0 45%,#ccecf9 46% 72%,transparent 73%)}.vakt-robot-stage{position:relative;z-index:1;min-height:230px}.vakt-robot-figure{position:absolute;top:-52px;right:-13px;width:278px;height:294px;margin:0}.vakt-robot-figure img{display:block;width:100%;height:100%;object-fit:contain;filter:drop-shadow(0 12px 11px #1e6b6521)}.vakt-speech{position:absolute;z-index:2;top:21px;left:1px;width:132px;margin:0;color:#153f48;font-family:"Segoe Print","Bradley Hand",cursive;font-size:18px;font-weight:500;line-height:1.17;transform:rotate(-5deg)}.vakt-speech:after{content:"";display:block;width:53px;height:34px;margin:1px 0 0 16px;border-bottom:2px dashed #0f6270;border-radius:0 0 100% 40%;transform:rotate(20deg)}.vakt-accent{position:absolute;z-index:2;top:133px;right:5px;width:30px;height:46px;border-right:4px solid #8bddeb;border-radius:50%;transform:rotate(18deg);opacity:.85}.vakt-accent:before,.vakt-accent:after{content:"";position:absolute;right:8px;width:20px;border-top:3px solid #8bddeb;border-radius:50%}.vakt-accent:before{top:-8px;transform:rotate(15deg)}.vakt-accent:after{bottom:-7px;transform:rotate(-16deg)}.vakt-alerts{position:relative;z-index:3;margin-top:0;padding:10px 13px;border:1px solid #ffffffd6;border-radius:16px;background:#fffffff2;box-shadow:0 9px 20px #1c596614}.vakt-alerts h3{display:flex;align-items:center;gap:8px;margin:0 0 3px;color:#183f46;font-size:13px;font-weight:650;line-height:1.3}.vakt-alerts h3 svg{width:26px;height:26px;padding:5px;border-radius:50%;background:#dff3fd;color:#247791;fill:none;stroke:currentColor;stroke-width:1.8}.vakt-alert{display:grid;grid-template-columns:31px minmax(0,1fr) auto;gap:8px;align-items:center;padding:6px 0;border-top:1px solid #e0ebee}.vakt-alert span{display:grid;place-items:center;width:30px;height:30px;border-radius:50%;background:#edf5f6;color:#164f56}.vakt-alert span svg{width:17px;height:17px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.vakt-alert strong,.vakt-alert small{display:block}.vakt-alert strong{color:#193f46;font-size:13px;font-weight:650;line-height:1.25}.vakt-alert small{margin-top:2px;color:#647a84;font-size:11.5px;font-weight:400;line-height:1.25}.vakt-alert time{color:#657986;font-size:11px;white-space:nowrap}.vakt-note{position:relative;z-index:3;align-self:flex-end;max-width:190px;margin:8px 9px 0 0;color:#153f48;font-family:"Segoe Print","Bradley Hand",cursive;font-size:16px;font-weight:500;line-height:1.13;text-align:right;transform:rotate(-4deg)}.vakt-note:before{content:"";position:absolute;top:-16px;left:-48px;width:52px;height:26px;border-top:2px dashed #0f6270;border-radius:70% 20% 0 0;transform:rotate(27deg)}.vakt-steps{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:28px;margin:18px 0 0;padding:0 38px;background:transparent;border:0;box-shadow:none}.vakt-steps h2{grid-column:1/-1;margin:0 0 -3px;color:#102f36;font-size:27px;font-weight:700;letter-spacing:-.04em;line-height:1.15}.vakt-step{display:grid;grid-template-columns:59px minmax(0,1fr);gap:14px;align-items:start}.vakt-step b{display:grid;place-items:center;width:59px;height:59px;border-radius:50%;background:#cdeee0;color:#087762;font-size:24px;font-weight:650}.vakt-step:nth-of-type(3) b{background:#d9effc;color:#24799a}.vakt-step strong{display:block;margin:3px 0 4px;color:#173c40;font-size:17px;font-weight:650;letter-spacing:-.02em;line-height:1.25}.vakt-step p{margin:0;color:#547078;font-size:14px;font-weight:400;line-height:1.42}.vakt-perks{display:flex;align-items:center;gap:52px;margin:15px 0 0;padding:13px 38px 10px;border-top:1px solid #e6eeeb;color:#385d61}.vakt-perk{display:inline-flex;align-items:center;gap:10px;font-size:14px;font-weight:500;white-space:nowrap}.vakt-perk svg{width:21px;height:21px;color:#087762;fill:none;stroke:currentColor;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round}.vakt-swoosh{margin-left:auto;color:#163f47;font-family:"Segoe Print","Bradley Hand",cursive;font-size:17px;line-height:1.15;text-align:right;transform:rotate(-4deg)}.vakt-swoosh:after{content:"";display:block;width:132px;margin:4px 0 0 auto;border-top:2px solid #078166;border-radius:50%;transform:rotate(-2deg)}.vakt-page>.site-footer{margin:19px 0 0;padding:10px 6px 0;border-color:#e1ebe7;color:#7d908d;font-family:Inter,system-ui,sans-serif}.vakt-page a:focus-visible,.vakt-page input:focus-visible,.vakt-page select:focus-visible,.vakt-page button:focus-visible,.vakt-page summary:focus-visible{outline:3px solid #72a994;outline-offset:3px}@media(max-width:1180px){.vakt-main-nav{gap:15px;margin-left:26px}.vakt-main-nav a,.vakt-main-nav span{font-size:13px}.vakt-grid{grid-template-columns:minmax(0,.92fr) minmax(0,1.08fr);gap:18px}.vakt-info{grid-column:1/-1;display:grid;grid-template-columns:minmax(260px,.7fr) minmax(0,1fr);gap:18px;align-items:center;min-height:0}.vakt-robot-stage{min-height:300px}.vakt-alerts{margin:0}.vakt-note{display:none}}@media(max-width:850px){.vakt-page{width:calc(100% - 32px)}.vakt-main-nav,.vakt-header-actions{display:none}.vakt-mobile-menu{display:block}.vakt-mobile-menu[open] .vakt-mobile-links{position:absolute;z-index:30;top:66px;right:0;display:grid;width:min(280px,calc(100vw - 32px));gap:4px;padding:9px;border:1px solid #dcebe5;border-radius:14px;background:#fff;box-shadow:0 12px 26px #173f3920}.vakt-mobile-links a,.vakt-mobile-links span{padding:10px;border-radius:8px;color:#214c4a;font-size:14px;text-decoration:none}.vakt-mobile-links a.active{background:#e5f6ee;color:#087762;font-weight:700}.vakt-mobile-links span{color:#80918d}.vakt-grid{grid-template-columns:1fr}.vakt-info{grid-column:auto;display:flex}.vakt-info,.vakt-intro,.vakt-form-card{min-height:0}.vakt-intro{min-height:520px}.vakt-form-card{min-height:570px}.vakt-steps{gap:20px;padding:0 18px}.vakt-perks{gap:20px;padding:16px 18px}}@media(max-width:560px){.vakt-page{width:100%;padding:0 12px 24px}.vakt-product-header{min-height:62px;padding:0 4px}.vakt-brand{font-size:23px}.vakt-brand .peil-mark svg{width:35px;height:35px}.vakt-intro{min-height:0;padding:25px 21px}.vakt-intro h1{font-size:38px}.vakt-intro h2{font-size:27px}.vakt-intro>p{font-size:15px}.vakt-benefits{gap:13px;padding-top:25px}.vakt-benefit{grid-template-columns:53px minmax(0,1fr);gap:11px}.vakt-benefit span{width:52px;height:52px}.vakt-benefit svg{width:24px;height:24px}.vakt-benefit strong{font-size:16px}.vakt-benefit small{font-size:13px}.vakt-form-card{min-height:0;padding:27px 21px}.vakt-form-card h2{font-size:31px}.vakt-form-card>p{margin-bottom:21px;font-size:15px}.vakt-info{padding:14px 14px 17px}.vakt-robot-stage{min-height:282px}.vakt-robot-figure{top:-13px;right:-16px;width:282px;height:300px}.vakt-speech{top:20px;font-size:17px}.vakt-accent{right:0}.vakt-alerts{padding:12px}.vakt-alert{grid-template-columns:28px minmax(0,1fr) auto;gap:7px;padding:8px 0}.vakt-alert strong{font-size:12px}.vakt-alert small{font-size:11px}.vakt-note{display:none}.vakt-steps{grid-template-columns:1fr;gap:15px;margin-top:28px;padding:0}.vakt-steps h2{font-size:25px}.vakt-step{grid-template-columns:50px minmax(0,1fr);gap:12px}.vakt-step b{width:50px;height:50px;font-size:21px}.vakt-step strong{font-size:16px}.vakt-step p{font-size:13px}.vakt-perks{display:grid;grid-template-columns:1fr;margin-top:23px;padding:16px 0 9px;gap:12px}.vakt-perk{font-size:13px}.vakt-swoosh{margin:5px 0 0}.vakt-page>.site-footer{margin-top:13px}.vakt-mobile-menu[open] .vakt-mobile-links{top:57px;right:0;width:min(280px,calc(100vw - 24px))}}@media(prefers-reduced-motion:reduce){.vakt-robot-figure img{filter:none}}
"""

VAKT_STYLE += """
/* The Vakt page uses the same shared site header as the About page. */
.vakt-page{width:100%;max-width:1500px;padding:12px 18px 28px}
.vakt-page>header{padding:7px 24px;min-height:58px;background:#eef8f2f2;border-radius:20px;box-shadow:0 5px 24px #183e3808;font-family:"Segoe UI",Arial,sans-serif}
.vakt-page>header .brand{gap:12px}.vakt-page>header .home-logo{width:40px;height:44px;flex:none;color:#148975}.vakt-page>header .brand-name{display:flex;flex-direction:column;font-size:27px;font-weight:750;letter-spacing:-.05em;line-height:1.15}.vakt-page>header .brand-name small{font-size:11px;font-weight:500;letter-spacing:.12em;margin-top:4px}
@media(max-width:700px){.vakt-page{padding:10px 12px 28px}.vakt-page>header{padding:10px 12px}.vakt-page>header .home-logo{width:35px;height:39px}.vakt-page>header .brand-name{font-size:23px}}
"""


VAKT_STYLE += """
.vakt-form-notice{margin:0 0 14px;padding:10px 12px;border:1px solid #bfe2d2;border-radius:10px;background:#edf9f3;color:#24594f;font-size:13px;line-height:1.4}
.vakt-form-notice strong{display:block;margin-bottom:2px;color:#174c43;font-size:14px}.vakt-form-notice p{margin:0;color:inherit;font-size:13px;line-height:1.4}
.vakt-form-notice.error{border-color:#edcfca;background:#fff3f1;color:#74463f}.vakt-form-notice.error strong{color:#6b3933}
"""

APPROVED_UI_STYLE += r"""
/* Compact visual alignment for the central Vakt form only. */
.vakt-page .vakt-form-card>p{margin-bottom:8px}.vakt-page .vakt-form-card input,.vakt-page .vakt-form-card select{box-sizing:border-box;height:56px;border:1px solid #d7e3e2;border-radius:13px;background:#fff;outline:none;box-shadow:none}.vakt-page .vakt-form-card input:focus,.vakt-page .vakt-form-card input:focus-visible,.vakt-page .vakt-form-card select:focus,.vakt-page .vakt-form-card select:focus-visible{border:1px solid #6d9e98;outline:none;box-shadow:none}.vakt-page .vakt-profession-search{box-sizing:border-box;height:56px;border:1px solid #d7e3e2;border-radius:13px;background:#fff;outline:none;box-shadow:none}.vakt-page .vakt-profession-search:focus-within{z-index:30;border:1px solid #6d9e98;outline:none;box-shadow:none}.vakt-page .vakt-profession-search input,.vakt-page .vakt-profession-search input:focus,.vakt-page .vakt-profession-search input:focus-visible{height:54px;border:0!important;outline:none!important;background:transparent;box-shadow:none!important}.vakt-page .vakt-explore-link{margin:4px 0 18px;font-size:14px;font-weight:600;text-decoration:none}.vakt-page .vakt-explore-link:hover,.vakt-page .vakt-explore-link:focus-visible{text-decoration:underline}.vakt-page .vakt-form-card button{height:54px;min-height:54px}.vakt-page .vakt-free-note{margin-top:10px!important}
"""

VAKT_LIFECYCLE_STYLE = """
.vakt-lifecycle-page{max-width:1120px;margin:0 auto;padding:12px 18px 34px;background:#f7f9f6;font-family:"Segoe UI",Arial,sans-serif;color:#153d3a}.vakt-lifecycle-page header{padding:7px 24px;min-height:58px;background:#eef8f2f2;border-radius:20px;box-shadow:0 5px 24px #183e3808}.vakt-lifecycle-page .brand{gap:12px}.vakt-lifecycle-page .home-logo{width:40px;height:44px;flex:none;color:#148975}.vakt-lifecycle-page .brand-name{display:flex;flex-direction:column;font-size:27px;font-weight:750;letter-spacing:-.05em;line-height:1.15}.vakt-lifecycle-page .brand-name small{font-size:11px;font-weight:500;letter-spacing:.12em;margin-top:4px}
.vakt-lifecycle-card{max-width:620px;margin:52px auto 0;padding:32px;border:1px solid #dce9e3;border-radius:20px;background:linear-gradient(135deg,#fff,#f3faf6);box-shadow:0 8px 24px #244f420d;text-align:center}.vakt-lifecycle-icon{display:grid;place-items:center;width:54px;height:54px;margin:0 auto 17px;border-radius:50%;background:#dff4e9;color:#176b5b;font-size:27px;font-weight:800}.vakt-lifecycle-card.invalid .vakt-lifecycle-icon{background:#f8e8e5;color:#8a5149}.vakt-lifecycle-card h1{margin:0 0 9px;font-size:clamp(31px,4vw,43px);line-height:1.12;letter-spacing:-.045em}.vakt-lifecycle-card p{max-width:500px;margin:0 auto;color:#456761;font-size:16px;line-height:1.55}.vakt-lifecycle-card .button{margin-top:21px;padding:10px 16px;border-radius:10px;background:#176c5c;color:#fff;font-size:14px;font-weight:700}.vakt-lifecycle-card .button:hover{background:#145b4e}
@media(max-width:700px){.vakt-lifecycle-page{padding:10px 12px 28px}.vakt-lifecycle-page header{padding:10px 12px}.vakt-lifecycle-page .home-logo{width:35px;height:39px}.vakt-lifecycle-page .brand-name{font-size:23px}.vakt-lifecycle-card{margin-top:24px;padding:26px 20px}.vakt-lifecycle-card h1{font-size:32px}}
"""


FYLKE_OPTIONS = ("Agder", "Akershus", "Buskerud", "Finnmark", "Innlandet", "M\u00f8re og Romsdal", "Nordland", "Oslo", "\u00d8stfold", "Rogaland", "Telemark", "Troms", "Tr\u00f8ndelag", "Vestfold", "Vestland")
REGION_THUMBNAILS = {
    "Oslo": "oslo.png", "Vestland": "vestland.png", "Akershus": "akershus.png",
    "Tr\u00f8ndelag": "trondelag.png", "Rogaland": "rogaland.png",
}

VAKT_PROFESSION_MAX_LENGTH = 120
VAKT_EMAIL_MAX_LENGTH = 254
VAKT_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
VAKT_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
VAKT_VERIFICATION_LIFETIME = timedelta(hours=48)


class VaktValidationError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def vakt_text_key(value):
    return " ".join(value.split()).casefold()


def validate_vakt_form(form):
    expected = {"profession", "county", "email"}
    if set(form) - expected or any(len(form.get(field, [])) != 1 for field in expected):
        raise VaktValidationError("invalid_form")

    profession = form["profession"][0].strip()
    if not profession or any(ord(character) < 32 or ord(character) == 127 for character in profession):
        raise VaktValidationError("invalid_profession")
    if len(profession) > VAKT_PROFESSION_MAX_LENGTH:
        raise VaktValidationError("profession_too_long")

    email = form["email"][0].strip().lower()
    if (not email or len(email) > VAKT_EMAIL_MAX_LENGTH or ".." in email
            or not VAKT_EMAIL_PATTERN.fullmatch(email)):
        raise VaktValidationError("invalid_email")

    county_key = vakt_text_key(form["county"][0])
    counties = {vakt_text_key(county): county for county in FYLKE_OPTIONS}
    county = counties.get(county_key)
    if county is None:
        raise VaktValidationError("invalid_county")

    return {
        "email": email,
        "profession_query": profession,
        "profession_query_key": vakt_text_key(profession),
        "fylke": county,
    }


def new_vakt_tokens():
    verification_token = secrets.token_urlsafe(32)
    unsubscribe_token = secrets.token_urlsafe(32)
    while unsubscribe_token == verification_token:
        unsubscribe_token = secrets.token_urlsafe(32)
    return verification_token, unsubscribe_token


def save_vakt_subscription(subscription, database=DATABASE, return_subscription=False):
    def result(status, verification_token_value, active):
        if not return_subscription:
            return status
        return {
            "status": status,
            "email": subscription["email"],
            "verification_token": verification_token_value,
            "active": active,
        }

    initialize_database(database)
    now = datetime.now(timezone.utc)
    created_at = now.isoformat()
    verification_expires_at = (now + VAKT_VERIFICATION_LIFETIME).isoformat()
    verification_token, unsubscribe_token = new_vakt_tokens()
    connection = sqlite3.connect(database, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT id, active, verified_at, unsubscribe_token FROM vakt_subscriptions "
            "WHERE email=? AND profession_query_key=? AND fylke=?",
            (subscription["email"], subscription["profession_query_key"], subscription["fylke"]),
        ).fetchone()
        if existing is not None and existing["active"] == 1:
            connection.commit()
            return result("existing_active", None, True)
        if existing is not None:
            if existing["verified_at"] is None:
                unsubscribe_token = existing["unsubscribe_token"]
            connection.execute(
                "UPDATE vakt_subscriptions SET profession_query=?, active=0, created_at=?, "
                "verified_at=NULL, verification_token=?, verification_expires_at=?, "
                "unsubscribe_token=?, last_checked_at=NULL "
                "WHERE id=?",
                (subscription["profession_query"], created_at, verification_token,
                 verification_expires_at,
                 unsubscribe_token, existing["id"]),
            )
            connection.commit()
            return result(
                "renewed" if existing["verified_at"] is not None else "pending_updated",
                verification_token,
                False,
            )
        connection.execute(
            "INSERT INTO vakt_subscriptions "
            "(email, profession_query, profession_query_key, fylke, active, created_at, verified_at, "
            "verification_token, verification_expires_at, unsubscribe_token, last_checked_at) "
            "VALUES (?, ?, ?, ?, 0, ?, NULL, ?, ?, ?, NULL)",
            (subscription["email"], subscription["profession_query"],
             subscription["profession_query_key"], subscription["fylke"], created_at,
             verification_token, verification_expires_at, unsubscribe_token),
        )
        connection.commit()
        return result("created", verification_token, False)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _vakt_mail_config():
    required = ("JOBBPEIL_SMTP_HOST", "JOBBPEIL_SMTP_PORT", "JOBBPEIL_SMTP_USER",
                "JOBBPEIL_SMTP_PASSWORD", "JOBBPEIL_MAIL_FROM", "JOBBPEIL_PUBLIC_BASE_URL")
    config = {name: os.environ.get(name, "").strip() for name in required}
    missing = [name for name in required if not config[name]]
    if missing:
        raise RuntimeError("Missing SMTP configuration: " + ", ".join(missing))
    try:
        port = int(config["JOBBPEIL_SMTP_PORT"])
    except ValueError as error:
        raise RuntimeError("Invalid JOBBPEIL_SMTP_PORT") from error
    config["JOBBPEIL_SMTP_PORT"] = port
    return config


def _send_vakt_email_message(message, config):
    with smtplib.SMTP(
            config["JOBBPEIL_SMTP_HOST"],
            config["JOBBPEIL_SMTP_PORT"],
            timeout=20,
    ) as smtp:
        smtp.ehlo()
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()
        smtp.login(config["JOBBPEIL_SMTP_USER"], config["JOBBPEIL_SMTP_PASSWORD"])
        smtp.send_message(message)


def _vakt_email_html(title, content, brand="JobbPeil"):
    """Shared email presentation; content is assembled from escaped values."""
    return (
        '<!doctype html><html lang="nb"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{e(title)}</title></head>'
        '<body style="margin:0;padding:0;background-color:#f5f6f2;color:#163e3a;'
        'font-family:Arial,Helvetica,sans-serif;font-size:16px;line-height:1.6;">'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
        'style="background-color:#f5f6f2;"><tr><td align="center" style="padding:24px 12px;">'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
        'style="max-width:600px;background-color:#ffffff;border:1px solid #d7e3e2;'
        'border-radius:18px;"><tr><td style="padding:28px 24px;">'
        f'<p style="margin:0;color:#087a61;font-size:26px;font-weight:700;">{e(brand)}</p>'
        '<p style="margin:0 0 28px;color:#587571;font-size:13px;">Finn din retning</p>'
        f'<h1 style="margin:0 0 20px;font-size:28px;line-height:1.2;">{e(title)}</h1>'
        f'{content}'
        '<p style="margin:28px 0 0;padding-top:20px;border-top:1px solid #d7e3e2;'
        'color:#587571;font-size:14px;">Med vennlig hilsen<br>'
        'JobbPeil<br>kontakt@jobbpeil.no</p>'
        '</td></tr></table></td></tr></table></body></html>'
    )


def _vakt_email_button(label, url):
    return (
        '<p style="margin:22px 0;">'
        f'<a href="{e(url)}" style="display:inline-block;background-color:#087a61;'
        'color:#ffffff;border:1px solid #087a61;border-radius:10px;padding:14px 22px;'
        f'font-weight:700;text-decoration:none;">{e(label)}</a></p>'
    )


def _vakt_email_following(profession_query, fylke):
    fields = ''.join(
        f'<p style="margin:8px 0;overflow-wrap:anywhere;"><strong>{label}:</strong><br>{e(value)}</p>'
        for label, value in (("Yrke", profession_query), ("Område", fylke)) if value
    )
    if not fields:
        return ""
    return (
        '<div style="margin:24px 0;padding:18px 20px;background-color:#edf6f1;'
        'border-radius:12px;"><h2 style="margin:0 0 12px;font-size:18px;">Du følger</h2>'
        f'{fields}</div>'
    )


def send_vakt_confirmation_email(email, verification_token, profession_query="", fylke=""):
    config = _vakt_mail_config()
    base_url = config["JOBBPEIL_PUBLIC_BASE_URL"].rstrip("/") + "/"
    confirmation_url = urljoin(base_url, "?mode=vakt_verify&token=" + quote(verification_token, safe=""))
    message = EmailMessage()
    message["From"] = "JobbPeil <" + config["JOBBPEIL_MAIL_FROM"] + ">"
    message["To"] = email
    message["Reply-To"] = config["JOBBPEIL_MAIL_FROM"]
    message["Subject"] = "Bekreft JobbPeil Vakt"
    if profession_query and fylke:
        message.replace_header("Subject", f"Bekreft JobbPeil Vakt – {profession_query} i {fylke}")
    following = [f"{label}: {value}" for label, value in
                 (("Yrke", profession_query), ("Område", fylke)) if value]
    intro = "Du er nesten klar.\nBekreft e-postadressen din for å aktivere JobbPeil Vakt."
    note = ("JobbPeil Vakt følger med på nye relevante stillinger for deg.\n"
            "Du får bare e-post når det finnes nye stillinger å vise.")
    ignore = "Hvis du ikke ba om denne JobbPeil Vakt, kan du ignorere denne e-posten."
    lines = ["JobbPeil", "Finn din retning", "", "Bekreft JobbPeil Vakt", "", "Hei!", "", intro, ""]
    if following:
        lines.extend(("Du følger", "", *following, ""))
    lines.extend(("Bekreft JobbPeil Vakt:", confirmation_url, "", note, "", ignore, "",
                  "Med vennlig hilsen", "JobbPeil", "kontakt@jobbpeil.no"))
    message.set_content("\n".join(lines), charset="utf-8")
    content = (
        f'<p style="margin:0 0 16px;">Hei!</p><p>{e(intro).replace(chr(10), "<br>")}</p>'
        + _vakt_email_following(profession_query, fylke)
        + _vakt_email_button("Bekreft JobbPeil Vakt", confirmation_url)
        + f'<p style="color:#587571;font-size:14px;">{e(note).replace(chr(10), "<br>")}</p>'
        + f'<p style="color:#587571;font-size:14px;">{e(ignore)}</p>'
    )
    message.add_alternative(_vakt_email_html("Bekreft JobbPeil Vakt", content),
                            subtype="html", charset="utf-8")
    _send_vakt_email_message(message, config)


def send_vakt_job_alert_email(subscription, candidates):
    candidates = list(candidates or [])[:4]
    if not candidates:
        return False

    config = _vakt_mail_config()
    base_url = config["JOBBPEIL_PUBLIC_BASE_URL"].rstrip("/") + "/"
    unsubscribe_url = urljoin(
        base_url,
        "?mode=vakt_unsubscribe&token="
        + quote(subscription["unsubscribe_token"], safe=""),
    )
    lines = [
        "JobbPeil Vakt",
        "",
        "Nye jobbmuligheter",
        "",
        "Hei!",
        "",
        "Vi fant nye stillinger som kan passe med det du følger.",
        "",
        "Yrke: " + subscription["profession_query"],
        "Område: " + subscription["fylke"],
        "",
    ]
    cards = []
    for number, candidate in enumerate(candidates, start=1):
        lines.append(f'{number}. {candidate["title"]}')
        card = [f'<h2 style="margin:0 0 12px;font-size:20px;line-height:1.3;'
                f'overflow-wrap:anywhere;">{e(candidate["title"])}</h2>']
        if candidate.get("employer"):
            lines.append("Arbeidsgiver: " + candidate["employer"])
            card.append(f'<p style="margin:8px 0;">{e(candidate["employer"])}</p>')
        location_labels = []
        for location in candidate.get("locations") or []:
            values = list(dict.fromkeys(
                str(location.get(key) or "").strip()
                for key in ("municipal", "city", "county")
                if str(location.get(key) or "").strip()
            ))
            if values:
                location_labels.append(", ".join(values))
        if location_labels:
            location_text = "; ".join(dict.fromkeys(location_labels))
            lines.append("Sted: " + location_text)
            card.append(f'<p style="margin:8px 0;color:#587571;">📍 {e(location_text)}</p>')
        if candidate.get("published_date"):
            lines.append("Publisert: " + candidate["published_date"])
            card.append(f'<p style="margin:8px 0;color:#587571;font-size:14px;">'
                        f'Publisert: {e(candidate["published_date"])}</p>')
        detail_url = candidate["detail_url"]
        detail_parts = urlsplit(detail_url)
        absolute_detail_url = (
            detail_url
            if detail_parts.scheme in ("http", "https") and detail_parts.netloc
            else urljoin(base_url, detail_url)
        )
        lines.extend((absolute_detail_url, ""))
        card.append(_vakt_email_button("Se stillingen", absolute_detail_url))
        cards.append('<div style="margin:18px 0;padding:20px;border:1px solid #d7e3e2;'
                     'border-radius:12px;background-color:#ffffff;">' + ''.join(card) + '</div>')
    why = ("Du får denne e-posten fordi JobbPeil Vakt følger "
           f'{subscription["profession_query"]} i {subscription["fylke"]} for deg.')
    lines.extend((
        why,
        "",
        "Meld deg av JobbPeil Vakt:",
        unsubscribe_url,
        "",
        "Med vennlig hilsen",
        "JobbPeil",
        "kontakt@jobbpeil.no",
    ))

    message = EmailMessage()
    message["From"] = "JobbPeil <" + config["JOBBPEIL_MAIL_FROM"] + ">"
    message["To"] = subscription["email"]
    message["Reply-To"] = config["JOBBPEIL_MAIL_FROM"]
    count = len(candidates)
    jobs_label = "ny jobb" if count == 1 else "nye jobber"
    message["Subject"] = (f'{count} {jobs_label} for {subscription["profession_query"]} '
                          f'i {subscription["fylke"]}')
    message.set_content("\n".join(lines), charset="utf-8")
    content = (
        '<p>Vi fant nye stillinger som kan passe med det du følger.</p>'
        + _vakt_email_following(subscription["profession_query"], subscription["fylke"])
        + ''.join(cards)
        + '<div style="margin:24px 0;padding:18px 20px;background-color:#edf6f1;'
        + f'border-radius:12px;color:#587571;font-size:14px;"><p>{e(why)}</p>'
        + f'<p><a href="{e(unsubscribe_url)}" style="color:#087a61;text-decoration:underline;">'
        + 'Meld deg av JobbPeil Vakt</a></p></div>'
    )
    message.add_alternative(_vakt_email_html("Nye jobbmuligheter", content, "JobbPeil Vakt"),
                            subtype="html", charset="utf-8")
    _send_vakt_email_message(message, config)
    return True


def valid_vakt_token_format(token):
    return isinstance(token, str) and VAKT_TOKEN_PATTERN.fullmatch(token) is not None


def vakt_verification_pending(token, database=DATABASE):
    if not valid_vakt_token_format(token):
        return False
    database_uri = Path(database).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(database_uri, uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        subscription = connection.execute(
            "SELECT active, verified_at, verification_expires_at "
            "FROM vakt_subscriptions WHERE verification_token=?",
            (token,),
        ).fetchone()
    if subscription is None or subscription[0] != 0 or subscription[1] is not None:
        return False
    try:
        expires_at = datetime.fromisoformat(subscription[2])
    except (TypeError, ValueError):
        return False
    return expires_at.tzinfo is not None and expires_at.astimezone(timezone.utc) > datetime.now(timezone.utc)


def verify_vakt_subscription(token, database=DATABASE):
    if not valid_vakt_token_format(token):
        return False
    initialize_database(database)
    now = datetime.now(timezone.utc)
    connection = sqlite3.connect(database, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("BEGIN IMMEDIATE")
        subscription = connection.execute(
            "SELECT id, active, verified_at, verification_expires_at "
            "FROM vakt_subscriptions WHERE verification_token=?",
            (token,),
        ).fetchone()
        if subscription is None or subscription["active"] != 0 or subscription["verified_at"] is not None:
            connection.rollback()
            return False
        try:
            expires_at = datetime.fromisoformat(subscription["verification_expires_at"])
        except (TypeError, ValueError):
            connection.rollback()
            return False
        if expires_at.tzinfo is None or expires_at.astimezone(timezone.utc) <= now:
            connection.rollback()
            return False
        rotated_token = secrets.token_urlsafe(32)
        connection.execute(
            "UPDATE vakt_subscriptions SET active=1, verified_at=?, verification_token=?, "
            "verification_expires_at=NULL WHERE id=? AND verification_token=?",
            (now.isoformat(), rotated_token, subscription["id"], token),
        )
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def unsubscribe_vakt_subscription(token, database=DATABASE):
    if not valid_vakt_token_format(token):
        return False
    initialize_database(database)
    connection = sqlite3.connect(database, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("BEGIN IMMEDIATE")
        subscription = connection.execute(
            "SELECT id FROM vakt_subscriptions WHERE unsubscribe_token=?",
            (token,),
        ).fetchone()
        if subscription is None:
            connection.rollback()
            return False
        connection.execute(
            "UPDATE vakt_subscriptions SET active=0 WHERE id=? AND unsubscribe_token=?",
            (subscription["id"], token),
        )
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def mark_vakt_jobs_sent(subscription_id, vacancy_uuids, sent_at=None, database=DATABASE):
    """Record vacancies only after a future digest has been delivered successfully."""
    if isinstance(subscription_id, bool) or not isinstance(subscription_id, int) or subscription_id < 1:
        raise ValueError("subscription_id must be a positive integer")
    unique_uuids = list(dict.fromkeys(
        uuid for uuid in vacancy_uuids if isinstance(uuid, str) and uuid.strip()
    ))
    if not unique_uuids:
        return 0
    if sent_at is None:
        sent_at = datetime.now(timezone.utc).isoformat()
    if not isinstance(sent_at, str) or not sent_at:
        raise ValueError("sent_at must be a non-empty timestamp string")

    initialize_database(database)
    connection = sqlite3.connect(database, timeout=10)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        before = connection.total_changes
        connection.executemany(
            "INSERT OR IGNORE INTO vakt_sent_jobs (subscription_id, vacancy_uuid, sent_at) "
            "VALUES (?, ?, ?)",
            ((subscription_id, uuid, sent_at) for uuid in unique_uuids),
        )
        inserted = connection.total_changes - before
        connection.commit()
        return inserted
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_vakt_candidates(subscription, limit=4, database=DATABASE):
    """Return unsent, ranked vacancies published at or after subscription activation.

    Candidates are not marked sent here: callers must call ``mark_vakt_jobs_sent``
    only after a digest email has been sent successfully.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")
    try:
        subscription_id = subscription["id"]
    except (KeyError, TypeError, IndexError):
        return []
    if isinstance(subscription_id, bool) or not isinstance(subscription_id, int) or subscription_id < 1:
        return []

    initialize_database(database)
    connection = sqlite3.connect(database)
    try:
        connection.row_factory = sqlite3.Row
        current = connection.execute(
            "SELECT id, profession_query, fylke, verified_at FROM vakt_subscriptions "
            "WHERE id=? AND active=1 AND verified_at IS NOT NULL",
            (subscription_id,),
        ).fetchone()
        if current is None:
            return []
        try:
            verified_at = datetime.fromisoformat(current["verified_at"])
            # Verification writes aware UTC ISO strings. Never guess a timezone
            # for malformed/legacy naive values or substitute created_at.
            if verified_at.tzinfo is None or verified_at.utcoffset() is None:
                return []
            verified_at = verified_at.astimezone(timezone.utc)
        except (TypeError, ValueError, OverflowError):
            return []
        sent_uuids = {
            row[0] for row in connection.execute(
                "SELECT vacancy_uuid FROM vakt_sent_jobs WHERE subscription_id=?",
                (subscription_id,),
            )
        }
    finally:
        connection.close()

    # Reuse Search's ACTIVE matching/order. Activation is the only time boundary;
    # last_checked_at must not exclude unsent vacancies ingested later.
    matches, published_dates = active_matches(current["profession_query"], current["fylke"])
    candidates = []
    production_relevance_threshold = 10
    for vacancy_uuid, (ad, locations, reasons, score) in matches.items():
        if vacancy_uuid in sent_uuids or ad.get("status") != "ACTIVE":
            continue
        if score < production_relevance_threshold:
            continue
        regional_locations = [
            location for location in locations
            if vakt_text_key(location.get("county") or "") == vakt_text_key(current["fylke"])
        ]
        if not regional_locations:
            continue
        published_at = published_dates.get(vacancy_uuid)
        # job_versions.published stores integer UTC microseconds, not seconds
        # or a display date. Missing/invalid values cannot establish eligibility.
        if not isinstance(published_at, int) or isinstance(published_at, bool):
            continue
        try:
            published_utc = EPOCH + timedelta(microseconds=published_at)
        except (ValueError, OverflowError):
            continue
        if published_utc < verified_at:
            continue
        candidates.append({
            "vacancy_uuid": vacancy_uuid,
            "title": ad.get("title") or ad.get("jobtitle") or "Uten tittel",
            "employer": (ad.get("employer") or {}).get("name"),
            "fylke": current["fylke"],
            "locations": regional_locations,
            "published_at": published_at,
            "published_date": format_published_short(published_at) if published_at is not None else None,
            "relevance": {"score": score, "reasons": dict(reasons)},
            "detail_url": internal_url({}, q=current["profession_query"], fylke=current["fylke"], job=vacancy_uuid),
        })
        if len(candidates) >= limit:
            break
    return candidates


def vakt_header(params, lang):
    preserve = lang == "en" or "lang" in params
    home = local_nav_url(lang=lang, include_lang=preserve)
    search = local_nav_url(lang=lang, fragment="profession", include_lang=preserve)
    explore = local_nav_url("explore", lang, include_lang=preserve)
    about = local_nav_url("about", lang, include_lang=preserve)
    vakt = local_nav_url("vakt", lang, include_lang=preserve)
    other_lang = "en" if lang == "no" else "no"
    labels = ({"home": "Hjem", "jobs": "Søk jobber"} if lang == "no" else {"home": "Home", "jobs": "Search jobs"})
    brand = f'<a class="vakt-brand" href="{e(home)}">{BRAND}</a>'
    nav = f'<a href="{e(home)}">{e(labels["home"])}</a><a href="{e(search)}">{e(labels["jobs"])}</a><a href="{e(explore)}">{e(t(lang, "nav.explore"))}</a><a class="active" href="{e(vakt)}" aria-current="page">JobbPeil Vakt</a><a href="{e(about)}">{e(t(lang, "nav.about"))}</a>'
    menu_icon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg>'
    mobile = f'<details class="vakt-mobile-menu"><summary>{menu_icon}<span>{e(t(lang, "nav.menu"))}</span></summary><nav class="vakt-mobile-links" aria-label="{e(t(lang, "nav.open_menu"))}">{nav}</nav></details>'
    language = f'<details class="vakt-language"><summary>{lang.upper()} <span aria-hidden="true">⌄</span></summary><div class="vakt-language-options"><span>{e(t(lang, "nav.norwegian" if lang == "no" else "nav.english"))}</span><a href="{e(language_change(params, other_lang))}">{e(t(lang, "nav.english" if lang == "no" else "nav.norwegian"))}</a></div></details>'
    return f'<header class="vakt-product-header">{brand}<nav class="vakt-main-nav" aria-label="{e(t(lang, "nav.open_menu"))}">{nav}</nav><div class="vakt-header-actions">{language}</div>{mobile}</header>'


def vakt_page(params=None, lang="no", submitted=False):
    params = params or {}
    lang = normalize_lang(lang)
    tr = lambda key: e(t(lang, key))
    get_param = lambda key: str(params.get(key, [""])[-1]) if params.get(key) else ""
    profession_value = get_param("vakt_profession").strip()[:VAKT_PROFESSION_MAX_LENGTH]
    requested_county = get_param("vakt_county")
    county_value = next((county for county in FYLKE_OPTIONS if county == requested_county), "")
    notice_html = ""
    notice_code = get_param("vakt_notice")
    if notice_code == "confirmation_sent" and get_param("vakt_email"):
        notice_html = (
            f'<div class="vakt-form-notice" role="status"><strong>{tr("vakt.confirmation_sent_title")}</strong>'
            f'<p>{e(t(lang, "vakt.confirmation_sent_copy", email=get_param("vakt_email")))}</p></div>'
        )
    elif notice_code == "registered":
        notice_html = (f'<div class="vakt-form-notice" role="status"><strong>{tr("vakt.registered_title")}</strong>'
                       f'<p>{tr("vakt.registered_copy")}</p></div>')
    else:
        error_code = get_param("vakt_error")
        error_keys = {
            "invalid_email": "vakt.error_invalid_email",
            "invalid_profession": "vakt.error_invalid_profession",
            "profession_too_long": "vakt.error_profession_too_long",
            "invalid_county": "vakt.error_invalid_county",
            "invalid_form": "vakt.error_invalid_form",
            "unavailable": "vakt.error_unavailable",
            "email_delivery": "vakt.error_email_delivery",
        }
        if error_code in error_keys:
            notice_html = f'<div class="vakt-form-notice error" role="alert"><p>{tr(error_keys[error_code])}</p></div>'
    preserve = lang == "en" or "lang" in params
    route = local_nav_url("vakt", lang, include_lang=preserve)
    explore = local_nav_url("explore", lang, include_lang=preserve)
    bell = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 9a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/></svg>'
    envelope = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></svg>'
    briefcase = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V4h8v3m-13 5h18M10 12v3h4v-3"/></svg>'
    search_icon = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6"/><path d="m16 16 4 4"/></svg>'
    pin = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 10c0 5-8 11-8 11S4 15 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/></svg>'
    chevron = '<svg class="vakt-select-chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="m7 10 5 5 5-5"/></svg>'
    benefits = (("vakt.benefit_1_title", "vakt.benefit_1_copy", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m13 2-9 12h7l-1 8 10-13h-7z"/></svg>'), ("vakt.benefit_2_title", "vakt.benefit_2_copy", '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="m18 6 3-3"/></svg>'), ("vakt.benefit_3_title", "vakt.benefit_3_copy", envelope))
    benefit_html = ''.join(f'<div class="vakt-benefit"><span>{icon}</span><div><strong>{tr(title)}</strong><small>{tr(copy)}</small></div></div>' for title, copy, icon in benefits)
    counties = ''.join(f'<option value="{e(county)}"{" selected" if county == county_value else ""}>{e(county)}</option>' for county in FYLKE_OPTIONS)
    alert_meta = (("vakt.alert_1", "Agder fylkeskommune", "i dag"), ("vakt.alert_2", "REMA 1000", "i går"), ("vakt.alert_3", "Compass Group", "2 dager siden")) if lang == "no" else (("vakt.alert_1", "Agder County Municipality", "today"), ("vakt.alert_2", "REMA 1000", "yesterday"), ("vakt.alert_3", "Compass Group", "2 days ago"))
    alerts = ''.join(f'<div class="vakt-alert"><span>{briefcase}</span><div><strong>{tr(title)}</strong><small>{e(employer)}</small></div><time>{e(when)}</time></div>' for title, employer, when in alert_meta)
    steps = ''.join(f'<article class="vakt-step"><b>{number}</b><div><strong>{tr(title)}</strong><p>{tr(copy)}</p></div></article>' for number, title, copy in ((1, "vakt.step_1_title", "vakt.step_1_copy"), (2, "vakt.step_2_title", "vakt.step_2_copy"), (3, "vakt.step_3_title", "vakt.step_3_copy")))
    speech = "Jeg holder<br>øye for deg!" if lang == "no" else "I keep an eye<br>out for you!"
    note = "Nye muligheter<br>&ndash; rett til deg!" if lang == "no" else "New opportunities<br>&ndash; straight to you!"
    perks = (("Gratis å bruke", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 11c0 5.6-7 10-7 10Z"/></svg>'), ("Ingen forpliktelser", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 5 6v5c0 5 3 8 7 10 4-2 7-5 7-10V6l-7-3Z"/><path d="m9 12 2 2 4-4"/></svg>'), ("Du kan når som helst melde deg av", '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.9 4.9 7 7M17 17l2.1 2.1M2 12h3M19 12h3M4.9 19.1 7 17M17 7l2.1-2.1"/></svg>')) if lang == "no" else (("Free to use", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 11c0 5.6-7 10-7 10Z"/></svg>'), ("No obligation", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 5 6v5c0 5 3 8 7 10 4 0 7-5 7-10V6l-7-3Z"/><path d="m9 12 2 2 4-4"/></svg>'), ("Unsubscribe at any time", '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.9 4.9 7 7M17 17l2.1 2.1M2 12h3M19 12h3M4.9 19.1 7 17M17 7l2.1-2.1"/></svg>'))
    perks_html = ''.join(f'<span class="vakt-perk">{icon}{e(label)}</span>' for label, icon in perks)
    body = site_header("vakt", params, lang) + f'''<div class="vakt-grid"><section class="vakt-intro"><span class="vakt-badge">{bell}{tr("vakt.badge")}</span><h1>{tr("vakt.title")}</h1><h2>{tr("vakt.lead")}</h2><p>{tr("vakt.intro")}</p><div class="vakt-benefits">{benefit_html}</div></section><section class="vakt-form-card"><h2>{tr("vakt.form_title")}</h2><p>{tr("vakt.form_helper")}</p><form method="post" action="{e(route)}"><div class="vakt-field"><label for="vakt-profession">{tr("vakt.profession")}</label><div class="search vakt-profession-search">{search_icon}<input id="vakt-profession" name="profession" data-autocomplete autocomplete="off" placeholder="{tr("vakt.profession_placeholder")}" required></div></div><a class="vakt-explore-link" href="{e(explore)}">{tr("vakt.explore_help")} &rarr;</a><div class="vakt-field"><label for="vakt-county">{tr("vakt.county")}</label>{pin}{chevron}<select id="vakt-county" name="county" required><option value="">{tr("vakt.county_placeholder")}</option>{counties}</select></div><div class="vakt-field"><label for="vakt-email">{tr("vakt.email")}</label>{envelope}<input id="vakt-email" name="email" type="email" placeholder="{tr("vakt.email_placeholder")}" required></div><button type="submit">{tr("vakt.submit")} <span aria-hidden="true">&rarr;</span></button><p class="vakt-free-note">{tr("vakt.free_note")}</p></form></section><aside class="vakt-info"><div class="vakt-robot-stage"><figure class="vakt-robot-figure"><img src="/static/jobbpeil-vakt-mascot.png" alt="" aria-hidden="true"></figure><p class="vakt-speech">{speech}</p><span class="vakt-accent" aria-hidden="true"></span></div><section class="vakt-alerts"><h3>{envelope}{tr("vakt.alerts_title")}</h3>{alerts}</section><p class="vakt-note">{note}</p></aside></div><section class="vakt-steps"><h2>{tr("vakt.steps_title")}</h2>{steps}</section><section class="vakt-perks">{perks_html}<span class="vakt-swoosh">{"Flere muligheter.<br>En enklere hverdag." if lang == "no" else "More opportunities.<br>A simpler everyday life."}</span></section>'''
    if notice_html:
        body = body.replace('<form method="post"', notice_html + '<form method="post"', 1)
    profession_attributes = f'name="profession" maxlength="{VAKT_PROFESSION_MAX_LENGTH}"'
    if profession_value:
        profession_attributes += f' value="{e(profession_value)}"'
    body = body.replace('name="profession"', profession_attributes, 1)
    body = body.replace('name="email" type="email"', f'name="email" type="email" maxlength="{VAKT_EMAIL_MAX_LENGTH}"', 1)
    return page_document(lang, t(lang, "vakt.page_title"), VAKT_STYLE, "vakt-page", body, params)


def vakt_lifecycle_page(mode, success, lang="no"):
    lang = normalize_lang(lang)
    safe_params = {"mode": [mode]}
    if lang == "en":
        safe_params["lang"] = [lang]
    prefix = "vakt.verify" if mode == "vakt_verify" else "vakt.unsubscribe"
    state = "success" if success else "invalid"
    title = e(t(lang, f"{prefix}_{state}_title"))
    copy = e(t(lang, f"{prefix}_{state}_copy"))
    home = local_nav_url(lang=lang, include_lang=lang == "en")
    icon = "&#10003;" if success else "!"
    body = site_header("vakt", safe_params, lang)
    analytics_marker = ' data-analytics-event="vakt_verified"' if mode == "vakt_verify" and success else ""
    body += (f'<section class="vakt-lifecycle-card{"" if success else " invalid"}"{analytics_marker}>'
             f'<span class="vakt-lifecycle-icon" aria-hidden="true">{icon}</span>'
             f'<h1>{title}</h1><p>{copy}</p>'
             f'<a class="button" href="{e(home)}">{e(t(lang, "vakt.lifecycle_home"))}</a></section>')
    return page_document(lang, title, VAKT_LIFECYCLE_STYLE, "vakt-lifecycle-page", body, safe_params)


def vakt_verify_page(params=None, lang="no"):
    params = params or {}
    tokens = params.get("token", [])
    token = tokens[0] if len(tokens) == 1 else ""
    if not vakt_verification_pending(token):
        return vakt_lifecycle_page("vakt_verify", False, lang)
    lang = normalize_lang(lang)
    safe_params = {"mode": ["vakt_verify"]}
    if lang == "en":
        safe_params["lang"] = [lang]
    action = local_nav_url("vakt_verify", lang, include_lang=lang == "en")
    title = "Confirm JobbPeil Vakt" if lang == "en" else "Bekreft JobbPeil Vakt"
    copy = "Confirm that you want to receive alerts about relevant new jobs." if lang == "en" else "Bekreft at du vil motta varsler om nye relevante stillinger."
    button = "Confirm Vakt" if lang == "en" else "Bekreft Vakt"
    body = site_header("vakt", safe_params, lang)
    body += ('<section class="vakt-lifecycle-card vakt-verify-confirmation">'
             f'<h1>{e(title)}</h1><p>{e(copy)}</p>'
             f'<form method="post" action="{e(action)}"><input type="hidden" name="token" value="{e(token)}">'
             f'<button type="submit">{e(button)}</button></form></section>')
    return page_document(lang, title, VAKT_LIFECYCLE_STYLE, "vakt-lifecycle-page", body, safe_params)


def vakt_unsubscribe_page(params=None, lang="no"):
    params = params or {}
    tokens = params.get("token", [])
    token = tokens[0] if len(tokens) == 1 else ""
    return vakt_lifecycle_page("vakt_unsubscribe", unsubscribe_vakt_subscription(token), lang)


def page_document(lang, title, css, page_class, body, params=None):
    html_lang = "en" if normalize_lang(lang) == "en" else "nb"
    analytics = ('<script async src="https://www.googletagmanager.com/gtag/js?id=G-KQ0F39GDTF"></script>'
                 '<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}'
                 'gtag("js",new Date());const gaReferrer=document.referrer?new URL(document.referrer).origin+new URL(document.referrer).pathname:"";'
                 'gtag("config","G-KQ0F39GDTF",{page_location:window.location.origin+window.location.pathname,page_referrer:gaReferrer});</script>')
    return '<!doctype html><html lang="' + html_lang + '"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + e(title) + '</title><style>' + CSS + css + APPROVED_UI_STYLE + '</style>' + analytics + '</head><body><main class="' + page_class + '" data-caption="' + e(t(lang, 'footer.tagline')) + '">' + body + site_footer(lang, params) + '</main><script>' + SCRIPT + '</script></body></html>'


def about_page(params=None, lang="no"):
    params = params or {}
    lang = normalize_lang(lang)
    tr = lambda key: e(t(lang, key))
    preserve = lang == "en" or "lang" in params
    search = local_nav_url(lang=lang, fragment="profession", include_lang=preserve)
    explore = local_nav_url("explore", lang, include_lang=preserve)
    contact = local_nav_url("kontakt", lang, include_lang=preserve)
    privacy = local_nav_url("personvern", lang, include_lang=preserve)
    body = site_header("about", params, lang) + f'''<section class="about-hero"><h1>{tr("about.title")}</h1><p class="lead">{tr("about.lead")}</p><p class="intro">{tr("about.intro")}</p><div class="about-hero-actions"><a class="button primary" href="{e(explore)}">{tr("about.explore_cta")}&nbsp;&rarr;</a><a class="button" href="{e(search)}">{tr("about.search_cta")}&nbsp;&rarr;</a></div><p class="about-hero-note">{t(lang, "about.note")}</p></section>
<section class="about-section"><h2><span class="about-heading-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.9 4.9 7 7M17 17l2.1 2.1M2 12h3M19 12h3M4.9 19.1 7 17M17 7l2.1-2.1"/></svg></span>{tr("about.how_title")}</h2><p class="section-intro">{tr("about.how_intro")}</p><div class="about-paths"><article class="about-path"><span class="about-card-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6"/><path d="m16 16 5 5"/></svg></span><h3><small>01</small> {tr("about.step_search_title")}</h3><p>{tr("about.step_search_copy")}</p><a class="button" href="{e(search)}">{tr("about.step_search_cta")}&nbsp;&rarr;</a></article><article class="about-path"><span class="about-card-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8"/><path d="m15.5 8.5-2.3 4.7-4.7 2.3 2.3-4.7 4.7-2.3Z"/></svg></span><h3><small>02</small> {tr("about.step_explore_title")}</h3><p>{tr("about.step_explore_copy")}</p><a class="button" href="{e(explore)}">{tr("about.step_explore_cta")}&nbsp;&rarr;</a></article><article class="about-path about-insight"><span class="about-card-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20V11M10 20V4M16 20v-7M22 20H2"/></svg></span><h3><small>03</small> {tr("about.step_insight_title")}</h3><p>{tr("about.step_insight_copy")}</p></article></div></section>
<div class="about-data-grid"><section class="about-section"><h2><span class="about-heading-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><ellipse cx="12" cy="5" rx="7" ry="3"/><path d="M5 5v7c0 1.7 3.1 3 7 3s7-1.3 7-3V5M5 12v7c0 1.7 3.1 3 7 3s7-1.3 7-3v-7"/></svg></span>{tr("about.data_title")}</h2><p class="section-intro">{tr("about.data_intro")}</p><div class="about-sources"><article class="about-source"><span class="about-source-mark nav">NAV</span><span class="status">{tr("about.active_source")}</span><h3>{tr("about.nav_source_title")}</h3><p>{tr("about.nav_source_copy")}</p><span class="about-source-link">{tr("about.nav_source_link")}&nbsp;&rarr;</span></article><article class="about-source soon"><span class="about-source-mark ssb">SSB</span><span class="status">{tr("about.coming_soon")}</span><h3>{tr("about.ssb_title")}</h3><p>{tr("about.ssb_copy")}</p></article></div></section><section class="about-section about-why"><h2><span class="about-heading-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 11c0 5.6-7 10-7 10Z"/></svg></span>{tr("about.why_title")}</h2><p class="section-intro">{tr("about.why_intro")}</p><ul class="about-benefits">{''.join(f'<li>{tr("about.benefit_" + str(i))}</li>' for i in range(1, 6))}</ul><p class="about-why-copy">{tr("about.mission")}</p></section></div>
<section class="about-small-grid"><a class="about-small-card about-small-link" href="{e(contact)}"><span class="about-card-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></svg></span><h3>{tr("about.contact_title")}</h3><p>{tr("about.contact_copy")}</p></a><a class="about-small-card about-small-link" href="{e(privacy)}"><span class="about-card-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 5 6v5c0 5 3 8 7 10 4-2 7-5 7-10V6l-7-3Z"/><path d="M9 11h6v5H9zM10 11V9a2 2 0 0 1 4 0v2"/></svg></span><h3>{tr("about.privacy_title")}</h3><p>{tr("about.privacy_copy")}</p></a><article class="about-small-card"><span class="about-card-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21V10M12 14c-5 0-7-3-8-7 5 0 8 2 8 7ZM12 11c2-5 5-7 9-7-1 5-4 7-9 7Z"/></svg></span><h3>{tr("about.future_title")}</h3><p>{tr("about.future_copy")}</p></article></section>'''
    return page_document(lang, t(lang, "about.page_title"), ABOUT_STYLE, "about-page", body, params)


def privacy_page(params=None, lang="no"):
    params = params or {}
    lang = normalize_lang(lang)
    tr = lambda key: e(t(lang, key))
    items = ''.join(f'<li>{tr(key)}</li>' for key in ("privacy.cv", "privacy.applications", "privacy.profiles", "privacy.passwords", "privacy.payment"))
    body = site_header("", params, lang) + f'''<section class="privacy-hero"><h1>{tr("privacy.title")}</h1><p>{tr("privacy.lead")}</p></section><div class="privacy-content"><section class="privacy-section"><h2>{tr("privacy.uses_title")}</h2><p>{tr("privacy.uses_copy_1")}</p><p>{tr("privacy.uses_copy_2")}</p></section><section class="privacy-section"><h2>{tr("privacy.no_storage_title")}</h2><p>{tr("privacy.no_storage_intro")}</p><p>{tr("privacy.no_storage_lead")}</p><ul>{items}</ul></section><div class="privacy-cards"><section class="privacy-section"><h2>{tr("privacy.external_title")}</h2><p>{tr("privacy.external_copy_1")}</p><p>{tr("privacy.external_copy_2")}</p></section><section class="privacy-section"><h2>{tr("privacy.technical_title")}</h2><p>{tr("privacy.technical_copy_1")}</p><p>{tr("privacy.technical_copy_2")}</p></section></div><section class="privacy-section"><h2>{tr("privacy.sources_title")}</h2><p>{tr("privacy.sources_copy_1")}</p><p>{tr("privacy.sources_copy_2")}</p></section><section class="privacy-section"><h2>{tr("privacy.contact_title")}</h2><p>{tr("privacy.contact_copy")}</p><p><a href="mailto:kontakt@jobbpeil.no">kontakt@jobbpeil.no</a></p></section><p class="privacy-updated">{tr("privacy.updated")}</p></div>'''
    return page_document(lang, t(lang, "privacy.page_title"), PRIVACY_STYLE, "privacy-page", body, params)


def contact_page(params=None, lang="no"):
    params = params or {}
    lang = normalize_lang(lang)
    tr = lambda key: e(t(lang, key))
    body = site_header("", params, lang) + f'''<section class="contact-card"><span class="contact-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></svg></span><h1>{tr("contact.title")}</h1><p>{tr("contact.copy_1")}</p><p>{tr("contact.copy_2")}</p><a class="contact-email" href="mailto:kontakt@jobbpeil.no">kontakt@jobbpeil.no</a><br><a class="contact-send" href="mailto:kontakt@jobbpeil.no">{tr("contact.cta")}</a></section>'''
    return page_document(lang, t(lang, "contact.page_title"), CONTACT_STYLE, "contact-page", body, params)


def explore_page(params, lang="no"):
    lang = normalize_lang(lang)
    preserve_lang = lang == "en" or "lang" in params
    get = lambda key: params.get(key, [''])[0]
    answers = {key: get(key) for key in QUESTIONS}
    body = site_header('explore', params, lang) + '<h1>Utforsk mulige jobber</h1>'
    body += '<p class="explore-intro">Svar på fem korte spørsmål, så finner vi reelle annonser du kan vurdere. Les kravene i hver annonse – forslagene garanterer ikke at du er kvalifisert.</p>'
    valid = all(answers[key] in dict(options) for key, (_, options) in QUESTIONS.items())
    groups = {}
    if not valid:
        body += '<form method="get" class="explore-form"><input type="hidden" name="mode" value="explore">' + ('<input type="hidden" name="lang" value="' + lang + '">' if preserve_lang else '') + '<fieldset><legend>Litt om deg og n\u00e5r du kan jobbe</legend>'
        for key, (label, options) in QUESTIONS.items():
            body += f'<p><label for="{key}">{e(label)}</label><select id="{key}" name="{key}" required><option value="">Velg</option>'
            body += ''.join(f'<option value="{value}"'+(' selected' if answers[key] == value else '')+f'>{e(text)}</option>' for value, text in options) + '</select></p>'
        body += '</fieldset><button>Se mulige retninger</button></form>'
    else:
        groups, counts = cached_explore_candidates(
            active_jobs_source_version(), tuple((key, answers[key]) for key in QUESTIONS))
        base = dict(mode='explore', **answers)
        if preserve_lang:
            base['lang'] = lang
        url = lambda **extra: '/?' + urlencode(dict(base, **extra))
        page_params = dict(base, **params)
        page_url = lambda **extra: '/?' + urlencode(
            {key: value for key, value in dict(page_params, **extra).items() if value is not None}, doseq=True)
        direction = get('direction')
        body += '<p><a href="/?mode=explore">← Endre svarene</a></p>'
        if direction in groups:
            label = DIRECTIONS[direction][0]
            items = groups[direction]
            place_counts = {}
            item_places = {}
            for uid, ad, *_ in items:
                places = set()
                for location in ad.get('workLocations', []):
                    place = str(location.get('municipal') or location.get('city') or '').strip()
                    if place:
                        places.add(place)
                item_places[uid] = {place.casefold() for place in places}
                for place in places:
                    key = place.casefold()
                    entry = place_counts.setdefault(key, {'name': place, 'count': 0})
                    entry['count'] += 1
            requested_place = get('sted').strip().casefold()
            selected_place = place_counts.get(requested_place)
            selected_key = requested_place if selected_place else ''
            shown_items = [item for item in items if not selected_key or selected_key in item_places[item[0]]]
            total_count = len(shown_items)
            total_pages = max((total_count + EXPLORE_PAGE_SIZE - 1) // EXPLORE_PAGE_SIZE, 1)
            try:
                page = max(int(get('page') or '1'), 1)
            except (TypeError, ValueError):
                page = 1
            page = min(page, total_pages)
            chosen = next((item for item in items if item[0] == get('job')), None)
            if get('job'):
                if chosen:
                    ad = chosen[1]
                    county = next((loc.get('county') for loc in ad.get('workLocations', []) if loc.get('county')), '')
                    body = site_header('explore', params, lang)
                    body += job_detail(label, county, chosen[0], return_url=page_url(page=page, job=None),
                                       status=explore_compatibility(chosen[2], answers), lang=lang, preserve_lang=preserve_lang)
                else:
                    body += '<p>Annonsen finnes ikke blant disse forslagene.</p>'
            else:
                page_items = shown_items[(page - 1) * EXPLORE_PAGE_SIZE:page * EXPLORE_PAGE_SIZE]
                place_entries = sorted(place_counts.values(), key=lambda entry: (-entry['count'], entry['name'].casefold()))
                visible_places, extra_places = place_entries[:8], place_entries[8:]
                body = site_header('explore', params, lang)
                body += f'<p class="back-link"><a href="{e(url())}">← Tilbake til resultater</a></p>'
                body += f'<h1 class="vacancy-direction-title">Stillinger innen {e(label.lower())}</h1>'
                body += '<p class="explore-intro">Vi har funnet relevante stillinger som passer valgene dine. Her ser du de neste og mest relevante annonsene. Klikk på en stilling for å lese mer.</p>'
                body += f'<p class="result-count">{total_count} annonser å undersøke nærmere.</p><div class="explore-vacancy-layout"><section class="explore-vacancy-results">'
                if selected_place:
                    body += f'<p class="place-result-note">{e(label)} i {e(selected_place["name"].title())} — {len(shown_items)} stillinger</p>'
                body += '<div class="job-list">'
                state_labels = {'required': 'Krav nevnt', 'preferred': 'Ønsket', 'not_required': 'Ikke nødvendig / opplæring', 'unknown': 'Uavklart'}
                published_dates = explore_published_dates([item[0] for item in page_items])
                for uid, ad, req, positive, unknown in page_items:
                    status = explore_compatibility(req, answers)
                    locations = ', '.join(dict.fromkeys(', '.join(x for x in (loc.get('municipal'), loc.get('county')) if x) for loc in ad.get('workLocations', [])))
                    municipality = (selected_place['name'] if selected_place else
                                    next((loc.get('municipal') for loc in ad.get('workLocations', []) if loc.get('municipal')), ''))
                    employer = (ad.get('employer') or {}).get('name') or ''
                    published = format_published_short(published_dates.get(uid))
                    summary = ad_summary(ad)
                    tags = direction_tags(label, req)
                    badge_class = 'badge needs-check' if status == 'Må avklares' else 'badge'
                    body += '<article class="job-row">'
                    body += f'<div class="job-main"><span class="{badge_class}">{e(status)}</span><h3>{e(ad.get("title") or ad.get("jobtitle") or "Stillingsannonse")}</h3><p>{e(employer)}</p><div class="job-meta">'
                    if municipality:
                        body += f'<span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 10c0 5-8 12-8 12S4 15 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/></svg>{e(municipality.title())}</span>'
                    if published:
                        body += f'<span><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18"/></svg>{e(published)}</span>'
                    body += '</div></div>'
                    body += f'<div class="job-middle"><div class="job-state-line"><details class="why"><summary>Hvorfor vises denne annonsen?</summary><p>Ingen tydelig konflikt funnet med svarene dine. Uavklarte og fagspesifikke krav må kontrolleres.</p><p><strong>{e(status)}</strong> · Status gjelder bare de fem spørsmålene, ikke full kvalifikasjonskontroll.</p>'
                    shown_evidence = set()
                    for key, item in req.items():
                        label_field = QUESTIONS[key][0] if key in QUESTIONS else 'Formelle kvalifikasjoner'
                        body += f'<p>{e(label_field)}: {state_labels[item["state"]]} · {e(item.get("compatibility", "Må avklares"))}</p>'
                        for _, quote in item['evidence']:
                            normalized_quote = ' '.join(quote.split()).casefold()
                            if normalized_quote not in shown_evidence:
                                shown_evidence.add(normalized_quote)
                                body += '<blockquote>' + e(quote) + '</blockquote>'
                    body += '</details></div>'
                    if summary:
                        body += f'<p class="summary-snippet">{e(summary)}</p>'
                    body += '<div class="job-tags">' + ''.join(f'<span>{e(tag)}</span>' for tag in tags) + '</div></div>'
                    body += f'<a class="job-link" href="{e(page_url(page=page, job=uid))}">Se hele stillingen →</a></article>'
                body += '</div><nav class="explore-pagination" aria-label="Pagination">'
                previous, following = e(t(lang, 'jobs.previous')), e(t(lang, 'jobs.next'))
                if page > 1:
                    body += f'<a rel="prev" href="{e(page_url(page=page - 1, job=None))}">← {previous}</a>'
                else:
                    body += f'<span class="page-disabled" aria-disabled="true">← {previous}</span>'
                page_label = f'Page {page} of {total_pages}' if lang == 'en' else f'Side {page} av {total_pages}'
                body += f'<span class="page-status">{page_label}</span>'
                if page < total_pages:
                    body += f'<a rel="next" href="{e(page_url(page=page + 1, job=None))}">{following} →</a>'
                else:
                    body += f'<span class="page-disabled" aria-disabled="true">{following} →</span>'
                body += '</nav></section><aside class="explore-place-filter"><section><h2>Velg sted</h2><p>Se stillinger i et sted fra dette utvalget.</p><nav aria-label="Filtrer etter sted">'
                all_current = ' class="active" aria-current="page"' if not selected_place else ''
                body += f'<a href="{e(url(direction=direction))}"{all_current}><span>Alle steder</span><strong>{len(items)}</strong></a>'
                for entry in visible_places:
                    current = ' class="active" aria-current="page"' if selected_key == entry['name'].casefold() else ''
                    body += f'<a href="{e(url(direction=direction, sted=entry["name"]))}"{current}><span>{e(entry["name"].title())}</span><strong>{entry["count"]}</strong></a>'
                if extra_places:
                    body += '<details class="place-more"><summary><span class="more-label">Vis flere steder</span><span class="less-label">Vis færre steder</span></summary>'
                    for entry in extra_places:
                        current = ' class="active" aria-current="page"' if selected_key == entry['name'].casefold() else ''
                        body += f'<a href="{e(url(direction=direction, sted=entry["name"]))}"{current}><span>{e(entry["name"].title())}</span><strong>{entry["count"]}</strong></a>'
                    body += '</details>'
                body += '</nav></section></aside></div>'
        else:
            populated = sorted(((key, items) for key, items in groups.items() if items), key=lambda pair: -len(pair[1]))[:5]
            if not populated:
                body += '<p>Ingen forslag funnet med disse svarene i det lokale utvalget.</p>'
            body += '<div class="direction-grid" data-caption="' + e(t(lang, 'footer.tagline')) + '">'
            for key, items in populated:
                regions = {}
                for _, ad, *_ in items:
                    for county in {loc.get('county') for loc in ad.get('workLocations', []) if loc.get('county')}:
                        regions[county] = regions.get(county, 0) + 1
                top = ', '.join(f'{name.title()} ({count})' for name, count in sorted(regions.items(), key=lambda x: (-x[1], x[0]))[:3])
                explanations = []
                count = lambda field, state: sum(item[2][field]['state'] == state for item in items)
                if answers['experience'] == 'none' and count('experience', 'not_required'):
                    explanations.append(f"Du har ikke arbeidserfaring. {count('experience', 'not_required')} annonser sier at erfaring ikke er nødvendig.")
                if answers['training'] == 'yes' and count('training', 'not_required'):
                    explanations.append(f"Du er åpen for opplæring. {count('training', 'not_required')} annonser omtaler opplæring.")
                if answers['licence'] == 'none' and count('licence', 'not_required'):
                    explanations.append(f"Du har ikke førerkort. {count('licence', 'not_required')} annonser sier at det ikke er nødvendig.")
                if answers['hours'] == 'flex' and count('hours', 'required'):
                    explanations.append(f"Du kan jobbe kveld, natt eller helg. {count('hours', 'required')} annonser omtaler arbeid på slike tider.")
                explanations.append('Språkvalg: ' + dict(QUESTIONS['language'][1])[answers['language']] + '. Bare tydelige nivåkrav er sammenlignet; øvrige språkkrav må avklares.')
                if len(explanations) == 1:
                    explanations.insert(0, 'Ingen tydelig uforenlige krav ble funnet for svarene dine. Vi har ikke nok opplysninger til å bekrefte at kravene er oppfylt.')
                body += f'<article class="card job direction-card"><h2>{e(DIRECTIONS[key][0])}</h2><p>Analysert: {counts[key]["analyzed"]} annonser</p><div class="direction-counts"><span>Bekreftet: {counts[key]["Bekreftet"]}</span><span>Må avklares: {counts[key]["Må avklares"]}</span></div><details class="reason-details"><summary>Hvorfor dette kan passe<span class="reason-preview">{e(" ".join(explanations))}</span></summary><p>{e(" ".join(explanations))}</p></details><p class="direction-regions">Flest alternativer i: {e(top) if top else "Region ikke oppgitt"}</p><a class="button" href="{e(url(direction=key))}">Se passende stillinger</a></article>'
                # Surface only existing factual sentences; keep the full explanation below.
                short_reasons = []
                for explanation in explanations:
                    if explanation.startswith('Språkvalg:'):
                        continue
                    sentences = explanation.split('. ')
                    short = sentences[1] if len(sentences) == 2 and sentences[1][:1].isdigit() else explanation
                    if explanation.startswith('Du har ikke førerkort.'):
                        short = short.replace('det ikke er nødvendig', 'førerkort ikke er nødvendig')
                    if explanation.startswith('Du kan jobbe kveld, natt eller helg.'):
                        short = short.replace('på slike tider', 'kveld, natt eller helg')
                    short_reasons.append(short)
                    if len(short_reasons) == 2:
                        break
                preview = '<span class="reason-preview">' + e(' '.join(explanations)) + '</span>'
                body = body.replace(preview, '')
                reasons_html = '<ul class="short-reasons">' + ''.join('<li>' + e(reason) + '</li>' for reason in short_reasons) + '</ul>'
                marker = '<details class="reason-details"><summary>Hvorfor dette kan passe</summary><p>' + e(' '.join(explanations))
                body = body.replace(marker, reasons_html + marker)
            body += '</div>'
    body += '<details id="datagrunnlag" class="disclosure"><summary>Om datagrunnlaget</summary><p>Bare sist lagrede aktive annonser brukes. Enkle tekstregler kan overse krav, alternativer og negasjoner. Språknivå og erfaring er ikke sertifisert; klasse «andre» bekrefter ingen bestemt førerkortklasse. Les originalannonsen. Manglende opplysninger betyr uavklart, ikke at et krav er oppfylt. Retningene er basert på konkrete stillingstitler, ikke automatisk adgang til et helt yrke. Svarene lagres ikke av appen, men vises i adressen og kan finnes i nettleserhistorikken.</p></details>'
    if not valid:
        body = site_header('explore', params, lang) + body[body.index('</header>') + len('</header>'):]
        body = body.replace('<h1>', '<div class="explore-heading"><p class="eyebrow">UTFORSK MULIGHETER</p><h1>', 1)
        body = body.replace('<form method="get" class="explore-form">', '</div><div class="explore-workspace"><form method="get" class="explore-form">', 1)
        body = body.replace('</form>', '</form><div class="explore-visual" aria-hidden="true"></div></div>', 1)
        icons = {
            'language': '<circle cx="12" cy="7" r="4"/><path d="M4 22v-3a8 8 0 0 1 16 0v3Z"/>',
            'licence': '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M6 9h3M6 14h3M13 9h5M13 14h5"/>',
            'experience': '<rect x="3" y="7" width="18" height="14" rx="3"/><path d="M8 7V3h8v4M3 12c5 4 13 4 18 0"/>',
            'hours': '<circle cx="12" cy="12" r="10"/><path d="M12 5v7l5 3"/>',
            'training': '<path d="m1 8 11-5 11 5-11 5ZM5 10v8c4 4 10 4 14 0v-8M2 9v10"/>',
        }
        for key, drawing in icons.items():
            body = body.replace(f'<p><label for="{key}">', f'<p><span class="question-icon" aria-hidden="true"><svg viewBox="0 0 24 24">{drawing}</svg></span><label for="{key}">')
        body += '<div class="entry-facts"><div><strong>Reelle annonser</strong><span>Basert på lagrede stillingsannonser.</span></div><div><strong>For mennesker</strong><span>Fem spørsmål som utgangspunkt.</span></div><div><strong>Fakta med forklaring</strong><span>Les kravene i den enkelte annonsen.</span></div></div>'
    directions_page = valid and get('direction') not in groups
    if directions_page:
        body = site_header('explore', params, lang) + body[body.index('</header>') + len('</header>'):]
        body = body.replace('<h1>', '<p class="results-eyebrow">DINE RESULTATER</p><h1>', 1)
        drawings = {
            'butikk': '<path d="M2 3h3l3 13h12l3-9H6M9 20h1M18 20h1"/><circle cx="9" cy="21" r="1"/><circle cx="19" cy="21" r="1"/>',
            'assistanse': '<circle cx="8" cy="7" r="3"/><circle cx="18" cy="8" r="3"/><path d="M2 21v-4a6 6 0 0 1 12 0v4ZM16 14a6 6 0 0 1 8 5v2h-7"/>',
            'hotell': '<path d="M2 18h22M4 16a9 9 0 0 1 18 0ZM12 7V4M9 4h6M5 22h16"/>',
            'renhold': '<path d="m18 2-8 12M7 12l8 5-4 7-10-6ZM5 16l-2 4M9 18l-2 4M21 10v4M19 12h4"/>',
            'lager': '<path d="m2 7 10-5 10 5v14l-10 5-10-5ZM2 7l10 5 10-5M12 12v14M7 4l10 5v5"/>',
        }
        for key, drawing in drawings.items():
            title = '<h2>' + e(DIRECTIONS[key][0]) + '</h2>'
            body = body.replace(title, '<span class="direction-icon" aria-hidden="true"><svg viewBox="0 0 26 28">' + drawing + '</svg></span>' + title)
        body += '<div class="direction-facts"><div><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 21V12h4v9M10 21V7h4v14M17 21V2h4v19"/></svg><strong>Reelle annonser</strong><span>Fra den lokale NAV-basen.</span></div><div><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m3 5 9-3 9 3v8c0 5-9 9-9 9s-9-4-9-9Z"/><path d="m7 12 3 3 7-7"/></svg><strong>Basert på svarene dine</strong><span>Les kravene i hver annonse.</span></div><div><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 10v7M12 6v2"/></svg><strong>Veiledende forslag</strong><span>Ingen garanti for kvalifikasjon.</span></div></div>'
    return page_document(lang, 'Utforsk jobber', 'select{font:inherit;padding:10px;border:1px solid var(--line);border-radius:9px;max-width:100%;width:100%}'+(EXPLORE_FORM_STYLE if not valid or directions_page else '')+(EXPLORE_RESULTS_STYLE if directions_page else '')+(DIRECTION_VACANCY_STYLE if get('direction') in groups and not get('job') else '')+(EXPLORE_DETAIL_STYLE if get('job') else ''), 'explore-entry explore-results' if directions_page else 'explore-entry' if not valid else 'explore-vacancies' if get('direction') in groups and not get('job') else 'explore-detail' if get('job') else '', body, params)


HOME_STYLE = """
/* A local landscape can later be supplied through --home-landscape.
   No image URL or network request is used by the current fallback. */
.home{--home-landscape:none;max-width:1500px;padding:22px 32px 36px}.home header{background:#ffffffcf;backdrop-filter:blur(12px);padding:16px 24px;box-shadow:0 5px 24px #153e3b08}.home .brand{gap:12px}.home .brand-name{display:flex;flex-direction:column;line-height:1.15}.home .brand-name small{font-size:11px;letter-spacing:.08em;font-weight:500;margin-top:4px}.home .peil-mark{padding:6px}
.home .hero{position:relative;isolation:isolate;overflow:hidden;margin:22px 0 14px;padding:44px 42px 30px;border:1px solid #dce5dc;border-radius:26px;gap:22px 32px;grid-template-columns:minmax(0,1.65fr) minmax(260px,1fr);background:#e4ede8;background-image:linear-gradient(90deg,#f7f8f2 0%,#f7f8f2ed 40%,#edf3ed70 72%,#dde9e32b),var(--home-landscape),linear-gradient(160deg,#dce7e5,#91afb0);background-size:cover;background-position:center,right center,center}.home .hero-copy{max-width:780px}.home .hero-brand{font-size:18px;font-weight:700;letter-spacing:-.02em;margin-bottom:12px}.home .hero h1{font-size:clamp(36px,3.7vw,56px);margin:14px 0 18px;max-width:740px}.home .hero .intro{max-width:620px;margin-bottom:0}
.home .signpost{min-height:330px;max-width:360px;padding:18px 12px 32px;gap:14px;background:none;filter:drop-shadow(5px 13px 9px #173c3525)}.home .signpost:before{width:21px;left:49%;top:8px;bottom:0;background:repeating-linear-gradient(88deg,#ffffff00 0 5px,#60452028 6px 7px),linear-gradient(90deg,#968265,#cfb897 50%,#9f896b);box-shadow:inset 2px 0 2px #f8e9c060;border-radius:5px}.home .signboard{width:96%;padding:12px 26px 12px 18px;font-size:18px;color:#354234;letter-spacing:.01em;background:repeating-linear-gradient(2deg,transparent 0 8px,#83623d18 9px 10px,transparent 11px 14px),linear-gradient(105deg,#e1cfaa,#c6ad84);box-shadow:inset 0 2px #f9e8c394,inset 0 -3px #82644230}.home .signboard:nth-child(2){margin-left:5px;background:repeating-linear-gradient(-2deg,transparent 0 6px,#83623d18 7px 8px),linear-gradient(105deg,#d2bc94,#e5d6b8)}.home .signboard:nth-child(4){margin-left:8px;background:repeating-linear-gradient(1deg,transparent 0 9px,#83623d18 10px 11px),linear-gradient(105deg,#d5c39e,#c3aa81)}.home .wood-icon{display:inline-block;width:29px;font-size:18px;font-weight:400;color:#5a654a}.home .signboard:after{left:55%;background:#8c7e62;box-shadow:0 1px #f7e6c0}
.home .scenario-choices{grid-column:1/-1;max-width:none;margin:8px 0 0;gap:18px}.home .scenario-choices a{background:#ffffffbb;backdrop-filter:blur(10px);border-color:#ffffffdb;box-shadow:0 5px 22px #24463b08;padding:24px;gap:10px}.home .choice-icon{display:grid;place-items:center;width:42px;height:42px;border-radius:12px;background:#e4ece1;color:#20584c;font-size:26px}.home .scenario-choices strong{font-size:21px;line-height:1.3;max-width:480px}.home .scenario-choices .choice-cta{align-self:flex-start;display:inline-flex;gap:18px;align-items:center;background:#194c45;color:white;border-radius:10px;padding:10px 16px;font-size:14px;font-weight:600;margin-top:6px}.home .choice-cta i{font-style:normal;transition:transform .2s ease}.home .scenario-choices a:hover .choice-cta i{transform:translateX(3px)}
.home .fact-strip{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;padding:18px 24px;background:#ffffffa6;border:1px solid var(--line);border-radius:15px;margin:0 0 24px}.home .fact-strip strong{display:block;font-size:14px}.home .fact-strip span{font-size:13px;color:var(--muted)}.home form{max-width:850px;margin:20px 0}
@media(max-width:850px){.home{padding:14px}.home .hero{padding:28px 22px;grid-template-columns:1fr}.home .signpost{min-height:260px;max-width:290px}.home .scenario-choices{grid-template-columns:1fr}.home .hero h1{font-size:36px}.home .fact-strip{grid-template-columns:1fr;gap:12px}.home header{padding:12px}.home .scenario-choices a{padding:20px}}
@media(prefers-reduced-motion:reduce){.home .choice-cta i{transition:none}.home .scenario-choices a:hover .choice-cta i{transform:none}}
"""

JOBS_SIDEBAR_REFERENCE_STYLE = """.jobs-side-hero{border-radius:22px!important;background:#fff!important;box-shadow:0 4px 16px #244f4208}.jobs-side-hero-top{display:grid;grid-template-columns:55% 45%;height:230px;min-height:0;background:#f1fbfe}.jobs-side-hero-copy{width:auto;padding:30px 0 25px 32px}.jobs-side-kicker{margin-bottom:16px;font-size:11px;font-weight:700;letter-spacing:.16em}.jobs-side-hero h2{max-width:235px;margin:0 0 14px;font-size:32px;line-height:1.1;font-weight:700}.jobs-side-hero p{max-width:330px;font-size:16px;line-height:1.42}.jobs-side-illustration{position:relative;right:auto;bottom:auto;width:100%;height:100%;align-self:stretch}.jobs-side-hero .jobs-help-row{grid-template-columns:48px minmax(0,1fr) 18px;gap:18px;height:90px;min-height:0;padding:13px 25px;box-sizing:border-box}.jobs-side-hero .jobs-help-row>span{width:48px;height:48px;border-radius:15px}.jobs-side-hero .jobs-help-row>span svg{width:24px;height:24px}.jobs-side-hero .jobs-help-row h3{font-size:18px;line-height:1.2}.jobs-side-hero .jobs-help-row p{font-size:14px;line-height:1.35}.jobs-help-arrow{width:18px;height:18px}.jobs-help-arrow svg{width:18px!important;height:18px!important}@media(max-width:1050px){.jobs-side-hero-top{height:230px}.jobs-side-hero-copy{padding:30px 0 25px 32px}.jobs-side-hero h2{font-size:32px}.jobs-side-illustration{width:100%;height:100%}.jobs-side-hero .jobs-help-row{grid-template-columns:48px minmax(0,1fr) 18px;gap:18px;padding:13px 25px}}@media(max-width:700px){.jobs-side-hero-top{grid-template-columns:56% 44%;height:220px}.jobs-side-hero-copy{padding:27px 0 22px 24px}.jobs-side-kicker{margin-bottom:13px}.jobs-side-hero h2{max-width:215px;margin-bottom:11px;font-size:28px}.jobs-side-hero p{font-size:14px}.jobs-side-illustration{width:100%;height:100%}.jobs-side-hero .jobs-help-row{grid-template-columns:48px minmax(0,1fr) 18px;gap:14px;height:88px;padding:12px 20px}.jobs-side-hero .jobs-help-row>span{width:48px;height:48px}.jobs-side-hero .jobs-help-row>span svg{width:24px;height:24px}}"""

HOME_STYLE += """
/* Laptop composition. No clipping or fixed page height; mobile can scroll. */
.home{max-width:1500px;padding:14px 24px 18px}.home header{padding:10px 20px;min-height:62px;border-radius:20px}.home .hero{margin:14px 0 10px;padding:26px 30px 24px;grid-template-columns:minmax(0,1.9fr) minmax(240px,1fr);gap:18px 30px;border-radius:22px}.home .hero-copy{grid-column:1;grid-row:1}.home .hero-brand{font-size:clamp(48px,5.1vw,72px);line-height:1.04;letter-spacing:-.055em;margin:0 0 8px;color:#132e36}.home .hero-brand span{color:#218570}.home .hero .eyebrow{font-size:14px;letter-spacing:.1em;margin:0 0 8px}.home .hero h1{font-size:clamp(29px,3vw,42px);line-height:1.12;margin:0 0 12px}.home .hero .intro{font-size:16px;line-height:1.5;margin:0;max-width:670px}
.home .signpost{grid-column:2;grid-row:1/3;align-self:stretch;min-height:360px;max-width:330px;gap:18px;padding:24px 6px 40px}.home .signpost:before{bottom:0;top:10px;width:23px}.home .signboard{font-size:19px;padding:14px 20px 14px 15px}.home .scenario-choices{grid-column:1;grid-row:2;gap:14px;margin:0}.home .scenario-choices a{padding:18px;gap:8px;display:grid;grid-template-columns:42px 1fr;align-content:start;border-radius:18px}.home .scenario-choices strong{font-size:18px;line-height:1.3;align-self:center}.home .scenario-choices a>span:not(.choice-icon){grid-column:1/-1}.home .scenario-choices a>span:not(.choice-icon):not(.choice-cta){font-size:14px;line-height:1.4}.home .scenario-choices .choice-cta{display:flex;justify-content:space-between;margin-top:4px;padding:9px 13px;font-size:14px}.home .scenario-choices a:last-child{background:#f4fbffce}.home .scenario-choices a:last-child .choice-icon{background:#e1edf0;color:#2c6976}.home .scenario-choices a:last-child .choice-cta{background:#286775}
.home form{max-width:none;margin:10px 0 12px;display:flex;align-items:center;gap:18px;padding:10px 18px;background:#ffffffb3;border:1px solid var(--line);border-radius:14px}.home form label{margin:0;white-space:nowrap;font-size:14px}.home form .search{flex:1;min-width:0}.home .fact-strip{padding:12px 20px;margin:0 0 8px;gap:16px}.home .fact-strip>div+div{border-left:1px solid var(--line);padding-left:20px}.home .fact-strip strong{font-size:13px}.home .fact-strip span{font-size:12px}.home>.disclosure{padding:7px 0;margin:0}
@media(min-width:851px) and (max-height:820px){.home .hero{padding:20px 26px;gap:14px 24px}.home .hero-brand{font-size:56px}.home .hero h1{font-size:32px}.home .scenario-choices a{padding:14px}.home .signpost{min-height:330px}.home .hero .intro{font-size:15px}}
@media(max-width:850px){.home{padding:12px}.home .hero{grid-template-columns:1fr;padding:24px 18px;gap:22px}.home .hero-copy{grid-row:auto;grid-column:1}.home .hero-brand{font-size:52px}.home .hero h1{font-size:32px}.home .signpost{grid-column:1;grid-row:auto;min-height:250px;max-width:290px;gap:10px;padding:12px 8px 25px}.home .signboard{padding:10px 18px;font-size:17px}.home .scenario-choices{grid-column:1;grid-row:auto;grid-template-columns:1fr}.home form{display:block;padding:14px}.home form label{margin-bottom:7px}.home .fact-strip>div+div{border-left:0;padding-left:0}}
"""


HOME_STYLE += """
/* Local assets, with the complete entry flow kept in the laptop viewport. */
.home{max-width:1600px;padding:12px 20px}.home header{margin-bottom:12px;background:#fffffff0;box-shadow:0 6px 28px #254c4010}.home .brand-name{font-size:25px;letter-spacing:-.04em}.home .brand-name small{letter-spacing:.12em}
.home .hero{margin:0 0 10px;padding:28px 36px 22px;grid-template-columns:minmax(0,1.8fr) minmax(230px,1fr);gap:22px 20px;background-image:linear-gradient(90deg,#fafbf6f5 0%,#fafbf6cf 34%,#f1f7f351 61%,#ffffff00 85%),url('/static/jobbpeil-bg.png');background-position:center;background-size:cover;border-color:#ffffffb0;box-shadow:0 10px 36px #234b4210}
.home .hero h1.hero-brand{font-size:clamp(58px,6vw,82px);line-height:1;letter-spacing:-.06em;margin:0 0 5px}.home .hero .hero-tagline{font-size:clamp(30px,3.4vw,46px);letter-spacing:-.045em;line-height:1.12;margin:0 0 14px;font-weight:700;color:#142e36}.home .hero .intro{max-width:620px;font-size:17px;line-height:1.45;color:#334f59}
.home .hero-signpost{grid-column:2;grid-row:1/3;align-self:center;justify-self:center;display:block;width:100%;height:410px;object-fit:contain;filter:drop-shadow(5px 9px 6px #173e3530);transform-origin:50% 95%;animation:sign-arrive .7s ease-out both}
.home .scenario-choices{gap:16px}.home .scenario-choices a{padding:18px;grid-template-columns:46px 1fr;gap:10px;background:#f5ffface;border:1px solid #ffffffd9;box-shadow:0 8px 24px #163e3b14;backdrop-filter:blur(12px)}.home .scenario-choices .choice-icon{width:46px;height:46px;border-radius:50%;background:#9fd7c9;color:#12564b}.home .choice-icon svg{width:24px;height:24px;stroke:currentColor;stroke-width:1.7;fill:none;stroke-linecap:round;stroke-linejoin:round}.home .scenario-choices strong{font-size:18px}.home .scenario-choices .choice-cta{padding:10px 14px}.home .scenario-choices a:last-child{background:#f3faffd9}.home .scenario-choices a:last-child .choice-cta{background:#247c99}.home .scenario-choices a:last-child .choice-icon{background:#c8e8f1}
.home form{margin:0 0 10px;padding:10px 18px}.home .fact-strip{margin:0 0 5px;background:#ffffffe6;padding:11px 20px}.home>.disclosure{margin:0;padding:5px 0}
@keyframes sign-arrive{from{opacity:0;transform:rotate(-1.5deg) translateY(5px)}to{opacity:1;transform:none}}
@media(min-width:851px) and (max-height:820px){.home .hero{padding:20px 30px;gap:16px 20px}.home .hero h1.hero-brand{font-size:64px}.home .hero .hero-tagline{font-size:36px;margin-bottom:10px}.home .hero .intro{font-size:16px}.home .hero-signpost{height:370px}.home .scenario-choices a{padding:14px}}
@media(max-width:850px){.home{padding:12px}.home .hero{grid-template-columns:1fr;padding:24px 18px;background-image:linear-gradient(90deg,#fafbf6ed,#f5f9f5aa),url('/static/jobbpeil-bg.png')}.home .hero h1.hero-brand{font-size:56px}.home .hero .hero-tagline{font-size:34px}.home .hero-signpost{grid-column:1;grid-row:2;height:260px;width:auto;max-width:100%}.home .scenario-choices{grid-row:3}.home .brand-name{font-size:22px}.home .hero .intro{font-size:16px}}
@media(prefers-reduced-motion:reduce){.home .hero-signpost{animation:none}}
"""


HOME_STYLE += """
/* Final homepage polish; internal pages retain their existing styles. */
.home{font-family:"Segoe UI",Arial,sans-serif}.home header{padding:9px 24px;background:#fffffff2;box-shadow:0 5px 24px #183e3808}.home .home-logo{width:45px;height:48px;flex:none;overflow:visible;color:#148975}.home .home-logo .peil-arrow{transform-origin:center;animation:peil-arrow .65s ease-out both}.home .brand-name{font-size:28px;font-weight:750;letter-spacing:-.05em}.home .brand-name small{font-size:11px;font-weight:500;letter-spacing:.12em}
.home .hero{padding-bottom:26px}.home .hero h1.hero-brand{font-weight:750;letter-spacing:-.055em}.home .hero .hero-tagline{font-weight:650;letter-spacing:-.045em}.home .hero .intro{max-width:580px;line-height:1.5}.home .hero-signpost{align-self:end;margin-bottom:-26px;object-position:center bottom;height:430px}
.home .scenario-choices a{grid-template-columns:54px 1fr;grid-template-rows:auto auto minmax(0,1fr) auto;padding:19px;gap:12px;border-radius:20px;background:linear-gradient(135deg,#f5fffaeb,#effbf4cb);box-shadow:inset 0 1px 0 #fff,0 10px 26px #173d3a18}.home .scenario-choices a:last-child{background:linear-gradient(135deg,#f4fcfff0,#eaf7ffdb)}.home .scenario-choices strong{font-size:19px;font-weight:650;line-height:1.25;letter-spacing:-.025em}.home .scenario-choices .choice-icon{height:54px;width:54px;background:linear-gradient(145deg,#a6ded0,#73c5b0);box-shadow:inset 0 1px 2px #ffffffa0,0 3px 8px #22615110}.home .choice-icon svg{width:32px;height:32px;stroke-width:1.8}.home .scenario-choices a:last-child .choice-icon{background:linear-gradient(145deg,#d9f2ff,#9ed5ed);color:#1678a3}.home .scenario-choices .choice-cta{grid-row:4;align-self:end;font-size:15px;font-weight:600;letter-spacing:-.01em;padding:11px 15px;box-shadow:0 2px 4px #12463f10}.home .scenario-choices a:last-child .choice-cta{background:#187eaa}
.home form{background:#fffffff0;box-shadow:0 3px 16px #244f4210}.home form input,.home form button{font-family:inherit}.home .search-icon{width:20px;height:20px;flex:none;margin-left:10px;color:#57766d;stroke:currentColor;stroke-width:1.8;fill:none}.home .fact-strip>div{display:grid;grid-template-columns:30px 1fr;column-gap:12px;align-content:center}.home .fact-strip strong,.home .fact-strip span{grid-column:2}.home .fact-icon{grid-column:1;grid-row:1/3;align-self:center;width:28px;height:28px;fill:none;stroke:#1c7968;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}.home .fact-strip strong{font-weight:650;font-size:14px}.home .fact-strip span{line-height:1.45}
@media(min-width:851px) and (max-height:820px){.home .hero{padding-bottom:24px}.home .hero-signpost{height:400px;margin-bottom:-24px}.home .scenario-choices a{padding:16px}.home .hero h1.hero-brand{font-size:68px}.home .hero .hero-tagline{font-size:38px}}
@media(max-width:850px){.home .hero-signpost{height:270px;margin-bottom:0}.home .scenario-choices a{padding:18px}.home .search-icon{display:none}.home .home-logo{width:35px;height:39px}.home .brand-name{font-size:23px}.home header{padding:10px 12px}}
@media(prefers-reduced-motion:reduce){.home .home-logo .peil-arrow{animation:none}}
"""


HOME_STYLE += """
.home .fact-strip{background:#edf7f1e8;border-color:#dcebe1}
"""


RESULT_STYLE = """
.results-page .region .badge.badge-medium{background:#fff3d1}
.results-page{font-family:"Segoe UI",Arial,sans-serif;max-width:1500px;padding:12px 24px;background:radial-gradient(ellipse at top right,#e4f3ef88,transparent 65%)}.results-page header{padding:7px 24px;min-height:58px;background:#fffffff0;border-radius:20px;box-shadow:0 5px 24px #183e3808}.results-page .brand{gap:12px}.results-page .home-logo{width:40px;height:44px;color:#148975;flex:none}.results-page .brand-name{display:flex;flex-direction:column;font-size:27px;font-weight:750;letter-spacing:-.05em;line-height:1.15}.results-page .brand-name small{font-size:11px;font-weight:500;letter-spacing:.12em;margin-top:4px}
.results-page .result-search{max-width:calc(100% - 235px);margin:16px 0 12px}.results-page .search{background:white;border:1px solid #d8e6e2;padding:5px}.results-page input,.results-page button{font-family:inherit}.results-page button,.results-page .region .button{background:#328a79;color:white;border:1px solid #2d8171;box-shadow:0 2px 6px #246b5710}.results-page button:hover,.results-page .region .button:hover{background:#287765;color:white}.results-page .direction-note{position:absolute;right:45px;top:98px;width:180px;font-family:"Segoe Print","Comic Sans MS",cursive;font-size:21px;line-height:1.3;color:#246457;transform:rotate(-7deg);text-align:center}.results-page{position:relative}.results-page .direction-note:after{content:"";display:block;border-bottom:2px solid #54a38e;width:100px;margin:7px auto}
.results-page>h2{font-size:32px;font-weight:700;letter-spacing:-.035em;line-height:1.15;margin:12px 0 5px}.results-page>h2+p{font-size:15px;margin-bottom:16px}.results-page .top-five{border:1px solid #e2ebe7;border-radius:20px;box-shadow:0 7px 25px #244b3e08;background:#fffffff5}.results-page .region{display:grid;grid-template-columns:195px minmax(400px,1fr) 174px 132px;gap:16px;align-items:center;padding:12px 20px;min-height:76px}.results-page .top-five .region{min-height:76px;padding:12px 20px}.results-page .region h3{font-size:20px;font-weight:650;letter-spacing:-.025em;margin:0}.results-page .region .card-head{gap:10px}.results-page .region .metrics{gap:18px;grid-template-columns:1fr .8fr 1.15fr}.results-page .metric b{font-size:24px;font-weight:650;line-height:1.1;font-variant-numeric:tabular-nums}.results-page .metric span{font-size:11px;line-height:1.3;color:#627b80;margin-top:5px}.results-page .region .badge{font-size:11px;padding:8px 10px;background:#eaf3ec;border:0;font-weight:400}.results-page .region .button{font-size:14px;padding:10px 12px;border-radius:11px;white-space:nowrap}.results-page .top-five .card-head:before{font-size:12px;color:#809899}.results-page>.disclosure{padding:6px 0;margin:3px 0}.results-page .results-facts{display:grid;grid-template-columns:repeat(3,1fr);gap:24px;padding:12px 20px;margin-top:8px;border:1px solid #e1ebe6;border-radius:16px;background:#ffffffce}.results-page .results-facts strong{display:block;font-size:13px;color:#235b50}.results-page .results-facts span{font-size:12px;color:#607976}
@media(min-width:851px){.results-page .top-five .region{min-height:68px;padding-top:8px;padding-bottom:8px}.results-page>.disclosure{padding:3px 0;margin:0}.results-page .result-search{margin-top:12px;margin-bottom:8px}.results-page .results-facts{padding:9px 20px;margin-top:5px}}
@media(max-width:1100px){.results-page .region{grid-template-columns:155px minmax(300px,1fr) 150px 120px;gap:10px}.results-page .region .badge,.results-page .region .button{grid-column:auto}}
@media(max-width:850px){.results-page .direction-note{display:none}.results-page .result-search{max-width:none}.results-page .region{grid-template-columns:1fr 1fr}.results-page .region .metrics{grid-column:1/-1;grid-row:2}.results-page .region .button{justify-self:end}.results-page>h2{font-size:28px}.results-page .results-facts{grid-template-columns:1fr;gap:10px}}
@media(max-width:700px){.results-page{padding:12px}.results-page header{padding:10px}.results-page .brand-name{font-size:22px}.results-page .home-logo{width:32px;height:36px}.results-page .top-five .region{padding:16px}.results-page .region .badge{justify-self:end}}
"""


RESULT_STYLE += """
.results-page:before{content:"";position:absolute;top:78px;left:18px;right:18px;height:170px;border-radius:22px;background:linear-gradient(112deg,#eaf6efb8,#edf5f9a8);pointer-events:none}
@media(max-width:850px){.results-page:before{left:8px;right:8px;height:205px}}
"""


VACANCY_LIST_STYLE = """
.vacancy-list-page{font-family:"Segoe UI",Arial,sans-serif;width:calc(100% - 56px);max-width:1500px;padding:12px 0 28px;background:#f7f8f4}.vacancy-list-page header{padding:7px 24px;border-radius:20px;background:#eef8f2f2;box-shadow:0 5px 24px #183e3808}.vacancy-list-page .brand{gap:12px}.vacancy-list-page .home-logo{width:40px;height:44px;flex:none;color:#148975}.vacancy-list-page .brand-name{display:flex;flex-direction:column;font-size:27px;font-weight:750;letter-spacing:-.05em;line-height:1.15}.vacancy-list-page .brand-name small{font-size:11px;font-weight:500;letter-spacing:.12em;margin-top:4px}
.vacancy-list-page .result-search{max-width:none;margin:14px 0 16px}.vacancy-list-page input,.vacancy-list-page button{font-family:inherit}.vacancy-list-page button,.vacancy-list-page .button{background:#2f6658;color:#fff}.vacancy-list-page button:hover,.vacancy-list-page .button:hover{background:#28594e;color:#fff}.vacancy-list-page .search{position:relative;background:white;border:1px solid #d7e5df;padding:5px 5px 5px 44px}.vacancy-list-page .search-icon{position:absolute;left:15px;top:50%;transform:translateY(-50%);width:21px;height:21px;fill:none;stroke:#1b5960;stroke-width:2;stroke-linecap:round}.vacancy-list-page>p{margin:7px 0 10px;font-size:14px}.vacancy-layout{display:grid;grid-template-columns:minmax(0,1fr) 350px;gap:26px;align-items:start}.vacancy-results{min-width:0}.vacancy-results>h2{font-size:31px;line-height:1.15;letter-spacing:-.035em;margin:0 0 5px;font-weight:700}.vacancy-results>p{font-size:15px;color:#607570;margin:0 0 12px}
.vacancy-list-page .job-list{display:flex;flex-direction:column;gap:8px;border:0;border-radius:0;background:transparent;overflow:visible}.vacancy-list-page .job-row{display:grid;grid-template-columns:56px minmax(0,1fr) 158px;align-items:start;gap:13px;padding:12px 14px;min-height:138px;border:1px solid #dce8e3;border-radius:15px;background:#fffffff5;box-shadow:0 5px 18px #244f4208}.vacancy-list-page .job-row:hover{background:#fbfefc;border-color:#b9d9cd}.vacancy-list-page .vacancy-icon{display:grid;place-items:center;width:50px;height:50px;margin-top:1px;border-radius:13px;background:#e2f4ec;color:#178f79}.vacancy-list-page .vacancy-icon svg{width:24px;height:24px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.vacancy-list-page .job-row:nth-child(4n+2) .vacancy-icon{background:#e5effc;color:#3972a2}.vacancy-list-page .job-row:nth-child(4n+3) .vacancy-icon{background:#e7f5ed;color:#1b8c76}.vacancy-list-page .job-row:nth-child(4n) .vacancy-icon{background:#f0eafa;color:#6d53a4}.vacancy-list-page .job-copy{min-width:0}.vacancy-list-page .job-row h3{font-size:17px;font-weight:700;line-height:1.22;letter-spacing:-.02em;margin:0 0 4px}.vacancy-list-page .job-row p{font-size:12.5px;line-height:1.35;margin:0 0 2px;color:#587571}.vacancy-list-page .job-meta-line{display:flex;flex-wrap:wrap;gap:4px 10px}.vacancy-list-page .job-meta-line span,.vacancy-list-page .job-date{display:inline-flex;align-items:center;gap:5px}.vacancy-list-page .job-meta-line svg,.vacancy-list-page .job-date svg{width:13px;height:13px;fill:none;stroke:#3f6d76;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round;flex:none}.vacancy-list-page .job-date{font-size:12px!important;color:#5f7780!important}.vacancy-list-page .job-row .job-snippet{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;max-width:70ch;margin-top:4px;color:#4b6965}.vacancy-list-page .job-tags{display:flex;flex-wrap:wrap;gap:5px;margin-top:6px}.vacancy-list-page .job-tags span{display:inline-flex;align-items:center;min-height:22px;padding:2px 9px;border-radius:999px;background:#eaf5f7;color:#245f73;font-size:11px;line-height:1}.vacancy-list-page .job-tags span:nth-child(even){background:#e8f5ee;color:#276c5c}.vacancy-list-page .job-link{align-self:start;justify-self:end;white-space:nowrap;margin-top:4px;background:#2f6658;color:#fff;padding:9px 12px;border-radius:10px;border:0;text-decoration:none;font-size:12.5px;font-weight:600;transition:background .18s ease,transform .18s ease}.vacancy-list-page .job-link:hover{background:#28594e;transform:translateY(-1px)}.vacancy-list-page .job-link:focus-visible{outline:2px solid #368875;outline-offset:3px}
.vacancy-sidebar{position:static;display:grid;gap:14px}.vacancy-sidebar>section{border:1px solid #dce9e3;border-radius:16px;box-shadow:0 5px 18px #244f4208;padding:15px 16px}.region-summary{display:grid;grid-template-columns:minmax(0,1fr) 150px;gap:11px;align-items:center;background:#edf8f4}.region-summary>div{display:grid;grid-template-columns:30px 1fr;align-items:center}.region-summary .region-pin{grid-row:1/3;display:grid;place-items:center;width:24px;height:24px;color:#0f7165}.region-summary .region-pin svg{width:23px;height:23px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}.region-summary h2{font-size:21px;line-height:1.15;margin:0}.region-summary p{font-size:13px;color:#587571;margin:3px 0 0}.city-photo{display:block;height:70px;border-radius:10px;background:#dfeeea url('/static/oslo-waterfront.png') center/cover no-repeat;box-shadow:inset 0 0 0 1px #ffffff99}
.vacancy-info{background:#eef8f5}.vacancy-info .eyebrow{font-size:11px;font-weight:700;letter-spacing:.1em;color:#397b6d}.vacancy-info h2,.vacancy-next h2{font-size:19px;line-height:1.18;letter-spacing:-.025em;margin:7px 0 5px}.vacancy-info>p,.vacancy-next p{font-size:13px;line-height:1.4;margin:0;color:#173f47}.vacancy-info ul{list-style:none;padding:0;margin:9px 0 0}.vacancy-info li{display:grid;grid-template-columns:34px 1fr;align-items:center;gap:8px;padding:4px 0;font-size:12.5px;line-height:1.3;border-top:0}.vacancy-info .info-icon{display:grid;place-items:center;width:30px;height:30px;border-radius:10px;background:#e1eefc;color:#3675a8}.vacancy-info .info-icon.shield{background:#e4f3ec;color:#207565}.vacancy-info .info-icon.people{background:#e6eefc;color:#3972a2}.vacancy-info .info-icon.location{background:#e8f0ff;color:#3b75ad}.vacancy-info .info-icon svg,.vacancy-next .next-icon svg{width:17px;height:17px;fill:none;stroke:currentColor;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round}.vacancy-next{position:relative;display:grid;grid-template-columns:42px 1fr;gap:9px;min-height:154px;padding:13px 15px 52px!important;overflow:hidden;background:linear-gradient(145deg,#f4f8f7,#edf5f3)}.vacancy-next .next-icon{z-index:2;display:grid;place-items:center;width:38px;height:38px;border-radius:11px;background:#e7f4e8;color:#176f61}.vacancy-next .next-icon svg{width:22px;height:22px}.vacancy-next>div{position:relative;z-index:2}.vacancy-next h2{margin:1px 0 4px}.next-landscape{position:absolute;left:0;right:0;bottom:0;height:48px;overflow:hidden;background:linear-gradient(to bottom,transparent 0 28%,#d9eef8 29% 55%,#c9e4e8 56% 100%);opacity:.88}.next-landscape:before,.next-landscape:after{content:"";position:absolute;bottom:-34px;width:74%;height:67px;border-radius:50% 56% 0 0}.next-landscape:before{left:-17%;background:#3c8f7f;transform:rotate(7deg)}.next-landscape:after{right:-18%;background:#73ac9d;transform:rotate(-8deg)}.next-landscape i{position:absolute;z-index:4;right:28px;top:2px;width:22px;height:22px;border-radius:50%;background:#f9dc92}.next-landscape b{position:absolute;z-index:1;left:14px;bottom:12px;width:105px;height:25px;background:linear-gradient(90deg,#c9d9e5 0 12%,transparent 12% 17%,#abc3d4 17% 28%,transparent 28% 34%,#92b2c8 34% 47%,transparent 47% 54%,#bdd0dd 54% 67%,transparent 67%);clip-path:polygon(0 100%,0 60%,12% 60%,12% 30%,17% 30%,17% 50%,28% 50%,28% 15%,34% 15%,34% 65%,47% 65%,47% 40%,54% 40%,54% 70%,67% 70%,67% 100%);transform:scale(.68);transform-origin:left bottom}.next-landscape em{position:absolute;z-index:0;left:42px;bottom:2px;width:155px;height:45px;background:#b6d1e6;clip-path:polygon(0 100%,45% 0,100% 100%);transform:scale(.65);transform-origin:left bottom}
@media(max-width:1050px){.vacancy-layout{grid-template-columns:1fr}.vacancy-sidebar{grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.region-summary{grid-template-columns:1fr 140px}.city-photo{height:72px}.vacancy-list-page .job-row{grid-template-columns:52px minmax(0,1fr) 154px}}
@media(max-width:700px){.vacancy-list-page{width:auto;padding:12px}.vacancy-list-page header{padding:10px}.vacancy-list-page .brand-name{font-size:22px}.vacancy-list-page .home-logo{width:32px;height:36px}.vacancy-list-page .job-row{grid-template-columns:46px minmax(0,1fr);gap:10px;padding:12px;min-height:0}.vacancy-list-page .vacancy-icon{width:42px;height:42px}.vacancy-list-page .vacancy-icon svg{width:23px;height:23px}.vacancy-list-page .job-link{grid-column:2;justify-self:start;margin-top:4px}.vacancy-sidebar{grid-template-columns:1fr}.region-summary{grid-template-columns:1fr 126px}.vacancy-results>h2{font-size:27px}.vacancy-list-page .job-tags{gap:5px}.vacancy-next{min-height:150px}}
@media(prefers-reduced-motion:reduce){.vacancy-list-page .job-link{transition:none}}
"""

VACANCY_LIST_STYLE += """.visually-hidden{position:absolute!important;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}.all-jobs-filter{display:grid;grid-template-columns:minmax(0,1fr) minmax(210px,.42fr) 220px;gap:14px;align-items:center;max-width:none!important;margin:14px 0 24px!important;padding:10px 12px;background:#ffffffd9;border:1px solid #dce8e3;border-radius:18px;box-shadow:0 7px 20px #244f4209}.all-jobs-filter .all-jobs-query{display:flex;align-items:center;min-height:54px;padding:4px 8px 4px 47px;border:1px solid #d2e0da;border-radius:12px;background:#fff}.all-jobs-query .search-icon{left:15px}.all-jobs-filter .all-jobs-query input{width:100%;padding:10px 8px;font-size:16px}.all-jobs-county{position:relative;min-height:54px}.all-jobs-county>svg{position:absolute;z-index:1;top:16px;left:14px;width:22px;height:22px;fill:none;stroke:#1b5960;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;pointer-events:none}.all-jobs-county select{width:100%;height:54px;padding:8px 35px 8px 46px;border:1px solid #d2e0da;border-radius:12px;background:#fff;color:var(--ink);font:600 16px inherit;appearance:auto}.all-jobs-filter>button{height:54px;padding:10px 16px;border-radius:12px;font-size:15px;font-weight:700;white-space:nowrap}.all-jobs-layout{grid-template-columns:minmax(0,1.9fr) minmax(340px,1fr);gap:28px}.all-jobs-heading{display:flex;align-items:end;justify-content:space-between;gap:20px;margin-bottom:12px}.all-jobs-heading .vacancy-results>h2,.all-jobs-heading h2{margin:0 0 5px}.all-jobs-heading p{margin:0;color:#587571}.all-jobs-pages{text-align:right;flex:none}.all-jobs-pages>p{font-size:13px!important;margin-bottom:7px!important}.all-jobs-pagination{display:flex;justify-content:flex-end;gap:5px;margin:0}.all-jobs-pagination .page-link,.all-jobs-pagination .page-ellipsis{display:grid;place-items:center;min-width:32px;height:32px;padding:0 8px;border:1px solid #d8e5df;border-radius:8px;background:#fff;color:#24534e;text-decoration:none;font-size:13px;font-weight:700}.all-jobs-pagination .page-link:hover{border-color:#93bbae;background:#f2f8f4}.all-jobs-pagination .page-link.current{border-color:#15594f;background:#15594f;color:#fff}.all-jobs-pagination .page-ellipsis{border:0;background:transparent}.all-jobs-sidebar{display:flex;flex-direction:column;gap:14px}.all-jobs-sidebar>section{padding:0;overflow:hidden}.jobs-side-hero{background:#f5fbff!important}.jobs-side-hero>img{display:block;width:100%;height:142px;object-fit:cover}.jobs-side-hero-copy{padding:18px 20px 12px;background:linear-gradient(135deg,#e8f3ff,#f9fcff)}.jobs-side-hero h2,.jobs-side-more h2,.jobs-side-tips h2{margin:0 0 7px;font-size:23px}.jobs-side-hero p,.jobs-side-more p{margin:0;font-size:14px;line-height:1.45}.jobs-help-row{display:grid;grid-template-columns:44px 1fr;gap:11px;padding:12px 20px;border-top:1px solid #deebed}.jobs-help-row>span{display:grid;place-items:center;width:40px;height:40px;border-radius:50%;background:#ddf1fb;color:#147492}.jobs-help-row.pin>span{background:#e1f5ec;color:#12896d}.jobs-help-row.star>span{background:#fff0cf;color:#db9611}.jobs-help-row svg{width:22px;height:22px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}.jobs-help-row h3{margin:0 0 2px;font-size:15px}.jobs-help-row p{margin:0;font-size:13px;line-height:1.35}.jobs-side-more{position:relative;display:grid;grid-template-columns:1fr 74px;gap:12px;padding:18px!important;background:linear-gradient(135deg,#e7f7f1,#f5fbf7)}.jobs-side-more h2{font-size:18px}.jobs-norway{display:grid;place-items:center;color:#4ca48a;font-size:53px;opacity:.7;transform:rotate(28deg)}.jobs-side-tips{padding:18px!important;background:#edf7ff}.jobs-side-tips h2{font-size:18px}.jobs-side-tips ul{margin:8px 0 0;padding:0;list-style:none}.jobs-side-tips li{position:relative;margin:7px 0;padding-left:21px;font-size:13px;line-height:1.35}.jobs-side-tips li:before{content:'✓';position:absolute;left:0;color:#15876b;font-weight:800}.jobs-side-tips a{font-weight:700}@media(max-width:1050px){.all-jobs-layout{grid-template-columns:1fr}.all-jobs-sidebar{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));align-items:start}.jobs-side-hero{grid-row:span 2}.jobs-side-hero>img{height:110px}}@media(max-width:700px){.all-jobs-filter{grid-template-columns:1fr;gap:9px;padding:10px}.all-jobs-filter .all-jobs-query,.all-jobs-county,.all-jobs-filter>button{width:100%;height:52px;min-height:52px}.all-jobs-heading{display:block}.all-jobs-pages{text-align:left;margin-top:12px}.all-jobs-pagination{justify-content:flex-start}.all-jobs-sidebar{display:flex}.jobs-side-hero>img{height:145px}.all-jobs-heading h2{font-size:29px}.all-jobs-pagination .page-link,.all-jobs-pagination .page-ellipsis{min-width:34px;height:34px}}"""
VACANCY_LIST_STYLE += """.all-jobs-filter .all-jobs-query .search-icon{position:absolute;top:50%;left:15px;width:22px;height:22px;flex:0 0 22px;transform:translateY(-50%);fill:none;stroke:#1b5960;stroke-width:2;stroke-linecap:round}"""
VACANCY_LIST_STYLE += """.jobs-side-hero{background:#fbfefd!important}.jobs-side-visual{position:relative;height:74px;overflow:hidden;border-bottom:1px solid #dcece7;background:linear-gradient(118deg,#e2f4ee 0%,#eaf5fb 56%,#dbeaf8 100%)}.jobs-side-visual:before{content:"";position:absolute;top:-36px;right:30px;width:110px;height:110px;border:18px solid #ffffff61;border-radius:50%}.jobs-side-visual:after{content:"";position:absolute;top:15px;left:26px;width:6px;height:6px;border-radius:50%;background:#42a88d;box-shadow:25px 12px #5aa9b8,65px -4px #7fc3ad,142px 17px #8dbed1,202px 0 #5da98f}.jobs-side-visual>span{position:absolute;z-index:2;top:15px;left:20px;width:34px;height:34px;border:1px solid #ffffffbd;border-radius:11px;background:#ffffffe0;box-shadow:0 5px 14px #1c655112}.jobs-side-visual>span:before{content:"";position:absolute;left:10px;top:8px;width:12px;height:12px;border:2px solid #28776a;border-radius:50%}.jobs-side-visual>span:after{content:"";position:absolute;left:22px;top:20px;width:8px;border-top:2px solid #28776a;transform:rotate(45deg);transform-origin:left}.jobs-side-visual svg{position:absolute;z-index:1;right:0;bottom:0;width:100%;height:54px}.jobs-side-horizon{fill:#c5e4df}.jobs-side-skyline{fill:#83b9b1;opacity:.68}.jobs-side-path{fill:none;stroke:#f9fffe;stroke-width:2;opacity:.8}.jobs-side-hero-copy{padding:13px 18px 10px;background:linear-gradient(135deg,#f4fbf8,#fbfefd)}.jobs-side-hero h2{margin:0 0 4px;font-size:21px;letter-spacing:-.025em}.jobs-side-hero p{margin:0;font-size:13px;line-height:1.4}.jobs-side-hero .jobs-help-row{display:grid;grid-template-columns:42px 1fr;gap:10px;padding:10px 18px;border-top:1px solid #e1ede8}.jobs-side-hero .jobs-help-row>span{display:grid;place-items:center;width:42px;height:42px;border-radius:50%;background:#e1f2fa;color:#197490}.jobs-side-hero .jobs-help-row.pin>span{background:#e0f3ea;color:#16836a}.jobs-side-hero .jobs-help-row.star>span{background:#fff1d5;color:#ca8914}.jobs-side-hero .jobs-help-row svg{width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}.jobs-side-hero .jobs-help-row h3{margin:1px 0 1px;font-size:14px;line-height:1.25}.jobs-side-hero .jobs-help-row p{margin:0;font-size:12.5px;line-height:1.3}@media(max-width:700px){.jobs-side-visual{height:70px}.jobs-side-hero-copy{padding:12px 16px 9px}.jobs-side-hero .jobs-help-row{padding:9px 16px}}"""
VACANCY_LIST_STYLE += """.jobs-side-hero{background:#fff!important}.jobs-side-hero-top{position:relative;min-height:238px;overflow:hidden;background:linear-gradient(135deg,#f2fbff 0%,#e8f7f3 100%)}.jobs-side-hero-copy{position:relative;z-index:2;width:62%;padding:34px 0 27px 34px;background:transparent}.jobs-side-kicker{display:block;margin-bottom:15px;color:#197a91;font-size:11px;font-weight:800;letter-spacing:.14em}.jobs-side-hero h2{max-width:290px;margin:0 0 15px;color:#083d4c;font-size:32px;line-height:1.04;letter-spacing:-.045em}.jobs-side-hero p{max-width:285px;margin:0;color:#526e7e;font-size:16px;line-height:1.4}.jobs-side-illustration{position:absolute;right:-7px;bottom:-5px;width:285px;height:auto}.jobs-side-hero .jobs-help-row{grid-template-columns:56px minmax(0,1fr) 24px;align-items:center;gap:17px;min-height:88px;padding:13px 26px;border-top:1px solid #dfe9eb;background:#fff}.jobs-side-hero .jobs-help-row>span{width:56px;height:56px;border-radius:17px;background:#e2f3fb;color:#087493}.jobs-side-hero .jobs-help-row.pin>span{background:#e1f5ed;color:#078b70}.jobs-side-hero .jobs-help-row.star>span{background:#fff1d8;color:#d28b08}.jobs-side-hero .jobs-help-row>span svg{width:31px;height:31px;stroke-width:2}.jobs-side-hero .jobs-help-row h3{margin:0 0 4px;color:#083d4c;font-size:18px;line-height:1.18;letter-spacing:-.025em}.jobs-side-hero .jobs-help-row p{max-width:none;margin:0;color:#607786;font-size:14px;line-height:1.35}.jobs-help-arrow{display:grid;place-items:center;width:24px;height:24px;color:#356171}.jobs-help-arrow svg{width:21px!important;height:21px!important;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}@media(max-width:1050px){.jobs-side-hero-top{min-height:220px}.jobs-side-hero-copy{padding:28px 0 23px 26px}.jobs-side-hero h2{font-size:28px}.jobs-side-illustration{width:255px}.jobs-side-hero .jobs-help-row{padding:12px 19px;gap:13px}}@media(max-width:700px){.jobs-side-hero-top{min-height:218px}.jobs-side-hero-copy{width:65%;padding:27px 0 22px 24px}.jobs-side-kicker{margin-bottom:12px}.jobs-side-hero h2{max-width:230px;margin-bottom:11px;font-size:28px}.jobs-side-hero p{max-width:245px;font-size:14px}.jobs-side-illustration{right:-34px;width:245px}.jobs-side-hero .jobs-help-row{grid-template-columns:54px minmax(0,1fr) 21px;gap:12px;min-height:82px;padding:11px 18px}.jobs-side-hero .jobs-help-row>span{width:54px;height:54px;border-radius:16px}.jobs-side-hero .jobs-help-row>span svg{width:29px;height:29px}.jobs-side-hero .jobs-help-row h3{font-size:16px}.jobs-side-hero .jobs-help-row p{font-size:13px}.jobs-help-arrow{width:21px;height:21px}}"""


HOME_STYLE += """
.home header .home-vakt-promo{position:absolute;z-index:2;top:50%;left:50%;display:grid;grid-template-columns:38px minmax(0,1fr) auto;align-items:center;gap:8px;width:min(560px,calc(100% - 460px));min-height:50px;margin:0;padding:6px 9px;border:1px solid #d6e8e2;border-radius:15px;background:#fffffff2;box-shadow:0 7px 22px #173d3a12;transform:translate(-50%,-50%)}.home header .home-vakt-promo:hover{border-color:#acd7c9}.home-vakt-robot{display:grid;place-items:center;width:36px;height:36px;border-radius:11px;background:linear-gradient(145deg,#d9f4ed,#d9effb);color:#146a60}.home-vakt-robot svg{width:24px;height:24px;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round;transform-origin:center;transform-box:fill-box}.home-vakt-copy{min-width:0}.home-vakt-copy span{display:block;font-size:10px;font-weight:700;letter-spacing:.04em;color:#297966}.home-vakt-copy strong{display:block;font-size:13px;line-height:1.25;color:#163e3b}.home-vakt-promo .button{padding:8px 12px;border-radius:10px;background:#176c5c;color:#fff;font-size:12px;font-weight:700;white-space:nowrap}.home-vakt-promo .button:hover{background:#145b4e}.home-vakt-promo:hover .home-vakt-robot svg{animation:vakt-robot-greeting .42s ease-in-out 1}.home-vakt-promo:hover .robot-eye{animation:vakt-robot-blink .22s ease-in-out 1}@keyframes vakt-robot-greeting{0%,100%{transform:none}45%{transform:rotate(-5deg) translateY(-1px)}70%{transform:rotate(3deg)}}@keyframes vakt-robot-blink{50%{transform:scaleY(.18)}}@media(max-width:700px){.home header .home-vakt-promo{left:auto;right:76px;width:118px;min-height:38px;grid-template-columns:28px minmax(0,1fr) auto;gap:5px;padding:5px 6px;transform:translateY(-50%)}.home-vakt-robot{width:28px;height:28px;border-radius:9px}.home-vakt-robot svg{width:20px;height:20px}.home-vakt-copy span{display:none}.home-vakt-copy strong{font-size:0}.home-vakt-copy strong:before{content:"Vakt";font-size:11px;font-weight:700}.home-vakt-promo .button{padding:6px 7px;font-size:10px}}@media(prefers-reduced-motion:reduce){.home-vakt-promo:hover .home-vakt-robot svg,.home-vakt-promo:hover .robot-eye{animation:none}}
"""

VACANCY_LIST_STYLE += JOBS_SIDEBAR_REFERENCE_STYLE
VACANCY_LIST_STYLE += """.jobs-side-hero-top{display:block;position:relative;height:230px;overflow:hidden;background:linear-gradient(135deg,#f2fbff 0%,#e8f7f3 100%)}.jobs-side-hero-copy{position:relative;z-index:2;width:65%;padding:26px 0 20px 30px}.jobs-side-kicker{margin-bottom:13px;font-size:11px;letter-spacing:.16em}.jobs-side-hero h2{max-width:260px;margin:0 0 10px;font-size:29px;line-height:1.1;letter-spacing:-.04em}.jobs-side-hero p{max-width:275px;font-size:15px;line-height:1.35}.jobs-side-illustration{position:absolute;z-index:1;right:0;bottom:0;width:52%;height:100%;mask-image:linear-gradient(to right,transparent 0%,#000 43%);-webkit-mask-image:linear-gradient(to right,transparent 0%,#000 43%)}.jobs-side-illustration rect{fill:transparent}.jobs-side-hero .jobs-help-row{grid-template-columns:45px minmax(0,1fr) 17px;gap:17px;height:82px;min-height:0;padding:11px 25px}.jobs-side-hero .jobs-help-row>span{width:45px;height:45px;border-radius:15px}.jobs-side-hero .jobs-help-row>span svg{width:22px;height:22px}.jobs-side-hero .jobs-help-row h3{margin:0 0 3px;font-size:17px;line-height:1.2}.jobs-side-hero .jobs-help-row p{font-size:14px;line-height:1.3}.jobs-help-arrow{width:17px;height:17px}.jobs-help-arrow svg{width:17px!important;height:17px!important}@media(max-width:1300px){.jobs-side-hero-copy{width:66%;padding-left:26px}.jobs-side-hero h2{max-width:235px;font-size:29px}.jobs-side-hero p{max-width:240px}.jobs-side-illustration{width:51%}.jobs-side-hero .jobs-help-row{gap:14px;padding-right:21px;padding-left:21px}}@media(max-width:700px){.jobs-side-hero-top{height:220px}.jobs-side-hero-copy{width:68%;padding:24px 0 18px 22px}.jobs-side-kicker{margin-bottom:11px}.jobs-side-hero h2{max-width:215px;margin-bottom:9px;font-size:27px}.jobs-side-hero p{max-width:230px;font-size:14px}.jobs-side-illustration{width:53%}.jobs-side-hero .jobs-help-row{grid-template-columns:45px minmax(0,1fr) 17px;gap:12px;height:80px;padding:10px 18px}.jobs-side-hero .jobs-help-row>span{width:45px;height:45px}.jobs-side-hero .jobs-help-row>span svg{width:22px;height:22px}.jobs-side-hero .jobs-help-row h3{font-size:16px}.jobs-side-hero .jobs-help-row p{font-size:13px}}"""
VACANCY_LIST_STYLE += """.jobs-side-hero{overflow:hidden;border-radius:22px!important}.jobs-side-hero-top{background:linear-gradient(135deg,#f3fbff 0%,#edf9f8 46%,#e1f4f1 100%)}.jobs-side-kicker{letter-spacing:.13em}.jobs-side-hero h2{margin-bottom:8px;font-weight:700}.jobs-side-hero p{line-height:1.4}.jobs-side-illustration>path:nth-of-type(1){fill:#dff2ef}.jobs-side-illustration>path:nth-of-type(2){fill:#b7e0da}.jobs-side-illustration>path:nth-of-type(4){fill:#e3f4f1}.jobs-side-hero>.jobs-help-row{grid-template-columns:43px minmax(0,1fr) 16px;gap:16px;height:78px;min-height:0;margin:0;padding:9px 25px;border:0;border-top:1px solid #dfe9e8!important;border-radius:0!important;box-shadow:none!important;background:#fff}.jobs-side-hero>.jobs-help-row>span{width:43px;height:43px;border-radius:14px}.jobs-side-hero>.jobs-help-row>span svg{width:21px;height:21px}.jobs-side-hero>.jobs-help-row h3{margin:0 0 2px;font-size:17px}.jobs-side-hero>.jobs-help-row p{font-size:13.5px;line-height:1.32}.jobs-side-hero .jobs-help-arrow{width:16px;height:16px}.jobs-side-hero .jobs-help-arrow svg{width:16px!important;height:16px!important}@media(max-width:1300px){.jobs-side-hero>.jobs-help-row{gap:13px;padding-right:21px;padding-left:21px}}@media(max-width:700px){.jobs-side-hero>.jobs-help-row{grid-template-columns:43px minmax(0,1fr) 16px;gap:12px;height:76px;padding:8px 18px}.jobs-side-hero>.jobs-help-row>span{width:43px;height:43px}.jobs-side-hero>.jobs-help-row>span svg{width:21px;height:21px}}"""
VACANCY_LIST_STYLE += """.jobs-side-hero{border-radius:24px!important}.jobs-side-hero-top{height:200px;background:#eaf8f8}.jobs-side-hero-image{position:absolute;inset:0;z-index:0;display:block;width:100%;height:100%;object-fit:cover;object-position:50% 56%}.jobs-side-hero-top:after{content:"";position:absolute;z-index:1;inset:0;background:linear-gradient(90deg,#f5fcff 0%,#f3fbfddd 35%,#effaf771 53%,transparent 74%);pointer-events:none}.jobs-side-hero-copy{position:absolute;z-index:2;top:26px;left:28px;width:52%;padding:0}.jobs-side-kicker{margin-bottom:12px;font-size:11px;font-weight:700;letter-spacing:.094em}.jobs-side-hero h2{max-width:none;margin:0 0 8px;font-size:28px;line-height:1.1}.jobs-side-hero p{max-width:none;margin:0;font-size:15px;line-height:1.4}.jobs-side-hero>.jobs-help-row{grid-template-columns:42px minmax(0,1fr) 16px;gap:16px;height:76px;padding:8px 24px}.jobs-side-hero>.jobs-help-row>span{width:42px;height:42px;border-radius:14px}.jobs-side-hero>.jobs-help-row>span svg{width:20px;height:20px}.jobs-side-hero>.jobs-help-row p{font-size:14px;line-height:1.3}@media(max-width:1300px){.jobs-side-hero>.jobs-help-row{padding-right:24px;padding-left:24px}}@media(max-width:700px){.jobs-side-hero-copy{top:22px;left:22px;width:58%}.jobs-side-hero h2{font-size:27px}.jobs-side-hero p{font-size:14px}.jobs-side-hero>.jobs-help-row{grid-template-columns:42px minmax(0,1fr) 16px;height:76px;padding:8px 18px}.jobs-side-hero>.jobs-help-row>span{width:42px;height:42px}.jobs-side-hero>.jobs-help-row>span svg{width:20px;height:20px}}"""
VACANCY_LIST_STYLE += """.jobs-side-hero>.jobs-help-row.search>span{display:grid;place-items:center}.jobs-side-hero>.jobs-help-row.search>span .search-icon{position:static!important;top:auto!important;left:auto!important;display:block;width:20px;height:20px;margin:0!important;transform:none!important;flex:none}.all-jobs-heading h2{font-size:29px;font-weight:650}"""
VACANCY_LIST_STYLE += """
.all-jobs-sidebar>.jobs-side-more{display:flex;flex-direction:column;min-height:586px;padding:0!important;overflow:hidden;border:1px solid #d9e8e5;border-radius:24px!important;background:#f8fcfb;box-shadow:0 8px 22px #194d4610}
.jobs-more-main{position:relative;min-height:386px;overflow:hidden;background:linear-gradient(135deg,#f6fcfb 0%,#eef9f7 100%)}
.jobs-more-image{position:absolute;inset:0 0 0 auto;width:58%;height:100%;object-fit:cover;object-position:72% 50%;opacity:.96}
.jobs-more-main:after{content:"";position:absolute;inset:0;background:linear-gradient(90deg,#f8fcfb 0%,#f8fcfbe8 43%,#f8fcfb48 62%,transparent 78%);pointer-events:none}
.jobs-more-copy{position:relative;z-index:1;width:63%;padding:27px 0 20px 27px}
.jobs-more-kicker{display:block;margin-bottom:9px;color:#197a70;font-size:10px;font-weight:800;letter-spacing:.14em}
.jobs-side-more .jobs-more-copy h2{max-width:275px;margin:0 0 7px;color:#083f48;font-size:25px;line-height:1.1;letter-spacing:-.035em}
.jobs-side-more .jobs-more-copy>p{max-width:280px;margin:0;color:#55737a;font-size:13px;line-height:1.42}
.jobs-more-counties{display:grid;gap:5px;margin-top:17px}
.jobs-more-county{display:grid;grid-template-columns:46px minmax(0,1fr) 14px;align-items:center;gap:9px;min-height:48px;padding:0 8px 0 5px;border:1px solid #dcebe7;border-radius:12px;background:#ffffffd9;color:#113f46;text-decoration:none;box-shadow:0 2px 8px #174b4108}
@media(min-width:701px){.jobs-more-county{width:calc(100% - 33px)}}
.jobs-more-county:hover{border-color:#a5d4c6;background:#fff}.jobs-more-county:focus-visible{outline-offset:2px}
.jobs-more-county-thumbnail,.jobs-more-county-tile{position:relative;display:grid;place-items:center;width:46px;height:46px;overflow:hidden;border-radius:13px}.jobs-more-county-thumbnail img{display:block;width:100%;height:100%;object-fit:cover}.jobs-more-county-tile{background:#def2ec;color:#15866f}.jobs-more-county-tile:before{content:"";width:16px;height:10px;border:2px solid currentColor;border-radius:7px 7px 5px 5px;transform:rotate(-21deg)}.jobs-more-county-tile i{position:absolute;width:6px;height:6px;border-radius:50%;background:currentColor;box-shadow:8px -8px 0 -1px #46ad92}
.jobs-more-county-copy{min-width:0}.jobs-more-county-copy b,.jobs-more-county-copy small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.jobs-more-county-copy b{font-size:12px;line-height:1.22}.jobs-more-county-copy small{margin-top:2px;color:#5b7779;font-size:10px;line-height:1.2}.jobs-more-county-arrow{color:#3a6f74;font-size:22px;font-weight:400;line-height:1}
.jobs-more-insight{padding:16px 27px 13px;border-top:1px solid #dbeae6;background:#fff}.jobs-more-insight strong{display:block;color:#0a4148;font-size:16px;line-height:1.17;letter-spacing:-.025em}.jobs-more-insight p{margin:6px 0 0;color:#63807d;font-size:12px;line-height:1.38}
.jobs-more-all{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:0 17px 17px;padding:11px 12px;border:1px solid #cfe5dd;border-radius:13px;background:#edf8f4;color:#124b47;text-decoration:none}.jobs-more-all:hover{border-color:#9dcebd;background:#e4f4ed}.jobs-more-all b,.jobs-more-all small{display:block}.jobs-more-all b{font-size:13px;line-height:1.25}.jobs-more-all small{margin-top:2px;color:#5b7775;font-size:11px;line-height:1.25}.jobs-more-all i{font-size:18px;font-style:normal}
@media(max-width:1050px){.all-jobs-sidebar>.jobs-side-more{min-height:510px}.jobs-more-main{min-height:334px}.jobs-more-copy{padding:23px 0 16px 22px}.jobs-side-more .jobs-more-copy h2{font-size:22px}.jobs-more-counties{margin-top:13px}.jobs-more-county{min-height:48px}.jobs-more-insight{padding:13px 22px 11px}.jobs-more-all{margin:0 14px 14px}}
@media(max-width:700px){.all-jobs-sidebar>.jobs-side-more{min-height:0;min-width:0}.jobs-more-main{display:flex;flex-direction:column;min-height:0;background:#f5fcfa}.jobs-more-main:after{display:none}.jobs-more-copy{order:0;width:auto;padding:24px 21px 17px}.jobs-side-more .jobs-more-copy h2{max-width:310px;font-size:25px}.jobs-side-more .jobs-more-copy>p{max-width:330px;font-size:14px}.jobs-more-counties{gap:7px;margin-top:16px}.jobs-more-county{grid-template-columns:46px minmax(0,1fr) 15px;min-height:52px;padding:2px 9px 2px 6px}.jobs-more-county-thumbnail,.jobs-more-county-tile{width:46px;height:46px}.jobs-more-county-copy b{font-size:13px}.jobs-more-county-copy small{font-size:11px}.jobs-more-image{position:static;order:1;width:100%;height:210px;object-position:72% 55%;opacity:1}.jobs-more-insight{min-width:0;padding:18px 21px 14px}.jobs-more-insight strong{font-size:18px}.jobs-more-insight p{max-width:280px;overflow-wrap:anywhere;font-size:13px}.jobs-more-all{margin:0 15px 15px;padding:12px 13px}.jobs-more-all>span{min-width:0}.jobs-more-all small{white-space:normal;overflow-wrap:anywhere}}
"""
VACANCY_LIST_STYLE += """
.all-jobs-sidebar>.jobs-side-tips{padding:0!important;overflow:hidden;border:1px solid #d8e9e5;border-radius:24px!important;background:#fbfefd;box-shadow:0 7px 20px #194d460c}
.jobs-tips-head{display:grid;grid-template-columns:42px minmax(0,1fr);gap:13px;align-items:start;padding:20px 22px 15px;background:#f7fdfb}.jobs-tips-head>div{min-width:0}
.jobs-tips-bulb,.jobs-tips-icon{display:grid;place-items:center;flex:0 0 42px;width:42px;height:42px;border-radius:14px;background:#e5f5ef;color:#075f58}
.jobs-tips-bulb svg,.jobs-tips-icon svg{width:21px;height:21px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.jobs-tips-bulb svg{filter:drop-shadow(0 0 5px #f4d96a88)}
.jobs-side-tips .jobs-tips-head h2{margin:0 0 3px;color:#083d4c;font-size:21px;line-height:1.18;letter-spacing:-.03em}.jobs-side-tips .jobs-tips-head p{margin:0;color:#647c88;font-size:14px;line-height:1.35}
.jobs-side-tips .jobs-tips-row{display:grid;grid-template-columns:42px minmax(0,1fr) 16px;align-items:center;gap:13px;width:100%;min-height:74px;padding:10px 22px;border:0;border-top:1px solid #deebe8;border-radius:0;background:transparent;color:#093e48;text-align:left;text-decoration:none;cursor:pointer;font:inherit}.jobs-side-tips .jobs-tips-row:hover{background:#f4fbf8;color:#093e48}.jobs-side-tips .jobs-tips-row:focus-visible{position:relative;z-index:1;outline:3px solid #83b9aa;outline-offset:-3px}
.jobs-tips-copy{min-width:0}.jobs-tips-copy b,.jobs-tips-copy small{display:block}.jobs-tips-copy b{font-size:16px;line-height:1.24;font-weight:700;letter-spacing:-.02em}.jobs-tips-copy small{margin-top:3px;color:#637b87;font-size:13px;line-height:1.3}.jobs-tips-arrow{display:grid;place-items:center;width:16px;height:16px;color:#2b6570}.jobs-tips-arrow svg{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round}
@media(max-width:1050px){.jobs-tips-head{padding:18px 18px 13px}.jobs-side-tips .jobs-tips-row{gap:11px;padding-right:18px;padding-left:18px}}
@media(max-width:700px){.all-jobs-sidebar>.jobs-side-tips{max-width:100%;min-width:0}.jobs-tips-head{padding:19px 18px 14px}.jobs-side-tips .jobs-tips-head p,.jobs-side-tips .jobs-tips-copy small{white-space:normal;overflow-wrap:anywhere}.jobs-side-tips .jobs-tips-row{grid-template-columns:42px minmax(0,1fr) 16px;gap:12px;min-height:72px;padding:9px 18px}.jobs-tips-copy b{font-size:16px}.jobs-tips-copy small{font-size:13px;overflow-wrap:anywhere}}
"""

HOME_STYLE += ".home header .home-vakt-promo{background:#E6F3FA;border-color:#C7E1EE}.home-vakt-robot{background:#D8F1E7}"

HOME_STYLE += """.home .search{position:relative;padding-left:44px}.home .search-icon{position:absolute;left:15px;top:50%;display:block;margin:0;transform:translateY(-50%)}@media(max-width:850px){.home .search-icon{display:block}}"""

HOME_STYLE += """@media(max-width:600px){.home header .home-vakt-promo{display:grid}.home .home-vakt-copy{display:none}.home .hero{padding:18px 18px 12px;gap:14px}.home .hero-brand{font-size:48px}.home .hero .hero-tagline{font-size:30px;line-height:1.15;margin:8px 0 6px}.home .hero .intro{font-size:15px;line-height:1.4;margin:0}.home .hero-signpost{height:220px;margin:-2px auto -12px;align-self:end;object-position:center bottom}.home .scenario-choices{gap:10px;margin-top:-2px}.home .scenario-choices a{padding:17px;gap:10px}.home .scenario-choices strong{font-size:18px}}"""

VACANCY_LIST_STYLE += """
.all-jobs-filter{grid-template-columns:minmax(260px,1.55fr) minmax(145px,.7fr) minmax(165px,.82fr) max-content}
.all-jobs-municipality{position:relative;min-height:54px;padding:5px 8px 5px 43px;border:1px solid #d2e0da;border-radius:12px;background:#fff}
.all-jobs-municipality>svg{position:absolute;top:15px;left:13px;width:22px;height:22px;fill:none;stroke:#1b5960;stroke-width:2;stroke-linecap:round;pointer-events:none}
.all-jobs-filter .all-jobs-municipality input{width:100%;min-height:42px;padding:8px;font-size:16px}
@media(min-width:701px) and (max-width:1050px){.all-jobs-filter{grid-template-columns:minmax(0,1fr) minmax(0,.72fr)}.all-jobs-filter>button{grid-column:2}}
@media(max-width:700px){.all-jobs-filter{grid-template-columns:minmax(0,1fr);gap:10px;padding:10px}.all-jobs-filter>button{grid-column:1;width:100%}}
"""


def home_data_details(lang):
    tr = lambda key: e(t(lang, key))
    return (f'<details class="disclosure" id="datagrunnlag"><summary>{tr("home.data_title")}</summary>'
            f'<p>{tr("home.data_copy_1")}</p><p>{tr("home.data_copy_2")}</p>'
            f'<p>{tr("home.data_copy_3")}</p><p>{tr("home.data_copy_4")}</p></details>')


def render_all_jobs(county="", job="", page=1, params=None, lang="no",
                    profession="", municipality=""):
    params = params or {}
    lang = normalize_lang(lang)
    preserve_lang = lang == "en" or "lang" in params
    if job:
        body = site_header("search", params, lang) + all_jobs_detail(
            job, county, page, lang, preserve_lang, profession, municipality)
        return page_document(lang, t(lang, "jobs.title"), EXPLORE_DETAIL_STYLE,
                             "explore-detail regional-detail", body, params)
    body = site_header("search", params, lang) + all_jobs_page(
        county, page, lang, preserve_lang, profession, municipality)
    return page_document(lang, t(lang, "jobs.title"), VACANCY_LIST_STYLE, "vacancy-list-page", body, params)


def render_job_detail(query, county, job, params, lang):
    loaded = load_detail_job(job)
    preserve_lang = lang == "en" or "lang" in params
    body = site_header('search', params, lang)
    # Unavailable ads need neither historical analytics nor related-job matching.
    row = detail_region_data(query, county) if loaded[0] is not None else None
    if loaded[0] is not None and row is None:
        body += '<p class="empty">Fylket finnes ikke i dette utvalget.</p>'
    else:
        current_county = row['fylke'] if row else county.upper()
        body += job_detail(query, current_county, job, lang=lang,
                           preserve_lang=preserve_lang, loaded=loaded)
    body += data_details([row] if row else [])
    return page_document(lang, t(lang, 'home.title'), EXPLORE_DETAIL_STYLE,
                         'explore-detail regional-detail', body, params)


def render(query="", county="", job="", params=None, lang="no"):
    params = params or {}
    lang = normalize_lang(lang)
    if job and county and normalize(query):
        return render_job_detail(query, county, job, params, lang)
    preserve_lang = lang == "en" or "lang" in params
    tr = lambda key: e(t(lang, key))
    lang_input = f'<input type="hidden" name="lang" value="{lang}">' if preserve_lang else ''
    if query and normalize(query):
        body = site_header('search', params, lang)
        body += f'<form class="result-search" method="get" action="/"><label for="profession">{tr("home.search_label")}</label>{lang_input}<div class="search"><input id="profession" name="q" data-autocomplete autocomplete="off" placeholder="{tr("home.search_placeholder")}" value="{e(query)}" maxlength="120" required><button data-loading-label="{tr("home.searching")}">{tr("home.search_cta")}</button></div></form>'
        rows, summary = features(normalize(query))
        counties, areas = result_regions(rows)
        if not county and summary['total'] - summary['weak'] > 0:
            body += f'<h2>Jobbmuligheter for {e(query)}</h2><p>Se hvor vi har funnet relevante annonser for yrket ditt.</p>'
        if county:
            valid = {r['fylke'].casefold(): r['fylke'] for r in counties + areas}
            if county.casefold() in valid:
                current_county = valid[county.casefold()]
                if job:
                    body += job_detail(query, current_county, job, lang=lang, preserve_lang=preserve_lang)
                else:
                    back = internal_url({}, q=query, lang=lang) if preserve_lang else internal_url({}, q=query)
                    body += f'<p><a href="{e(back)}">&larr; Tilbake til fylkene</a></p>' + vacancies(query, current_county, lang=lang, preserve_lang=preserve_lang)
            else:
                body += '<p class="empty">Fylket finnes ikke i dette utvalget.</p>'
        elif summary['total'] - summary['weak'] == 0:
            body += f'<p class="empty">Vi fant ingen relevante stillinger for &laquo;{e(query)}&raquo;. Sjekk skrivemåten eller prøv en annen yrkestittel.</p>'
            counties, areas = [], []
        else:
            body += '<div class="grid top-five">' + ''.join(region_card(r, query, lang, preserve_lang) for r in counties[:5]) + '</div>'
            if counties[5:]:
                body += '<details class="disclosure"><summary>Vis alle fylker</summary><div class="grid">' + ''.join(region_card(r, query, lang, preserve_lang) for r in counties[5:]) + '</div></details>'
            if areas:
                body += '<details class="disclosure"><summary>Andre områder</summary><div class="grid">' + ''.join(region_card(r, query, lang, preserve_lang) for r in areas) + '</div></details>'
        body += data_details(counties + areas)
    else:
        search = local_nav_url(lang=lang, fragment='profession', include_lang=preserve_lang)
        explore = local_nav_url('explore', lang, include_lang=preserve_lang)
        hero = f'''<section class="hero"><div class="hero-copy"><h1 class="hero-brand">Jobb<span>Peil</span></h1><p class="hero-tagline">{tr("home.eyebrow")}</p><p class="intro">{tr("home.hero_intro_short")}</p></div><img class="hero-signpost" src="/static/jobbpeil-signpost.png" alt="{tr("home.signpost_alt")}" fetchpriority="high"><div class="scenario-choices"><a href="{e(search)}"><span class="choice-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="3" y="7" width="18" height="14" rx="3"/><path d="M8 7V4h8v3M3 12c5 4 13 4 18 0M12 12v4"/></svg></span><strong>{tr("home.choice_search_title")}</strong><span>{tr("home.choice_search_copy")}</span><span class="choice-cta">{tr("home.choice_search_cta")} <i aria-hidden="true">&rarr;</i></span></a><a href="{e(explore)}"><span class="choice-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="m16 7-3 7-6 3 3-7Z"/></svg></span><strong>{tr("home.choice_explore_title")}</strong><span>{tr("home.choice_explore_copy")}</span><span class="choice-cta">{tr("home.choice_explore_cta")} <i aria-hidden="true">&rarr;</i></span></a></div></section>'''
        form = f'''<form method="get" action="/"><label for="profession">{tr("home.search_label")}</label>{lang_input}<input type="hidden" name="mode" value="jobs"><div class="search"><svg class="search-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="10" cy="10" r="6.5"/><path d="m15 15 6 6"/></svg><input id="profession" name="q" data-autocomplete autocomplete="off" placeholder="{tr("home.search_placeholder")}" value="" maxlength="120"><button data-loading-label="{tr("home.searching")}">{tr("home.search_cta")}</button></div></form>'''
        strip = f'''<div class="fact-strip"><div><strong>{tr("home.fact_region_title")}</strong><span>{tr("home.fact_region_copy")}</span></div><div><strong>{tr("home.fact_people_title")}</strong><span>{tr("home.fact_people_copy")}</span></div><div><strong>{tr("home.fact_data_title")}</strong><span>{tr("home.fact_data_copy")}</span></div></div>'''
        vakt = local_nav_url('vakt', lang, include_lang=preserve_lang)
        promo = f'<aside class="home-vakt-promo"><span class="home-vakt-robot"><svg viewBox="0 0 32 32" aria-hidden="true"><rect x="6" y="10" width="20" height="16" rx="5"/><path d="M16 5v5M12 21c2 1 6 1 8 0M3 16h3m20 0h3"/><circle class="robot-eye" cx="13" cy="17" r=".8"/><circle class="robot-eye" cx="19" cy="17" r=".8"/><circle cx="16" cy="4" r="1"/></svg></span><span class="home-vakt-copy"><span>{tr("vakt.badge")}</span><strong>{tr("vakt.title")} &middot; {tr("vakt.promo_copy")}</strong></span><a class="button" href="{e(vakt)}">{tr("vakt.try")} &rarr;</a></aside>'
        header = site_header('', params, lang, homepage=True).replace('</header>', promo + '</header>', 1)
        body = header + hero + form + strip + home_data_details(lang)
    homepage = not (query and normalize(query))
    results_page = not homepage and not county
    vacancy_list_page = not homepage and bool(county) and not job
    regional_detail_page = not homepage and bool(county) and bool(job)
    if vacancy_list_page:
        body = site_header('search', params, lang) + body[body.index('</header>') + len('</header>'):]
        body = body.replace('<div class="search">', '<div class="search"><svg class="search-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="10" cy="10" r="6.5"/><path d="m15 15 6 6"/></svg>', 1)
    if results_page:
        body = body.replace('<span class="badge">Middels datagrunnlag</span>', '<span class="badge badge-medium">Middels datagrunnlag</span>')
        body = site_header('search', params, lang) + body[body.index('</header>') + len('</header>'):]
        if summary['total'] - summary['weak'] > 0:
            body += '<span class="direction-note" aria-hidden="true">Se hvor mulighetene er størst</span>'
        body += '<div class="results-facts"><div><strong>Reelle annonser</strong><span>Basert på lagrede NAV-annonser.</span></div><div><strong>Regionfokus</strong><span>Se annonser fordelt på fylke.</span></div><div><strong>Fakta med forklaring</strong><span>Perioder og begrensninger i datagrunnlaget.</span></div></div>'
    if regional_detail_page:
        body = site_header('search', params, lang) + body[body.index('<section class="explore-job'):]
    page_style = HOME_STYLE if homepage else RESULT_STYLE if results_page else VACANCY_LIST_STYLE if vacancy_list_page else EXPLORE_DETAIL_STYLE if regional_detail_page else ''
    page_class = 'home' if homepage else 'results-page' if results_page else 'vacancy-list-page' if vacancy_list_page else 'explore-detail regional-detail' if regional_detail_page else ''
    return page_document(lang, t(lang, 'home.title'), page_style, page_class, body, params)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # A detached/closed console must not abort send_response before headers.
        try:
            if "token" in parse_qs(urlsplit(self.path).query, keep_blank_values=True, max_num_fields=20):
                return
        except ValueError:
            return
        try:
            super().log_message(format, *args)
        except (OSError, ValueError, AttributeError):
            pass

    def do_GET(self):
        parts = urlsplit(self.path)
        if parts.path in ("/static/jobbpeil-bg.png", "/static/jobbpeil-signpost.png", "/static/jobbpeil-explore-bg.png", "/static/oslo-waterfront.png", "/static/jobbpeil-vakt-mascot.png", "/static/jobbpeil-sidebar-hero.png", "/static/jobbpeil-norway-opportunities.png", "/static/regions/oslo.png", "/static/regions/vestland.png", "/static/regions/akershus.png", "/static/regions/trondelag.png", "/static/regions/rogaland.png"):
            asset = Path(__file__).resolve().parent / parts.path.lstrip("/")
            # Accept the supplied Windows filenames with a doubled extension.
            if not asset.is_file():
                asset = asset.with_name(asset.name + ".png")
            try:
                stat = asset.stat()
                etag = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
                if self.headers.get("If-None-Match") == etag:
                    self.send_response(304)
                    self.send_header("Cache-Control", "public, max-age=3600, must-revalidate")
                    self.send_header("ETag", etag)
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    return
                raw = asset.read_bytes()
            except OSError:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "public, max-age=3600, must-revalidate")
            self.send_header("ETag", etag)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(raw)
            return
        if parts.path != "/":
            self.send_error(404)
            return
        params = parse_qs(parts.query)
        query, county = params.get("q", [""])[0].strip(), params.get("fylke", [""])[0].strip()
        municipality = params.get("kommune", [""])[0].strip()
        lang = normalize_lang(params.get("lang", [""])[0])
        if len(query) > 120 or len(county) > 120 or len(municipality) > 120:
            self.send_error(400)
            return
        if params.get("mode") == ["suggestions"]:
            raw = json.dumps(autocomplete_suggestions(query), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)
            return
        if params.get("mode") == ["municipality_suggestions"]:
            raw = json.dumps(municipality_suggestions(municipality), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)
            return
        try:
            page = max(int(params.get("page", ["1"])[0]), 1)
        except ValueError:
            page = 1
        status = 200
        try:
                page = (render_all_jobs(county, params.get('job', [''])[0], page, params, lang,
                            query, municipality)
                    if params.get('mode') == ['jobs'] else explore_page(params, lang)
                    if params.get('mode') == ['explore'] else about_page(params, lang)
                    if params.get('mode') == ['about'] else privacy_page(params, lang)
                    if params.get('mode') == ['personvern'] else contact_page(params, lang)
                    if params.get('mode') == ['kontakt'] else vakt_verify_page(params, lang)
                    if params.get('mode') == ['vakt_verify'] else vakt_unsubscribe_page(params, lang)
                    if params.get('mode') == ['vakt_unsubscribe'] else vakt_page(params, lang)
                    if params.get('mode') == ['vakt'] else render(query, county, params.get('job', [''])[0], params, lang))
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
            status = 503
            home = internal_url({}, lang=lang) if lang == 'en' else '/'
            document_lang = 'en' if lang == 'en' else 'nb'
            page = f'<html lang="{document_lang}"><meta charset="utf-8"><h1>{e(t(lang, "error.data_title"))}</h1><p>{e(t(lang, "error.data_copy"))}</p><a href="{e(home)}">{e(t(lang, "error.home"))}</a></html>'
        raw = page.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        if params.get("mode") == ["vakt_verify"]:
            self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'none'; connect-src 'self' https://www.google-analytics.com https://analytics.google.com https://region1.google-analytics.com; img-src 'self'; script-src 'sha256-" + SCRIPT_HASH + "' 'sha256-pz9Z/26XP+y8pSumaekFZ2WWFfB7LSQ9/+EE3bhU74A=' https://www.googletagmanager.com; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        parts = urlsplit(self.path)
        params = parse_qs(parts.query)
        if parts.path != '/' or params.get('mode') not in (['vakt'], ['vakt_verify']):
            self.send_error(405)
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            self.send_error(400)
            return
        if length < 0 or length > 16384:
            self.send_error(413)
            return
        content_type = self.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
        if params.get('mode') == ['vakt_verify']:
            success = False
            if content_type == 'application/x-www-form-urlencoded':
                try:
                    payload = self.rfile.read(length).decode('utf-8')
                    form = parse_qs(payload, keep_blank_values=True, max_num_fields=2)
                    tokens = form.get('token', [])
                    if len(tokens) == 1:
                        success = verify_vakt_subscription(tokens[0])
                except (UnicodeDecodeError, ValueError):
                    success = False
                except (OSError, sqlite3.Error):
                    success = False
            page = vakt_lifecycle_page('vakt_verify', success, normalize_lang(params.get('lang', [''])[0]))
            raw = page.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header("Content-Security-Policy", "default-src 'none'; connect-src 'self' https://www.google-analytics.com https://analytics.google.com https://region1.google-analytics.com; img-src 'self'; script-src 'sha256-" + SCRIPT_HASH + "' 'sha256-pz9Z/26XP+y8pSumaekFZ2WWFfB7LSQ9/+EE3bhU74A=' https://www.googletagmanager.com; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(raw)
            return
        error_code = None
        confirmation_email = None
        form = {}
        if content_type != 'application/x-www-form-urlencoded':
            error_code = 'invalid_form'
        else:
            try:
                payload = self.rfile.read(length).decode('utf-8')
                form = parse_qs(payload, keep_blank_values=True, max_num_fields=10)
                subscription = validate_vakt_form(form)
                saved_subscription = save_vakt_subscription(subscription, return_subscription=True)
                if (not saved_subscription["active"]
                        and saved_subscription["verification_token"]):
                    try:
                        send_vakt_confirmation_email(
                            saved_subscription["email"],
                            saved_subscription["verification_token"],
                            profession_query=subscription["profession_query"],
                            fylke=subscription["fylke"],
                        )
                    except Exception as error:
                        self.log_error(
                            "Vakt confirmation email failed: %s",
                            type(error).__name__,
                        )
                        error_code = 'email_delivery'
                    else:
                        confirmation_email = saved_subscription["email"]
            except VaktValidationError as error:
                error_code = error.code
            except (UnicodeDecodeError, ValueError):
                error_code = 'invalid_form'
            except (OSError, sqlite3.Error):
                error_code = 'unavailable'

        lang = normalize_lang(params.get('lang', [''])[0])
        target_params = {'mode': 'vakt'}
        if lang == 'en' or 'lang' in params:
            target_params['lang'] = lang
        if error_code is None:
            if confirmation_email:
                target_params['vakt_notice'] = 'confirmation_sent'
                target_params['vakt_email'] = confirmation_email
            else:
                target_params['vakt_notice'] = 'registered'
        else:
            target_params['vakt_error'] = error_code
            profession_values = form.get('profession', [])
            if len(profession_values) == 1:
                profession = profession_values[0].strip()
                if 0 < len(profession) <= VAKT_PROFESSION_MAX_LENGTH:
                    target_params['vakt_profession'] = profession
            county_values = form.get('county', [])
            if len(county_values) == 1:
                county_key = vakt_text_key(county_values[0])
                county = next((item for item in FYLKE_OPTIONS if vakt_text_key(item) == county_key), None)
                if county:
                    target_params['vakt_county'] = county
        target = internal_url(target_params)
        self.send_response(303)
        self.send_header('Location', target)
        self.send_header('Content-Length', '0')
        self.end_headers()


if __name__ == "__main__":
    initialize_database(DATABASE)
    print("Åpne http://127.0.0.1:8000 — stopp med Ctrl+C", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
