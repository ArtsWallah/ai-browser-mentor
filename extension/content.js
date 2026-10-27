(() => {
  "use strict";

  const API_BASE_URL = "https://ai-browser-mentor.onrender.com";
  const HOST_ID = "ai-browser-mentor-v3";
  const HOVER_ID = "ai-browser-mentor-hover-v3";

const S = {
  read:false,
  reading:false,
  asking:false,

  page:null,
  pageId:null,

  scan:null,

  scannerEnabled:true,
  hoverEnabled:true,

  hover:false,
  hoverTimer:null,
  hovered:null,
  highlight:null,

  url:location.href
};

  let host = null, root = null, el = {};

  const clean = v => String(v ?? "").replace(/\s+/g," ").trim();

  const visible = e => {
    if (!e || !(e instanceof Element)) return false;

    const r = e.getBoundingClientRect();
    const s = getComputedStyle(e);

    return (
      r.width > 0 &&
      r.height > 0 &&
      s.display !== "none" &&
      s.visibility !== "hidden"
    );
  };

  const label = e =>
    clean(
      e?.innerText ||
      e?.textContent ||
      e?.getAttribute("aria-label") ||
      e?.title ||
      e?.placeholder ||
      e?.value ||
      ""
    );

  const esc = v =>
    String(v ?? "").replace(
      /[&<>"']/g,
      c => ({
        "&":"&amp;",
        "<":"&lt;",
        ">":"&gt;",
        "\"":"&quot;",
        "'":"&#039;"
      }[c])
    );

    // ============================================================
// HTML ESCAPE
// ============================================================

function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

  // ============================================================
  // PAGE CHUNKING
  // ============================================================

  function chunks(rootNode) {

    const out = [];
    let cur = null;

    rootNode
      .querySelectorAll(
        "h1,h2,h3,h4,h5,h6,p,li,blockquote"
      )
      .forEach(n => {

        const t =
          clean(
            n.innerText ||
            n.textContent
          );

        if (!t) return;

        const tag =
          n.tagName.toLowerCase();

        if (/^h[1-6]$/.test(tag)) {

          cur = {
            heading:t,
            text:"",
            level:+tag[1],
            type:"section"
          };

          out.push(cur);

        } else {

          if (!cur) {

            cur = {
              heading:"Introduction",
              text:"",
              level:0,
              type:"paragraph"
            };

            out.push(cur);
          }

          if (cur.text) {
            cur.text += "\n\n";
          }

          cur.text += t;
        }
      });

    return out;
  }


  // ============================================================
  // INTERACTIVE ELEMENTS
  // ============================================================

 function interactive() {
  const q =
    "a,button,input,textarea,select," +
    "[role='button']," +
    "[role='link']," +
    "[role='textbox']," +
    "[role='searchbox']," +
    "[onclick]," +
    "[tabindex]";

  const out = [];

  document
    .querySelectorAll(q)
    .forEach((e, i) => {
      try {
        if (!visible(e)) return;

        const r = e.getBoundingClientRect();

        out.push({
          index: i,

          tag:
            e.tagName
              ? e.tagName.toLowerCase()
              : "",

          type:
            e.getAttribute("type") || "",

          role:
            e.getAttribute("role") || "",

          text:
            label(e),

          ariaLabel:
            clean(
              e.getAttribute("aria-label")
            ),

          placeholder:
            clean(
              e.getAttribute("placeholder")
            ),

          href:
            e.tagName?.toLowerCase() === "a"
              ? (
                  e.href ||
                  e.getAttribute("href") ||
                  ""
                )
              : "",

          x:
            Math.round(
              r.left + scrollX
            ),

          y:
            Math.round(
              r.top + scrollY
            ),

          width:
            Math.round(r.width),

          height:
            Math.round(r.height)
        });

      } catch (error) {
        console.warn(
          "INTERACTIVE EXTRACTION ERROR:",
          error
        );
      }
    });

  console.log(
    "INTERACTION MAP: FOUND",
    out.length,
    "usable elements"
  );

  return out;
}

  // ============================================================
  // IMAGE EXTRACTION
  // ============================================================

  function images() {

  const out = [];

  const imageElements =
    Array.from(
      document.querySelectorAll("img")
    );

  imageElements.forEach((e, i) => {

    try {

      if (!visible(e)) {
        return;
      }

      const r =
        e.getBoundingClientRect();

      out.push({
        index: i,

        src:
          e.currentSrc ||
          e.src ||
          e.getAttribute("data-src") ||
          "",

        alt:
          clean(
            e.alt ||
            e.getAttribute("aria-label") ||
            ""
          ),

        title:
          clean(e.title),

        x:
          Math.round(
            r.left + scrollX
          ),

        y:
          Math.round(
            r.top + scrollY
          ),

        width:
          Math.round(r.width),

        height:
          Math.round(r.height)
      });

    } catch (error) {

      console.warn(
        "IMAGE EXTRACTION ERROR:",
        error
      );

    }

  });

  console.log(
    "IMAGE MAP: FOUND",
    out.length,
    "images"
  );

  return out;
}

// ============================================================
// LINK SECURITY
// ============================================================

const suspicious = [
    "login",
    "signin",
    "verify",
    "verification",
    "password",
    "wallet",
    "payment",
    "billing",
    "recover",
    "unlock",
    "authenticate",
    "credential",
    "gift",
    "prize"
];

  const trusted = [
    "wikipedia.org",
    "wikimedia.org",
    "google.com",
    "github.com",
    "microsoft.com",
    "apple.com",
    "amazon.com",
    "openai.com",
    "mozilla.org",
    "stackoverflow.com",
    "python.org",
    "npmjs.com",
    "linkedin.com",
    "youtube.com"
  ];

  const trustedHost =
    h =>
      trusted.some(
        d =>
          h === d ||
          h.endsWith("." + d)
      );


  function linkRisk(
    url,
    txt = ""
  ) {

    const r = {
      risk:"Low",
      score:0,
      reasons:[],
      url:String(url || ""),
      text:clean(txt)
    };

    if (!url) {

      r.risk = "Unknown";
      r.score = 100;
      r.reasons.push(
        "Missing URL"
      );

      return r;
    }

    if (
      !/^https?:\/\//i.test(url)
    ) {

      r.reasons.push(
        "Non-web URL"
      );

      return r;
    }

    let u;

    try {

      u = new URL(url);

    } catch {

      r.risk = "High";
      r.score = 100;

      r.reasons.push(
        "Malformed URL"
      );

      return r;
    }

    const h =
      u.hostname.toLowerCase();

    const path =
      (
        u.pathname +
        " " +
        u.search
      ).toLowerCase();


    if (
      u.protocol !== "https:"
    ) {

      r.score += 25;

      r.reasons.push(
        "Uses HTTP instead of HTTPS"
      );
    }


    if (
      /^\d{1,3}(?:\.\d{1,3}){3}$/.test(h)
    ) {

      r.score += 25;

      r.reasons.push(
        "Uses a raw IP address"
      );
    }


    if (
      h.includes("xn--")
    ) {

      r.score += 30;

      r.reasons.push(
        "Uses a punycode domain"
      );
    }


    if (
      u.username ||
      u.password ||
      url.includes("@")
    ) {

      r.score += 25;

      r.reasons.push(
        "Contains an @ credential pattern"
      );
    }


    if (
      suspicious.some(
        w => path.includes(w)
      )
    ) {

      r.score += 18;

      r.reasons.push(
        "Contains security-sensitive URL terms"
      );
    }


    if (
      h.split(".").length > 4
    ) {

      r.score += 15;

      r.reasons.push(
        "Unusually deep subdomain"
      );
    }


    if (
      trustedHost(h)
    ) {

      r.score =
        Math.max(
          0,
          r.score - 25
        );
    }


    r.risk =
      r.score >= 60
        ? "High"
        : r.score >= 25
          ? "Medium"
          : "Low";

    return r;
  }


function scan() {

  const links =
    Array.from(
      document.querySelectorAll("a[href]")
    );

  const suspiciousWords = [
    "login",
    "signin",
    "sign-in",
    "verify",
    "verification",
    "password",
    "credential",
    "wallet",
    "payment",
    "billing",
    "recover",
    "unlock",
    "authenticate",
    "gift",
    "prize",
    "claim",
    "bonus",
    "confirm",
    "security-alert",
    "account-verify"
  ];


  const results = [];


  for (
    let i = 0;
    i < links.length;
    i++
  ) {

    const link =
      links[i];

    const href =
      link.href || "";

    const text =
      clean(
        link.textContent || ""
      );


    if (!href)
      continue;


    let url;

    try {

      url =
        new URL(
          href,
          location.href
        );

    } catch {

      continue;
    }


    let riskScore = 0;

    const reasons = [];


    // ========================================================
    // 1. HTTP
    // ========================================================

    if (
      url.protocol === "http:"
    ) {

      riskScore += 25;

      reasons.push(
        "Uses HTTP instead of HTTPS"
      );
    }


    // ========================================================
    // 2. IP ADDRESS
    // ========================================================

    const hostname =
      url.hostname;


    if (
      /^\d{1,3}(\.\d{1,3}){3}$/
        .test(hostname)
    ) {

      riskScore += 35;

      reasons.push(
        "Uses a raw IP address"
      );
    }


    // ========================================================
    // 3. PUNYCODE
    // ========================================================

    if (
      hostname
        .toLowerCase()
        .includes("xn--")
    ) {

      riskScore += 40;

      reasons.push(
        "Uses a punycode domain"
      );
    }


    // ========================================================
    // 4. USERNAME/PASSWORD IN URL
    // ========================================================

    if (
      href.includes("@")
    ) {

      riskScore += 35;

      reasons.push(
        "URL contains @"
      );
    }


    // ========================================================
    // 5. SUSPICIOUS WORDS
    // ========================================================

    const combined =
      (
        href +
        " " +
        text
      ).toLowerCase();


    const matchedWords =
      suspiciousWords.filter(
        word =>
          combined.includes(word)
      );


    if (
      matchedWords.length > 0
    ) {

      riskScore +=
        Math.min(
          matchedWords.length * 8,
          24
        );

      reasons.push(
        "Contains security-sensitive wording: " +
        matchedWords
          .slice(0, 3)
          .join(", ")
      );
    }


    // ========================================================
    // 6. EXCESSIVE SUBDOMAINS
    // ========================================================

    const parts =
      hostname
        .split(".")
        .filter(Boolean);


    if (
      parts.length >= 5
    ) {

      riskScore += 15;

      reasons.push(
        "Has an unusually deep subdomain structure"
      );
    }


    // ========================================================
    // 7. SUSPICIOUS URL LENGTH
    // ========================================================

    if (
      href.length > 250
    ) {

      riskScore += 10;

      reasons.push(
        "Unusually long URL"
      );
    }


    // ========================================================
    // 8. JAVASCRIPT URL
    // ========================================================

    if (
      url.protocol === "javascript:"
    ) {

      riskScore += 80;

      reasons.push(
        "Uses a javascript: URL"
      );
    }


    // ========================================================
    // FINAL CLASSIFICATION
    // ========================================================

    let level;

    if (
      riskScore >= 60
    ) {

      level =
        "high";

    } else if (
      riskScore >= 30
    ) {

      level =
        "suspicious";

    } else {

      level =
        "low";
    }


    results.push({

      index:
        i,

      href,

      text,

      hostname,

      score:
        riskScore,

      level,

      reasons
    });
  }


  const high =
    results.filter(
      x => x.level === "high"
    );

  const suspicious =
    results.filter(
      x => x.level === "suspicious"
    );

  const low =
    results.filter(
      x => x.level === "low"
    );


  console.log(
    "PAGE SCANNER:",
    results.length,
    "links scanned"
  );


  console.log(
    "HIGH RISK:",
    high.length
  );


  console.log(
    "SUSPICIOUS:",
    suspicious.length
  );


  console.log(
    "LOW RISK:",
    low.length
  );


  return {

    total:
      results.length,

    high:
      high.length,

    suspicious:
      suspicious.length,

    low:
      low.length,

    results
  };
}

  // ============================================================
  // COMPLETE PAGE EXTRACTION
  // ============================================================

  function extract() {

    if (!document.body) {

      throw new Error(
        "Page body is not available."
      );
    }


    const clone =
      document.body.cloneNode(true);
      
      
// ============================================================
// DYNAMIC PAGE SUPPORT
// ============================================================

const liveText = clean(
    document.body.innerText ||
    document.body.textContent ||
    ""
);


    clone
      .querySelectorAll(
        "script,style,noscript,iframe,svg,canvas,video,audio"
      )
      .forEach(
        e => e.remove()
      );


    const body =
    liveText ||
    clean(
        clone.innerText ||
        clone.textContent ||
        ""
    );


    const c =
      chunks(clone);

    const i =
      interactive();

    const im =
      images();


    const links =
      Array.from(
        document.querySelectorAll(
          "a[href]"
        )
      ).map(
        (a,index) => ({
          index,
          text:label(a),
          href:
            a.href ||
            a.getAttribute("href") ||
            "",
          title:
            clean(a.title)
        })
      );


    return {

      title:
        clean(document.title) ||
        "Current webpage",

      url:
        location.href,

      description:
        clean(
          document
            .querySelector(
              'meta[name="description"]'
            )
            ?.content ||
          ""
        ),

      text:body,

      chunks:c,

      interactiveElements:i,

      images:im,

      links,

      stats:{
        chunks:c.length,
        images:im.length,
        links:links.length,
        interactiveElements:i.length,
        characters:body.length
      }
    };
  }


  // ============================================================
  // FIND / NAVIGATION
  // ============================================================

  function clearHighlight() {

    const e =
      S.highlight;

    if (!e) return;

    e.style.outline =
      e.dataset.aimOldOutline ||
      "";

    e.style.outlineOffset =
      e.dataset.aimOldOffset ||
      "";

    delete e.dataset.aimOldOutline;
    delete e.dataset.aimOldOffset;

    S.highlight = null;
  }


  function highlight(
    e,
    msg = "Found here"
  ) {

    clearHighlight();

    if (!e) return false;


    e.dataset.aimOldOutline =
      e.style.outline || "";

    e.dataset.aimOldOffset =
      e.style.outlineOffset || "";


    e.style.outline =
      "3px solid #6d5dfc";

    e.style.outlineOffset =
      "4px";


    S.highlight = e;


    try {

      e.scrollIntoView({
        behavior:"smooth",
        block:"center",
        inline:"nearest"
      });

    } catch {}


    const old =
      document.getElementById(
        "ai-browser-mentor-find-label"
      );

    old?.remove();


    const b =
      document.createElement("div");

    b.id =
      "ai-browser-mentor-find-label";

    b.textContent =
      msg;


    Object.assign(
      b.style,
      {
        position:"absolute",
        zIndex:2147483646,
        padding:"7px 10px",
        borderRadius:"8px",
        background:"#171827",
        color:"#fff",
        font:"700 12px system-ui",
        boxShadow:
          "0 10px 30px rgba(0,0,0,.25)",
        pointerEvents:"none"
      }
    );


    document.body.appendChild(b);


    const r =
      e.getBoundingClientRect();


    b.style.left =
      `${Math.max(
        8,
        r.left + scrollX
      )}px`;


    b.style.top =
      `${Math.max(
        8,
        r.top + scrollY - 38
      )}px`;


    setTimeout(
      () => b.remove(),
      2500
    );


    return true;
  }


  function matchScore(
    q,
    v
  ) {

    q =
      clean(q).toLowerCase();

    v =
      clean(v).toLowerCase();


    if (!q || !v)
      return 0;


    if (q === v)
      return 100;


    if (v.includes(q))
      return 90;


    const words =
      q
        .split(/\s+/)
        .filter(Boolean);


    return (
      words.filter(
        x => v.includes(x)
      ).length /
      words.length
    ) * 70;
  }


  function findElement(q) {

    let best = null;
    let score = 0;

    document
        .querySelectorAll(
            "a,button,input,textarea,select,label," +
            "h1,h2,h3,h4,h5,h6,li,p," +
            "[role='button']," +
            "[role='link']," +
            "[role='textbox']," +
            "[role='searchbox']"
        )
        .forEach(e => {

            if (!visible(e))
                return;

            const text = label(e);

            if (!text)
                return;

            const s =
                matchScore(
                    q,
                    text
                );

            if (s > score) {

                score = s;
                best = e;
            }
        });

    return best
        ? {
            element: best,
            score
        }
        : null; 
}

// ============================================================
  // SECTION FINDER
  // ============================================================

  function findSection(q) {

    let best = null;
    let score = 0;

    document
      .querySelectorAll(
        "h1,h2,h3,h4,h5,h6"
      )
      .forEach(
        heading => {

          if (!visible(heading))
            return;

          const headingText =
            label(heading);

          if (!headingText)
            return;

          const s =
            matchScore(
              q,
              headingText
            );

          if (s > score) {

            score = s;
            best = heading;
          }
        }
      );

    return best
      ? {
          element: best,
          score
        }
      : null;
  }

  // ============================================================
// TABLE OF CONTENTS FINDER
// ============================================================

function findTableOfContents() {

    const selectors = [
        "#toc",
        ".toc",
        "[role='navigation'][aria-label*='Contents' i]",
        "[aria-label*='table of contents' i]",
        "[aria-label*='contents' i]"
    ];

    for (const selector of selectors) {

        const element =
            document.querySelector(
                selector
            );

        if (
            element &&
            visible(element)
        ) {
            return element;
        }
    }

    // Wikipedia often exposes a TOC toggle/button.
    const candidates =
        document.querySelectorAll(
            "button, a, [role='button']"
        );

    for (const element of candidates) {

        if (!visible(element))
            continue;

        const text =
            clean(
                label(element)
            ).toLowerCase();

        if (
            text.includes(
                "toggle the table of contents"
            ) ||
            text === "table of contents" ||
            text.includes(
                "table of contents"
            )
        ) {
            return element;
        }
    }

    return null;
}


// ============================================================
// IMAGE FINDER
// ============================================================

function findImage(q) {

    const query =
        clean(q)
            .toLowerCase()
            .replace(
                /\b(please|show me|show|find|locate|where is|where can i find|display|image|images|picture|pictures|photo|photos|diagram|figure|illustration|what does|what do|how does|how do|looks like|look like|look|like|of|the|a|an)\b/gi,
                " "
            )
            .replace(/\s+/g, " ")
            .trim();

    if (!query) {
        return null;
    }

    let best = null;
    let bestScore = 0;

    document
        .querySelectorAll("img")
        .forEach(img => {

            if (!visible(img))
                return;

            const figure =
                img.closest("figure");

            const caption =
                figure?.querySelector("figcaption");

            const alt =
                clean(img.alt);

            const title =
                clean(img.title);

            const captionText =
                clean(
                    caption?.innerText ||
                    caption?.textContent ||
                    ""
                );

            const surrounding =
                clean(
                    figure?.innerText ||
                    ""
                );

            const values = [
                alt,
                title,
                captionText,
                surrounding
            ].filter(Boolean);

            if (!values.length)
                return;

            let score = 0;

            values.forEach(value => {

                const s =
                    matchScore(
                        query,
                        value
                    );

                if (s > score)
                    score = s;
            });

            if (score > bestScore) {

                bestScore = score;

                best = {
                    element: img,
                    score,
                    caption:
                        captionText ||
                        alt ||
                        title ||
                        "matching image"
                };
            }
        });

    console.log(
        "IMAGE FINDER:",
        {
            query,
            score: bestScore,
            caption: best?.caption || null
        }
    );

    return best;
}
function navigation(q) {

    const low =
        clean(q).toLowerCase();

    // ========================================================
    // SEARCH BOX
    // ========================================================

    if (
        low.includes("search box") ||
        low.includes("search bar") ||
        low.includes("search field") ||
        low.includes("search input")
    ) {

        const e =
            searchBox();

        if (!e) {

            return {
                handled: true,
                ok: false,
                msg:
                    "I couldn't find a search box on this page."
            };
        }

        highlight(
            e,
            "Search box"
        );

        e.focus();

        return {
            handled: true,
            ok: true,
            msg:
                "I found the search box and focused it."
        };
    }

        // ========================================================
    // IMAGE REQUEST
    // ========================================================

    const imageRequest =
        /\b(image|images|picture|pictures|photo|photos|diagram|figure|illustration|looks like|look like|show me how|show me what|what does .* look like)\b/i
            .test(low);

    if (imageRequest) {

        const image =
            findImage(q);

        if (
            image &&
            image.score >= 40
        ) {

            highlight(
                image.element,
                `Found image: ${image.caption.slice(0, 100)}`
            );

            return {
                handled: true,
                ok: true,
                msg:
                    `I found the relevant image: â€œ${image.caption.slice(0, 120)}â€.`
            };
        }

        return {
            handled: true,
            ok: false,
            msg:
                `I couldn't confidently locate an image matching â€œ${q}â€ on this page.`
        };
    }
    // ========================================================
    // FIND / LOCATE REQUEST
    // ========================================================

    const nav =
        /\b(find|locate|show me|take me to|go to|navigate to|where is|where can i find)\b/i
            .test(low);

    if (!nav) {

        return {
            handled: false
        };
    }

    let q2 =
        clean(q)

            .replace(
                /^(please\s+)?(find|locate|show me|take me to|go to|navigate to)\s+/i,
                ""
            )

            .replace(
                /^where (can i find|is)\s+/i,
                ""
            )

            .replace(
                /^the\s+/i,
                ""
            );

    // ========================================================
    // SECTION REQUEST
    // ========================================================

    const sectionRequest =
        /\b(section|heading|chapter|topic)\b/i
            .test(low);

    if (sectionRequest) {

        q2 =
            q2.replace(
                /\b(section|heading|chapter|topic)\b/gi,
                ""
            ).trim();

        const section =
            findSection(q2);

        if (
            section &&
            section.score >= 35
        ) {

            highlight(
                section.element,
                `Found section: ${label(
                    section.element
                ).slice(0, 100)}`
            );

            return {
                handled: true,
                ok: true,
                msg:
                    `I found the section â€œ${label(
                        section.element
                    ).slice(0, 120)}â€ and highlighted it.`
            };
        }
    }

    // ========================================================
    // GENERAL ELEMENT REQUEST
    // ========================================================
// ========================================================
// TABLE OF CONTENTS
// ========================================================

if (
    low.includes("table of contents") ||
    low.includes("contents") ||
    low.includes("toc")
) {

    const toc =
        findTableOfContents();

    if (!toc) {

        return {
            handled: true,
            ok: false,
            msg:
                "I couldn't find the table of contents on this page."
        };
    }

    highlight(
        toc,
        "Table of contents"
    );

    toc.scrollIntoView({
        behavior: "smooth",
        block: "center"
    });

    return {
        handled: true,
        ok: true,
        msg:
            "I found the table of contents and highlighted it."
    };
}
    const f =
        findElement(q2);

    if (
        f &&
        f.score >= 45
    ) {

        highlight(
            f.element,
            `Found: ${label(
                f.element
            ).slice(0, 80)}`
        );

        return {
            handled: true,
            ok: true,
            msg:
                `I found the closest matching element: â€œ${label(
                    f.element
                ).slice(0, 120)}â€.`
        };
    }

    // ========================================================
    // DON'T CLAIM WE FOUND SOMETHING
    // ========================================================

    return {
        handled: true,
        ok: false,
        msg:
            `I couldn't confidently locate â€œ${q2}â€ on this page.`
    };
}
  // ============================================================
  // HOVER SECURITY
  // ============================================================

  function removeHover() {

    document
      .getElementById(
        HOVER_ID
      )
      ?.remove();
  }


  function hoverBox(
    link,
    r
  ) {

    removeHover();


    const b =
      document.createElement("div");

    b.id =
      HOVER_ID;


    const title =
      r.risk === "High"
        ? "High-risk signals"
        : r.risk === "Medium"
          ? "Suspicious signals"
          : "No obvious risk signals";


    b.innerHTML = `
      <div style="
        font:800 12px system-ui;
        margin-bottom:5px
      ">
        ${esc(title)}
      </div>

      <div style="
        font:500 10px system-ui;
        opacity:.8;
        margin-bottom:5px;
        word-break:break-word
      ">
        ${esc(r.url)}
      </div>

      <div style="
        font:500 10px system-ui;
        line-height:1.45
      ">
        ${esc(
          r.reasons
            .slice(0,3)
            .join(" â€¢ ") ||
          "No heuristic warning"
        )}
      </div>

      <div style="
        font:700 10px system-ui;
        margin-top:5px
      ">
        Heuristic score: ${r.score}/100
      </div>
    `;


    Object.assign(
      b.style,
      {
        position:"fixed",
        zIndex:2147483647,
        maxWidth:"320px",
        padding:"11px 12px",
        borderRadius:"12px",
        background:
          r.risk === "High"
            ? "#35151b"
            : r.risk === "Medium"
              ? "#3a2a0d"
              : "#17202d",
        color:"#fff",
        boxShadow:
          "0 14px 40px rgba(0,0,0,.28)",
        pointerEvents:"none"
      }
    );


    document.body.appendChild(b);


    const a =
      link.getBoundingClientRect();

    const br =
      b.getBoundingClientRect();


    let x =
      a.left;

    let y =
      a.bottom + 8;


    if (
      x + br.width >
      innerWidth - 10
    ) {

      x =
        innerWidth -
        br.width -
        10;
    }


    if (
      y + br.height >
      innerHeight - 10
    ) {

      y =
        a.top -
        br.height -
        8;
    }


    b.style.left =
      `${Math.max(10,x)}px`;

    b.style.top =
      `${Math.max(10,y)}px`;
  }
function enableHover() {

  if (!S.hoverEnabled)
    return;

  if (S.hover)
    return;

  S.hover = true;

    document.addEventListener(
      "mouseover",
      over,
      true
    );

    document.addEventListener(
      "mouseout",
      out,
      true
    );
  }


  function disableHover() {

    S.hover = false;

    document.removeEventListener(
      "mouseover",
      over,
      true
    );

    document.removeEventListener(
      "mouseout",
      out,
      true
    );

    clearTimeout(
      S.hoverTimer
    );

    S.hovered = null;

    removeHover();
  }


  function over(event) {

    if (
  !S.read ||
  !S.hover ||
  !S.hoverEnabled
) {
  return;
}


    const target =
      event.target;


    if (
      !(target instanceof Element)
    ) {
      return;
    }


    const a =
      target.closest(
        "a[href]"
      );


    if (
      !a ||
      !a.href ||
      a === S.hovered
    ) {
      return;
    }


    S.hovered = a;


    clearTimeout(
      S.hoverTimer
    );


    S.hoverTimer =
      setTimeout(
        () => {

          if (
            S.hovered === a
          ) {

            hoverBox(
              a,
              linkRisk(
                a.href,
                label(a)
              )
            );
          }

        },
        220
      );
  }


  function out(event) {

    const target =
      event.target;


    if (
      !(target instanceof Element)
    ) {
      return;
    }


    const a =
      target.closest(
        "a[href]"
      );


    if (!a)
      return;


    const related =
      event.relatedTarget;


    if (
      related instanceof Node &&
      a.contains(related)
    ) {
      return;
    }


    clearTimeout(
      S.hoverTimer
    );


    S.hovered = null;

    removeHover();
  }


  // ============================================================
  // BACKEND
  // ============================================================

 async function post(
  path,
  payload
) {

 const url =
    API_BASE_URL + path;

  console.log(
    "AI MENTOR: POST",
    url,
    payload
  );


  let response;

  try {

    response =
      await fetch(
        url,
        {
          method:
            "POST",

          headers: {
            "Content-Type":
              "application/json"
          },

          body:
            JSON.stringify(
              payload
            )
        }
      );

  } catch (error) {

    console.error(
      "AI MENTOR: FETCH FAILED",
      {
        url,
        error
      }
    );

    throw new Error(
      `Could not connect to backend at ${url}. ` +
      `Make sure FastAPI is running.`
    );

  }


  let data =
    null;


  try {

    data =
      await response.json();

  } catch (error) {

    console.error(
      "AI MENTOR: INVALID JSON RESPONSE",
      error
    );

  }


  console.log(
    "AI MENTOR: RESPONSE",
    {
      status:
        response.status,

      ok:
        response.ok,

      data
    }
  );


  if (
    !response.ok
  ) {

    throw new Error(
      data?.message ||
      data?.detail ||
      data?.error ||
      `Backend returned HTTP ${response.status}`
    );

  }


  return data;

}

  const ingest =
    page =>
      post(
        "/page/ingest",
        page
      );


  async function ask(question) {

  if (!S.pageId) {

    throw new Error(
      "No page ID is available. Read the page first."
    );

  }

  if (!question || !question.trim()) {

    throw new Error(
      "Please enter a question."
    );

  }

  console.log(
    "AI MENTOR: ASKING",
    {
      pageId: S.pageId,
      question: question
    }
  );

  const result =
    await post(
      "/ask",
      {
        page_id:
          S.pageId,

        question:
          question.trim(),

        top_k:
          5
      }
    );

  console.log(
    "AI MENTOR: ASK RESPONSE",
    result
  );

  if (
    !result ||
    result.success === false
  ) {

    throw new Error(
      result?.message ||
      "The backend could not answer the question."
    );

  }

  if (
    !result.answer ||
    !result.answer.trim()
  ) {

    throw new Error(
      "The backend returned an empty answer."
    );

  }

  return result;

}


  // ============================================================
  // REMOVE OLD UI
  // ============================================================

  function removeUI() {

    document
      .getElementById(
        HOST_ID
      )
      ?.remove();


    document
      .querySelectorAll(
        "#ai-browser-mentor-floating-panel"
      )
      .forEach(
        e => e.remove()
      );
  }


  // ============================================================
  // CREATE UI
  // ============================================================

  function createUI() {

    removeUI();


    host =
      document.createElement(
        "div"
      );


    host.id =
      HOST_ID;


    Object.assign(
      host.style,
      {
        position:"fixed",
        top:"16px",
        right:"16px",
        zIndex:2147483645
      }
    );


    document.documentElement
      .appendChild(host);


    root =
      host.attachShadow({
        mode:"open"
      });


    const css =
      document.createElement(
        "style"
      );

css.textContent = `

/* ============================================================
   AI BROWSER MENTOR â€” PREMIUM UI
   ============================================================ */

* {
  box-sizing: border-box;
}


/* ============================================================
   PANEL
   ============================================================ */

.panel {
  width: 390px;
  max-width: calc(100vw - 28px);
  max-height: calc(100vh - 28px);

  overflow-y: auto;
  overflow-x: hidden;

  padding: 0;

  border: 1px solid rgba(255,255,255,.10);
  border-radius: 22px;

  background:
    linear-gradient(
      180deg,
      #11131c 0%,
      #171925 100%
    );

  box-shadow:
    0 30px 80px rgba(0,0,0,.35),
    0 8px 30px rgba(0,0,0,.18);

  color: #f7f7fb;

  font-family:
    Inter,
    ui-sans-serif,
    system-ui,
    -apple-system,
    BlinkMacSystemFont,
    "Segoe UI",
    sans-serif;

  scrollbar-width: thin;
  scrollbar-color: #3a3d4b transparent;
}


/* ============================================================
   SCROLLBAR
   ============================================================ */

.panel::-webkit-scrollbar {
  width: 6px;
}

.panel::-webkit-scrollbar-track {
  background: transparent;
}

.panel::-webkit-scrollbar-thumb {
  background: #383b49;
  border-radius: 999px;
}


/* ============================================================
   HEADER
   ============================================================ */

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;

  gap: 12px;

  padding: 20px 20px 16px;

  background:
    linear-gradient(
      180deg,
      #171a27,
      #13151f
    );
}


/* Brand wrapper */

.head > div:first-child {
  min-width: 0;
}


/* Brand */

.brand {
  display: flex;
  align-items: center;

  font-size: 17px;
  font-weight: 750;

  letter-spacing: -.035em;

  color: #ffffff;
}

.brand::before {
  content: "âœ¦";

  display: inline-flex;
  align-items: center;
  justify-content: center;

  width: 28px;
  height: 28px;

  margin-right: 9px;

  border-radius: 9px;

  background:
    linear-gradient(
      135deg,
      #7867ff,
      #5d4df4
    );

  color: #ffffff;

  font-size: 14px;

  box-shadow:
    0 6px 18px rgba(109,93,252,.28);
}


/* Subtitle */

.sub {
  margin-top: 5px;
  margin-left: 37px;

  font-size: 10px;

  color: #8e92a5;

  letter-spacing: .01em;
}


/* ============================================================
   STATUS
   ============================================================ */

.status {
  display: inline-flex;
  align-items: center;

  flex-shrink: 0;

  padding: 6px 9px;

  border: 1px solid rgba(255,255,255,.08);

  border-radius: 999px;

  background: #1e2230;

  color: #aeb3c7;

  font-size: 9px;
  font-weight: 750;
}

.status:before {
  content: "";

  width: 6px;
  height: 6px;

  margin-right: 6px;

  border-radius: 50%;

  background: #42d392;

  box-shadow:
    0 0 0 3px rgba(66,211,146,.10);
}


/* ============================================================
   CURRENT PAGE CARD
   ============================================================ */

.card {
  margin: 0 14px;

  padding: 15px;

  border:
    1px solid rgba(255,255,255,.08);

  border-radius: 16px;

  background:
    linear-gradient(
      145deg,
      #1d2130,
      #191c28
    );

  box-shadow:
    inset 0 1px 0 rgba(255,255,255,.025);
}


/* Page title */

.title {
  font-size: 14px;

  font-weight: 700;

  line-height: 1.35;

  letter-spacing: -.015em;

  color: #f5f6fa;
}


/* Page description */

.meta {
  margin-top: 5px;

  font-size: 10px;

  line-height: 1.5;

  color: #9297aa;
}


/* ============================================================
   BUTTONS
   ============================================================ */

.primary,
.ask {
  width: 100%;

  border: 0;

  border-radius: 11px;

  padding: 11px 13px;

  margin-top: 12px;

  color: #ffffff;

  font-size: 11px;

  font-weight: 750;

  cursor: pointer;

  transition:
    transform .15s ease,
    box-shadow .15s ease,
    opacity .15s ease;
}


.primary {
  background:
    #272b39;

  border:
    1px solid rgba(255,255,255,.08);
}

.primary:hover {
  background: #303443;
}


.ask {
  background:
    linear-gradient(
      135deg,
      #7565ff,
      #5d4df0
    );

  box-shadow:
    0 8px 22px rgba(109,93,252,.20);
}

.primary:hover,
.ask:hover {
  transform: translateY(-1px);
}

.ask:hover {
  box-shadow:
    0 10px 26px rgba(109,93,252,.28);
}

.primary:active,
.ask:active {
  transform: translateY(0);
}


.primary:disabled,
.ask:disabled {
  opacity: .45;

  cursor: wait;

  transform: none;
}


/* ============================================================
   WORKSPACE
   ============================================================ */

.workspace {
  padding: 2px 14px 16px;

  margin-top: 8px;
}


/* Section labels */

.label {
  margin: 16px 2px 7px;

  color: #73788c;

  font-size: 9px;

  font-weight: 800;

  letter-spacing: .12em;
}


/* ============================================================
   QUESTION INPUT
   ============================================================ */

textarea {
  width: 100%;

  min-height: 84px;

  resize: vertical;

  padding: 12px 13px;

  outline: none;

  border:
    1px solid #303443;

  border-radius: 12px;

  background:
    #11141d;

  color:
    #f5f6fa;

  font:
    500 11px/1.55
    Inter,
    system-ui,
    sans-serif;

  transition:
    border-color .15s ease,
    box-shadow .15s ease;
}

textarea::placeholder {
  color: #62687a;
}

textarea:focus {
  border-color: #6d5dfc;

  box-shadow:
    0 0 0 3px
    rgba(109,93,252,.12);
}


/* ============================================================
   AI ANSWER
   ============================================================ */

.answer {
  margin-top: 10px;

  padding: 13px;

  border:
    1px solid #2c3040;

  border-radius: 13px;

  background:
    linear-gradient(
      145deg,
      #1b1e2a,
      #171a25
    );

  color: #dfe2ec;

  font-size: 11px;

  line-height: 1.65;

  white-space: pre-wrap;

  box-shadow:
    inset 0 1px 0 rgba(255,255,255,.025);
}


.error {
  background:
    rgba(239,68,68,.07);

  border-color:
    rgba(239,68,68,.22);

  color:
    #ff9a9a;
}


/* ============================================================
   PAGE SECURITY
   ============================================================ */

.scan {
  margin-top: 12px;

  padding: 13px;

  border:
    1px solid #2b3040;

  border-radius: 15px;

  background:
    #151822;
}


/* Scan header */

.scanhead {
  display: flex;

  align-items: center;

  justify-content: space-between;

  gap: 8px;
}

.scantitle {
  font-size: 11px;

  font-weight: 750;

  color: #f0f1f6;
}

.scanstate {
  font-size: 9px;

  font-weight: 750;

  color: #8f84ff;
}


/* Scan description */

.scansummary {
  margin-top: 5px;

  font-size: 9px;

  line-height: 1.45;

  color: #777d90;
}


/* ============================================================
   SECURITY STATS
   ============================================================ */

.stats {
  display: grid;

  grid-template-columns:
    repeat(3, 1fr);

  gap: 6px;

  margin-top: 10px;
}

.stat {
  min-width: 0;

  padding: 10px;

  border:
    1px solid #292e3c;

  border-radius: 11px;

  background:
    #10131b;
}

.num {
  font-size: 16px;

  font-weight: 800;

  line-height: 1;
  
  color: #f5f6fa;
}

.small {
  margin-top: 5px;

  font-size: 8px;

  color: #73798c;

  text-transform: uppercase;

  letter-spacing: .04em;
}


/* ============================================================
   SUSPICIOUS LINKS
   ============================================================ */

.suspicious-list {
  margin-top: 9px;

  padding: 9px;

  border:
    1px solid #292e3c;

  border-radius: 12px;

  background: #10131b;
}

.suspicious-title {
  margin-bottom: 7px;

  color: #aeb3c3;

  font-size: 9px;

  font-weight: 750;

  text-transform: uppercase;

  letter-spacing: .08em;
}

.suspicious-item {
  width: 100%;

  display: block;

  padding: 9px;

  margin-top: 6px;

  text-align: left;

  border:
    1px solid #2b3040;

  border-radius: 9px;

  background:
    #181b25;

  color: #e7e9f0;

  cursor: pointer;

  transition:
    background .15s ease,
    border-color .15s ease;
}

.suspicious-item:hover {
  background: #202432;

  border-color: #444a5d;
}

.suspicious-item.high {
  border-left:
    3px solid #ef5b67;
}

.suspicious-item.suspicious {
  border-left:
    3px solid #e7ad43;
}

.suspicious-item-title {
  font-size: 9px;

  font-weight: 700;

  color: #e8eaf1;

  white-space: nowrap;

  overflow: hidden;

  text-overflow: ellipsis;
}

.suspicious-item-url {
  margin-top: 3px;

  color: #73798c;

  font-size: 8px;

  word-break: break-all;
}

.suspicious-item-reason {
  margin-top: 4px;

  color: #9ca2b3;

  font-size: 8px;

  line-height: 1.4;
}


/* ============================================================
   ACTIVE TOOLS
   ============================================================ */

.tools {
  margin-top: 14px;
}

.tool-card {
  display: flex;

  align-items: center;

  justify-content: space-between;

  gap: 10px;

  padding: 11px 12px;

  margin-top: 6px;

  border:
    1px solid #292e3c;

  border-radius: 12px;

  background:
    #151822;

  transition:
    background .15s ease,
    border-color .15s ease;
}

.tool-card:hover {
  background: #191d28;

  border-color: #353b4c;
}

.tool-info {
  min-width: 0;
}

.tool-name {
  font-size: 10px;

  font-weight: 700;

  color: #e7e9f0;
}

.tool-desc {
  margin-top: 3px;

  font-size: 8px;

  color: #747a8d;

  line-height: 1.35;
}


/* ============================================================
   MODERN TOGGLE
   ============================================================ */

.tool-toggle {
  position: relative;

  flex-shrink: 0;

  width: 42px;
  height: 23px;

  padding: 0;

  border: 0;

  border-radius: 999px;

  background:
    #303443;

  color: transparent;

  font-size: 0;

  cursor: pointer;

  transition:
    background .2s ease;
}

.tool-toggle::after {
  content: "";

  position: absolute;

  top: 3px;
  left: 3px;

  width: 17px;
  height: 17px;

  border-radius: 50%;

  background: #ffffff;

  box-shadow:
    0 2px 5px rgba(0,0,0,.25);

  transition:
    transform .2s ease;
}

.tool-toggle.active {
  background:
    #6d5dfc;
}

.tool-toggle.active::after {
  transform:
    translateX(19px);
}


/* ============================================================
   HINT
   ============================================================ */

.hint {
  margin-top: 12px;

  padding: 0 2px;

  color: #666c7e;

  font-size: 8px;

  line-height: 1.5;
}


/* ============================================================
   MOBILE / NARROW PANEL
   ============================================================ */

@media (max-width: 500px) {

  .panel {
    width: 360px;
    max-width: calc(100vw - 20px);
  }

  .head {
    padding: 17px 16px 14px;
  }

  .workspace {
    padding-left: 12px;
    padding-right: 12px;
  }

  .card {
    margin-left: 12px;
    margin-right: 12px;
  }
}

`;


    root.appendChild(css);


    const p =
      document.createElement(
        "div"
      );


    p.className =
      "panel";


    p.innerHTML = `

      <div class="head">

        <div>

          <div class="brand">
            AI Browser Mentor
          </div>

          <div class="sub">
            Understand and navigate the web
          </div>

        </div>

        <div
          class="status"
          id="status"
        >
          Ready
        </div>

      </div>


      <div class="card">

        <div
          class="title"
          id="title"
        >
          ${esc(
            clean(document.title) ||
            "Current webpage"
          )}
        </div>


        <div
          class="meta"
          id="meta"
        >
          Read the page to activate grounded
          questions, navigation help and link safety.
        </div>


        <button
          class="primary"
          id="read"
        >
          Read Current Page
        </button>

      </div>


      <div
        class="workspace"
        id="workspace"
        hidden
      >

        <div class="label">
          ASK MENTOR
        </div>


        <textarea
          id="question"
          placeholder="Ask about this page, or say what you want to find..."
        ></textarea>


        <button
          class="ask"
          id="ask"
        >
          Ask Mentor
        </button>


        <div
          class="answer"
          id="answer"
          hidden
        ></div>


        <div class="scan">

          <div class="scanhead">

            <div class="scantitle">
              Page link safety
            </div>

            <div
              class="scanstate"
              id="scanstate"
            >
              Waiting
            </div>

          </div>


          <div
            class="scansummary"
            id="scansummary"
          >
            Links will be checked automatically
            after the page is read.
          </div>


          <div class="stats">

            <div class="stat">

              <div
                class="num"
                id="safe"
              >
                0
              </div>

              <div class="small">
                low risk
              </div>

            </div>


            <div class="stat">

              <div
                class="num"
                id="medium"
              >
                0
              </div>

              <div class="small">
                suspicious
              </div>

            </div>


            <div class="stat">

              <div
                class="num"
                id="high"
              >
                0
              </div>

              <div class="small">
                high risk
              </div>

            </div>

          </div>

        </div>


                </div>
                <div
  class="suspicious-list"
  id="suspicious-list"
  hidden
></div>


        <div class="tools">

          <div class="label">
            ACTIVE TOOLS
          </div>

          <div class="tool-card">

            <div class="tool-info">
              <div class="tool-name">
                Page Scanner
              </div>

              <div class="tool-desc">
                Checks links for suspicious signals.
              </div>
            </div>

            <button
              class="tool-toggle active"
              id="scanner-toggle"
              type="button"
            >
              ON
            </button>

          </div>


          <div class="tool-card">

            <div class="tool-info">
              <div class="tool-name">
                Hover Protection
              </div>

              <div class="tool-desc">
                Shows link safety when you hover.
              </div>
            </div>

            <button
              class="tool-toggle active"
              id="hover-toggle"
              type="button"
            >
              ON
            </button>

          </div>

        </div>


        <div class="hint">
          Try: â€œfind the history sectionâ€,
          â€œwhere is the search box?â€,
          or â€œhow do I use this page?â€
        </div>

      </div>

    `;


    root.appendChild(p);


    el = {

      status:
        root.getElementById(
          "status"
        ),

      title:
        root.getElementById(
          "title"
        ),

      meta:
        root.getElementById(
          "meta"
        ),

      read:
        root.getElementById(
          "read"
        ),

      workspace:
        root.getElementById(
          "workspace"
        ),

      question:
        root.getElementById(
          "question"
        ),

      ask:
        root.getElementById(
          "ask"
        ),

      answer:
        root.getElementById(
          "answer"
        ),

      scanstate:
        root.getElementById(
          "scanstate"
        ),

      scansummary:
        root.getElementById(
          "scansummary"
        ),
      suspiciousList:
  root.getElementById(
    "suspicious-list"
  ),

      safe:
        root.getElementById(
          "safe"
        ),

      medium:
        root.getElementById(
          "medium"
        ),

            high:
        root.getElementById(
          "high"
        ),

      scannerToggle:
        root.getElementById(
          "scanner-toggle"
        ),

      hoverToggle:
        root.getElementById(
          "hover-toggle"
        )
    };


    el.read.onclick =
      readPage;


    el.ask.onclick =
      askQuestion;


    el.question.onkeydown =
      e => {

        if (
          (e.ctrlKey || e.metaKey) &&
          e.key === "Enter"
        ) {

          e.preventDefault();

          askQuestion();
        }
      };
  el.scannerToggle.onclick =
  toggleScanner;


el.hoverToggle.onclick =
  toggleHoverGuard;


updateToolUI();

}
  // ============================================================
// TOOL TOGGLES
// ============================================================

function updateToolUI() {

  if (el.scannerToggle) {

    el.scannerToggle.textContent =
      S.scannerEnabled
        ? "ON"
        : "OFF";

    el.scannerToggle.classList.toggle(
      "active",
      S.scannerEnabled
    );
  }


  if (el.hoverToggle) {

    el.hoverToggle.textContent =
      S.hoverEnabled
        ? "ON"
        : "OFF";

    el.hoverToggle.classList.toggle(
      "active",
      S.hoverEnabled
    );
  }
}


function toggleScanner() {

  S.scannerEnabled =
    !S.scannerEnabled;


  if (!S.scannerEnabled) {

    console.log(
      "PAGE SCANNER: OFF"
    );

    S.scan = null;

    if (el.scanstate)
      el.scanstate.textContent =
        "Disabled";

    if (el.scansummary)
      el.scansummary.textContent =
        "Page scanning is turned off.";

  } else {

    console.log(
      "PAGE SCANNER: ON"
    );

    if (S.read) {

      S.scan =
        scan();

      renderScan(
        S.scan
      );
    }
  }


  updateToolUI();
}


function toggleHoverGuard() {

  S.hoverEnabled =
    !S.hoverEnabled;


  if (S.hoverEnabled) {

    console.log(
      "HOVER GUARD: ON"
    );

    if (S.read) {
      enableHover();
    }

  } else {

    console.log(
      "HOVER GUARD: OFF"
    );

    disableHover();
  }


  updateToolUI();
}


  // ============================================================
  // UI HELPERS
  // ============================================================

  function status(v) {

    if (
      el.status
    ) {

      el.status.textContent =
        v;
    }
  }


  function answerBox(
    v,
    error = false
  ) {

    if (!el.answer)
      return;


    el.answer.hidden =
      false;


    el.answer.classList.toggle(
      "error",
      error
    );


    el.answer.textContent =
      String(v || "");
  }


function renderScan(s) {

  const total =
    s?.total || 0;

  const low =
    s?.low || 0;

  const suspicious =
    s?.suspicious || 0;

  const high =
    s?.high || 0;

  const results =
    Array.isArray(s?.results)
      ? s.results
      : [];


  // ==========================================================
  // UPDATE COUNTERS
  // ==========================================================

  if (el.safe)
    el.safe.textContent =
      low;

  if (el.medium)
    el.medium.textContent =
      suspicious;

  if (el.high)
    el.high.textContent =
      high;


  if (el.scanstate)
    el.scanstate.textContent =
      "Scan complete";


  if (el.scansummary)
    el.scansummary.textContent =
      `${total} links checked.`;


  // ==========================================================
  // SUSPICIOUS LINK LIST
  // ==========================================================

  if (!el.suspiciousList)
    return;


  const flagged =
    results
      .filter(
        item =>
          item.level === "suspicious" ||
          item.level === "high"
      )
      .sort(
        (a, b) =>
          (b.score || 0) -
          (a.score || 0)
      )
      .slice(0, 20);


  // No suspicious links
  if (!flagged.length) {

    el.suspiciousList.hidden =
      true;

    el.suspiciousList.innerHTML =
      "";

    return;
  }


  el.suspiciousList.hidden =
    false;


  // ==========================================================
  // HEADER
  // ==========================================================

  let html = `
    <div class="suspicious-title">
      Suspicious links (${flagged.length})
    </div>
  `;


  // ==========================================================
  // CREATE ITEMS
  // ==========================================================

  flagged.forEach(
    (item, position) => {

      const level =
        item.level === "high"
          ? "high"
          : "suspicious";


      const title =
        clean(
          item.text ||
          item.hostname ||
          item.href ||
          "Unknown link"
        );


      const url =
        clean(
          item.href ||
          ""
        );


      const reasons =
        Array.isArray(
          item.reasons
        )
          ? item.reasons
          : [];


      const reasonText =
        reasons.length
          ? reasons
              .slice(0, 3)
              .join(" â€¢ ")
          : "Suspicious URL characteristics detected.";


      html += `
        <button
          type="button"
          class="suspicious-item ${level}"
          data-suspicious-index="${position}"
        >

          <div class="suspicious-item-title">
            ${escapeHtml(title)}
          </div>

          <div class="suspicious-item-url">
            ${escapeHtml(url)}
          </div>

          <div class="suspicious-item-reason">
            ${escapeHtml(reasonText)}
          </div>

        </button>
      `;
    }
  );


  el.suspiciousList.innerHTML =
    html;


  // ==========================================================
  // CLICK HANDLERS
  // ==========================================================

  const buttons =
    el.suspiciousList.querySelectorAll(
      ".suspicious-item"
    );


  buttons.forEach(
    button => {

      button.addEventListener(
        "click",
        () => {

          const position =
            Number(
              button.dataset.suspiciousIndex
            );


          const item =
            flagged[position];


          if (!item)
            return;


          const links =
            document.querySelectorAll(
              "a[href]"
            );


          const element =
            links[item.index];


          if (!element) {

            answerBox(
              "I found the suspicious link in the scan, but I couldn't locate its current position on the page.",
              true
            );

            return;
          }


          highlight(
            element,
            `Suspicious link: ${
              item.reasons
                ?.slice(0, 2)
                .join(" â€¢ ") ||
              "Suspicious signals detected"
            }`
          );


          element.scrollIntoView({
            behavior:
              "smooth",

            block:
              "center"
          });
        }
      );
    }
  );
}

  // ============================================================
  // READ PAGE
  // ============================================================

  async function readPage() {

    if (S.reading)
      return;


    S.reading =
      true;


    clearHighlight();
    removeHover();


    el.read.disabled =
      true;

    el.read.textContent =
      "Reading page...";


    status("Reading");


    el.meta.textContent =
      "Extracting page content and interactive elements...";


    try {

      const page =
        extract();


      S.page =
        page;


      S.scan =
  S.scannerEnabled
    ? scan()
    : null;


      el.title.textContent =
        page.title;


      el.workspace.hidden =
        false;


      renderScan(
        S.scan
      );


      status("Connecting");


      const d =
        await ingest(
          page
        );


      S.pageId =
        d?.page_id ||
        d?.id ||
        d?.dataset_id;


      if (!S.pageId) {

        throw new Error(
          "Backend did not return a page_id."
        );
      }


      S.read =
  true;


if (S.hoverEnabled) {
  enableHover();
}


      status("Ready");


      el.meta.textContent =
        `Page understood` +
        `${page.stats.chunks} sections â€¢ ` +
        `${page.stats.links} links`;


      el.read.textContent =
        "Page Read Successfully";


    } catch (e) {

      S.read =
        false;

      S.pageId =
        null;


      disableHover();


      status("Error");


      el.meta.textContent =
        "The page could not be prepared.";


      answerBox(
        `Could not read this page. ${
          e?.message || e
        }`,
        true
      );


      el.read.disabled =
        false;


      el.read.textContent =
        "Read Current Page";


      console.error(
        "AI BROWSER MENTOR READ ERROR",
        e
      );


    } finally {

      S.reading =
        false;
    }
  }


  // ============================================================
  // ASK MENTOR
  // ============================================================

  async function askQuestion() {

    if (S.asking)
      return;


    const q =
      clean(
        el.question.value
      );


    if (!q) {

      answerBox(
        "Please enter a question.",
        true
      );

      return;
    }


    if (
      !S.read ||
      !S.pageId
    ) {

      answerBox(
        "Read the current page first so I can answer from its content.",
        true
      );

      return;
    }


    S.asking =
      true;


    el.ask.disabled =
      true;


    el.ask.textContent =
      "Thinking...";


    status("Thinking");


    try {

      const n =
        navigation(q);


      if (
        n.handled
      ) {

        answerBox(
          n.msg,
          !n.ok
        );

        return;
      }


      const d =
        await ask(q);


      const a =
        d?.answer ||
        d?.response ||
        d?.message ||
        "";


      if (!a) {

        throw new Error(
          "The Mentor returned an empty answer."
        );
      }


      answerBox(a);

      status("Ready");


    } catch (e) {

      console.error(
        "AI BROWSER MENTOR ASK ERROR",
        e
      );


      answerBox(
        `I couldn't answer that from the current page. ${
          e?.message || e
        }`,
        true
      );


      status("Error");


    } finally {

      S.asking =
        false;


      el.ask.disabled =
        false;


      el.ask.textContent =
        "Ask Mentor";
    }
  }


  // ============================================================
  // PAGE / SPA RESET
  // ============================================================

  function reset() {

    S.read =
      false;

    S.page =
      null;

    S.pageId =
      null;

    S.scan =
      null;


    clearHighlight();
    disableHover();


    if (!el.read)
      return;


    el.read.disabled =
      false;


    el.read.textContent =
      "Read Current Page";


    el.workspace.hidden =
      true;


    el.answer.hidden =
      true;


    el.question.value =
      "";


    el.title.textContent =
      clean(document.title) ||
      "Current webpage";


    el.meta.textContent =
      "New page detected. Read it to continue.";


    status("Ready");
  }


  function urlCheck() {

    if (
      location.href !==
      S.url
    ) {

      S.url =
        location.href;

      reset();
    }
  }


  function spa() {

    const p =
      history.pushState;

    const r =
      history.replaceState;


    history.pushState =
      function(...a) {

        const x =
          p.apply(
            this,
            a
          );


        setTimeout(
          urlCheck,
          100
        );


        return x;
      };


    history.replaceState =
      function(...a) {

        const x =
          r.apply(
            this,
            a
          );


        setTimeout(
          urlCheck,
          100
        );


        return x;
      };


    addEventListener(
      "popstate",
      () =>
        setTimeout(
          urlCheck,
          100
        )
    );


    setInterval(
      urlCheck,
      700
    );
  }


  // ============================================================
  // BACKGROUND COMPATIBILITY
  // ============================================================

  chrome.runtime.onMessage.addListener(
    (
      m,
      s,
      send
    ) => {

      const t =
        m?.type;

      if (t === "SCAMSHIELD_GET_GMAIL_EMAIL") {
        try {
          if (!location.hostname.endsWith("mail.google.com")) {
            send({ success: false, message: "Open Gmail and select an email first." });
            return false;
          }

          const subject = document.querySelector("h2.hP")?.innerText?.trim() || "";
          const sender = document.querySelector("span[email]")?.getAttribute("email") || "";
          const body = Array.from(document.querySelectorAll("div.a3s"))
            .map(el => el.innerText.trim())
            .filter(Boolean)
            .join("\n\n");

          if (!subject && !body) {
            send({ success: false, message: "Open an individual Gmail message, then try again." });
            return false;
          }

          send({
            success: true,
            subject,
            sender,
            message: [subject ? "Subject: " + subject : "", sender ? "Sender: " + sender : "", body]
              .filter(Boolean).join("\n\n").slice(0, 10000)
          });
        } catch (e) {
          send({ success: false, message: "Could not extract the open Gmail message." });
        }
        return false;
      }



      if (t === "GET_SELECTION") {
        try {
          let sel = window.getSelection() ? window.getSelection().toString().trim() : "";
          if (!sel && document.activeElement && (document.activeElement.tagName === "INPUT" || document.activeElement.tagName === "TEXTAREA")) {
            const el = document.activeElement;
            if (typeof el.selectionStart === "number" && typeof el.selectionEnd === "number" && el.selectionStart !== el.selectionEnd) {
              sel = el.value.substring(el.selectionStart, el.selectionEnd).trim();
            }
          }
          send({
            success: true,
            has_selection: Boolean(sel),
            selection: sel.slice(0, 15000)
          });
        } catch (e) {
          send({ success: false, selection: "", error: e?.message });
        }
        return false;
      }

      if (
        t ===
        "GET_PAGE_CONTENT"
      ) {

        try {

          send(
            extract()
          );

        } catch (e) {

          send({
            error:
              e?.message ||
              "Could not extract page."
          });
        }


        return false;
      }


      if (
        t ===
        "READ_CURRENT_PAGE"
      ) {

        readPage()
          .then(
            () =>
              send({
                success:S.read,
                page_id:S.pageId
              })
          )
          .catch(
            e =>
              send({
                success:false,
                message:
                  e?.message ||
                  "Could not read page."
              })
          );


        return true;
      }


      if (
        t ===
        "SCAN_PAGE"
      ) {

        if (!S.read) {

          send({
            success:false,
            message:
              "Read the page first."
          });

          return false;
        }


        S.scan =
          scan();


        renderScan(
          S.scan
        );


        send({
          success:true,
          summary:
            S.scan.summary
        });


        return false;
      }


      if (
        t === "ENABLE_MENTOR" ||
        t === "TOGGLE_MENTOR"
      ) {

        // Floating UI disabled; use the Chrome toolbar popup instead.


        send({
          success:true,
          enabled:true
        });


        return false;
      }


      if (
        t ===
        "DISABLE_MENTOR"
      ) {

        host?.remove();

        host =
          null;

        root =
          null;

        el =
          {};

        disableHover();


        send({
          success:true,
          enabled:false
        });


        return false;
      }


      // Fixes the old
      // UNKNOWN MESSAGE TYPE MENTOR_STATE
      // warning.

      if (
        t ===
        "MENTOR_STATE"
      ) {

        if (
          m.enabled ===
          false
        ) {

          host?.remove();

          host =
            null;

          root =
            null;

          el =
            {};

          disableHover();

        } else if (!host) {
    // Floating UI disabled; use the Chrome toolbar popup instead.
}


        send({
          success:true,
          enabled:
            m.enabled !== false
        });


        return false;
      }


      return false;
    }
  );


  // ============================================================
  // INITIALIZATION
  // ============================================================

  function init() {

    spa();


    try {

      chrome.runtime
        .sendMessage({
          type:
            "CONTENT_READY",

          url:
            location.href,

          title:
            document.title
        })
        .catch?.(
          () => {}
        );

    } catch {}


    console.log(
      "AI BROWSER MENTOR READY"
    );
  }


  if (
    document.readyState ===
    "loading"
  ) {

    document.addEventListener(
      "DOMContentLoaded",
      init,
      {
        once:true
      }
    );

  } else {

    init();
  }


  addEventListener(
    "beforeunload",
    () => {

      disableHover();

      clearHighlight();
    }
  );
})();

