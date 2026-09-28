"""Render an agent trace (JSONL of LangChain messages) as one self-contained HTML page.

Viewer adapted from jeromevde/Agimo fix_scrapers/debug.py: collapsible tool calls with their
results, token counts per model call. Open the file in a browser; nothing is fetched.
"""

from __future__ import annotations


def render(lines: list[str], title: str, live: bool = False) -> str:
    """The HTML viewer for these JSONL trace lines; `live` reloads it every 5 seconds."""
    safe = "\n".join(lines).replace("&", "&amp;").replace("<", "&lt;")
    page = HTML.replace("__DATA__", safe).replace("__TITLE__", title)
    refresh = '<meta http-equiv="refresh" content="5">' if live else ""
    return page.replace('<meta charset="utf-8">', '<meta charset="utf-8">' + refresh, 1)


HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Agent trace — __TITLE__</title>
<style>
:root{
  --bg:#0d1117; --bg-raised:#151b23; --bg-hover:#1c2531; --border:#242c38;
  --text:#c9d1d9; --text-dim:#7d8590; --text-faint:#4d5561;
  --accent-user:#5b9dd9; --accent-ai:#8b7fd9; --accent-tool:#4fae7a;
  --accent-warn:#d99a4f;
  --mono: "SF Mono","Berkeley Mono",ui-monospace,"Cascadia Code","JetBrains Mono",Consolas,monospace;
}
*{box-sizing:border-box;}
html,body{margin:0; background:var(--bg);}
body{padding:24px 12px; font-family:var(--mono);}
#root{
  background:var(--bg); color:var(--text); font-family:var(--mono);
  font-size:12.5px; line-height:1.55; border-radius:10px; border:1px solid var(--border);
  overflow:hidden; max-width:900px; margin:0 auto;
}
.tv-header{display:flex; align-items:center; justify-content:space-between; padding:10px 16px; background:var(--bg-raised); border-bottom:1px solid var(--border);}
.tv-header-left{display:flex; align-items:center; gap:8px;}
.tv-dots{display:flex; gap:6px;}
.tv-dot{width:9px;height:9px;border-radius:50%;}
.tv-title{color:var(--text-dim); font-size:11.5px; letter-spacing:.02em;}
.tv-stats{color:var(--text-faint); font-size:11px; display:flex; gap:14px;}
.tv-stats b{color:var(--text-dim); font-weight:600;}
.tv-body{max-height:82vh; overflow-y:auto; padding:10px 0;}
.tv-body::-webkit-scrollbar{width:9px;}
.tv-body::-webkit-scrollbar-thumb{background:#2a3341; border-radius:5px;}
.tv-row{position:relative; padding:3px 16px;}
.tv-rail{position:absolute; left:26px; top:0; bottom:0; width:1px; background:var(--border);}
.tv-row:first-child .tv-rail{top:18px;}
.tv-row:last-child .tv-rail{bottom:calc(100% - 18px);}
.tv-block{position:relative; margin:6px 0 6px 34px; border:1px solid var(--border); border-radius:8px; background:var(--bg-raised); overflow:hidden;}
.tv-node{position:absolute; left:-34px; top:10px; width:19px;height:19px;border-radius:50%; display:flex;align-items:center;justify-content:center; font-size:10px; font-weight:700; border:2px solid var(--bg); z-index:2;}
.tv-node.system{background:var(--text-faint); color:#0d1117;}
.tv-node.user{background:var(--accent-user); color:#08131e;}
.tv-node.ai{background:var(--accent-ai); color:#0d0a1e;}
.tv-node.tool{background:var(--accent-tool); color:#04140b;}
.tv-pad{padding:8px 12px;}
.tv-head{display:flex; align-items:flex-start; gap:8px; padding:8px 12px; cursor:pointer; user-select:none;}
.tv-head:hover{background:var(--bg-hover);}
.tv-role{font-weight:700; font-size:11.5px; letter-spacing:.03em;}
.tv-role.system{color:var(--text-dim);}
.tv-role.user{color:var(--accent-user);}
.tv-role.ai{color:var(--accent-ai);}
.tv-role.tool{color:var(--accent-tool); font-weight:700; flex:1; min-width:0; white-space:pre-wrap; word-break:break-word;}
.tv-meta{color:var(--text-faint); font-size:10.5px; flex-shrink:0; display:flex; gap:8px; align-items:center;}
.tv-badge{font-size:9.5px; padding:1px 6px; border-radius:20px; border:1px solid var(--border); color:var(--text-faint);}
.tv-chevron{color:var(--text-faint); font-size:10px; transition:transform .12s ease; flex-shrink:0; margin-top:3px;}
.tv-chevron.open{transform:rotate(90deg);}
.tv-content{padding:0 12px 12px 12px; display:none;}
.tv-content.open{display:block;}
.tv-text{white-space:pre-wrap; word-break:break-word; color:var(--text); font-size:12px; line-height:1.6; padding:4px 0 0 0;}
.tv-text a{color:var(--accent-user); text-decoration:underline;}
.tv-text a:hover{color:#7eb8e8;}
.tv-toolresult{background:#0b0f14; padding:8px 10px; font-size:11.3px; color:var(--text-dim); white-space:pre-wrap; word-break:break-word; max-height:320px; overflow-y:auto; border-radius:6px; border:1px solid var(--border);}
.tv-toolresult::-webkit-scrollbar{width:7px;}
.tv-toolresult::-webkit-scrollbar-thumb{background:#2a3341; border-radius:4px;}
.tv-linenum{color:var(--text-faint); display:inline-block; width:2.4em; user-select:none;}
.tv-exit{display:inline-block; font-size:9.5px; padding:1px 6px; border-radius:20px; flex-shrink:0;}
.tv-exit.ok{color:var(--accent-tool); border:1px solid #1e3a2a;}
.tv-exit.err{color:#e06c75; border:1px solid #4a2323;}
.tv-empty{padding:40px; text-align:center; color:var(--text-faint);}
</style>
</head>
<body>
<div id="root"></div>
<pre id="trace-data" hidden>__DATA__</pre>
<script>
function parseTrace(raw){
  return raw.split("\n").map(l=>l.trim()).filter(Boolean).map(l=>{
    try { return JSON.parse(l); } catch(e){ return null; }
  }).filter(Boolean);
}
function esc(s){
  return String(s).replace(/[&<>"']/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
function linkify(text){
  let s = esc(text || "");
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  s = s.replace(/(^|[\s(])((https?:\/\/)[^\s<>&"]+)/g, (m, pre, url) => `${pre}<a href="${url}" target="_blank" rel="noopener">${url}</a>`);
  return s;
}
function argText(v){ return typeof v === "string" ? v : JSON.stringify(v, null, 2); }
function callLine(tc){
  const args = tc.args && typeof tc.args === "object" ? tc.args : {};
  const bits = [tc.name];
  Object.entries(args).forEach(([k,v])=>{
    let t = argText(v).replace(/\s+/g, " ");
    if(t.length > 160) t = t.slice(0, 160) + "…";
    bits.push(k, t);
  });
  return bits.join(" ");
}
function longArgs(tc){
  const args = tc.args && typeof tc.args === "object" ? tc.args : {};
  return Object.entries(args).filter(([,v])=> argText(v).replace(/\s+/g," ").length > 160);
}
function toolResultText(content){
  if(content == null) return "";
  let s = typeof content === "string" ? content : (function(){ try { return JSON.stringify(content, null, 2); } catch(e){ return String(content); } })();
  if(s.length > 8000) s = s.slice(0, 3000) + "\n… truncated …\n" + s.slice(-2000);
  return s;
}
function addLineNumbers(text){
  const lines = text.split("\n");
  if(lines.length < 3) return linkify(text);
  return lines.map((l,i)=>`<span class="tv-linenum">${i+1}</span>${linkify(l)}`).join("\n");
}
function row(blockHtml){ return `<div class="tv-row"><div class="tv-rail"></div>${blockHtml}</div>`; }
function textBlock(kind, letter, label, text, meta){
  return row(`
    <div class="tv-block">
      <div class="tv-node ${kind}">${letter}</div>
      <div class="tv-pad">
        <span class="tv-role ${kind}">${label}</span>
        ${meta||""}
        <div class="tv-text">${linkify(text||"")}</div>
      </div>
    </div>`);
}
function callBlock(tc, result, id){
  const exitCode = result && result.artifact && result.artifact.exit_code;
  const status = result && result.status;
  const long = longArgs(tc);
  let inner = "";
  long.forEach(([k,v])=>{
    inner += `<div class="tv-text"><span style="color:var(--accent-warn)">${esc(k)}</span>\n${linkify(argText(v))}</div>`;
  });
  if(result) inner += `<div class="tv-toolresult">${addLineNumbers(toolResultText(result.content))}</div>`;
  const badge = exitCode !== undefined
    ? `<span class="tv-exit ${exitCode===0?'ok':'err'}">exit ${exitCode}</span>`
    : (status ? `<span class="tv-badge">${esc(status)}</span>` : "");
  if(!inner){
    return row(`
      <div class="tv-block">
        <div class="tv-node tool">T</div>
        <div class="tv-pad"><span class="tv-role tool">${esc(callLine(tc))}</span></div>
      </div>`);
  }
  return row(`
    <div class="tv-block">
      <div class="tv-node tool">T</div>
      <div class="tv-head" onclick="tvToggle('${id}')">
        <span class="tv-role tool">${esc(callLine(tc))}</span>
        <span class="tv-meta">${badge}</span>
        <span class="tv-chevron" id="${id}-chev">▸</span>
      </div>
      <div class="tv-content" id="${id}">${inner}</div>
    </div>`);
}

function render(){
  const dataTag = document.getElementById("trace-data");
  const raw = dataTag ? dataTag.textContent : "";
  const data = parseTrace(raw);
  const root = document.getElementById("root");
  if(!data.length){ root.innerHTML = '<div class="tv-empty">No trace data found</div>'; return; }

  const byCall = {};
  data.forEach(m => { if(m.type === "tool" && m.tool_call_id) byCall[m.tool_call_id] = m; });

  const nCalls = data.filter(m=>m.type==="ai" && m.tool_calls && m.tool_calls.length).length;
  const totalTok = data.reduce((a,m)=> a + (m.usage_metadata && m.usage_metadata.total_tokens || 0), 0);

  let html = `<div class="tv-header">
    <div class="tv-header-left">
      <div class="tv-dots">
        <div class="tv-dot" style="background:#ff5f57"></div>
        <div class="tv-dot" style="background:#febc2e"></div>
        <div class="tv-dot" style="background:#28c840"></div>
      </div>
      <span class="tv-title">__TITLE__</span>
    </div>
    <div class="tv-stats">
      <span><b>${data.length}</b> events</span>
      <span><b>${nCalls}</b> tool calls</span>
      ${totalTok ? `<span><b>${totalTok.toLocaleString()}</b> tokens</span>` : ""}
    </div>
  </div><div class="tv-body">`;

  data.forEach((msg, idx)=>{
    if(msg.type === "tool" && msg.tool_call_id && byCall[msg.tool_call_id]) return;
    if(msg.type === "system" || msg.type === "human"){
      const kind = msg.type === "system" ? "system" : "user";
      html += textBlock(kind, kind==="system"?"S":"U", kind, msg.content||"");
    } else if(msg.type === "ai"){
      const calls = msg.tool_calls || [];
      if(msg.content){
        const model = msg.response_metadata && msg.response_metadata.model_name;
        const tok = msg.usage_metadata && msg.usage_metadata.total_tokens;
        const meta = (model||tok)
          ? `<span class="tv-meta" style="float:right">${model?`<span class="tv-badge">${esc(model)}</span>`:""}${tok?`<span>${tok}tok</span>`:""}</span>`
          : "";
        html += textBlock("ai", "A", "assistant", msg.content, meta);
      }
      calls.forEach((tc, i)=>{
        html += callBlock(tc, tc.id ? byCall[tc.id] : null, "b"+idx+"c"+i);
      });
    } else if(msg.type === "tool"){
      html += callBlock({name: msg.name || "tool", args: {}}, msg, "b"+idx);
    }
  });

  html += "</div>";
  root.innerHTML = html;
  const body = root.querySelector(".tv-body");
  if (body) body.scrollTop = body.scrollHeight;
}
window.tvToggle = function(id){
  const el = document.getElementById(id);
  const chev = document.getElementById(id+"-chev");
  if(el) el.classList.toggle("open");
  if(chev) chev.classList.toggle("open");
};
render();
</script>
</body>
</html>
"""
