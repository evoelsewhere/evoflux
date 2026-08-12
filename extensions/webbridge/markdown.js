(() => {
  "use strict";

  // This renderer intentionally has no runtime dependencies. WebBridge runs as
  // an unpacked MV3 extension, so loading a parser, highlighter, or TeX engine
  // from a CDN would violate both its CSP and its offline contract.
  const TOKEN_PREFIX = "\u0000WBMD";
  const SAFE_BLOCK = Symbol("WebBridgeMarkdown.safeBlock");
  const MAX_MATH_LENGTH = 4096;
  const MAX_MATH_DEPTH = 32;

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function safeHref(value) {
    try {
      const url = new URL(String(value ?? "").trim());
      return ["http:", "https:", "mailto:"].includes(url.protocol) ? url.href : "";
    } catch {
      return "";
    }
  }

  function safeMediaSource(value) {
    const source = String(value ?? "").trim();
    if (!source || source.startsWith("data:") || source.startsWith("blob:")) return "";
    try {
      const url = new URL(source);
      return ["http:", "https:"].includes(url.protocol) ? url.href : "";
    } catch {
      if (source.startsWith("//") || source.startsWith("/") || source.includes("..")) return "";
      return source.replace(/^\.\//, "");
    }
  }

  const words = (value) => new Set(value.split(/\s+/).filter(Boolean));
  const COMMON_LITERALS = words("true false null undefined None True False nil NaN Infinity");
  const COMMON_TYPES = words(
    "any bool boolean byte char class decimal dict double enum float int integer list long map number object set short string struct tuple void"
  );

  const SYNTAX = {
    javascript: {
      keywords: words(
        "as async await break case catch class const continue debugger default delete do else export extends finally for from function get if import in instanceof let new of return set static super switch throw try typeof var while with yield"
      ),
      lineComments: ["//"],
      blockComments: [["/*", "*/"]],
      quotes: ["'", "\"", "`"],
    },
    typescript: {
      keywords: words(
        "abstract as async await break case catch class const constructor continue declare default delete do else enum export extends finally for from function get if implements import in infer instanceof interface keyof let module namespace new of private protected public readonly return satisfies set static super switch throw try type typeof var while with yield"
      ),
      lineComments: ["//"],
      blockComments: [["/*", "*/"]],
      quotes: ["'", "\"", "`"],
    },
    python: {
      keywords: words(
        "and as assert async await break class continue def del elif else except finally for from global if import in is lambda match nonlocal not or pass raise return try while with yield"
      ),
      lineComments: ["#"],
      blockComments: [],
      quotes: ["'", "\""],
    },
    shell: {
      keywords: words(
        "case do done elif else esac export fi for function if in local readonly return select then time until while"
      ),
      lineComments: ["#"],
      blockComments: [],
      quotes: ["'", "\"", "`"],
    },
    json: {
      keywords: new Set(),
      lineComments: [],
      blockComments: [],
      quotes: ["\""],
    },
    css: {
      keywords: words("and from important media not only or supports var"),
      lineComments: [],
      blockComments: [["/*", "*/"]],
      quotes: ["'", "\""],
    },
    sql: {
      keywords: words(
        "add all alter and any as asc begin between by case check column commit constraint create database default delete desc distinct drop else end exists foreign from full grant group having in index inner insert intersect into is join key left like limit not null on or order outer primary references right rollback row select set table then union unique update values view when where with"
      ),
      lineComments: ["--"],
      blockComments: [["/*", "*/"]],
      quotes: ["'", "\"", "`"],
    },
    java: {
      keywords: words(
        "abstract assert boolean break byte case catch char class const continue default do double else enum extends final finally float for goto if implements import instanceof int interface long native new package private protected public return short static strictfp super switch synchronized this throw throws transient try void volatile while"
      ),
      lineComments: ["//"],
      blockComments: [["/*", "*/"]],
      quotes: ["'", "\""],
    },
    kotlin: {
      keywords: words(
        "as break by catch class companion const constructor continue data do dynamic else enum expect external false field file finally for fun get if import in infix init inline inner interface internal is lateinit noinline null object open operator out override package private protected public reified return sealed set suspend tailrec this throw true try typealias val var vararg when where while"
      ),
      lineComments: ["//"],
      blockComments: [["/*", "*/"]],
      quotes: ["'", "\""],
    },
    c: {
      keywords: words(
        "auto break case char const continue default do double else enum extern float for goto if inline int long register restrict return short signed sizeof static struct switch typedef union unsigned void volatile while"
      ),
      lineComments: ["//"],
      blockComments: [["/*", "*/"]],
      quotes: ["'", "\""],
    },
    cpp: {
      keywords: words(
        "alignas alignof and asm auto bitand bitor bool break case catch char class compl concept const consteval constexpr constinit const_cast continue co_await co_return co_yield decltype default delete do double dynamic_cast else enum explicit export extern false float for friend goto if inline int long mutable namespace new noexcept not nullptr operator or private protected public register reinterpret_cast requires return short signed sizeof static static_assert static_cast struct switch template this thread_local throw true try typedef typeid typename union unsigned using virtual void volatile wchar_t while xor"
      ),
      lineComments: ["//"],
      blockComments: [["/*", "*/"]],
      quotes: ["'", "\""],
    },
    csharp: {
      keywords: words(
        "abstract as async await base bool break byte case catch char checked class const continue decimal default delegate do double else enum event explicit extern false finally fixed float for foreach goto if implicit in int interface internal is lock long namespace new null object operator out override params private protected public readonly record ref return sbyte sealed short sizeof stackalloc static string struct switch this throw true try typeof uint ulong unchecked unsafe ushort using virtual void volatile while"
      ),
      lineComments: ["//"],
      blockComments: [["/*", "*/"]],
      quotes: ["'", "\""],
    },
    go: {
      keywords: words(
        "break case chan const continue default defer else fallthrough for func go goto if import interface map package range return select struct switch type var"
      ),
      lineComments: ["//"],
      blockComments: [["/*", "*/"]],
      quotes: ["'", "\"", "`"],
    },
    rust: {
      keywords: words(
        "as async await break const continue crate dyn else enum extern false fn for if impl in let loop match mod move mut pub ref return self Self static struct super trait true type unsafe use where while"
      ),
      lineComments: ["//"],
      blockComments: [["/*", "*/"]],
      quotes: ["'", "\""],
    },
    yaml: {
      keywords: words("true false null yes no on off"),
      lineComments: ["#"],
      blockComments: [],
      quotes: ["'", "\""],
    },
    toml: {
      keywords: words("true false"),
      lineComments: ["#"],
      blockComments: [],
      quotes: ["'", "\""],
    },
  };

  const LANGUAGE_ALIASES = {
    bash: "shell",
    cjs: "javascript",
    cs: "csharp",
    h: "c",
    hpp: "cpp",
    html: "markup",
    java: "java",
    js: "javascript",
    jsx: "javascript",
    kt: "kotlin",
    mjs: "javascript",
    py: "python",
    rb: "text",
    rs: "rust",
    sh: "shell",
    svg: "markup",
    ts: "typescript",
    tsx: "typescript",
    txt: "text",
    xml: "markup",
    yml: "yaml",
    zsh: "shell",
  };

  function canonicalLanguage(value) {
    const raw = String(value ?? "")
      .trim()
      .toLowerCase()
      .replace(/^language-/, "");
    const language = LANGUAGE_ALIASES[raw] || raw;
    if (language === "diff" || language === "markup" || language === "text") return language;
    return Object.prototype.hasOwnProperty.call(SYNTAX, language) ? language : "text";
  }

  function syntaxSpan(kind, value) {
    return `<span class="wb-syntax wb-syntax-${kind}">${escapeHtml(value)}</span>`;
  }

  function readQuotedEnd(source, start, quote) {
    let index = start + quote.length;
    while (index < source.length) {
      if (source[index] === "\\") {
        index += Math.min(2, source.length - index);
        continue;
      }
      if (source.startsWith(quote, index)) return index + quote.length;
      index += 1;
    }
    return source.length;
  }

  function highlightDiff(source) {
    return String(source ?? "")
      .split(/(?<=\n)/)
      .map((line) => {
        if (line.startsWith("+++ ") || line.startsWith("--- ") || line.startsWith("@@")) {
          return syntaxSpan("meta", line);
        }
        if (line.startsWith("+")) return syntaxSpan("addition", line);
        if (line.startsWith("-")) return syntaxSpan("deletion", line);
        return escapeHtml(line);
      })
      .join("");
  }

  function findMarkupTagEnd(source, start) {
    let quote = "";
    for (let index = start + 1; index < source.length; index += 1) {
      const char = source[index];
      if (quote) {
        if (char === "\\") index += 1;
        else if (char === quote) quote = "";
      } else if (char === "'" || char === "\"") {
        quote = char;
      } else if (char === ">") {
        return index + 1;
      }
    }
    return source.length;
  }

  function highlightMarkup(source) {
    const value = String(source ?? "");
    let output = "";
    let index = 0;
    while (index < value.length) {
      if (value.startsWith("<!--", index)) {
        const close = value.indexOf("-->", index + 4);
        const end = close < 0 ? value.length : close + 3;
        output += syntaxSpan("comment", value.slice(index, end));
        index = end;
        continue;
      }
      if (value[index] === "<") {
        const end = findMarkupTagEnd(value, index);
        output += syntaxSpan("tag", value.slice(index, end));
        index = end;
        continue;
      }
      const next = value.indexOf("<", index);
      const end = next < 0 ? value.length : next;
      output += escapeHtml(value.slice(index, end));
      index = end;
    }
    return output;
  }

  function highlightCode(source, requestedLanguage) {
    const value = String(source ?? "");
    const language = canonicalLanguage(requestedLanguage);
    if (language === "text") return escapeHtml(value);
    if (language === "diff") return highlightDiff(value);
    if (language === "markup") return highlightMarkup(value);

    const config = SYNTAX[language];
    let output = "";
    let index = 0;
    while (index < value.length) {
      const blockComment = config.blockComments.find(([open]) => value.startsWith(open, index));
      if (blockComment) {
        const [open, close] = blockComment;
        const closeIndex = value.indexOf(close, index + open.length);
        const end = closeIndex < 0 ? value.length : closeIndex + close.length;
        output += syntaxSpan("comment", value.slice(index, end));
        index = end;
        continue;
      }

      const lineComment = config.lineComments.find((marker) => value.startsWith(marker, index));
      if (lineComment) {
        const newline = value.indexOf("\n", index + lineComment.length);
        const end = newline < 0 ? value.length : newline;
        output += syntaxSpan("comment", value.slice(index, end));
        index = end;
        continue;
      }

      const quote = config.quotes.find((candidate) => value.startsWith(candidate, index));
      if (quote) {
        const end = readQuotedEnd(value, index, quote);
        const token = value.slice(index, end);
        let kind = "string";
        if (language === "json") {
          let lookahead = end;
          while (/\s/.test(value[lookahead] || "")) lookahead += 1;
          if (value[lookahead] === ":") kind = "property";
        }
        output += syntaxSpan(kind, token);
        index = end;
        continue;
      }

      const number = value.slice(index).match(/^(?:0[xX][\da-fA-F]+|0[bB][01]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/);
      if (number) {
        output += syntaxSpan("number", number[0]);
        index += number[0].length;
        continue;
      }

      const identifier = value.slice(index).match(/^[A-Za-z_$][\w$]*/);
      if (identifier) {
        const token = identifier[0];
        const normalized = language === "sql" ? token.toLowerCase() : token;
        let kind = "";
        if (config.keywords.has(normalized)) kind = "keyword";
        else if (COMMON_LITERALS.has(token)) kind = "literal";
        else if (COMMON_TYPES.has(token)) kind = "type";
        else {
          let lookahead = index + token.length;
          while (/\s/.test(value[lookahead] || "")) lookahead += 1;
          if (value[lookahead] === "(") kind = "function";
          else if ((language === "yaml" || language === "toml" || language === "css") && value[lookahead] === ":") kind = "property";
        }
        output += kind ? syntaxSpan(kind, token) : escapeHtml(token);
        index += token.length;
        continue;
      }

      output += escapeHtml(value[index]);
      index += 1;
    }
    return output;
  }

  const GREEK = {
    alpha: "α", beta: "β", gamma: "γ", delta: "δ", epsilon: "ϵ", varepsilon: "ε",
    zeta: "ζ", eta: "η", theta: "θ", vartheta: "ϑ", iota: "ι", kappa: "κ",
    lambda: "λ", mu: "μ", nu: "ν", xi: "ξ", omicron: "ο", pi: "π", varpi: "ϖ",
    rho: "ρ", varrho: "ϱ", sigma: "σ", varsigma: "ς", tau: "τ", upsilon: "υ",
    phi: "ϕ", varphi: "φ", chi: "χ", psi: "ψ", omega: "ω", Gamma: "Γ",
    Delta: "Δ", Theta: "Θ", Lambda: "Λ", Xi: "Ξ", Pi: "Π", Sigma: "Σ",
    Upsilon: "Υ", Phi: "Φ", Psi: "Ψ", Omega: "Ω",
  };
  const MATH_SYMBOLS = {
    approx: "≈", ast: "∗", bullet: "•", cap: "∩", cdot: "⋅", circ: "∘", cong: "≅",
    cup: "∪", div: "÷", emptyset: "∅", equiv: "≡", exists: "∃", forall: "∀",
    ge: "≥", geq: "≥", gets: "←", iff: "⇔", implies: "⇒", in: "∈", infty: "∞",
    land: "∧", le: "≤", leftarrow: "←", Leftrightarrow: "⇔", leq: "≤", lnot: "¬",
    lor: "∨", mapsto: "↦", mid: "∣", mp: "∓", nabla: "∇", ne: "≠", neq: "≠",
    ni: "∋", notin: "∉", oplus: "⊕", otimes: "⊗", parallel: "∥", partial: "∂",
    perp: "⊥", pm: "±", propto: "∝", rightarrow: "→", Rightarrow: "⇒",
    subset: "⊂", subseteq: "⊆", supset: "⊃", supseteq: "⊇", therefore: "∴",
    times: "×", to: "→",
  };
  const MATH_FUNCTIONS = new Set([
    "arccos", "arcsin", "arctan", "cos", "cosh", "cot", "coth", "csc", "det", "dim",
    "exp", "gcd", "hom", "inf", "ker", "lg", "lim", "liminf", "limsup", "ln", "log",
    "max", "min", "Pr", "sec", "sin", "sinh", "sup", "tan", "tanh",
  ]);
  const LARGE_OPERATORS = { int: "∫", iint: "∬", iiint: "∭", oint: "∮", prod: "∏", sum: "∑" };
  const DELIMITERS = {
    langle: "⟨", rangle: "⟩", lbrace: "{", rbrace: "}", lceil: "⌈", rceil: "⌉",
    lfloor: "⌊", rfloor: "⌋", vert: "|", Vert: "‖",
  };

  class CommonMathParser {
    constructor(source, depth = 0) {
      this.source = String(source ?? "");
      this.index = 0;
      this.depth = depth;
    }

    render(stop = "") {
      const output = [];
      while (this.index < this.source.length) {
        if (stop && this.source[this.index] === stop) break;
        if (/\s/.test(this.source[this.index])) {
          while (/\s/.test(this.source[this.index] || "")) this.index += 1;
          output.push('<mspace width="0.25em"></mspace>');
          continue;
        }
        output.push(this.renderElement());
      }
      return output.join("");
    }

    renderElement() {
      let base = this.renderAtom();
      let subscript = "";
      let superscript = "";
      while (this.source[this.index] === "_" || this.source[this.index] === "^") {
        const operator = this.source[this.index];
        this.index += 1;
        const argument = this.renderArgument();
        if (operator === "_") subscript = argument;
        else superscript = argument;
      }
      if (subscript && superscript) {
        return `<msubsup>${base}<mrow>${subscript}</mrow><mrow>${superscript}</mrow></msubsup>`;
      }
      if (subscript) return `<msub>${base}<mrow>${subscript}</mrow></msub>`;
      if (superscript) return `<msup>${base}<mrow>${superscript}</mrow></msup>`;
      return base;
    }

    renderAtom() {
      if (this.index >= this.source.length) return "";
      const char = this.source[this.index];
      if (char === "{") {
        if (this.depth >= MAX_MATH_DEPTH) {
          this.index += 1;
          return "<mtext>{</mtext>";
        }
        this.index += 1;
        const nested = new CommonMathParser(this.source.slice(this.index), this.depth + 1);
        const body = nested.render("}");
        this.index += nested.index;
        if (this.source[this.index] === "}") this.index += 1;
        return `<mrow>${body}</mrow>`;
      }
      if (char === "\\") return this.renderCommand();
      if (/\d/.test(char)) {
        const number = this.source.slice(this.index).match(/^\d+(?:\.\d+)?/)[0];
        this.index += number.length;
        return `<mn>${escapeHtml(number)}</mn>`;
      }
      if (/[A-Za-z]/.test(char)) {
        const identifier = this.source.slice(this.index).match(/^[A-Za-z]+/)[0];
        this.index += identifier.length;
        return `<mi>${escapeHtml(identifier)}</mi>`;
      }
      this.index += 1;
      if (/[+\-=<>()[\]|,:;.!]/.test(char)) return `<mo>${escapeHtml(char)}</mo>`;
      return `<mtext>${escapeHtml(char)}</mtext>`;
    }

    renderArgument() {
      while (/\s/.test(this.source[this.index] || "")) this.index += 1;
      if (this.source[this.index] === "{") return this.renderAtom().replace(/^<mrow>|<\/mrow>$/g, "");
      return this.renderElement();
    }

    readRawGroup() {
      while (/\s/.test(this.source[this.index] || "")) this.index += 1;
      if (this.source[this.index] !== "{") return "";
      this.index += 1;
      const start = this.index;
      let depth = 1;
      while (this.index < this.source.length && depth > 0) {
        if (this.source[this.index] === "\\") {
          this.index += Math.min(2, this.source.length - this.index);
          continue;
        }
        if (this.source[this.index] === "{") depth += 1;
        else if (this.source[this.index] === "}") depth -= 1;
        this.index += 1;
      }
      return this.source.slice(start, depth === 0 ? this.index - 1 : this.index);
    }

    renderRequiredGroup() {
      while (/\s/.test(this.source[this.index] || "")) this.index += 1;
      if (this.source[this.index] !== "{") return this.renderElement();
      return this.renderAtom().replace(/^<mrow>|<\/mrow>$/g, "");
    }

    renderDelimiter() {
      while (/\s/.test(this.source[this.index] || "")) this.index += 1;
      if (this.source[this.index] === "\\") {
        this.index += 1;
        const name = (this.source.slice(this.index).match(/^[A-Za-z]+/) || [""])[0];
        this.index += name.length;
        return DELIMITERS[name] || MATH_SYMBOLS[name] || name || "|";
      }
      return this.source[this.index++] || "";
    }

    renderMatrix(environment, content) {
      const rows = content.split(/\\\\/).map((row) => (
        `<mtr>${row.split("&").map((cell) => (
          `<mtd><mrow>${new CommonMathParser(cell.trim(), this.depth + 1).render()}</mrow></mtd>`
        )).join("")}</mtr>`
      )).join("");
      const table = `<mtable>${rows}</mtable>`;
      if (environment === "pmatrix") return `<mrow><mo stretchy="true">(</mo>${table}<mo stretchy="true">)</mo></mrow>`;
      if (environment === "bmatrix") return `<mrow><mo stretchy="true">[</mo>${table}<mo stretchy="true">]</mo></mrow>`;
      if (environment === "Bmatrix") return `<mrow><mo stretchy="true">{</mo>${table}<mo stretchy="true">}</mo></mrow>`;
      if (environment === "vmatrix") return `<mrow><mo stretchy="true">|</mo>${table}<mo stretchy="true">|</mo></mrow>`;
      if (environment === "cases") return `<mrow><mo stretchy="true">{</mo>${table}</mrow>`;
      return table;
    }

    renderCommand() {
      this.index += 1;
      if (this.index >= this.source.length) return "<mtext>\\</mtext>";
      const match = this.source.slice(this.index).match(/^[A-Za-z]+/);
      if (!match) {
        const escaped = this.source[this.index++];
        return `<mo>${escapeHtml(escaped)}</mo>`;
      }
      const name = match[0];
      this.index += name.length;

      if (GREEK[name]) return `<mi>${GREEK[name]}</mi>`;
      if (MATH_SYMBOLS[name]) return `<mo>${MATH_SYMBOLS[name]}</mo>`;
      if (LARGE_OPERATORS[name]) return `<mo largeop="true" movablelimits="true">${LARGE_OPERATORS[name]}</mo>`;
      if (MATH_FUNCTIONS.has(name)) return `<mi mathvariant="normal">${escapeHtml(name)}</mi>`;
      if (name === "frac" || name === "dfrac" || name === "tfrac") {
        const numerator = this.renderRequiredGroup();
        const denominator = this.renderRequiredGroup();
        return `<mfrac><mrow>${numerator}</mrow><mrow>${denominator}</mrow></mfrac>`;
      }
      if (name === "sqrt") {
        let index = "";
        while (/\s/.test(this.source[this.index] || "")) this.index += 1;
        if (this.source[this.index] === "[") {
          const close = this.source.indexOf("]", this.index + 1);
          if (close >= 0) {
            index = new CommonMathParser(this.source.slice(this.index + 1, close), this.depth + 1).render();
            this.index = close + 1;
          }
        }
        const radicand = this.renderRequiredGroup();
        return index
          ? `<mroot><mrow>${radicand}</mrow><mrow>${index}</mrow></mroot>`
          : `<msqrt><mrow>${radicand}</mrow></msqrt>`;
      }
      if (["text", "textrm", "textsf", "texttt"].includes(name)) {
        return `<mtext>${escapeHtml(this.readRawGroup())}</mtext>`;
      }
      if (["mathbf", "mathrm", "mathit", "mathsf", "mathtt"].includes(name)) {
        const variants = {
          mathbf: "bold", mathrm: "normal", mathit: "italic", mathsf: "sans-serif", mathtt: "monospace",
        };
        return `<mstyle mathvariant="${variants[name]}"><mrow>${this.renderRequiredGroup()}</mrow></mstyle>`;
      }
      if (["left", "right"].includes(name)) {
        return `<mo stretchy="true">${escapeHtml(this.renderDelimiter())}</mo>`;
      }
      if (["hat", "bar", "vec", "overline", "underline"].includes(name)) {
        const body = this.renderRequiredGroup();
        if (name === "underline") return `<munder accentunder="true"><mrow>${body}</mrow><mo>_</mo></munder>`;
        const accent = name === "vec" ? "→" : name === "bar" || name === "overline" ? "¯" : "^";
        return `<mover accent="true"><mrow>${body}</mrow><mo>${accent}</mo></mover>`;
      }
      if ([",", ";", "quad", "qquad", "!"].includes(name)) {
        const widths = { ",": "0.17em", ";": "0.28em", quad: "1em", qquad: "2em", "!": "-0.17em" };
        return `<mspace width="${widths[name]}"></mspace>`;
      }
      if (name === "begin") {
        const environment = this.readRawGroup().trim();
        const supported = new Set(["matrix", "pmatrix", "bmatrix", "Bmatrix", "vmatrix", "cases", "aligned"]);
        if (supported.has(environment)) {
          const endMarker = `\\end{${environment}}`;
          const end = this.source.indexOf(endMarker, this.index);
          const content = this.source.slice(this.index, end < 0 ? this.source.length : end);
          this.index = end < 0 ? this.source.length : end + endMarker.length;
          return this.renderMatrix(environment, content);
        }
        return `<mtext>\\begin{${escapeHtml(environment)}}</mtext>`;
      }
      return `<mtext>\\${escapeHtml(name)}</mtext>`;
    }
  }

  function renderMath(tex, options = {}) {
    const display = Boolean(options.display);
    const complete = options.complete !== false;
    const source = String(tex ?? "").slice(0, MAX_MATH_LENGTH);
    const body = new CommonMathParser(source).render();
    const className = [
      "wb-math",
      display ? "wb-math-display" : "wb-math-inline",
      complete ? "" : "wb-streaming-incomplete",
    ].filter(Boolean).join(" ");
    const math = `<math xmlns="http://www.w3.org/1998/Math/MathML"${display ? ' display="block"' : ""} aria-label="${escapeHtml(source)}"><semantics><mrow>${body}</mrow><annotation encoding="application/x-tex">${escapeHtml(source)}</annotation></semantics></math>`;
    const tag = display ? "div" : "span";
    return `<${tag} class="${className}" data-tex="${escapeHtml(source)}">${math}</${tag}>`;
  }

  function renderInlineMath(source, hold) {
    let output = "";
    let index = 0;
    while (index < source.length) {
      if (source.startsWith("\\(", index)) {
        const close = source.indexOf("\\)", index + 2);
        if (close >= 0) {
          output += hold(renderMath(source.slice(index + 2, close)));
          index = close + 2;
          continue;
        }
      }
      if (source[index] === "$" && source[index + 1] !== "$" && source[index - 1] !== "\\") {
        let close = index + 1;
        while (close < source.length) {
          close = source.indexOf("$", close);
          if (close < 0) break;
          if (source[close - 1] !== "\\") break;
          close += 1;
        }
        const body = close < 0 ? "" : source.slice(index + 1, close);
        const valid = Boolean(
          body
          && !body.includes("\n")
          && !/^\s|\s$/.test(body)
          && !/\d/.test(source[close + 1] || "")
        );
        if (valid) {
          output += hold(renderMath(body));
          index = close + 1;
          continue;
        }
      }
      output += source[index];
      index += 1;
    }
    return output;
  }

  function renderInline(source) {
    const tokens = [];
    const hold = (html) => {
      const token = `${TOKEN_PREFIX}${tokens.length}\u0000`;
      tokens.push(html);
      return token;
    };

    // NUL cannot be authored into a placeholder. This prevents a hostile model
    // response from referencing a previously held safe-HTML token by name.
    let value = String(source ?? "").replace(/\u0000/g, "\uFFFD");
    value = value.replace(/`([^`\n]+)`/g, (_match, code) => (
      hold(`<code>${escapeHtml(code)}</code>`)
    ));
    value = value.replace(/!\[([^\]\n]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g, (_match, alt, rawSource) => {
      const mediaSource = safeMediaSource(rawSource);
      if (!mediaSource) return escapeHtml(alt || "Image unavailable");
      if (/^https?:\/\//i.test(mediaSource)) {
        return hold(
          `<button type="button" data-webbridge-remote-media-src="${escapeHtml(mediaSource)}" data-webbridge-remote-media-alt="${escapeHtml(alt || "Image")}">Load remote image: ${escapeHtml(alt || "Image")}</button>`
        );
      }
      return hold(
        `<img data-webbridge-media-src="${escapeHtml(mediaSource)}" alt="${escapeHtml(alt || "Image")}" loading="lazy">`
      );
    });
    value = value.replace(/\[([^\]\n]+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g, (_match, label, rawHref) => {
      const href = safeHref(rawHref);
      if (!href) return escapeHtml(label);
      return hold(
        `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a>`
      );
    });
    value = renderInlineMath(value, hold);
    value = escapeHtml(value)
      .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
      .replace(/__([^_\n]+)__/g, "<strong>$1</strong>")
      .replace(/~~([^~\n]+)~~/g, "<del>$1</del>")
      .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>")
      .replace(/(^|[^\w])_([^_\n]+)_(?!\w)/g, "$1<em>$2</em>");

    tokens.forEach((html, tokenIndex) => {
      value = value.split(`${TOKEN_PREFIX}${tokenIndex}\u0000`).join(html);
    });
    return value;
  }

  function splitTableRow(line) {
    const trimmed = line.trim().replace(/^\|/, "").replace(/\|$/, "");
    return trimmed.split("|").map((cell) => cell.trim());
  }

  function isTableDivider(line) {
    return /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
  }

  function isFenceClose(line, marker, minimum) {
    const trimmed = line.trim();
    return trimmed.length >= minimum && [...trimmed].every((char) => char === marker);
  }

  function startsBlock(lines, index) {
    const line = lines[index] || "";
    const next = lines[index + 1] || "";
    const trimmed = line.trim();
    return (
      /^\s*$/.test(line) ||
      /^\s{0,3}(`{3,}|~{3,})/.test(line) ||
      trimmed.startsWith("$$") ||
      trimmed.startsWith("\\[") ||
      /^\s{0,3}#{1,6}\s+/.test(line) ||
      /^\s{0,3}>\s?/.test(line) ||
      /^\s*[-+*]\s+/.test(line) ||
      /^\s*\d+[.)]\s+/.test(line) ||
      /^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line) ||
      (line.includes("|") && isTableDivider(next))
    );
  }

  function codeBlockHtml(code, requestedLanguage, complete) {
    const language = canonicalLanguage(requestedLanguage);
    const classes = [
      "wb-code-block",
      complete ? "" : "wb-streaming-incomplete",
    ].filter(Boolean).join(" ");
    return `<pre class="${classes}" data-language="${escapeHtml(language)}"><code class="wb-code language-${escapeHtml(language)}">${highlightCode(code, language)}</code></pre>`;
  }

  function safeBlock(type, raw, html, start, end, complete = true, extra = {}) {
    return Object.freeze({
      type,
      raw,
      html,
      start,
      end,
      complete,
      streaming: !complete,
      ...extra,
      [SAFE_BLOCK]: true,
    });
  }

  function parseBlocks(source, options = {}) {
    const value = String(source ?? "").replace(/\r\n?/g, "\n");
    const lines = value.split("\n");
    const offsets = [0];
    for (let index = 0; index < lines.length - 1; index += 1) {
      offsets.push(offsets[index] + lines[index].length + 1);
    }
    const blocks = [];
    let index = 0;

    const addBlock = (type, startLine, endLine, html, complete = true, extra = {}) => {
      const start = offsets[startLine] ?? value.length;
      const end = endLine < offsets.length ? offsets[endLine] : value.length;
      blocks.push(safeBlock(
        type,
        lines.slice(startLine, endLine).join("\n"),
        html,
        start,
        end,
        complete,
        extra,
      ));
    };

    while (index < lines.length) {
      const line = lines[index];
      if (!line.trim()) {
        index += 1;
        continue;
      }

      const fence = line.match(/^\s{0,3}(`{3,}|~{3,})\s*([\w#+.-]*)\s*$/);
      if (fence) {
        const start = index;
        const marker = fence[1][0];
        const minimum = fence[1].length;
        const language = canonicalLanguage(fence[2]);
        const body = [];
        let complete = false;
        index += 1;
        while (index < lines.length) {
          if (isFenceClose(lines[index], marker, minimum)) {
            complete = true;
            index += 1;
            break;
          }
          body.push(lines[index]);
          index += 1;
        }
        addBlock(
          "code",
          start,
          index,
          codeBlockHtml(body.join("\n"), language, complete),
          complete,
          { language },
        );
        continue;
      }

      const trimmed = line.trim();
      const displayKind = trimmed.startsWith("$$") ? "dollar" : trimmed.startsWith("\\[") ? "bracket" : "";
      if (displayKind) {
        const start = index;
        const open = displayKind === "dollar" ? "$$" : "\\[";
        const close = displayKind === "dollar" ? "$$" : "\\]";
        const first = trimmed.slice(open.length);
        const parts = [];
        let complete = false;
        if (first.endsWith(close) && first.length >= close.length) {
          parts.push(first.slice(0, -close.length));
          complete = true;
          index += 1;
        } else {
          if (first) parts.push(first);
          index += 1;
          while (index < lines.length) {
            const candidate = lines[index];
            const closeIndex = candidate.lastIndexOf(close);
            if (closeIndex >= 0 && !candidate.slice(closeIndex + close.length).trim()) {
              parts.push(candidate.slice(0, closeIndex));
              complete = true;
              index += 1;
              break;
            }
            parts.push(candidate);
            index += 1;
          }
        }
        const tex = parts.join("\n").trim();
        addBlock("math", start, index, renderMath(tex, { display: true, complete }), complete, { tex });
        continue;
      }

      const heading = line.match(/^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/);
      if (heading) {
        const level = heading[1].length;
        addBlock("heading", index, index + 1, `<h${level}>${renderInline(heading[2])}</h${level}>`, true, { level });
        index += 1;
        continue;
      }

      if (/^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
        addBlock("thematic_break", index, index + 1, "<hr>");
        index += 1;
        continue;
      }

      if (/^\s{0,3}>\s?/.test(line)) {
        const start = index;
        const quote = [];
        while (index < lines.length && /^\s{0,3}>\s?/.test(lines[index])) {
          quote.push(lines[index].replace(/^\s{0,3}>\s?/, ""));
          index += 1;
        }
        const nested = parseBlocks(quote.join("\n"), options);
        addBlock("blockquote", start, index, `<blockquote>${renderBlocks(nested)}</blockquote>`);
        continue;
      }

      if (line.includes("|") && isTableDivider(lines[index + 1] || "")) {
        const start = index;
        const headers = splitTableRow(line);
        const alignments = splitTableRow(lines[index + 1]).map((cell) => {
          const left = cell.startsWith(":");
          const right = cell.endsWith(":");
          return left && right ? "center" : right ? "right" : left ? "left" : "";
        });
        index += 2;
        const rows = [];
        while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
          rows.push(splitTableRow(lines[index]));
          index += 1;
        }
        const cells = (items, tag) => items.map((cell, cellIndex) => {
          const align = alignments[cellIndex] ? ` style="text-align:${alignments[cellIndex]}"` : "";
          return `<${tag}${align}>${renderInline(cell)}</${tag}>`;
        }).join("");
        const html = `<div class="table-wrap"><table><thead><tr>${cells(headers, "th")}</tr></thead><tbody>${rows.map((row) => `<tr>${cells(row, "td")}</tr>`).join("")}</tbody></table></div>`;
        addBlock("table", start, index, html, true, { alignments });
        continue;
      }

      const unordered = line.match(/^\s*[-+*]\s+(.+)$/);
      const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
      if (unordered || ordered) {
        const start = index;
        const tag = unordered ? "ul" : "ol";
        const items = [];
        const pattern = unordered ? /^\s*[-+*]\s+(.+)$/ : /^\s*\d+[.)]\s+(.+)$/;
        while (index < lines.length) {
          const item = lines[index].match(pattern);
          if (!item) break;
          const task = item[1].match(/^\[([ xX])\]\s+(.+)$/);
          items.push(task
            ? `<li class="task"><input type="checkbox" disabled${task[1].toLowerCase() === "x" ? " checked" : ""}>${renderInline(task[2])}</li>`
            : `<li>${renderInline(item[1])}</li>`
          );
          index += 1;
        }
        addBlock("list", start, index, `<${tag}>${items.join("")}</${tag}>`, true, { ordered: Boolean(ordered) });
        continue;
      }

      const start = index;
      const paragraph = [line];
      index += 1;
      while (index < lines.length && !startsBlock(lines, index)) {
        paragraph.push(lines[index]);
        index += 1;
      }
      addBlock("paragraph", start, index, `<p>${paragraph.map(renderInline).join("<br>")}</p>`);
    }
    return Object.freeze(blocks);
  }

  function renderBlocks(blocks) {
    if (!Array.isArray(blocks)) return "";
    return blocks.map((block) => (
      block && block[SAFE_BLOCK] ? block.html : escapeHtml(block?.raw ?? "")
    )).join("");
  }

  function toSafeHtml(source, options = {}) {
    return renderBlocks(parseBlocks(source, options));
  }

  function render(target, markdown, options = {}) {
    const blocks = parseBlocks(markdown, options);
    target.innerHTML = renderBlocks(blocks);
    return blocks;
  }

  globalThis.WebBridgeMarkdown = Object.freeze({
    highlight: highlightCode,
    parseBlocks,
    render,
    renderBlocks,
    renderMath,
    toSafeHtml,
  });
})();
