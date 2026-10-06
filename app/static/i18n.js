/* Isôko web UI language: Kinyarwanda by default, English on request.
   Pages are written in English; this layer translates text nodes and attributes as they render
   (including dynamic tables via a MutationObserver). window.T(s) translates a string in JS. */
(function () {
  var RW = {
    "Measured, not claimed": "Byapimwe, si amagambo gusa", "Advisory answers: generic model vs Isôko (v0.1 → v0.2)": "Ibisubizo: moderi isanzwe na Isôko (v0.1 → v0.2)",
    "Kinyarwanda speech recognition (error %, lower is better)": "Kumva Ikinyarwanda kivugwa (amakosa %, make ni byiza)",
    "Spoken answers: intelligibility (error %, lower is better)": "Ibisubizo bivugwa: byumvikana (amakosa %, make ni byiza)",
    "Translation (chrF, 0–100)": "Ubusemuzi (chrF, 0–100)", "Photo diagnosis (accuracy %)": "Isuzuma ry'amafoto (ukuri %)",
    "Security and robustness tests": "Isuzuma ry'umutekano n'ubudahangarwa", "80 real Kinyarwanda recordings": "Amajwi 80 nyayo y'Ikinyarwanda",
    "Speech → recognition round trip on 20 advisory sentences": "Interuro 20 z'inama: ijwi → kumva", "60 agriculture sentence pairs · Digital Umuganda corpus": "Interuro 60 z'ubuhinzi · Digital Umuganda",
    "East African field photos · beans and cassava": "Amafoto yo mu mirima y'Afurika y'Iburasirazuba · ibishyimbo n'imyumbati",
    "Kinyarwanda speech recognition error": "Amakosa yo kumva Ikinyarwanda", "Spoken-answer error": "Amakosa y'ibisubizo bivugwa", "Security tests passed": "Isuzuma ry'umutekano ryatsinzwe",
    "Generic gemma3:4b": "gemma3:4b isanzwe", "Isôko v0.1": "Isôko v0.1", "Isôko v0.2": "Isôko v0.2", "Character error": "Amakosa y'inyuguti", "Word error": "Amakosa y'amagambo",
    "Raw text": "Inyandiko uko iri", "Numbers spoken as words": "Imibare ivugwa mu magambo", "With Kinyarwanda number & unit normaliser": "Imibare n'ibipimo byanditswe mu Kinyarwanda",
    "Accuracy": "Ukuri", "Accuracy when confident": "Ukuri iyo yizeye", "Category": "Icyiciro", "Passed": "Byatsinze",
    // v0.2: phone, promoter, voice, photo
    "Farmer phone": "Telefoni y'umuhinzi", "Farmer promoter": "Umuhinzi mworozi w'icyitegererezo",
    "Farmer promoters & extension officers": "Abahinzi borozi b'icyitegererezo n'abajyanama b'ubuhinzi",
    "Advice in your language, on your phone": "Inama mu rurimi rwawe, kuri telefoni yawe",
    "Speak, send a photo, or use the menu.": "Vuga, ohereza ifoto, cyangwa ukoreshe menu.",
    "Talk to the advisor": "Vugana n'umujyanama", "Send a crop photo": "Ohereza ifoto y'igihingwa", "USSD menu": "Menu ya USSD",
    "Back": "Subira inyuma", "Ask in Kinyarwanda": "Baza mu Kinyarwanda",
    "Tap to speak, tap again to send": "Kanda uvuge, wongere ukande wohereze", "Listening… tap to send": "Ndumva… kanda wohereze",
    "Microphone not available": "Mikoro ntiboneka", "Tap to ask again": "Kanda wongere ubaze",
    "Which crop?": "Igihingwa ki?", "Take or choose a photo": "Fata cyangwa uhitemo ifoto",
    "On a basic phone: 1 is an IVR call-back, 2 goes through WhatsApp or a farmer promoter's smartphone, 3 is the USSD menu.":
      "Kuri telefoni isanzwe: 1 ni ihamagara ry'ijwi (IVR), 2 inyura kuri WhatsApp cyangwa kuri telefoni y'umuhinzi mworozi, 3 ni menu ya USSD.",
    "Your field toolkit": "Ibikoresho byawe byo mu murima", "More farmers reached, the same validated advice.": "Abahinzi benshi bagerwaho, inama zemewe zimwe.",
    "Second opinion": "Igitekerezo cya kabiri", "Log a farm visit": "Andika uruzinduko", "Quick refresher": "Kwibutsa byihuse",
    "Report an outbreak": "Tanga raporo y'icyorezo", "Beans": "Ibishyimbo", "Cassava": "Imyumbati", "Maize": "Ibigori", "Potato": "Ibirayi",
    "Farmer code": "Kode y'umuhinzi", "Crop": "Igihingwa", "No problem": "Nta kibazo", "Notes": "Ibisobanuro",
    "Save visit": "Bika uruzinduko", "Saved": "Byabitswe", "Ask": "Baza", "Sent": "Byoherejwe",
    "Send to MINAGRI / RAB": "Ohereza kuri MINAGRI / RAB", "How many farms are affected?": "Imirima ingahe yibasiwe?",
    "e.g. Ibigori byanjye bifite nkongwa, nkore iki?": "urugero: Ibigori byanjye bifite nkongwa, nkore iki?",
    "Last 30 days · live · no phone numbers shown": "Iminsi 30 ishize · ako kanya · nta nimero za telefoni zigaragazwa",
    "Voice questions": "Ibibazo by'ijwi", "Photo diagnoses": "Isuzuma ry'amafoto", "Promoter farm visits": "Inzinduko z'abahinzi borozi",
    "Same open model · left alone · right through Isôko": "Moderi imwe · ibumoso yonyine · iburyo binyuze muri Isôko",
    "70 farmer questions · 49 English · 21 Kinyarwanda · 8 off-topic": "Ibibazo 70 · 49 mu Cyongereza · 21 mu Kinyarwanda · 8 bitari iby'ubuhinzi",
    "no speech recognised": "nta majwi yumvikanye", "audio too short": "ijwi ni rigufi cyane",
    // navigation and brand
    "USSD simulator": "Igerageza rya USSD",
    "MINAGRI dashboard": "Imbonerahamwe ya MINAGRI",
    "Live comparison": "Igereranya",
    "Evaluation": "Isuzuma",
    "AI farm advisory · USSD / SMS": "Inama z'ubuhinzi zifashishije AI · USSD / SMS",
    "Farmer needs, in real time": "Ibyo abahinzi bakeneye, ako kanya",
    "Same open model, with and without grounding": "Moderi imwe, ifite cyangwa idafite ubumenyi bwemewe",
    "How accurate is it, and how will it improve?": "Ni iy'ukuri ku rugero rungana iki, kandi izanozwa ite?",
    // simulator
    "Dial the service code to start: *xxx#": "Kanda kode ya serivisi kugira ngo utangire: *xxx#",
    "Cancel": "Hagarika", "Dial": "Hamagara", "Send": "Ohereza",
    "Feature-phone farmer experience": "Uko umuhinzi akoresha telefoni isanzwe",
    "Any phone, no internet, no app. Menus are Kinyarwanda first (option 8 switches to English). Short answers appear on screen; the full advice follows by SMS, and free-text questions are answered by SMS.":
      "Telefoni iyo ari yo yose, nta interineti, nta porogaramu. Menu ziri mu Kinyarwanda (8 ihindura mu Cyongereza). Igisubizo kigufi kigaragara kuri ecran; inama irambuye yoherezwa kuri SMS, kandi ibibazo byanditswe bisubizwa kuri SMS.",
    "Phone number": "Nimero ya telefoni", "New farmer": "Umuhinzi mushya", "SMS inbox": "Ubutumwa bwakiriwe (SMS)",
    "No messages yet.": "Nta butumwa buraza.", "— session ended —": "— ikiganiro kirangiye —",
    // dashboard
    "What farmers are asking, and where the gaps are": "Ibyo abahinzi babaza, n'aho ubumenyi bubura",
    "For MINAGRI, RAB and district agronomists. Updates every 10 seconds, last 30 days. Phone numbers are never shown: farmers are counted by salted hash.":
      "Bigenewe MINAGRI, RAB n'aba agronome b'uturere. Bivugururwa buri masegonda 10, iminsi 30 ishize. Nimero za telefoni ntizigaragazwa: abahinzi babarwa hakoreshejwe kode ihishe.",
    "Demo mode: the figures below are simulated traffic generated by driving the real USSD and advisory pipeline, not real farmer usage.":
      "Uburyo bw'igerageza: imibare iri hano ni iy'igerageza yakozwe hakoreshejwe USSD n'urwego nyarwo rw'inama, si iy'abahinzi nyabo.",
    "Daily interactions": "Ibikorwa bya buri munsi", "Top needs (crop · topic)": "Ibikenewe cyane (igihingwa · ingingo)",
    "By district": "Ku karere", "Field reports & automatic alerts": "Raporo zo mu murima n'imiburo yikora",
    "Knowledge gaps: questions the system escalated instead of guessing": "Ibyuho mu bumenyi: ibibazo sisitemu yohereje ku bantu aho gukeka",
    "Recent free-text questions": "Ibibazo byanditswe vuba",
    "Advisory interactions": "Ibikorwa by'inama", "Unique farmers": "Abahinzi batandukanye", "In Kinyarwanda": "Mu Kinyarwanda",
    "Escalated to humans": "Byoherejwe ku bantu", "Field reports & alerts": "Raporo n'imiburo", "Avg. response time": "Igihe cyo gusubiza (impuzandengo)",
    "No data yet.": "Nta makuru araboneka.", "None in this period.": "Nta na kimwe muri iki gihe.",
    "Dashboard token required (?token=…)": "Hakenewe ijambo ry'ibanga (?token=…)",
    "Time": "Igihe", "District": "Akarere", "Issue": "Ikibazo", "Detail": "Ibisobanuro", "Source": "Inkomoko", "Lang": "Ururimi",
    "Question": "Ikibazo", "Channel": "Umuyoboro", "Answer": "Igisubizo", "Engine": "Moteri",
    "Crop pest/disease": "Ibyonnyi/indwara z'ibihingwa", "Animal disease": "Indwara z'amatungo", "Drought": "Amapfa",
    "Heavy rain/flood": "Imvura nyinshi/imyuzure", "Inputs unavailable": "Inyongeramusaruro zabuze", "Other": "Ibindi",
    "simulated demo report": "raporo y'igerageza",
    // comparison
    "Ask anything a farmer might ask": "Baza icyo umuhinzi yabaza cyose", "Compare": "Gereranya",
    "Generic open model": "Moderi isanzwe ifunguye", "No knowledge base, no guardrails": "Nta bumenyi bwemewe, nta ngamba z'umutekano",
    "Curated corpus · sources cited · escalates instead of guessing": "Ubumenyi bwemewe · inkomoko zigaragazwa · yohereza ku bantu aho gukeka",
    "Thinking…": "Iratekereza…", "No sources": "Nta nkomoko", "Kinyarwanda": "Ikinyarwanda", "English": "Icyongereza",
    "Curated text": "Inyandiko yemewe", "Generated, grounded": "Yakozwe na AI, ishingiye ku bumenyi",
    "Escalated to an extension officer": "Byoherejwe ku mujyanama w'ubuhinzi", "Unavailable": "Ntibiboneka",
    "Live comparison needs DEMO_MODE and a local model (Ollama).": "Igereranya risaba uburyo bw'igerageza na moderi ikorera kuri mudasobwa (Ollama).",
    "Both columns use the same open-source model running locally on Ollama. On the left it answers alone; on the right it answers through Isôko's curated knowledge base and guardrails.":
      "Inkingi zombi zikoresha moderi imwe ifunguye ikorera kuri iyi mudasobwa (Ollama). Ibumoso isubiza yonyine; iburyo isubiza binyuze mu bumenyi bwemewe bwa Isôko n'ingamba zayo z'umutekano.",
    // evaluation
    "Evaluation v0.1: baseline before C4IR's refinement data": "Isuzuma v0.1: aho duhera mbere y'amakuru ya C4IR yo kunoza",
    "70 held-out farmer questions (49 English, 21 Kinyarwanda, 8 off-topic), each with required key facts. The same open models, run locally on Ollama, are tested alone and inside Isôko.":
      "Ibibazo 70 by'abahinzi bitakoreshejwe mu kubaka sisitemu (49 mu Cyongereza, 21 mu Kinyarwanda, 8 bitari iby'ubuhinzi), buri kimwe gifite ingingo z'ingenzi zigomba kuboneka. Moderi zimwe zifunguye, zikorera kuri Ollama, zigeragezwa zonyine no muri Isôko.",
    "Q&A quality by configuration": "Ireme ry'ibisubizo hakurikijwe uburyo", "Open model": "Moderi ifunguye",
    "Kinyarwanda ↔ English translation quality (chrF, 0–100)": "Ireme ry'ubusemuzi Ikinyarwanda ↔ Icyongereza (chrF, 0–100)",
    "60 agriculture-domain sentence pairs from the Digital Umuganda Kinyarwanda–English corpus (CC-BY-4.0), a stand-in for the EOI's 2,000-pair benchmark. Low English→Kinyarwanda scores are why Isôko serves reviewed Kinyarwanda text until a model passes C4IR's benchmark.":
      "Interuro 60 z'ubuhinzi zivuye mu nyandiko za Digital Umuganda (Ikinyarwanda–Icyongereza, CC-BY-4.0), zisimbura by'agateganyo interuro 2,000 za C4IR. Amanota make yo guhindura mu Kinyarwanda ni yo mpamvu Isôko itanga inyandiko z'Ikinyarwanda zasuzumwe kugeza moderi itsinze isuzuma rya C4IR.",
    "All results (table view)": "Ibisubizo byose (imbonerahamwe)", "Method and limits": "Uburyo n'aho bigarukira",
    "Generic open model (no knowledge base)": "Moderi isanzwe (nta bumenyi bwemewe)", "Isôko, curated text only": "Isôko, inyandiko yemewe gusa",
    "Isôko + open model": "Isôko + moderi ifunguye", "Fully correct": "Ibisubizo byuzuye neza",
    "Fully correct (Kinyarwanda)": "Ibisubizo byuzuye neza (Ikinyarwanda)", "Replies in Kinyarwanda when asked": "Isubiza mu Kinyarwanda iyo ibajijwe",
    "Off-topic handled safely": "Ibibazo bitari iby'ubuhinzi bikemurwa neza", "Unsupported figures (lower is better)": "Imibare idafite ishingiro (bike ni byiza)",
    "Fully correct answers": "Ibisubizo byuzuye neza", "Fully correct in Kinyarwanda": "Byuzuye neza mu Kinyarwanda",
    "Answers with unsupported figures": "Ibisubizo birimo imibare idafite ishingiro", "Off-topic questions handled safely": "Ibibazo bitari iby'ubuhinzi bikemuwe neza",
    "English → Kinyarwanda": "Icyongereza → Ikinyarwanda", "Kinyarwanda → English": "Ikinyarwanda → Icyongereza",
    "Configuration": "Uburyo", "Model": "Moderi", "No evaluation results yet. Run eval/run_eval.py.": "Nta bisubizo by'isuzuma biraboneka.",
    "Translation results pending.": "Ibisubizo by'ubusemuzi biracyategerejwe.",
  };
  var WORDS = { maize: "ibigori", beans: "ibishyimbo", potato: "ibirayi", rice: "umuceri", cassava: "imyumbati",
    banana: "urutoki", coffee: "ikawa", cattle: "inka", poultry: "inkoko", pig: "ingurube", goat: "ihene",
    general: "rusange", pests: "ibyonnyi", disease: "indwara", feeding: "kugaburira", planting: "gutera",
    fertiliser: "ifumbire", harvest: "gusarura", climate: "ikirere", weather: "iteganyagihe", inputs: "inyongeramusaruro",
    support: "ubufasha", other: "ibindi" };
  var RULES = [
    [/^([a-z]+) · ([a-z]+)$/, function (m, a, b) { return (WORDS[a] || a) + " · " + (WORDS[b] || b); }],
    [/^Forecast alert: (.*)$/, "Umuburo w'iteganyagihe: $1"],
    [/^Sources: (.*)$/, "Inkomoko: $1"],
    [/^(\d+) figures, unverified$/, "Imibare $1 itagenzuwe"],
    [/^generic (.+): (.+)$/, "moderi isanzwe $1: $2"],
    [/^Both columns use the same open-source model \((.+)\) running locally on Ollama\..*$/,
      "Inkingi zombi zikoresha moderi imwe ifunguye ($1) ikorera kuri iyi mudasobwa (Ollama). Ibumoso isubiza yonyine; iburyo isubiza binyuze mu bumenyi bwemewe bwa Isôko n'ingamba zayo z'umutekano."],
    [/^Generic (.+) alone$/, "$1 yonyine"],
    [/^Isôko \+ (.+)$/, "Isôko + $1"],
  ];

  var lang = "rw";
  try { lang = localStorage.getItem("isoko-lang") || "rw"; } catch (e) {}
  document.documentElement.lang = lang;

  function norm(s) { return s.replace(/\s+/g, " ").trim(); }
  function T(s) {
    if (lang !== "rw" || s == null) return s;
    var k = norm(String(s));
    if (RW[k]) return RW[k];
    for (var i = 0; i < RULES.length; i++) if (RULES[i][0].test(k)) return k.replace(RULES[i][0], RULES[i][1]);
    return s;
  }
  window.T = T;
  window.ISOKO_LANG = lang;

  var SKIP = { SCRIPT: 1, STYLE: 1, CODE: 1, TEXTAREA: 1 };
  function translateNode(root) {
    if (lang !== "rw" || !root) return;
    if (root.nodeType === 3) {
      var p = root.parentNode;
      if (!p || SKIP[p.nodeName] || (p.closest && p.closest("[data-no-i18n]"))) return;
      var raw = root.nodeValue, k = norm(raw);
      if (!k) return;
      var t = T(k);
      if (t !== k) root.nodeValue = raw.match(/^\s*/)[0] + t + raw.match(/\s*$/)[0];
      return;
    }
    if (root.nodeType !== 1 || SKIP[root.nodeName] || root.hasAttribute("data-no-i18n")) return;
    ["placeholder", "title", "aria-label", "data-tip"].forEach(function (a) {
      if (root.hasAttribute(a)) { var v = root.getAttribute(a), t = T(v); if (t !== v) root.setAttribute(a, t); }
    });
    for (var c = root.firstChild; c; c = c.nextSibling) translateNode(c);
  }

  function addToggle() {
    var nav = document.querySelector("header.top nav");
    if (!nav || document.getElementById("lang-toggle")) return;
    var b = document.createElement("button");
    b.id = "lang-toggle"; b.type = "button"; b.className = "lang-toggle"; b.setAttribute("data-no-i18n", "");
    b.textContent = lang === "rw" ? "English" : "Ikinyarwanda";
    b.onclick = function () {
      try { localStorage.setItem("isoko-lang", lang === "rw" ? "en" : "rw"); } catch (e) {}
      location.reload();
    };
    nav.appendChild(b);
  }

  document.addEventListener("DOMContentLoaded", function () {
    addToggle();
    if (lang !== "rw") return;
    document.title = document.title.replace(/·\s*(.+)$/, function (m, s) {
      var map = { "USSD Simulator": "Igerageza rya USSD", "Farmer Needs Dashboard": "Imbonerahamwe y'ibyo abahinzi bakeneye",
        "Live Comparison": "Igereranya", "Evaluation": "Isuzuma" };
      return "· " + (map[s] || s);
    });
    translateNode(document.body);
    new MutationObserver(function (muts) {
      muts.forEach(function (m) {
        if (m.type === "characterData") translateNode(m.target);
        m.addedNodes && m.addedNodes.forEach(translateNode);
      });
    }).observe(document.body, { childList: true, subtree: true, characterData: true });
  });
})();
