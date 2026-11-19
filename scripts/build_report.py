# -*- coding: utf-8 -*-
"""Stage 3: build a single-file issues-report.html from issues.json (images embedded as base64).

Every card has a "功能正确" checkbox:
  - problem/unconfirmed -> checked  => moves to 正常功能
  - 正常功能 -> unchecked            => moves back to 确认问题
  - 正常功能速查 thumbnails also support reverse marking.
State persists in localStorage.
"""
import argparse
import base64
import html
import io
import json
import os
import re
import sys

CSS = """
:root{--bg:#FBFAF7;--surface:#fff;--ink:#16232B;--muted:#63717B;--rule:#E3DED4;--accent:#0B7A66;--red:#B3261E;--amber:#B4761B;--gray:#78868F}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:"PingFang SC","Microsoft YaHei","Noto Sans SC",-apple-system,sans-serif;font-size:15px;line-height:1.65}
.wrap{max-width:1120px;margin:0 auto;padding:0 25px}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
header{background:#101C22;color:#EAF2EF;padding:34px 0 28px}
header .kicker{font-size:11.5px;letter-spacing:.2em;text-transform:uppercase;color:#8DB1A7;margin-bottom:10px}
header h1{margin:0 0 10px;font-size:30px;line-height:1.25}
header p{margin:0;color:#B7C8C3;font-size:14px}
.meta{display:flex;flex-wrap:wrap;gap:8px 22px;margin-top:14px;font-size:12.5px;color:#9FB4AE}
.meta b{color:#DCE9E5;font-weight:600}
.note{background:#FFF8E9;border:1px solid #F0DFB8;border-radius:8px;padding:10px 14px;margin:18px 0 0;font-size:13px;color:#6B5318}
.cov{background:var(--surface);border:1px solid var(--rule);border-radius:10px;padding:14px 16px;margin:18px 0 0}
.cov h3{margin:0 0 8px;font-size:15px}
.cov .stats{display:flex;gap:16px;flex-wrap:wrap;font-size:12.5px;color:#33424C}
.cov .stats b{font-size:19px;color:var(--accent);margin-right:4px}
.cov .miss{margin-top:10px;font-size:12.5px}
.cov table{width:100%;border-collapse:collapse;margin-top:8px;font-size:12.5px}
.cov th,.cov td{text-align:left;padding:5px 8px;border-top:1px solid #F0ECE4;vertical-align:top}
.cov .st-blocked{color:#9A4718;font-weight:700}
.cov .st-failed{color:#992019;font-weight:700}
.cov .st-untested{color:#78868F;font-weight:700}
nav{position:sticky;top:0;z-index:9;background:rgba(251,250,247,.95);backdrop-filter:blur(6px);border-bottom:1px solid var(--rule);padding:10px 0}
nav .wrap{display:flex;gap:8px;flex-wrap:wrap}
nav a{font-size:12.5px;padding:4px 10px;border:1px solid var(--rule);border-radius:999px;color:#3E4C56;background:#fff}
nav a:hover{border-color:var(--accent);color:var(--accent);text-decoration:none}
h2{font-size:21px;margin:38px 0 14px;padding-bottom:9px;border-bottom:2px solid var(--ink);display:flex;align-items:baseline;gap:10px}
h2 small{font-size:12px;color:var(--muted);font-weight:400}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}
.card{background:var(--surface);border:1px solid var(--rule);border-radius:10px;overflow:hidden;display:flex;flex-direction:column}
.card .top{padding:12px 14px 10px;border-bottom:1px solid #F0ECE4}
.card .path{font-size:11.5px;color:var(--muted);font-family:Consolas,monospace}
.card h3{margin:4px 0 6px;font-size:15.5px;line-height:1.4}
.card .sym{margin:0;font-size:13.5px;color:#33424C}
.card .sym b{color:var(--red)}
.evi{margin:8px 0 0;font-size:12px;color:#7A4A20;background:#FDF4E7;border-left:3px solid var(--amber);padding:5px 9px;border-radius:0 4px 4px 0;word-break:break-all}
.card .shots{display:flex;gap:10px;background:#F4F1EA;padding:12px;margin-top:auto;justify-content:center;align-items:flex-start;flex-wrap:wrap}
.card .shots a{flex:0 0 auto;display:block;background:#0F1519;border-radius:6px;overflow:hidden;border:1px solid #DCD6C9}
.card .shots img{height:360px;width:auto;max-width:100%;object-fit:contain;display:block}
.card .foot{padding:7px 12px;font-size:11.5px;color:var(--muted);background:#FCFBF8;border-top:1px solid var(--rule);display:flex;justify-content:space-between;gap:8px}
.tags{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.tag{font-size:11px;font-weight:700;padding:1px 7px;border-radius:999px}
.p0{background:#FAE3E1;color:#992019}
.p1{background:#FBEBDD;color:#9A4718}
.p2{background:#F7F0D8;color:#7C6014}
.p3{background:#E7EEF5;color:#3B5A79}
.okc{border-left:4px solid var(--accent)}
.okc .sym b{color:var(--accent)}
.okc .tag{background:#E5F3EE;color:#086353}
.ok{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:16px 0 10px}
.ok>a{background:#F4F1EA;border:1px solid var(--rule);border-radius:9px;overflow:hidden;color:var(--ink);display:flex;flex-direction:column;align-items:center}
.ok img{height:250px;width:auto;max-width:100%;object-fit:contain;background:#0F1519;display:block;border-radius:6px;border:1px solid #DCD6C9;margin:10px 0 0}
.ok span{display:block;padding:7px 10px;font-size:12.5px;border-top:1px solid var(--rule);width:100%;text-align:center}
.ok span b{color:var(--accent);font-weight:600}
.okitem{background:#F4F1EA;border:1px solid var(--rule);border-radius:9px;overflow:hidden;display:flex;flex-direction:column;align-items:center}
.okitem>a{background:transparent;border:none;border-radius:0;width:100%}
.okitem .okcheck{margin:8px 0 10px}
.okitem.off{display:none}
.okcheck{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);cursor:pointer;user-select:none;white-space:nowrap;margin-left:auto}
.okcheck input{width:15px;height:15px;accent-color:var(--accent);cursor:pointer;margin:0}
.card.checked{border-color:var(--accent);box-shadow:0 0 0 1px rgba(11,122,102,.35)}
.card.checked .okcheck{color:var(--accent);font-weight:700}
.okTag{background:#E5F3EE;color:#086353}
.badTag{background:#FAE3E1;color:#992019}
.card.problem{border-color:#E0B4AF}
.card.checked .tags .p0,.card.checked .tags .p1,.card.checked .tags .p2,.card.checked .tags .p3{display:none}
#ck-count{margin-left:auto;font-size:12.5px;color:var(--muted);white-space:nowrap;padding:4px 0}
@media(max-width:860px){#ck-count{margin-left:0;width:100%}}
footer{border-top:1px solid var(--rule);margin-top:46px;padding:20px 0 50px;color:var(--muted);font-size:12.5px}
#lb-overlay{display:none;position:fixed;inset:0;background:rgba(8,14,18,.93);z-index:9999;align-items:center;justify-content:center;padding:24px;cursor:zoom-out}
#lb-overlay img{max-width:94vw;max-height:92vh;border-radius:8px;box-shadow:0 20px 60px rgba(0,0,0,.5)}
#lb-tip{position:absolute;left:0;right:0;bottom:14px;text-align:center;color:#9DB3AD;font-size:12px;pointer-events:none}
@media(max-width:860px){.grid{grid-template-columns:1fr}.ok{grid-template-columns:repeat(2,1fr)}}
@media(max-width:520px){.ok{grid-template-columns:1fr}.card .shots img{height:auto}}
@media print{nav{display:none}.card{break-inside:avoid}body{background:#fff}}
"""

JS_LIGHTBOX = """
(function(){
  function ready(fn){ if(document.readyState!=='loading'){fn();} else {document.addEventListener('DOMContentLoaded',fn);} }
  ready(function(){
    var ov=document.createElement('div');
    ov.id='lb-overlay';
    ov.innerHTML='<img alt="预览"><div id="lb-tip">点击任意位置关闭</div>';
    document.body.appendChild(ov);
    ov.addEventListener('click',function(){ ov.style.display='none'; });
    document.querySelectorAll('.shots a, .ok a').forEach(function(a){
      a.addEventListener('click',function(e){
        var im=a.querySelector('img');
        if(!im || !im.src) return;
        e.preventDefault();
        ov.querySelector('img').src=im.src;
        ov.style.display='flex';
      });
    });
  });
})();
"""

JS_CHECK = """
(function(){
  var KEY='__KEY__';
  var state={};
  try{ state=JSON.parse(localStorage.getItem(KEY)||'{}')||{}; }catch(e){ state={}; }
  var grids={};
  ['c1','c2','c3'].forEach(function(id){ var g=document.querySelector('#'+id+' .grid'); if(g){ grids[id]=g; } });
  var destProblem=grids.c1, destOk=grids.c3;
  var okWrap=document.querySelector('#ok .ok');
  var okItems=[];
  var all=[];
  Object.keys(grids).forEach(function(key){
    [].slice.call(grids[key].children).forEach(function(el){ if(el.classList.contains('card')){ all.push(el); } });
  });
  function save(){ try{ localStorage.setItem(KEY, JSON.stringify(state)); }catch(e){} }
  function count(grid){ return grid?[].slice.call(grid.children).filter(function(el){ return el.classList.contains('card'); }).length:0; }
  function refresh(){
    var n1=count(grids.c1), n2=count(grids.c2), n3=count(grids.c3);
    var n4=okItems.filter(function(w){ return !w.classList.contains('off'); }).length;
    function set(id,txt){ var el=document.getElementById(id); if(el){ el.textContent=txt; } }
    function nav(id,n){ var el=document.getElementById(id); if(el){ el.textContent=(el.dataset.title||'')+'（'+n+'）'; } }
    nav('nav-c1',n1); nav('nav-c2',n2); nav('nav-c3',n3);
    set('hd-c1', n1+' 项 · 勾选后移入正常功能');
    set('hd-c2', n2+' 项 · 勾选后移入正常功能');
    set('hd-c3', n3+' 项 · 取消勾选会移回问题列表');
    set('hd-ok', n4+' 项 · 点击缩略图查看原始截图 · 取消勾选即标记为问题');
    set('ck-count','问题 '+(n1+n2)+' · 正常 '+(n3+n4));
    var m=document.getElementById('meta-count');
    if(m){ m.innerHTML='确认问题 <b>'+n1+' · 待确认 '+n2+' · 正常 '+(n3+n4)+'</b>'; }
  }
  all.forEach(function(card){
    var origin=card.dataset.origin;
    var idx=[].slice.call(grids[origin].children).filter(function(el){ return el.classList.contains('card'); }).indexOf(card);
    var id=origin+'-'+idx;
    var foot=card.querySelector('.foot') || card.querySelector('.top');
    var label=document.createElement('label');
    label.className='okcheck';
    label.innerHTML='<input type="checkbox"> 功能正确';
    foot.appendChild(label);
    var tags=card.querySelector('.tags');
    var badge=document.createElement('span');
    badge.className='tag';
    if(tags){ tags.appendChild(badge); }
    var cb=label.querySelector('input');
    function ensurePh(){
      if(card._ph){ return; }
      var ph=document.createElement('div');
      ph.className='ck-ph';
      ph.style.display='none';
      card.parentNode.insertBefore(ph,card);
      card._ph=ph;
    }
    function restorePh(){
      if(card._ph && card._ph.parentNode){ card._ph.parentNode.replaceChild(card,card._ph); card._ph=null; return true; }
      return false;
    }
    function apply(on){
      cb.checked=on;
      card.classList.toggle('checked',on);
      card.classList.toggle('okc',on);
      card.classList.toggle('problem',!on && origin==='c3');
      if(on){
        if(origin!=='c3' && destOk){ ensurePh(); destOk.appendChild(card); }
        else if(!restorePh() && destOk && card.parentNode!==destOk){ destOk.appendChild(card); }
        badge.className='tag okTag';
        badge.textContent='已确认正常';
        badge.style.display='inline-block';
      } else {
        if(origin==='c3' && destProblem){
          ensurePh();
          destProblem.appendChild(card);
          badge.className='tag badTag';
          badge.textContent='已标记为问题';
          badge.style.display='inline-block';
        } else {
          if(!restorePh() && grids[origin]){ grids[origin].appendChild(card); }
          badge.style.display='none';
        }
      }
    }
    var initial=(id in state)?!!state[id]:(origin==='c3');
    apply(initial);
    cb.addEventListener('change',function(){
      state[id]=cb.checked;
      save();
      apply(cb.checked);
      refresh();
    });
  });
  function manualCard(name, anchor, onBack){
    var art=document.createElement('article');
    art.className='card problem';
    var top=document.createElement('div');
    top.className='top';
    top.innerHTML='<div class="path">正常功能速查 → '+name+'</div><h3>人工标记为问题</h3><p class="sym">复核时确认该功能存在问题（原判定为正常）。</p>';
    var shots=document.createElement('div');
    shots.className='shots';
    shots.appendChild(anchor);
    var foot=document.createElement('div');
    foot.className='foot';
    foot.innerHTML='<span class="tags"><span class="tag badTag">已标记为问题</span></span><span>manual</span>';
    var lab=document.createElement('label');
    lab.className='okcheck';
    lab.innerHTML='<input type="checkbox"> 功能正确';
    foot.appendChild(lab);
    art.appendChild(top);
    art.appendChild(shots);
    art.appendChild(foot);
    lab.querySelector('input').addEventListener('change',function(){
      if(this.checked){ onBack(); }
    });
    return art;
  }
  if(okWrap && destProblem){
    [].slice.call(okWrap.children).filter(function(el){ return el.tagName==='A'; }).forEach(function(a,i){
      var wrap=document.createElement('div');
      wrap.className='okitem';
      a.parentNode.insertBefore(wrap,a);
      wrap.appendChild(a);
      var lab=document.createElement('label');
      lab.className='okcheck';
      lab.innerHTML='<input type="checkbox" checked> 功能正确';
      wrap.appendChild(lab);
      okItems.push(wrap);
      var cb=lab.querySelector('input');
      var nameEl=a.querySelector('span b');
      var name=nameEl?nameEl.textContent.trim():'功能';
      var card=null;
      function setProblem(p){
        if(p){
          if(!card){
            card=manualCard(name,a,function(){ setProblem(false); });
            destProblem.appendChild(card);
          }
          wrap.classList.add('off');
          cb.checked=false;
        } else {
          if(card){
            wrap.insertBefore(a,lab);
            card.parentNode.removeChild(card);
            card=null;
          }
          wrap.classList.remove('off');
          cb.checked=true;
        }
        refresh();
      }
      cb.addEventListener('change',function(){ state['ok-'+i]=cb.checked?0:1; save(); setProblem(!cb.checked); });
      if(state['ok-'+i]===1){ setProblem(true); }
    });
  }
  refresh();
})();
"""


def md_bold(text):
    s = html.escape(str(text or ""))
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)


def data_uri(path):
    ext = os.path.splitext(path)[1].lower()
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}.get(ext, "image/png")
    with open(path, "rb") as f:
        return f"data:{mime};base64," + base64.b64encode(f.read()).decode("ascii")


def resolve(root, p):
    if os.path.isabs(p):
        return p
    return os.path.normpath(os.path.join(root, p))


def card_html(root, item, origin, shot_count):
    imgs = []
    for p in item.get("images", []):
        full = resolve(root, p)
        if not os.path.isfile(full):
            print(f"警告：缺少截图 {p}", file=sys.stderr)
            continue
        imgs.append(f'<a href="{html.escape(p)}"><img src="{data_uri(full)}" alt=""></a>')
    if not imgs:
        imgs.append('<div class="missing" style="color:#992019;font-size:12px;padding:20px">未提供截图</div>')
    sev = html.escape(item.get("severity", "P2"))
    tags = "".join(f'<span class="tag {html.escape(t)}">{html.escape(t.upper())}</span>' for t in item.get("tags", []))
    evi = f'<p class="evi">{md_bold(item["evidence"])}</p>' if item.get("evidence") else ""
    foot = item.get("foot") or ""
    if foot:
        foot = f'<span>{html.escape(str(foot))}</span>'
    return (
        f'<article class="card problem" data-origin="{origin}">'
        f'<div class="top"><div class="path">{html.escape(item.get("path", ""))}</div>'
        f'<h3>{html.escape(item.get("title", ""))}</h3>'
        f'<p class="sym">{md_bold(item.get("desc", ""))}</p>{evi}</div>'
        f'<div class="shots">{"".join(imgs)}</div>'
        f'<div class="foot"><span class="tags"><span class="tag {sev}">{sev.upper()}</span>{tags}</span>{foot}</div>'
        f'</article>'
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="测试产物根目录")
    ap.add_argument("--issues", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    root = os.path.abspath(a.run)
    with io.open(a.issues, encoding="utf-8") as f:
        data = json.load(f)

    app = data.get("app", {})
    meta_items = [("目标", app.get("package", "")), ("版本", app.get("version", "")),
                  ("设备/浏览器", app.get("device", "")), ("系统", app.get("os", "")),
                  ("测试日期", app.get("date", ""))]
    meta = "".join(f"<span>{html.escape(k)} <b>{html.escape(str(v))}</b></span>" for k, v in meta_items if v)
    meta += '<span id="meta-count"></span>'

    sections = {s.get("id"): s for s in data.get("sections", [])}
    for sid in ["c1", "c2", "c3"]:
        sections.setdefault(sid, {"id": sid, "title": {"c1": "确认问题", "c2": "待确认", "c3": "正常功能"}[sid], "items": []})

    nav_links = []
    for sid in ["c1", "c2", "c3"]:
        nav_links.append(f'<a href="#{sid}" id="nav-{sid}" data-title="{html.escape(sections[sid].get("title", ""))}">{html.escape(sections[sid].get("title", ""))}</a>')

    body_sections = []
    for sid in ["c1", "c2", "c3"]:
        s = sections[sid]
        cards = "".join(card_html(root, item, sid, 0) for item in s.get("items", []))
        body_sections.append(
            f'<section id="{sid}"><h2>{html.escape(s.get("title", ""))} <small id="hd-{sid}"></small></h2>'
            f'<div class="grid">{cards}</div></section>'
        )

    ok_html = ""
    ok_items = data.get("ok", [])
    if ok_items:
        anchors = []
        for it in ok_items:
            full = resolve(root, it.get("image", ""))
            if not os.path.isfile(full):
                print(f"警告：缺少速查截图 {it.get('image')}", file=sys.stderr)
                img = '<div style="color:#992019;font-size:12px;padding:20px">未提供截图</div>'
                src = ""
            else:
                src = data_uri(full)
                img = f'<img src="{src}" alt="">'
            anchors.append(
                f'<a href="{html.escape(it.get("image", ""))}">{img}'
                f'<span><b>{html.escape(it.get("name", ""))}</b><br>{html.escape(it.get("desc", ""))}</span></a>'
            )
        ok_html = f'<section id="ok"><h2>四、正常功能速查 <small id="hd-ok"></small></h2><div class="ok">{"".join(anchors)}</div></section>'
        nav_links.append('<a href="#ok">正常功能速查</a>')

    nav_links.append('<span id="ck-count"></span>')

    notes = data.get("notes", [])
    note_html = ""
    if notes:
        note_html = '<div class="note">判定依据（本轮口径，可在待确认区调整）：' + "；".join(html.escape(n) for n in notes) + "</div>"

    coverage = data.get("coverage") or {}
    cov_items = coverage.get("items", [])
    cov_html = ""
    if cov_items or coverage.get("total"):
        total = coverage.get("total") or len(cov_items)
        tested = coverage.get("tested")
        if tested is None:
            tested = sum(1 for i in cov_items if i.get("status") == "tested")
        blocked = coverage.get("blocked")
        if blocked is None:
            blocked = sum(1 for i in cov_items if i.get("status") == "blocked")
        failed = coverage.get("failed")
        if failed is None:
            failed = sum(1 for i in cov_items if i.get("status") == "failed")
        untested = max(0, total - tested - blocked - failed)
        rest = [i for i in cov_items if i.get("status") != "tested"]
        rows = "".join(
            f'<tr><td>{html.escape(i.get("name", ""))}</td>'
            f'<td class="st-{html.escape(i.get("status", "untested"))}">{html.escape({"blocked": "受阻", "failed": "失败", "untested": "未测"}.get(i.get("status"), i.get("status", "")))}</td>'
            f'<td>{html.escape(i.get("note", ""))}</td></tr>'
            for i in rest
        )
        miss = ("<div class='miss'><b>未测/受阻清单</b><table><tr><th>功能</th><th>状态</th><th>原因 / 证据</th></tr>"
                + rows + "</table></div>") if rest else "<div class='miss'>功能地图条目已全部执行，无未测项。</div>"
        cov_html = (f'<div class="cov" id="coverage"><h3>覆盖台账 <small>（功能地图逐条执行）</small></h3>'
                    f'<div class="stats"><span><b>{tested}</b>/ {total} 已测</span>'
                    f'<span><b>{blocked}</b> 受阻</span><span><b>{failed}</b> 失败</span>'
                    f'<span><b>{untested}</b> 未测</span></div>{miss}</div>')
        nav_links.insert(0, '<a href="#coverage">覆盖台账</a>')

    key = "flowtest-" + (app.get("package") or os.path.basename(root)) + "-v1"

    page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(data.get("title", "问题取证清单"))}</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <div class="wrap">
    <div class="kicker">{html.escape(data.get("kicker", "功能测试 · 取证清单"))}</div>
    <h1>{html.escape(data.get("title", ""))}</h1>
    <p>{html.escape(data.get("subtitle", ""))}</p>
    <div class="meta">{meta}</div>
  </div>
</header>
<nav><div class="wrap">{"".join(nav_links)}</div></nav>
<div class="wrap">
  {note_html}
  {cov_html}
  {"".join(body_sections)}
  {ok_html}
</div>
<footer><div class="wrap">每一步均有截图与页面快照留证，截图内嵌在本文件中，可离线查看。勾选状态保存在本机浏览器。</div></footer>
<script>{JS_LIGHTBOX}</script>
<script>{JS_CHECK.replace("__KEY__", key)}</script>
</body>
</html>
"""

    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with io.open(a.out, "w", encoding="utf-8") as f:
        f.write(page)

    counts = {sid: len(sections[sid].get("items", [])) for sid in ["c1", "c2", "c3"]}
    print(json.dumps({"out": os.path.abspath(a.out), "size": os.path.getsize(a.out),
                      "counts": counts, "ok": len(ok_items),
                      "coverage": {k: coverage.get(k) for k in ("total", "tested", "blocked", "failed")} if coverage else None},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
