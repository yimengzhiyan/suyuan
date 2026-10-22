/* 溯源 前端 —— 无依赖。所有第三方文本均经 esc() 转义后再插入 DOM。 */
(function () {
  'use strict';
  document.documentElement.classList.remove('no-js');

  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var EASE = 'cubic-bezier(.16,1,.3,1)';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function safeUrl(u) {
    try {
      var x = new URL(String(u || ''), location.href);
      return (x.protocol === 'http:' || x.protocol === 'https:') ? x.href : '#';
    } catch (e) { return '#'; }
  }
  function ext(u, inner, cls) {
    return '<a' + (cls ? ' class="' + cls + '"' : '') + ' href="' + esc(safeUrl(u)) + '" target="_blank" rel="noopener noreferrer">' + inner + '</a>';
  }
  function clip(s, n) { s = String(s || '').replace(/\s+/g, ' ').trim(); return s.length > n ? s.slice(0, n) + '…' : s; }
  function tierNum(t) { t = parseInt(t, 10); return t >= 1 && t <= 5 ? t : 5; }
  var TIER_NAMES = { 1: '政府/官方', 2: '中央媒体', 3: '主流媒体', 4: '门户/垂直', 5: '自媒体/未知' };
  function tierBadge(t, name) { t = tierNum(t); return '<span class="tier tier--' + t + '">' + esc(name || TIER_NAMES[t]) + '</span>'; }
  function dateOf(e) { return (e && (e.date_parsed || String(e.date || '').slice(0, 10).replace(/\//g, '-'))) || ''; }
  function scrollToEl(el, block) { if (el) el.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: block || 'start' }); }

  /* ---------------- 噪点纹理：canvas 生成，写入 CSS 变量 ---------------- */
  (function grain() {
    try {
      var c = document.createElement('canvas'); c.width = c.height = 160;
      var g = c.getContext('2d'); var img = g.createImageData(160, 160); var d = img.data;
      for (var i = 0; i < d.length; i += 4) {
        var v = Math.random() * 255 | 0; d[i] = d[i + 1] = d[i + 2] = v; d[i + 3] = 22;
      }
      g.putImageData(img, 0, 0);
      document.documentElement.style.setProperty('--noise', 'url(' + c.toDataURL('image/png') + ')');
    } catch (e) { /* 无噪点也能正常显示 */ }
  })();

  /* ---------------- Hero：逐字拆分 ---------------- */
  (function splitTitle() {
    var h = $('[data-split]'); if (!h) return;
    var label = h.textContent.replace(/\s+/g, '');
    var accent = '从哪来'; var i = 0;
    var full = h.textContent; var accentStart = full.indexOf(accent);
    var pos = 0; var out = '';
    h.childNodes.forEach(function (n) {
      if (n.nodeType === 1 && n.tagName === 'BR') { out += '<br>'; return; }
      var t = n.textContent;
      for (var k = 0; k < t.length; k++) {
        var ch = t[k]; var abs = pos + k;
        if (/\s/.test(ch)) continue;
        var acc = accentStart >= 0 && abs >= accentStart && abs < accentStart + accent.length;
        out += '<span class="w"><span class="c' + (acc ? ' c--accent' : '') + '" style="--i:' + (i++) + '">' + esc(ch) + '</span></span>';
      }
      pos += t.length;
    });
    h.innerHTML = '<span aria-hidden="true">' + out + '</span><span class="sr">' + esc(label) + '</span>';
  })();

  /* ---------------- 跑马灯 ---------------- */
  (function marquee() {
    var el = $('#marquee'); if (!el) return;
    var lines = ['网传：下月起全面取消医保个人账户', '网传：交通部已下发文件', '网传：明天全市停水停电', '网传：某地发现新型病毒', '网传：内部消息，速转', '网传：再不转发就晚了', '网传：官方已证实'];
    var one = lines.map(function (s) { return '<span>' + esc(s) + '</span>'; }).join('');
    el.innerHTML = one + one;
  })();

  /* ---------------- 导航 ---------------- */
  var nav = $('#nav');
  (function navInit() {
    var ticking = false;
    function onScroll() {
      if (ticking) return; ticking = true;
      requestAnimationFrame(function () { nav.classList.toggle('is-scrolled', window.scrollY > 24); ticking = false; });
    }
    window.addEventListener('scroll', onScroll, { passive: true }); onScroll();
    var tog = $('#navToggle');
    function setOpen(o) { nav.classList.toggle('is-open', o); tog.setAttribute('aria-expanded', o ? 'true' : 'false'); }
    tog.addEventListener('click', function () { setOpen(!nav.classList.contains('is-open')); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') setOpen(false); });
    document.addEventListener('click', function (e) { if (!nav.contains(e.target)) setOpen(false); });
    $$('#navMenu a').forEach(function (a) { a.addEventListener('click', function () { setOpen(false); }); });
    // 平滑滚动
    document.addEventListener('click', function (e) {
      var a = e.target.closest && e.target.closest('a[href^="#"]'); if (!a) return;
      var id = a.getAttribute('href'); if (id.length < 2) return;
      var t = document.getElementById(id.slice(1)); if (!t) return;
      e.preventDefault(); scrollToEl(t);
      if (history.replaceState) history.replaceState(null, '', id);
      if (id === '#check') setTimeout(function () { $('#text').focus({ preventScroll: true }); }, reduce ? 0 : 600);
    });
    // 当前区块高亮
    if ('IntersectionObserver' in window) {
      var links = {}; $$('#navMenu a[href^="#"]').forEach(function (a) { links[a.getAttribute('href').slice(1)] = a; });
      var io = new IntersectionObserver(function (es) {
        es.forEach(function (en) {
          if (en.isIntersecting && links[en.target.id]) {
            $$('#navMenu a').forEach(function (a) { a.classList.remove('is-active'); });
            links[en.target.id].classList.add('is-active');
          }
        });
      }, { rootMargin: '-45% 0px -50% 0px' });
      ['check', 'how', 'about'].forEach(function (id) { var s = document.getElementById(id); if (s) io.observe(s); });
    }
  })();

  /* ---------------- Reveal ---------------- */
  var revealIO = null;
  function markIn(el) { if (el.classList.contains('is-in')) return; el.classList.add('is-in'); if (el._onIn) el._onIn(); }
  function observe(root) {
    var els = $$('[data-reveal], [data-in]', root || document).filter(function (el) { return !el.classList.contains('is-in'); });
    if (reduce || !revealIO) { els.forEach(markIn); return; }
    els.forEach(function (el) { revealIO.observe(el); });
  }
  if ('IntersectionObserver' in window && !reduce) {
    revealIO = new IntersectionObserver(function (es) {
      es.forEach(function (en) { if (en.isIntersecting) { revealIO.unobserve(en.target); markIn(en.target); } });
    }, { threshold: 0.12, rootMargin: '0px 0px -6% 0px' });
  }
  observe();

  /* ---------------- 数字滚动 ---------------- */
  function countUp(el, to, dec, dur) {
    to = Number(to) || 0; dec = dec || 0; dur = dur || 1400;
    var fmt = function (v) { return dec ? v.toFixed(dec) : Math.round(v).toLocaleString('zh-CN'); };
    if (reduce) { el.textContent = fmt(to); return; }
    var t0 = null;
    function step(t) {
      if (t0 === null) t0 = t;
      var p = Math.min(1, (t - t0) / dur); var e = 1 - Math.pow(1 - p, 3);
      el.textContent = fmt(to * e);
      if (p < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  /* ---------------- 输入区 ---------------- */
  var form = $('#form'), ta = $('#text'), submitBtn = $('#submit'), hint = $('#hint');
  var F = {
    wsa: $('#wsaKey'), preset: $('#preset'), llm: $('#llmKey'), base: $('#baseUrl'), model: $('#model'),
    think: $('#thinkingOff'), cache: $('#useCache'), noLlm: $('#noLlm')
  };
  var PRESETS = {
    kimi: ['https://api.moonshot.cn/v1', 'kimi-k2.6', true],
    kimicode: ['https://api.kimi.com/coding/v1', 'kimi-for-coding', true],
    deepseek: ['https://api.deepseek.com', 'deepseek-chat', false],
    hunyuan: ['https://api.hunyuan.cloud.tencent.com/v1', 'hunyuan-turbos-latest', false]
  };
  var CFG = { public: false, server_search_key: true, server_llm_key: true };
  var SKEY = 'suyuan.keys.v1';

  function autosize() { ta.style.height = 'auto'; ta.style.height = (ta.scrollHeight + 2) + 'px'; $('#counter').textContent = ta.value.length + ' / 1500'; }
  ta.addEventListener('input', function () { autosize(); $$('.chip').forEach(function (c) { c.classList.remove('is-on'); }); updateState(); });
  ta.addEventListener('keydown', function (e) { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); if (!submitBtn.disabled) form.requestSubmit ? form.requestSubmit() : submitBtn.click(); } });

  function applyPreset() {
    var p = PRESETS[F.preset.value]; if (!p) return;
    F.base.value = p[0]; F.model.value = p[1]; F.think.checked = p[2];
  }
  F.preset.addEventListener('change', function () { applyPreset(); save(); });
  function load() {
    var s = null;
    try { s = JSON.parse(sessionStorage.getItem(SKEY) || 'null'); } catch (e) { s = null; }
    if (s && typeof s === 'object') {
      F.wsa.value = s.wsa || ''; F.llm.value = s.llm || '';
      if (s.preset && (PRESETS[s.preset] || s.preset === 'custom')) F.preset.value = s.preset;
      F.base.value = s.base || ''; F.model.value = s.model || '';
      F.think.checked = !!s.think; F.cache.checked = s.cache !== false; F.noLlm.checked = !!s.noLlm;
      if (!F.base.value && PRESETS[F.preset.value]) applyPreset();
    } else { applyPreset(); }
  }
  function save() {
    try {
      sessionStorage.setItem(SKEY, JSON.stringify({
        wsa: F.wsa.value, llm: F.llm.value, preset: F.preset.value, base: F.base.value,
        model: F.model.value, think: F.think.checked, cache: F.cache.checked, noLlm: F.noLlm.checked
      }));
    } catch (e) { /* 隐私模式等情况下忽略 */ }
  }
  [F.wsa, F.llm, F.base, F.model].forEach(function (i) { i.addEventListener('input', function () { save(); updateState(); }); });
  [F.think, F.cache].forEach(function (i) { i.addEventListener('change', save); });
  F.noLlm.addEventListener('change', function () { save(); updateState(); });
  load();

  var keysToggle = $('#keysToggle'), keysPanel = $('#keysPanel');
  function setKeysOpen(o) { keysPanel.hidden = !o; keysToggle.setAttribute('aria-expanded', o ? 'true' : 'false'); }
  keysToggle.addEventListener('click', function () { setKeysOpen(keysPanel.hidden); });

  var running = false;
  function needWsa() { return CFG.public || !CFG.server_search_key; }
  function updateState() {
    var hasWsa = !!F.wsa.value.trim(), hasLlm = !!F.llm.value.trim();
    var st = $('#keysState'); var warn = false, msg = '';
    if (hasWsa || hasLlm) { st.textContent = '· 已填写' + (hasWsa && hasLlm ? '' : (hasWsa ? '搜索 Key' : '大模型 Key')); }
    else if (needWsa()) { st.textContent = '· 需要填写'; warn = true; }
    else { st.textContent = '· 可选，默认使用服务器的 Key'; }
    st.classList.toggle('is-warn', warn);

    var len = ta.value.trim().length; var block = false;
    if (needWsa() && !hasWsa) { block = true; msg = CFG.public ? '公开部署需要你自带 Key：请先在「你的 Key」里填写元宝搜索 Key。' : '服务器未配置搜索 Key，请填写你的元宝搜索 Key。'; }
    else if (len < 2) { block = true; msg = '粘贴一条传闻，或点一个示例。⌘/Ctrl + Enter 也可以提交。'; warn = false; }
    else if (F.noLlm.checked) { msg = '仅检索模式：只做检索与信源分级，不调用大模型，判定固定为"证据不足"。'; }
    else if ((CFG.public || !CFG.server_llm_key) && !hasLlm) { msg = '未填大模型 Key：将只做检索与信源分级，判定固定为"证据不足"。'; }
    else { msg = '预计 30~60 秒。核查过程会实时显示在下方。'; }
    hint.textContent = msg;
    hint.classList.toggle('is-warn', needWsa() && !hasWsa);
    submitBtn.disabled = running || block;
  }

  function loadMeta() {
    fetch('/api/config').then(function (r) { return r.json(); }).then(function (c) {
      if (c && typeof c === 'object') CFG = c;
      if (needWsa() && !F.wsa.value.trim()) setKeysOpen(true);
      updateState();
    }).catch(function () { updateState(); });
    fetch('/api/examples').then(function (r) { return r.json(); }).then(function (list) {
      var box = $('#chips');
      (Array.isArray(list) ? list : []).forEach(function (ex) {
        var b = document.createElement('button'); b.type = 'button'; b.className = 'chip'; b.textContent = ex.label || '示例';
        b.title = ex.text || '';
        b.addEventListener('click', function () {
          ta.value = ex.text || ''; autosize(); updateState();
          $$('.chip').forEach(function (c) { c.classList.remove('is-on'); }); b.classList.add('is-on');
          ta.focus();
        });
        box.appendChild(b);
      });
    }).catch(function () { });
  }
  autosize(); updateState(); loadMeta();

  /* ---------------- 核查链条 ---------------- */
  var STEPS = [
    ['claims', '拆主张'], ['search', '五路检索'], ['timeline', '溯源时间线'], ['deepread', '原文深读'],
    ['judge', '有据判定'], ['extend', '延伸话题'], ['done', '核查卡']
  ];
  var chain = $('#chain'), track = $('#chainTrack'), logEl = $('#log'), errEl = $('#err'), resultEl = $('#result');
  var cur = -1, t0 = 0, timerId = 0, ctrl = null;
  var CHECK_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  function buildChain() {
    track.innerHTML = STEPS.map(function (s, i) {
      return '<li class="node" data-step="' + s[0] + '"><span class="node__dot"><span class="node__num">' + (i + 1) + '</span><span class="node__check">' + CHECK_SVG + '</span></span>' +
        '<span class="node__label">' + s[1] + '</span><span class="node__line" aria-hidden="true"><i></i></span></li>';
    }).join('');
    cur = -1;
  }
  function paint(active, allDone) {
    $$('.node', track).forEach(function (n, i) {
      var done = allDone || i < active;
      n.classList.toggle('is-done', done);
      n.classList.toggle('is-active', !done && i === active);
      if (!done && i === active) n.setAttribute('aria-current', 'step'); else n.removeAttribute('aria-current');
    });
  }
  function setStep(step) {
    if (!step) return;
    if (step === 'start') { if (cur < 0) { cur = 0; paint(0); } return; }
    var idx = -1; STEPS.forEach(function (s, i) { if (s[0] === step) idx = i; });
    if (idx < 0) return;
    if (idx > cur) { cur = idx; paint(cur); }
  }
  function fmtT(ms) { var s = Math.floor(ms / 1000); return ('0' + Math.floor(s / 60)).slice(-2) + ':' + ('0' + s % 60).slice(-2); }
  function log(msg, kind) {
    var p = document.createElement('p'); if (kind) p.className = kind;
    var t = document.createElement('time'); t.textContent = fmtT(Date.now() - t0);
    var s = document.createElement('span'); s.textContent = msg;
    p.appendChild(t); p.appendChild(s); logEl.appendChild(p);
    logEl.scrollTop = logEl.scrollHeight;
  }
  function startTimer() {
    t0 = Date.now(); clearInterval(timerId);
    timerId = setInterval(function () { $('#timer').textContent = ((Date.now() - t0) / 1000).toFixed(1) + 's'; }, 100);
  }
  function stopTimer() { clearInterval(timerId); }
  function setRunning(on) {
    running = on;
    submitBtn.innerHTML = on ? '核查中…' : '开始核查<span class="btn__arrow" aria-hidden="true">→</span>';
    $('#cancel').hidden = !on;
    updateState();
  }
  function beginRun() {
    errEl.hidden = true; resultEl.hidden = true; resultEl.innerHTML = '';
    chain.hidden = false; chain.classList.remove('is-done', 'is-fail');
    $('#chainStatus').textContent = '核查中';
    buildChain(); logEl.innerHTML = ''; startTimer(); setRunning(true);
    setTimeout(function () { scrollToEl(chain, 'center'); }, 60);
  }
  function fail(msg) {
    stopTimer(); setRunning(false);
    chain.classList.add('is-fail'); $('#chainStatus').textContent = '核查中断';
    log(msg, 'is-err');
    errEl.innerHTML = '<strong>核查没有完成</strong>' + esc(msg);
    errEl.hidden = false;
  }
  function finish(report) {
    stopTimer(); setRunning(false);
    cur = STEPS.length; paint(cur, true);
    chain.classList.add('is-done');
    var el = report && report.stats && report.stats.elapsed;
    $('#chainStatus').textContent = '核查完成' + (el ? ' · 用时 ' + Number(el).toFixed(1) + ' 秒' : '');
    renderResult(report);
  }

  $('#cancel').addEventListener('click', function () { if (ctrl) ctrl.abort(); });

  form.addEventListener('submit', function (e) {
    e.preventDefault(); if (running || submitBtn.disabled) return;
    var text = ta.value.trim(); if (text.length < 2) return;
    var llmKey = F.llm.value.trim();
    var body = {
      text: text,
      wsa_key: F.wsa.value.trim(),
      // 只有访问者自带大模型 Key 时才传接口地址/模型，避免用服务器 Key 去请求别家的接口
      llm_base_url: llmKey ? F.base.value.trim() : '',
      llm_api_key: llmKey,
      llm_model: llmKey ? F.model.value.trim() : '',
      thinking_off: llmKey ? F.think.checked : false,
      use_cache: F.cache.checked,
      no_llm: F.noLlm.checked
    };
    beginRun();
    ctrl = window.AbortController ? new AbortController() : null;
    var gotEnd = false;
    fetch('/api/verify', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
      body: JSON.stringify(body), signal: ctrl ? ctrl.signal : undefined
    }).then(function (res) {
      var ct = res.headers.get('content-type') || '';
      if (!res.ok || ct.indexOf('text/event-stream') < 0) {
        return res.text().then(function (t) {
          var m = '';
          try { var j = JSON.parse(t); m = j.error || (j.detail && (typeof j.detail === 'string' ? j.detail : '请求参数不合法')) || ''; } catch (x) { m = ''; }
          throw new Error(m || ('服务器返回 ' + res.status));
        });
      }
      return readSSE(res, function (ev, data) {
        if (ev === 'progress') { setStep(data.step); log(data.msg || '', data.step ? 'is-step' : ''); }
        else if (ev === 'result') { gotEnd = true; finish(data); }
        else if (ev === 'error') { gotEnd = true; fail((data && data.error) || '未知错误'); }
      });
    }).then(function () {
      if (!gotEnd) fail('连接意外中断，请重试。');
    }).catch(function (err) {
      if (gotEnd) return;
      gotEnd = true;
      if (err && err.name === 'AbortError') fail('已手动停止。');
      else fail((err && err.message) || '网络错误');
    });
  });

  function readSSE(res, onEvent) {
    var reader = res.body.getReader(); var dec = new TextDecoder('utf-8'); var buf = '';
    function handle(block) {
      var ev = 'message', data = [];
      block.split('\n').forEach(function (line) {
        if (!line || line.charAt(0) === ':') return;
        var i = line.indexOf(':'); var k = i < 0 ? line : line.slice(0, i);
        var v = i < 0 ? '' : line.slice(i + 1); if (v.charAt(0) === ' ') v = v.slice(1);
        if (k === 'event') ev = v; else if (k === 'data') data.push(v);
      });
      if (!data.length) return;
      var parsed; try { parsed = JSON.parse(data.join('\n')); } catch (e) { return; }
      onEvent(ev, parsed);
    }
    function pump() {
      return reader.read().then(function (r) {
        if (r.done) { buf += dec.decode(); if (buf.trim()) handle(buf.replace(/\r\n/g, '\n')); return; }
        buf += dec.decode(r.value, { stream: true }); buf = buf.replace(/\r\n/g, '\n');
        var i; while ((i = buf.indexOf('\n\n')) >= 0) { handle(buf.slice(0, i)); buf = buf.slice(i + 2); }
        return pump();
      });
    }
    return pump();
  }

  /* ---------------- 结果渲染 ---------------- */
  var EV = {};      // idx -> evidence
  var REPORT = null;

  function citeHtml(text) {
    var safe = esc(text);
    return safe.replace(/\[(\d+(?:\s*[,，、]\s*\d+)*)\]/g, function (m, g) {
      return g.split(/\s*[,，、]\s*/).map(function (n) {
        return EV[n] ? '<button type="button" class="cite" data-cite="' + n + '" aria-label="证据 ' + n + '">' + n + '</button>' : '[' + n + ']';
      }).join('');
    });
  }
  function paras(text) {
    return String(text || '').split(/\n+/).filter(function (s) { return s.trim(); }).map(function (s) { return '<p>' + citeHtml(s) + '</p>'; }).join('');
  }
  function siteTag(e) {
    var t = tierNum(e.tier); var s = String(e.site || '').trim() || (function () { try { return new URL(e.url).hostname; } catch (x) { return '来源'; } })();
    return ext(e.url, '<i>' + esc(s.charAt(0).toUpperCase()) + '</i><span>' + esc(s) + '</span>', 'site tc' + t);
  }

  function blockVerdict(r) {
    var v = ['属实', '不实', '部分属实', '证据不足'].indexOf(r.verdict) >= 0 ? r.verdict : '证据不足';
    var conf = Math.max(0, Math.min(1, Number(r.confidence) || 0));
    var R = 52, C = 2 * Math.PI * R;
    var word = v.split('').map(function (c, i) { return '<span class="c" style="--i:' + i + '">' + esc(c) + '</span>'; }).join('');
    var stampTxt = { '属实': '经核实', '不实': '已证伪', '部分属实': '有出入', '证据不足': '待证实' }[v];
    var claims = (r.claims || []).map(function (c) {
      var meta = [];
      if (c.time) meta.push('时间：' + esc(c.time));
      if (c.place) meta.push('地点：' + esc(c.place));
      if (c.entities && c.entities.length) meta.push('实体：' + c.entities.map(esc).join('、'));
      return '<li><div><p>' + esc(c.text) + '</p>' + (meta.length ? '<div class="meta">' + meta.map(function (m) { return '<span>' + m + '</span>'; }).join('') + '</div>' : '') + '</div></li>';
    }).join('');
    return '<article class="card r-block verdict" data-v="' + esc(v) + '" data-reveal id="rVerdict">' +
      '<div class="verdict__top"><div><p class="verdict__label">核查结论</p>' +
      '<h2 class="verdict__word" aria-label="' + esc(v) + '">' + word + '</h2>' +
      '<span class="stamp">' + stampTxt + '</span></div>' +
      '<div class="ring" role="img" aria-label="置信度 ' + Math.round(conf * 100) + '%"><svg viewBox="0 0 120 120"><circle class="ring__bg" cx="60" cy="60" r="' + R + '"/>' +
      '<circle class="ring__fg" cx="60" cy="60" r="' + R + '" stroke-dasharray="' + C.toFixed(2) + '" stroke-dashoffset="' + C.toFixed(2) + '" data-off="' + (C * (1 - conf)).toFixed(2) + '"/></svg>' +
      '<div class="ring__val"><b><span data-conf="' + Math.round(conf * 100) + '">0</span><small>%</small></b><span>置信度</span></div></div></div>' +
      (r.topic ? '<p class="verdict__topic"><span>话题</span>' + esc(r.topic) + '</p>' : '') +
      (claims ? '<ol class="claims" aria-label="拆出的主张">' + claims + '</ol>' : '') +
      '</article>';
  }

  function blockReasoning(r) {
    if (!r.reasoning) return '';
    return '<article class="card r-block" data-reveal><h3 class="r-title">结论与依据<small>点击编号查看对应证据</small></h3>' +
      '<div class="reasoning">' + paras(r.reasoning) + '</div></article>';
  }

  function blockKey(r) {
    var list = r.key_evidence || []; if (!list.length) return '';
    var cards = list.map(function (e, i) {
      return '<li class="kcard" data-reveal style="--d:' + i + '"><div class="kcard__top"><span class="kcard__idx">[' + esc(e.idx) + ']</span>' + tierBadge(e.tier, e.tier_name) +
        '<span>' + esc(dateOf(e) || '日期未知') + '</span><span>·</span><span>' + esc(e.site) + '</span>' + (e.is_debunk ? '<span class="debunk">辟谣平台</span>' : '') + '</div>' +
        '<h4>' + ext(e.url, esc(e.title || e.url)) + '</h4>' + (e.snippet ? '<p>' + esc(clip(e.snippet, 120)) + '</p>' : '') + '</li>';
    }).join('');
    return '<section class="card r-block" data-reveal><h3 class="r-title">关键证据<small>' + list.length + ' 条</small></h3><ul class="kev">' + cards + '</ul></section>';
  }

  function blockTwo(r) {
    var stance = r.official_stance ? '<p class="stance__q">' + citeHtml(r.official_stance) + '</p>' : '<p class="empty">未检索到明确的官方口径。</p>';
    var o = r.origin, rumor = r.origin_kind === 'rumor', originHtml;
    if (o) {
      originHtml = '<span class="badge ' + (rumor ? 'badge--rumor' : 'badge--bg') + '">' + (rumor ? '传闻首发' : '最早相关背景') + '</span>' +
        (rumor ? '' : '<p class="origin__note" style="margin-top:8px">未找到传闻本身的早期版本，以下是搜索可见范围内最早的相关内容。</p>') +
        '<p class="origin__date">' + esc(dateOf(o) || '日期未知') + '</p>' +
        '<div class="origin__site">' + tierBadge(o.tier, o.tier_name) + '<span>' + esc(o.site) + '</span>' + (o.idx != null && EV[o.idx] ? '<button type="button" class="cite" data-cite="' + esc(o.idx) + '">' + esc(o.idx) + '</button>' : '') + '</div>' +
        ext(o.url, esc(o.title || o.url), 'origin__title') +
        (r.origin_note ? '<p class="origin__note">' + esc(r.origin_note) + '</p>' : '');
    } else {
      originHtml = '<p class="empty">' + esc(r.origin_note || '没有找到带日期的相关内容，无法定位首发。') + '</p>';
    }
    return '<div class="two"><article class="card r-block" data-reveal><h3 class="r-title">官方口径</h3>' + stance + '</article>' +
      '<article class="card r-block origin ' + (o ? (rumor ? 'origin--rumor' : 'origin--bg') : '') + '" data-reveal style="--d:1"><h3 class="r-title">' + (rumor ? '首发来源' : '溯源起点') + '</h3>' + originHtml + '</article></div>';
  }

  var TL_LIMIT = 25;
  function blockTimeline(r) {
    var list = r.timeline || []; if (!list.length) return '';
    var ou = r.origin && r.origin.url, rumor = r.origin_kind === 'rumor', marked = false;
    var items = list.map(function (t, i) {
      var isO = !marked && ou && t.url === ou; if (isO) marked = true;
      return '<li class="tl__item tc' + tierNum(t.tier) + (isO ? ' is-origin' : '') + '" style="--d:' + Math.min(i, TL_LIMIT) + '"' + (i >= TL_LIMIT ? ' hidden data-more' : '') + '>' +
        '<span class="tl__date">' + esc(t.date) + '</span><div class="tl__body">' +
        (isO ? '<span class="flag' + (rumor ? '' : ' flag--bg') + '">' + (rumor ? '首发' : '最早背景') + '</span>' : '') +
        ext(t.url, esc(t.title || t.url)) + tierBadge(t.tier) + '<span class="tl__site">' + esc(t.site) + '</span></div></li>';
    }).join('');
    var more = list.length > TL_LIMIT ? '<button type="button" class="btn btn--ghost btn--sm tl__more" id="tlMore">展开其余 ' + (list.length - TL_LIMIT) + ' 条<span class="btn__arrow" aria-hidden="true">↓</span></button>' : '';
    return '<section class="card r-block" data-reveal><h3 class="r-title">传播时间线<small>按日期排列 · ' + list.length + ' 条</small></h3>' +
      '<div class="tl" data-in id="tl"><svg class="tl__line" viewBox="0 0 4 100" preserveAspectRatio="none" aria-hidden="true">' +
      '<defs><linearGradient id="tlGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#e8632b"/><stop offset=".35" stop-color="#101c2c" stop-opacity=".5"/><stop offset="1" stop-color="#101c2c" stop-opacity=".08"/></linearGradient></defs>' +
      '<rect x="1" y="0" width="2" height="100" fill="url(#tlGrad)"/></svg><ol class="tl__list">' + items + '</ol>' + more + '</div></section>';
  }

  var TBL_LIMIT = 20;
  var sortState = { key: 'idx', dir: 'asc' }, tblExpanded = false;
  function blockTable(r) {
    var n = (r.evidence || []).length; if (!n) return '';
    return '<section class="card r-block" data-reveal id="evidence"><h3 class="r-title">全部证据<small>' + n + ' 条 · 点击表头排序</small></h3>' +
      '<div class="tbl-wrap"><table class="tbl"><thead><tr>' +
      '<th scope="col"><button type="button" data-sort="idx">编号</button></th>' +
      '<th scope="col"><button type="button" data-sort="tier">等级</button></th>' +
      '<th scope="col"><button type="button" data-sort="date">日期</button></th>' +
      '<th scope="col">标题</th><th scope="col">链接</th></tr></thead><tbody id="tbody"></tbody></table></div>' +
      (n > TBL_LIMIT ? '<div class="tbl-more"><button type="button" class="btn btn--ghost btn--sm" id="tblMore">显示全部 ' + n + ' 条<span class="btn__arrow" aria-hidden="true">↓</span></button></div>' : '') +
      '</section>';
  }
  var CH_NAMES = { mixed: '混合', news: '新闻', gov: '政务', debunk: '辟谣', debunk_site: '辟谣平台', origin_probe: '溯源补搜' };
  function renderRows() {
    var tb = $('#tbody'); if (!tb || !REPORT) return;
    var list = (REPORT.evidence || []).slice();
    var k = sortState.key, d = sortState.dir === 'asc' ? 1 : -1;
    list.sort(function (a, b) {
      var x, y;
      if (k === 'tier') { x = tierNum(a.tier); y = tierNum(b.tier); }
      else if (k === 'date') { x = dateOf(a) || (d > 0 ? '9999' : '0000'); y = dateOf(b) || (d > 0 ? '9999' : '0000'); }
      else { x = Number(a.idx); y = Number(b.idx); }
      if (x < y) return -d; if (x > y) return d; return Number(a.idx) - Number(b.idx);
    });
    tb.innerHTML = list.map(function (e, i) {
      var ch = (e.channels || []).map(function (c) { return CH_NAMES[c] || c; });
      return '<tr id="ev-' + esc(e.idx) + '"' + (!tblExpanded && i >= TBL_LIMIT ? ' hidden' : '') + '>' +
        '<td class="n">' + esc(e.idx) + '</td><td>' + tierBadge(e.tier, e.tier_name) + '</td>' +
        '<td class="d">' + esc(dateOf(e) || '—') + '</td>' +
        '<td class="t">' + ext(e.url, esc(clip(e.title || e.url, 80))) + (ch.length || e.is_debunk ? '<span class="via">' + (ch.length ? '来自：' + esc(ch.join(' / ')) : '') + (e.is_debunk ? ' · 辟谣平台' : '') + '</span>' : '') + '</td>' +
        '<td>' + siteTag(e) + '</td></tr>';
    }).join('');
    $$('.tbl th button').forEach(function (b) {
      if (b.getAttribute('data-sort') === k) b.setAttribute('data-dir', sortState.dir); else b.removeAttribute('data-dir');
    });
  }

  function blockExt(r) {
    var list = r.extensions || []; if (!list.length) return '';
    return '<section class="card r-block" data-reveal><h3 class="r-title">延伸话题<small>看完这条，还可以看看</small></h3><div class="ext">' +
      list.map(function (x, i) {
        var items = (x.items || []).slice(0, 4).map(function (it) {
          return '<li>' + ext(it.url, esc(clip(it.title || it.url, 60))) + '<small>' + esc(it.site) + (it.date ? ' · ' + esc(String(it.date).slice(0, 10).replace(/\//g, '-')) : '') + '</small></li>';
        }).join('');
        return '<article class="ecard" data-reveal style="--d:' + i + '"><span class="ecard__n">0' + (i + 1) + '</span><h4>' + esc(x.query) + '</h4>' + (items ? '<ul>' + items + '</ul>' : '') + '</article>';
      }).join('') + '</div></section>';
  }

  function blockStats(r) {
    var s = r.stats || {};
    var dist = s.tier_distribution || {}; var total = 0;
    var parts = [1, 2, 3, 4, 5].map(function (t) { var v = Number(dist[TIER_NAMES[t]]) || 0; total += v; return [t, v]; });
    var bar = total ? '<div class="dist" aria-hidden="true">' + parts.filter(function (p) { return p[1]; }).map(function (p, i) {
      return '<i class="tc' + p[0] + '" style="width:' + (p[1] / total * 100).toFixed(2) + '%;transition-delay:' + (i * 120) + 'ms"></i>';
    }).join('') + '</div><div class="dist-legend">' + parts.map(function (p) { return '<span class="tc' + p[0] + '">' + TIER_NAMES[p[0]] + ' ' + p[1] + '</span>'; }).join('') + '</div>' : '';
    function stat(v, label, dec, unit) { return '<div class="stat"><b><span data-count="' + (Number(v) || 0) + '" data-dec="' + (dec || 0) + '">0</span>' + (unit ? '<small style="font-size:.4em;margin-left:4px">' + unit + '</small>' : '') + '</b><span>' + label + '</span></div>'; }
    return '<section class="card r-block" data-reveal data-in id="rStats"><h3 class="r-title">本次开销</h3><div class="stats">' +
      stat(s.search_calls, '搜索调用') + stat(s.llm_calls, '大模型调用') + stat(s.evidence_count, '证据条数') + stat(s.elapsed, '耗时', 1, '秒') + '</div>' +
      '<p class="stats__foot"><span>深读原文 ' + esc(s.deep_read_pages || 0) + ' 篇</span><span>缓存命中 ' + esc(s.cached_hits || 0) + ' 次</span><span>送入大模型 ' + esc(s.evidence_to_llm || 0) + ' 条证据</span>' + (s.llm_tokens ? '<span>消耗 ' + esc(Number(s.llm_tokens).toLocaleString('zh-CN')) + ' tokens</span>' : '') + '</p>' + bar + '</section>';
  }

  function blockDl() {
    return '<section class="card r-block dl" data-reveal><p>把核查卡带走，或者再核查一条。</p><div class="dl__btns">' +
      '<button type="button" class="btn btn--primary btn--sm" data-dl="md">下载 Markdown<span class="btn__arrow" aria-hidden="true">↓</span></button>' +
      '<button type="button" class="btn btn--ghost btn--sm" data-dl="json">下载 JSON<span class="btn__arrow" aria-hidden="true">↓</span></button>' +
      '<a class="btn btn--ghost btn--sm" href="#check">再核查一条<span class="btn__arrow" aria-hidden="true">↑</span></a></div></section>';
  }

  function renderResult(r) {
    if (!r || typeof r !== 'object') { fail('返回的报告格式不正确'); return; }
    REPORT = r; EV = {}; sortState = { key: 'idx', dir: 'asc' }; tblExpanded = false;
    (r.evidence || []).forEach(function (e) { EV[String(e.idx)] = e; });
    (r.key_evidence || []).forEach(function (e) { if (!EV[String(e.idx)]) EV[String(e.idx)] = e; });
    var warns = (r.warnings || []).length ? '<div class="warns" data-reveal>' + r.warnings.map(function (w) { return '<p class="warn">' + esc(w) + '</p>'; }).join('') + '</div>' : '';
    resultEl.innerHTML = '<div class="wrap">' + warns + blockVerdict(r) + blockReasoning(r) + blockKey(r) + blockTwo(r) +
      blockTimeline(r) + blockTable(r) + blockExt(r) + blockStats(r) + blockDl() + '</div>';
    resultEl.hidden = false;
    renderRows();

    // 进入视口时的动作
    var v = $('#rVerdict');
    if (v) v._onIn = function () {
      var fg = $('.ring__fg', v); var n = $('[data-conf]', v);
      requestAnimationFrame(function () { fg.style.strokeDashoffset = fg.getAttribute('data-off'); });
      countUp(n, Number(n.getAttribute('data-conf')), 0, 1600);
    };
    var st = $('#rStats');
    if (st) st._onIn = function () { $$('[data-count]', st).forEach(function (el) { countUp(el, Number(el.getAttribute('data-count')), Number(el.getAttribute('data-dec'))); }); };

    var more = $('#tlMore');
    if (more) more.addEventListener('click', function () {
      var hiddenItems = $$('#tl [data-more]');
      hiddenItems.forEach(function (li, i) {
        li.hidden = false;
        if (!reduce && li.animate) li.animate([{ opacity: 0, transform: 'translateX(-10px)' }, { opacity: 1, transform: 'none' }], { duration: 500, delay: Math.min(i, 30) * 25, easing: EASE, fill: 'backwards' });
      });
      more.remove();
    });
    var tm = $('#tblMore');
    if (tm) tm.addEventListener('click', function () { tblExpanded = true; renderRows(); tm.parentNode.remove(); });
    $$('.tbl th button').forEach(function (b) {
      b.addEventListener('click', function () {
        var k = b.getAttribute('data-sort');
        if (sortState.key === k) sortState.dir = sortState.dir === 'asc' ? 'desc' : 'asc';
        else { sortState.key = k; sortState.dir = 'asc'; }
        renderRows();
      });
    });
    $$('[data-dl]', resultEl).forEach(function (b) {
      b.addEventListener('click', function () {
        var md = b.getAttribute('data-dl') === 'md';
        var stamp = new Date().toISOString().slice(0, 10);
        download(md ? (r.markdown || '') : JSON.stringify(r, null, 2), '溯源-核查卡-' + stamp + (md ? '.md' : '.json'), md ? 'text/markdown;charset=utf-8' : 'application/json;charset=utf-8');
      });
    });

    observe(resultEl);
    setTimeout(function () { scrollToEl(resultEl.querySelector('.verdict') || resultEl); }, reduce ? 0 : 450);
  }

  function download(text, name, type) {
    var url = URL.createObjectURL(new Blob([text], { type: type }));
    var a = document.createElement('a'); a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1500);
  }

  /* ---------------- 引用：浮层 + 跳转 ---------------- */
  var tip = $('#tip'), tipFor = null;
  function showTip(btn) {
    var e = EV[btn.getAttribute('data-cite')]; if (!e) return;
    tipFor = btn;
    tip.innerHTML = '<div class="tip__meta">' + tierBadge(e.tier, e.tier_name) + '<span>' + esc(e.site) + '</span><span>' + esc(dateOf(e) || '日期未知') + '</span></div><b>' + esc(clip(e.title, 70)) + '</b>';
    tip.hidden = false;
    var r = btn.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight;
    var left = Math.max(12, Math.min(window.innerWidth - w - 12, r.left + r.width / 2 - w / 2));
    var top = r.top - h - 10; if (top < 70) top = r.bottom + 10;
    tip.style.left = left + 'px'; tip.style.top = top + 'px';
    requestAnimationFrame(function () { tip.classList.add('is-on'); });
  }
  function hideTip() { tipFor = null; tip.classList.remove('is-on'); tip.hidden = true; }
  document.addEventListener('mouseover', function (e) { var b = e.target.closest && e.target.closest('.cite'); if (b && b !== tipFor) showTip(b); else if (!b && tipFor) hideTip(); });
  document.addEventListener('focusin', function (e) { if (e.target.classList && e.target.classList.contains('cite')) showTip(e.target); });
  document.addEventListener('focusout', function (e) { if (e.target === tipFor) hideTip(); });
  window.addEventListener('scroll', function () { if (tipFor) hideTip(); }, { passive: true });
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('.cite'); if (!b) return;
    hideTip();
    var id = b.getAttribute('data-cite'); var row = document.getElementById('ev-' + id);
    if (row && row.hidden) { tblExpanded = true; renderRows(); var m = $('#tblMore'); if (m) m.parentNode.remove(); row = document.getElementById('ev-' + id); }
    if (!row) return;
    scrollToEl(row, 'center');
    row.classList.remove('is-flash'); void row.offsetWidth; row.classList.add('is-flash');
  });

  /* ---------------- 演示模式：?demo=1 直接渲染样例；?demo=play 回放链条 ---------------- */
  var demo = new URLSearchParams(location.search).get('demo');
  if (demo) {
    fetch('/static/dev/sample.json').then(function (r) { return r.json(); }).then(function (r) {
      ta.value = r.input_text || ''; autosize(); updateState();
      beginRun(); $('#cancel').hidden = true;
      if (demo !== 'play') {
        cur = 0; paint(0);
        log('（演示模式：载入 web/dev/sample.json）');
        finish(r); return;
      }
      var steps = [['开始核查', 'start'], ['抽取可核实主张…', 'claims']];
      (r.claims || []).forEach(function (c, i) { steps.push(['主张 ' + (i + 1) + '：' + c.text, null]); });
      steps.push(['主张 1：多路检索（混合 / 新闻 / 政务 / 辟谣）…', 'search'], ['构建溯源时间线…', 'timeline'], ['主张 1：深读原文…', 'deepread'],
        ['大模型基于证据判定…', 'judge'], ['生成延伸话题…', 'extend'], ['完成', 'done']);
      var i = 0;
      (function next() {
        if (i >= steps.length) { setTimeout(function () { finish(r); }, 500); return; }
        var s = steps[i++]; setStep(s[1]); log(s[0], s[1] ? 'is-step' : ''); setTimeout(next, 650);
      })();
    }).catch(function () { fail('演示样例 /static/dev/sample.json 加载失败'); });
  }
})();
