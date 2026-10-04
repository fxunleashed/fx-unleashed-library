// Command line for the checked-script rules: reads a JSON array of scripts (the text after "js:") on stdin and prints a JSON
// array with the list of problems of each (an empty list = allowed). Used by tools/jscheck.py.
import { checkScript } from "./script_rules.mjs";

let input = "";
process.stdin.setEncoding("utf8");
for await (const chunk of process.stdin) input += chunk;
const scripts = JSON.parse(input || "[]");
if (!Array.isArray(scripts)) throw new Error("expected a JSON array of scripts");
process.stdout.write(JSON.stringify(scripts.map(s => checkScript(s))));
