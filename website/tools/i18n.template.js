/* Liga localization. The editable Portuguese catalogue is compiled by build_i18n.py.
   New interface copy uses data-i18n keys and JSON data-i18n-vars. Interpolation is
   plain text: user names and PGN metadata are never treated as translation keys.
   Legacy labels remain supported while templates migrate to explicit keys. */
(() => {
  'use strict';
  const PT = __DICTIONARY__;
  const KEY = 'clubdraft.language';
  let language = 'pt-PT';
  try { if (localStorage.getItem(KEY) === 'en') language = 'en'; } catch (_) {}
  document.documentElement.lang = language;
  const originals = new WeakMap();
  const attrOriginals = new WeakMap();
  const attrs = ['placeholder','title','aria-label','data-confirm','alt','data-label'];
  const keyAttrs = attrs.map(attr=>'data-i18n-'+attr);
  const observedAttributes = [...attrs,...keyAttrs,'data-i18n','data-i18n-vars','data-i18n-translated-vars','data-no-i18n'];
  const allowedAttributes = new Set(attrs);
  const phrases = [
    [/^Photo of (.+)$/,m=>t('Photo of {name}',{name:m[1]})],
    [/^Profiles for (.+)$/,m=>t('Profiles for {name}',{name:m[1]})],
    [/^Invite manager for (.+)$/,m=>t('Invite manager for {name}',{name:m[1]})],
    [/^CHESS GAME #(\d+)( \/)?$/,m=>t('CHESS GAME #{number}',{number:m[1]})+(m[2]||'')],
    [/^CLUB TEAM \/ EST\. (\d{4})$/,m=>t('CLUB TEAM / EST. {year}',{year:m[1]})],
    [/^\/ AUCTION #(\d+)$/,m=>t('/ AUCTION #{number}',{number:m[1]})],
    [/^(\d+) most recent high bids$/,m=>t('{count} most recent high bids',{count:m[1]})],
    [/^for (\d+) credits(\.)?$/,m=>t('for {credits} credits',{credits:m[1]})+(m[2]||'')],
    [/^(-?\d+) fantasy pts · (\d+) CR remaining$/,m=>`${m[1]} ponto${m[1]==='1'?'':'s'} fantasia · ${m[2]} CR restantes`],
    [/^No confirmed player membership records are available for (\d{4})\. Older roster details may not have been recorded before this feature was introduced\.$/,m=>t('No confirmed player membership records are available for {year}. Older roster details may not have been recorded before this feature was introduced.',{year:m[1]})],
    [/^The minimum bid is (\d+) credits\.$/,m=>t('The minimum bid is {minimum} credits.',{minimum:m[1]})],
    [/^You have (\d+) credits available for this auction \(other leading bids reserve credits\)\.$/,m=>t('You have {available} credits available for this auction (other leading bids reserve credits).',{available:m[1]})],
    [/^Your (manager|player) role is already active\.$/,m=>t('Your {role} role is already active.',{role:t(m[1])})],
    [/^The attached PGN declares (1-0|0-1|1\/2-1\/2|\*); choose that result or replace the PGN\.$/,m=>t('The attached PGN declares {result}; choose that result or replace the PGN.',{result:m[1]})],
    [/^Invalid chess moves in PGN: (.+)$/,m=>t('Invalid chess moves in PGN: {detail}',{detail:m[1]})],
    [/^PGN is too long \(maximum (\d+) half-moves\)\.$/,m=>t('PGN is too long (maximum {maximum} half-moves).',{maximum:m[1]})],
    [/^Account menu for (.+)$/, m=>`Menu da conta de ${m[1]}`],
    [/^Manager: (.+)$/,m=>`Gestor: ${m[1]}`],
    [/^Founded (\d{4}-\d{2}-\d{2})$/,m=>`Fundada em ${m[1]}`],
    [/^Club member since (.+)$/,m=>`Membro do clube desde ${m[1]}`],
    [/^These players currently belong to (.+)\.$/,m=>`Estes jogadores pertencem atualmente à equipa ${m[1]}.`],
    [/^January 1 – December 31, (\d{4}) · all dates UTC\. This is a roster membership history, not a match-results or historical-points table\.$/,m=>`1 de janeiro – 31 de dezembro de ${m[1]} · todas as datas em UTC. Este é um histórico dos plantéis, não uma tabela de resultados ou pontuações por época.`],
    [/^(\d{4}) season$/,m=>`Época de ${m[1]}`],
    [/^Transfers in (\d{4})$/,m=>`Transferências em ${m[1]}`],
    [/^Chess games in (\d{4})$/,m=>`Partidas de xadrez em ${m[1]}`],
    [/^Managers during (\d{4})$/,m=>`Gestores durante ${m[1]}`],
    [/^Showing (\d+) games \(newest first\)$/,m=>`A mostrar ${m[1]} partidas (mais recentes primeiro)`],
    [/^(\d+) bids?$/,m=>`${m[1]} licitaç${Number(m[1])===1?'ão':'ões'}`],
    [/^(.+) · (\d+) rating$/,m=>`${m[1]} · rating ${m[2]}`],
    [/^Welcome back, (.+)!$/,m=>`Bem-vindo de volta, ${m[1]}!`],
    [/^(\d+) fantasy pts pending$/,m=>`${m[1]} ponto${m[1]==='1'?'':'s'} fantasia pendente${m[1]==='1'?'':'s'}`],
    [/^(\d+) fantasy pts awarded$/,m=>`${m[1]} ponto${m[1]==='1'?'':'s'} fantasia atribuído${m[1]==='1'?'':'s'}`],
    [/^Team at match: (.+)$/,m=>`Equipa na data da partida: ${m[1]}`],
    [/^([0-9]+) players$/,m=>`${m[1]} jogadores`],
    [/^Showing (\d+) matching players?$/i, (m) => `A mostrar ${m[1]} jogador${Number(m[1])===1?'':'es'} correspondente${Number(m[1])===1?'':'s'}`],
    [/^Showing (\d+) matching teams?$/i, (m) => `A mostrar ${m[1]} equipa${Number(m[1])===1?'':'s'} correspondente${Number(m[1])===1?'':'s'}`],
    [/^(\d+) half-moves$/,m=>`${m[1]} meios-lances`],
    [/^Move (\d+)(\.|…) (\S+) · (\d+) \/ (\d+) half-moves$/,m=>`Lance ${m[1]}${m[2]} ${m[3]} · ${m[4]} / ${m[5]} meios-lances`],
    [/^(\d+) days?$/,m=>`${m[1]} dia${m[1]==='1'?'':'s'}`],
    [/^No completed transfers recorded for this team during (\d{4})\.$/,m=>`Não há transferências concluídas desta equipa durante ${m[1]}.`],
    [/^No fixtures or results recorded for this team during (\d{4})\.$/,m=>`Não há partidas ou resultados registados desta equipa durante ${m[1]}.`]
  ];
  function localize(original) {
    const str = String(original);
    const trimmed = str.trim();
    if (!trimmed) return str;
    let translation = PT[trimmed];
    if (translation === undefined) {
      for (const [regex,fn] of phrases) {
        const match = trimmed.match(regex);
        if (match) { translation = fn(match); break; }
      }
    }
    if (translation === undefined) return str;
    const leading = (str.match(/^\s*/) || [''])[0];
    const trailing = (str.match(/\s*$/) || [''])[0];
    return leading + translation + trailing;
  }
  function t(key, variables={}) {
    const source=String(key);
    // Constrained legacy sentence adapters also cover dynamic domain errors;
    // interpolation values are never passed through this lookup.
    const value=language==='en' ? source : (PT[source] ?? localize(source));
    return value.replace(/\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g,(placeholder,name)=>
      Object.prototype.hasOwnProperty.call(variables,name) ? String(variables[name]) : placeholder);
  }
  function variablesFor(el) {
    try {
      const variables=JSON.parse(el.dataset.i18nVars || '{}');
      if (!variables || typeof variables!=='object' || Array.isArray(variables))return {};
      // Only opt-in enums (such as role) are keys; player/team names remain literal.
      for (const name of (el.dataset.i18nTranslatedVars || '').split(/\s+/))
        if (Object.prototype.hasOwnProperty.call(variables,name))variables[name]=t(variables[name]);
      return variables;
    } catch (_) {return {};}
  }
  function skip(node) {
    const el = node.nodeType===1 ? node : node.parentElement;
    return !el || !!el.closest('[data-no-i18n],script,style,noscript,textarea,svg,code,pre');
  }
  function keyedElement(el) {
    if (skip(el)) return;
    const variables=variablesFor(el);
    if (el.hasAttribute('data-i18n')) {
      const output=t(el.dataset.i18n,variables);
      if (el.textContent!==output)el.textContent=output;
    }
    for (const attr of attrs) {
      const key=el.getAttribute('data-i18n-'+attr);
      if (key!==null) {
        const output=t(key,variables);
        if (el.getAttribute(attr)!==output)el.setAttribute(attr,output);
      }
    }
  }
  function textNode(node) {
    if (skip(node) || node.parentElement.closest('[data-i18n]') || !node.nodeValue.trim()) return;
    const record = originals.get(node);
    let source = record && (node.nodeValue === record.output || node.nodeValue === record.source)
      ? record.source : node.nodeValue;
    const output = language==='en' ? source : localize(source);
    originals.set(node,{source,output});
    if (node.nodeValue !== output) node.nodeValue=output;
  }
  function translateAttr(el, attr) {
    if (skip(el) || el.hasAttribute('data-i18n-'+attr) || !el.hasAttribute(attr)) return;
    let cache = attrOriginals.get(el);
    if (!cache) {cache={};attrOriginals.set(el,cache);}
    const current=el.getAttribute(attr);
    const record=cache[attr];
    const source=record && (current===record.output || current===record.source) ? record.source : current;
    const output=language==='en'?source:localize(source);
    cache[attr]={source,output};
    if (current!==output)el.setAttribute(attr,output);
  }
  function translateTree(root) {
    if (root.nodeType===3) {textNode(root);return;}
    if (root.nodeType!==1 || skip(root)) return;
    keyedElement(root);
    for (const attr of attrs)translateAttr(root,attr);
    const walker=document.createTreeWalker(root,NodeFilter.SHOW_ELEMENT|NodeFilter.SHOW_TEXT);
    let current;
    while ((current=walker.nextNode())) {
      if (current.nodeType===3) textNode(current);
      else if (!skip(current)) {keyedElement(current);for(const attr of attrs)translateAttr(current,attr);}
    }
  }
  const originalDocumentTitle = document.title;
  function apply() {
    document.documentElement.lang=language;
    // Dynamic document titles may be player/team names. Only explicit keys translate.
    const title=document.querySelector('title[data-i18n]');
    document.title=title ? t(title.dataset.i18n,variablesFor(title)) : originalDocumentTitle;
    if (document.body) translateTree(document.body);
    const flag=document.getElementById('language-flag');
    if (flag) flag.src=language==='en'?'/static/flags/gb.svg':'/static/flags/pt.svg';
    for (const button of document.querySelectorAll('[data-language]'))
      button.setAttribute('aria-pressed',String(button.dataset.language===language));
  }
  function setLanguage(lang) {
    if (lang!=='pt-PT'&&lang!=='en')return;
    language=lang;
    try {localStorage.setItem(KEY,lang);}catch(_){}
    // Cookie retains the choice on a different tab and future server-side locales.
    try {document.cookie='clubdraft_language='+encodeURIComponent(lang)+'; Path=/; SameSite=Lax; Max-Age=31536000';}catch(_){}
    apply();
    document.dispatchEvent(new CustomEvent('liga:languagechange',{detail:{language}}));
    document.dispatchEvent(new CustomEvent('clubdraft:languagechange',{detail:{language}}));
  }
  window.LigaI18n={t,get language(){return language;},setLanguage};
  window.ClubDraftI18n=window.LigaI18n;
  document.addEventListener('DOMContentLoaded',()=>{
    const toggle=document.getElementById('language-toggle');
    const menu=document.getElementById('language-menu');
    if (toggle&&menu) {
      const choices=[...menu.querySelectorAll('[data-language]')];
      const closeMenu=(restoreFocus=false)=>{
        menu.hidden=true;toggle.setAttribute('aria-expanded','false');
        if(restoreFocus)toggle.focus();
      };
      toggle.addEventListener('click',()=>{
        menu.hidden=!menu.hidden;
        toggle.setAttribute('aria-expanded',String(!menu.hidden));
        if(!menu.hidden)(choices.find(button=>button.dataset.language===language)||choices[0])?.focus();
      });
      choices.forEach(button=>button.addEventListener('click',()=>{
        setLanguage(button.dataset.language);closeMenu(true);
      }));
      menu.addEventListener('keydown',event=>{
        if(!['ArrowDown','ArrowUp','Home','End'].includes(event.key)||!choices.length)return;
        event.preventDefault();
        const current=choices.indexOf(document.activeElement);
        const index=event.key==='Home'?0:event.key==='End'?choices.length-1:
          (current+(event.key==='ArrowDown'?1:-1)+choices.length)%choices.length;
        choices[index].focus();
      });
      document.addEventListener('click',event=>{
        if (!event.target.closest('.language-picker'))closeMenu();
      });
      document.addEventListener('keydown',event=>{
        if(event.key==='Escape'&&!menu.hidden)closeMenu(true);
      });
    }
    apply();
    // React to dynamically updated page elements.
    const observer=new MutationObserver(changes=>{
      for(const change of changes) {
        if(change.type==='characterData')textNode(change.target);
        else if(change.type==='attributes') {
          if(allowedAttributes.has(change.attributeName))translateAttr(change.target,change.attributeName);
          else translateTree(change.target);
        }
        else if(change.type==='childList')for(const node of change.addedNodes)translateTree(node);
      }
    });
    observer.observe(document.body,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:observedAttributes});
  });
})();
