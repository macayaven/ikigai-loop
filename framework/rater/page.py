"""Slice A, AD7: the offline rater page, one self-contained file."""

from __future__ import annotations

import html
import json
from collections.abc import Sequence

CSP = (
    '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
    "script-src 'unsafe-inline'; style-src 'unsafe-inline'; base-uri 'none'; "
    "form-action 'none'\">"
)


def render_page(
    pack_id: str,
    pack_hash: str,
    items: Sequence[tuple[str, str, Sequence[str]]],
) -> str:
    """Render the whole rating flow as one offline HTML document."""
    rows = [
        {"item_id": item_id, "text": text, "evidence": list(evidence)}
        for item_id, text, evidence in items
    ]
    payload = json.dumps(
        {"pack_id": pack_id, "pack_hash": pack_hash, "items": rows},
        ensure_ascii=False,
        sort_keys=True,
    ).replace("<", "\\u003c")
    cards = "\n".join(
        '      <section class="card" data-item="'
        + html.escape(item_id, quote=True)
        + '">\n        <p class="sentence">'
        + html.escape(text)
        + '</p>\n        <h2 class="evidence-label">Cited data</h2>\n        <ul>\n'
        + "".join("          <li>" + html.escape(line) + "</li>\n" for line in evidence)
        + "        </ul>\n      </section>"
        for item_id, text, evidence in items
    )
    count = len(rows)
    return (
        """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
"""
        + CSP
        + """
<title>Rater pack """
        + html.escape(pack_id)
        + """</title>
<style>
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.5;
color:#111;background:#fff;max-width:40rem;margin:0 auto;padding:1rem;}
h1{font-size:1.6rem;}p,li{font-size:1.15rem;}
.sentence{font-weight:700;font-size:1.35rem;}
.evidence-label{font-size:1.15rem;margin-bottom:0;}
button{font-size:1.2rem;min-height:56px;width:100%;box-sizing:border-box;
display:block;margin:.4rem 0;padding:.7rem 1.2rem;border:2px solid #111;
background:#fff;color:#111;}
button.primary{background:#111;color:#fff;}
button.chosen{outline:4px solid #111;outline-offset:2px;}
button small{display:block;font-size:.9rem;font-weight:normal;}
.counter{font-size:1rem;color:#111;}
.evidence{background:#f2f2f2;padding:.6rem 1rem;}
.end textarea,pre.result{white-space:pre-wrap;word-break:break-word;
border:1px solid #111;padding:.6rem;font-size:.95rem;}
.hidden{display:none;}
</style>
</head>
<body>
<div id="start">
<h1>Rate """
        + str(count)
        + """ sentences</h1>
<p>This takes about 10 minutes. You will see """
        + str(count)
        + """ sentences,
one at a time, each with the facts and numbers it rests on.</p>
<p>Each card looked at the three days before it as three back-to-back 24-hour periods called earlier, prior and last, last being the most recent. Across the whole three-day window means all three together. A change since the previous card compares this card's number with the number on the card before.</p>
<p>Each sentence comes from a card the app showed Carlos, with the data it cites under it. Judge only whether the sentence follows from that data, not whether it is a good idea.</p>
<p><strong>Yes</strong> means the data shown backs up everything the sentence says about it. <strong>No</strong> means the data shown says something different, or does not back up what the sentence says. <strong>Can't tell</strong> means you cannot decide from what is shown. Nothing is sent anywhere; your answers stay on this device until you send the result file back.</p>
<p id="preview-note">If the Start button does nothing, open this file in a web
browser instead of a preview.</p>
<noscript><p>If the Start button does nothing, open this file in a web browser
instead of a preview.</p></noscript>
<p id="progress"></p>
<p><button class="primary" id="begin" type="button">Start</button></p>
</div>
<div id="rate" class="hidden">
<p class="counter"><span id="pos">1 of """
        + str(count)
        + """</span></p>
"""
        + cards
        + """
<div>
<button id="yes" type="button">Yes<small>The data backs up everything it says.</small></button>
<button id="no" type="button">No<small>It says something different, or does not back it up.</small></button>
<button id="cant" type="button">Can't tell<small>You cannot decide from what is shown.</small></button>
</div>
<div><button id="back" type="button">Back</button></div>
</div>
<div id="end" class="hidden">
<h1>Done</h1>
<p>Download the result file and send it back, or copy the text below.</p>
<p><button id="download" type="button">Download result</button>
<button id="copy" type="button">Copy result</button></p>
<p id="copy-status"></p>
<pre class="result" id="result-text"></pre>
<div><button id="again" type="button">Back to the sentences</button></div>
</div>
<script type="application/json" id="rater-data">"""
        + payload
        + """</script>
<script>
(function(){
var data=JSON.parse(document.getElementById("rater-data").textContent);
var key="rater-"+data.pack_id;
var startKey=key+"-started";
var answers={};
var memoryOnly=false;
function load(){
 try{var raw=window.localStorage.getItem(key);if(raw){answers=JSON.parse(raw);}}
 catch(err){answers={};memoryOnly=true;}
}
function save(){
 try{window.localStorage.setItem(key,JSON.stringify(answers));}
 catch(err){memoryOnly=true;}
}
function loadStart(){
 var startedAt=null;
 try{startedAt=window.localStorage.getItem(startKey);}catch(err){startedAt=null;}
 if(!startedAt){
  startedAt=new Date().toISOString();
  try{window.localStorage.setItem(startKey,startedAt);}
  catch(err){memoryOnly=true;}
 }
 return startedAt;
}
var startedAt=loadStart();
var order=[];for(var i=0;i<data.items.length;i++){order.push(data.items[i].item_id);}
var pos=0;
var startPane=document.getElementById("start");
var ratePane=document.getElementById("rate");
var endPane=document.getElementById("end");
var posLabel=document.getElementById("pos");
var progress=document.getElementById("progress");
var beginButton=document.getElementById("begin");
var previewNote=document.getElementById("preview-note");
var copyStatus=document.getElementById("copy-status");
var yesButton=document.getElementById("yes");
var noButton=document.getElementById("no");
var cantButton=document.getElementById("cant");
if(previewNote){previewNote.style.display="none";}
function answeredCount(){
 var done=0;
 for(var i=0;i<order.length;i++){if(answers[order[i]]){done++;}}
 return done;
}
function firstUnanswered(){
 for(var i=0;i<order.length;i++){if(!answers[order[i]]){return i;}}
 return order.length;
}
function refreshStart(){
 load();
 var done=answeredCount();
 var first=firstUnanswered();
 if(order.length&&done>0){
  progress.textContent=done+" of "+order.length+" already answered.";
  if(first<order.length){beginButton.textContent="Continue at sentence "+(first+1);}
  else{beginButton.textContent="Review sentences";}
 }else{
  progress.textContent="";
  beginButton.textContent="Start";
 }
 if(first<order.length){pos=first;}
 else{pos=0;}
}
var sections=ratePane.querySelectorAll("section.card");
function markChosen(){
 var entry=answers[order[pos]];
 yesButton.classList.toggle("chosen",!!(entry&&entry.label==="supported"));
 noButton.classList.toggle("chosen",!!(entry&&entry.label==="not_supported"));
 cantButton.classList.toggle("chosen",!!(entry&&entry.label==="cant_tell"));
}
function show(){
 for(var i=0;i<sections.length;i++){
  sections[i].classList.toggle("hidden",i!==pos);
 }
 posLabel.textContent=(pos+1)+" of "+order.length;
 markChosen();
}
function answer(label){
 if(!order.length){return;}
 answers[order[pos]]={label:label,at:new Date().toISOString()};
 save();
 if(pos<order.length-1){pos++;show();}
 else{finish();}
}
function finish(){
 var out={pack_id:data.pack_id,pack_hash:data.pack_hash,started_at:startedAt,
  ended_at:new Date().toISOString(),answers:[]};
 for(var i=0;i<order.length;i++){
  var entry=answers[order[i]];
  if(entry){out.answers.push({item_id:order[i],label:entry.label,answered_at:entry.at});}
 }
 document.getElementById("result-text").textContent=JSON.stringify(out,null,2);
 ratePane.classList.add("hidden");
 endPane.classList.remove("hidden");
}
document.getElementById("begin").addEventListener("click",function(){
 refreshStart();
 startPane.classList.add("hidden");ratePane.classList.remove("hidden");show();
});
yesButton.addEventListener("click",function(){answer("supported");});
noButton.addEventListener("click",function(){answer("not_supported");});
cantButton.addEventListener("click",function(){answer("cant_tell");});
document.getElementById("back").addEventListener("click",function(){
 if(pos>0){pos--;show();}
});
document.getElementById("again").addEventListener("click",function(){
 endPane.classList.add("hidden");ratePane.classList.remove("hidden");show();
});
document.getElementById("download").addEventListener("click",function(){
 var blob=new Blob([document.getElementById("result-text").textContent],
  {type:"application/json"});
 var target=window.URL.createObjectURL(blob);
 var link=document.createElement("a");
 link.setAttribute("download","result-"+data.pack_id+".json");
 link.setAttribute("href",target);
 document.body.appendChild(link);link.click();link.remove();
 window.setTimeout(function(){window.URL.revokeObjectURL(target);},1000);
});
document.getElementById("copy").addEventListener("click",function(){
 var text=document.getElementById("result-text").textContent;
 function setStatus(message){copyStatus.textContent=message;}
 function fallback(){
  var area=document.createElement("textarea");
  area.value=text;document.body.appendChild(area);area.select();
  try{
   document.execCommand("copy");
   setStatus("Copied.");
  }catch(err){
   setStatus("Copy did not work. Select the text above and copy it by hand.");
  }
  area.remove();
 }
 if(window.navigator.clipboard&&window.navigator.clipboard.writeText){
  window.navigator.clipboard.writeText(text).then(function(){
   setStatus("Copied.");
  },function(){
   fallback();
  });
 }else{fallback();}
});
refreshStart();
})();
// answers are kept in memory when storage throws
</script>
</body>
</html>
"""
    )
