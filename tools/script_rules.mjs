// The only JavaScript a library dash may carry: a "checked script" (SCRIPTS.md). A dash formula starting with "js:" is real
// code that SimHub runs, so it is parsed (with acorn) and allowed only when every part of it is on a short list. Anything else is
// refused, never judged. The plugin has the same rules (Usb/ScriptCheck.cs, using SimHub's own parser) and checks again when
// something is installed; both run the cases in tools/tests/script_vectors.json.
import { parse } from "acorn";

export const LIMITS = { chars: 2000, nodes: 400, depth: 16, text: 200, scripts: 16 };

const MATH_OK = new Set(["abs", "min", "max", "round", "floor", "ceil", "trunc", "sign", "sqrt", "pow", "log", "exp", "sin", "cos", "tan", "atan", "atan2", "PI", "E"]);
const BAD_NAMES = new Set(["constructor", "__proto__", "prototype", "__defineGetter__", "__defineSetter__", "__lookupGetter__", "__lookupSetter__"]);
const GLOBALS = new Set(["root", "undefined", "NaN", "Infinity"]);
const BINARY_OK = new Set(["+", "-", "*", "/", "%", "==", "!=", "===", "!==", "<", "<=", ">", ">="]);
const UNARY_OK = new Set(["!", "-", "+"]);
const ASSIGN_OK = new Set(["=", "+=", "-="]);

/** The problems with a script (the text after "js:"); an empty list = it may be used. */
export function checkScript(source) {
  const problems = [];
  const seen = new Set();
  const add = p => { if (!seen.has(p) && problems.length < 8) { seen.add(p); problems.push(p); } };
  try {
    run(String(source ?? ""), add);
  } catch (e) {
    add("couldn't be checked (" + (e && e.name) + "): refused to be safe");
  }
  return problems;
}

function run(source, add) {
  if (source.length > LIMITS.chars) { add(`is ${source.length} characters (at most ${LIMITS.chars})`); return; }
  let program;
  try {
    program = parse(source, { ecmaVersion: "latest", sourceType: "script", allowReturnOutsideFunction: true });
  } catch (e) {
    add("isn't valid JavaScript: " + e.message);
    return;
  }
  const locals = new Set();
  let nodes = 0, tooBig = false;
  const count = depth => {
    if (++nodes > LIMITS.nodes || depth > LIMITS.depth) {
      if (!tooBig) { tooBig = true; add("is too long or too deeply nested"); }
      return false;
    }
    return true;
  };
  const plainName = name => typeof name === "string" && name.length > 0 && !BAD_NAMES.has(name) && !GLOBALS.has(name) && name !== "Math" && name !== "$prop" && /^[A-Za-z_][A-Za-z0-9_]*$/.test(name);
  const isRootMember = n => n.type === "MemberExpression" && !n.computed && !n.optional && n.object.type === "Identifier" && n.object.name === "root" && n.property.type === "Identifier" && !BAD_NAMES.has(n.property.name);
  const isMathMember = n => n.type === "MemberExpression" && !n.computed && !n.optional && n.object.type === "Identifier" && n.object.name === "Math" && n.property.type === "Identifier" && MATH_OK.has(n.property.name);
  const describe = n => n.type.replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase();

  function statement(n, depth) {
    if (!count(depth)) return;
    switch (n.type) {
      case "ExpressionStatement":
        if (typeof n.directive === "string") break; // "use strict"
        expression(n.expression, depth + 1);
        break;
      case "IfStatement":
        expression(n.test, depth + 1);
        statement(n.consequent, depth + 1);
        if (n.alternate) statement(n.alternate, depth + 1);
        break;
      case "BlockStatement":
        for (const s of n.body) statement(s, depth + 1);
        break;
      case "ReturnStatement":
        if (n.argument) expression(n.argument, depth + 1);
        break;
      case "EmptyStatement":
        break;
      case "VariableDeclaration":
        for (const d of n.declarations) {
          if (d.id.type === "Identifier" && plainName(d.id.name)) {
            locals.add(d.id.name);
            if (d.init) expression(d.init, depth + 1);
          } else add("declares something that isn't a plain variable name");
        }
        break;
      default:
        add(describe(n) + " isn't allowed");
    }
  }

  function expression(n, depth) {
    if (!count(depth)) return;
    switch (n.type) {
      case "Literal":
        if (n.regex || n.bigint !== undefined) add("uses a " + (n.regex ? "regular expression" : "BigInt"));
        else if (typeof n.value === "string" && n.value.length > LIMITS.text) add(`has a text longer than ${LIMITS.text} characters`);
        break;
      case "Identifier":
        if (!locals.has(n.name) && !GLOBALS.has(n.name)) add(`uses "${n.name}": only root, $prop(...), Math and its own variables are available`);
        break;
      case "MemberExpression":
        if (isRootMember(n) || isMathMember(n)) break;
        add("uses a property of something other than root or Math");
        break;
      case "CallExpression":
        if (n.optional) { add("uses ?.()"); break; }
        if (n.callee.type === "Identifier" && n.callee.name === "$prop") {
          if (n.arguments.length < 1 || n.arguments.length > 2 || !(n.arguments[0].type === "Literal" && typeof n.arguments[0].value === "string")) add("calls $prop with something other than a written-out property name");
          else if (n.arguments.length === 2) expression(n.arguments[1], depth + 1);
          count(depth + 1);
        } else if (isMathMember(n.callee)) {
          for (const a of n.arguments) expression(a, depth + 1);
        } else add(`calls ${n.callee.type === "Identifier" ? n.callee.name + "(...)" : "something else"}: only $prop('...') and Math.name(...) may be called`);
        break;
      case "UnaryExpression":
        if (UNARY_OK.has(n.operator)) expression(n.argument, depth + 1);
        else add("uses the operator " + n.operator);
        break;
      case "BinaryExpression":
        if (BINARY_OK.has(n.operator)) { expression(n.left, depth + 1); expression(n.right, depth + 1); }
        else add("uses the operator " + n.operator);
        break;
      case "LogicalExpression":
        expression(n.left, depth + 1); expression(n.right, depth + 1);
        break;
      case "ConditionalExpression":
        expression(n.test, depth + 1); expression(n.consequent, depth + 1); expression(n.alternate, depth + 1);
        break;
      case "AssignmentExpression":
        if (!ASSIGN_OK.has(n.operator)) add("uses the assignment " + n.operator);
        if (!(isRootMember(n.left) || (n.left.type === "Identifier" && locals.has(n.left.name)))) add("assigns to something other than root.name or its own variable");
        expression(n.right, depth + 1);
        break;
      default:
        add(describe(n) + " isn't allowed");
    }
  }

  for (const s of program.body) statement(s, 1);
}
