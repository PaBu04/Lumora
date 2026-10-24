/**
 * English interface without touching every component: visible texts and the title / placeholder /
 * aria-label attributes are swapped for their translation (en.ts) as React renders them. Keys with
 * placeholders ("Dynamik {0} %") match texts with values in them; the values are translated too
 * when they are known words. Inputs, code and user content in text areas stay as they are.
 */
import { EN } from "./en";

const exact = new Map(Object.entries(EN));
const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const patterns = Object.entries(EN)
  .filter(([k]) => /\{\w+\}/.test(k))
  .map(([k, out]) => {
    const names: string[] = [];
    const source = k
      .split(/(\{\w+\})/)
      .map((part) => {
        const m = part.match(/^\{(\w+)\}$/);
        if (!m) return escape(part);
        names.push(m[1]);
        return "(.+?)";
      })
      .join("");
    return { re: new RegExp(`^${source}$`, "s"), names, out };
  });

/** The English text for a German one, keeping surrounding spaces; null when there is none. */
export function translate(text: string): string | null {
  const key = text.replace(/\s+/g, " ").trim();
  if (!key) return null;
  let out = exact.get(key);
  if (out === undefined) {
    for (const p of patterns) {
      const m = key.match(p.re);
      if (!m) continue;
      out = p.out;
      p.names.forEach((n, i) => (out = out!.split(`{${n}}`).join(exact.get(m[i + 1].trim()) ?? m[i + 1])));
      break;
    }
  }
  if (out === undefined || out === key) return null;
  return (text.match(/^\s*/)?.[0] ?? "") + out + (text.match(/\s*$/)?.[0] ?? "");
}

const ATTRS = ["title", "placeholder", "aria-label"];
const SKIP = new Set(["SCRIPT", "STYLE", "TEXTAREA", "PRE", "CODE", "INPUT"]);

function attrs(el: Element) {
  for (const a of ATTRS) {
    const v = el.getAttribute(a);
    if (!v) continue;
    const t = translate(v);
    if (t !== null) el.setAttribute(a, t);
  }
}

function fix(node: Node) {
  if (node.nodeType === Node.TEXT_NODE) {
    const parent = node.parentElement;
    if (parent && SKIP.has(parent.tagName)) return;
    const t = translate(node.nodeValue ?? "");
    if (t !== null) node.nodeValue = t;
  } else if (node.nodeType === Node.ELEMENT_NODE) {
    const el = node as Element;
    if (SKIP.has(el.tagName)) return attrs(el);
    attrs(el);
    el.childNodes.forEach(fix);
  }
}

export function startDomTranslation(): void {
  document.documentElement.lang = "en";
  fix(document.body);
  new MutationObserver((records) => {
    for (const r of records) {
      if (r.type === "characterData") fix(r.target);
      else if (r.type === "attributes") attrs(r.target as Element);
      else r.addedNodes.forEach(fix);
    }
  }).observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
  // native dialogs too
  const confirm = window.confirm.bind(window);
  const prompt = window.prompt.bind(window);
  window.confirm = (msg?: string) => confirm(msg ? (translate(msg) ?? msg) : msg);
  window.prompt = (msg?: string, value?: string) => prompt(msg ? (translate(msg) ?? msg) : msg, value);
}
