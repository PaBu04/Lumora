// Lists the visible German texts of the interface (for the English dictionary in src/i18n/en.ts).
// node scripts/extract-strings.mjs [--missing]  -> JSON on stdout; --missing: only texts without translation
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1")), "../src");
const ATTRS = new Set(["title", "placeholder", "label", "aria-label", "alt", "hint", "text"]);
const CALLS = new Set(["notify", "confirm", "prompt", "alert", "t"]);
const PROPS = new Set(["label", "hint", "title", "text", "description", "de"]);
const SKIP_FILES = new Set(["help.ts", "i18n.ts", "en.ts"]);
const found = new Map();

const visible = (s) =>
  /[A-Za-zÄÖÜäöüß]/.test(s) && !/^[a-z0-9_.\-/#:]+$/.test(s) && !/^(https?:|\/api\/|#)/.test(s) && !/=>|\/api\/|^&nbsp;/.test(s);

function add(text, file) {
  const s = text.replace(/\s+/g, " ").trim();
  if (!s || !visible(s)) return;
  if (!found.has(s)) found.set(s, new Set());
  found.get(s).add(path.basename(file));
}

function template(node) {
  // `Dynamik ${x} %` -> "Dynamik {0} %"
  let s = node.head.text;
  node.templateSpans.forEach((span, i) => (s += `{${i}}` + span.literal.text));
  return s;
}

function walk(file) {
  const src = ts.createSourceFile(file, fs.readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true, file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const visit = (node) => {
    if (ts.isJsxText(node)) add(node.text, file);
    else if (ts.isJsxAttribute(node) && node.initializer && ATTRS.has(node.name.getText())) {
      const init = node.initializer;
      if (ts.isStringLiteral(init)) add(init.text, file);
      else if (ts.isJsxExpression(init) && init.expression) {
        const e = init.expression;
        if (ts.isStringLiteral(e) || ts.isNoSubstitutionTemplateLiteral(e)) add(e.text, file);
        else if (ts.isTemplateExpression(e)) add(template(e), file);
      }
    } else if (ts.isJsxExpression(node) && node.expression) {
      const e = node.expression;
      if (ts.isStringLiteral(e) || ts.isNoSubstitutionTemplateLiteral(e)) add(e.text, file);
      else if (ts.isTemplateExpression(e)) add(template(e), file);
      else if (ts.isConditionalExpression(e)) {
        for (const b of [e.whenTrue, e.whenFalse]) {
          if (ts.isStringLiteral(b)) add(b.text, file);
          else if (ts.isTemplateExpression(b)) add(template(b), file);
        }
      }
    } else if (ts.isCallExpression(node)) {
      const name = node.expression.getText().split(".").pop();
      if (CALLS.has(name)) {
        for (const a of node.arguments.slice(0, 1)) {
          if (ts.isStringLiteral(a) || ts.isNoSubstitutionTemplateLiteral(a)) add(a.text, file);
          else if (ts.isTemplateExpression(a)) add(template(a), file);
        }
      }
    } else if (ts.isPropertyAssignment(node) && PROPS.has(node.name.getText())) {
      const v = node.initializer;
      if (ts.isStringLiteral(v)) add(v.text, file);
      else if (ts.isTemplateExpression(v)) add(template(v), file);
    } else if (ts.isArrayLiteralExpression(node) && node.elements.length === 2 && node.elements.every(ts.isStringLiteral)) {
      // [value, label] pairs of option lists
      add(node.elements[1].text, file);
    }
    ts.forEachChild(node, visit);
  };
  visit(src);
}

function files(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((d) =>
    d.isDirectory() ? files(path.join(dir, d.name)) : /\.tsx?$/.test(d.name) && !SKIP_FILES.has(d.name) ? [path.join(dir, d.name)] : [],
  );
}

files(root).forEach(walk);
let out = [...found.keys()].sort();
if (process.argv.includes("--missing")) {
  const code = ts.transpileModule(fs.readFileSync(path.join(root, "i18n/en.ts"), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS },
  }).outputText;
  const mod = { exports: {} };
  new Function("module", "exports", code)(mod, mod.exports);
  const keys = Object.keys(mod.exports.EN);
  const known = (s) => keys.includes(s) || keys.some((k) => /\{\w+\}/.test(k) && k.replace(/\{\w+\}/g, "{0}") === s.replace(/\{\w+\}/g, "{0}"));
  // class names and the like are not visible text
  out = out.filter((s) => !known(s) && !/^[\w-]*\{\d\}|^\{0\}-|^[a-z-]+ \{\d\}$|^(on live|m\)|m²|claude )/.test(s));
}
console.log(JSON.stringify(out, null, 1));
console.error(`${out.length} texts`);
