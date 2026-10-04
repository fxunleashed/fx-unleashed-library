# Scripts in library dashes

Most dashes need none. A dash can show any SimHub value with the plugin's own data keys, or with an **NCalc formula**
(`ncalc:...`), which is only an expression and can't do anything outside the dash.

A few formulas need a little memory: "show LIFT once the lift-and-coast value passes 240, and keep showing it until the
driver brakes". That takes a **script**: a formula that starts with `js:`. A script is real code that SimHub runs on the
player's PC, so the library does not take any script it is handed. It takes a **checked script**: one that is made only of the
short list below. The check is automatic and runs in three places: when you submit (the bot), over the whole library (every push),
and in the plugin when someone installs a dash (so a changed library can't get around it).

## What a checked script may contain

| Part | Allowed |
|---|---|
| Statements | `if` / `else`, `{ ... }` blocks, `return`, `var` / `let` / `const` with a plain name |
| Values | numbers, true, false, null, `undefined`, texts up to 200 characters, its own variables, and `root.name` (the dash's own memory, kept between updates) |
| Operators | `+ - * / %`, `== != === !==`, `< <= > >=`, `&& \|\| ??`, `!` `-` `+` in front of a value, `a ? b : c` |
| Assigning | `=`, `+=`, `-=` onto `root.name` or one of its own variables |
| Calls | `$prop('Some.Property')` with the property name written out in quotes (a second value is the fallback), and `Math.abs`, `min`, `max`, `round`, `floor`, `ceil`, `trunc`, `sign`, `sqrt`, `pow`, `log`, `exp`, `sin`, `cos`, `tan`, `atan`, `atan2`, `PI`, `E` |

Comments are fine. At most 2,000 characters, about 400 syntax nodes, 16 levels deep, and 16 scripts per dash.

## What is refused

Everything else, and in particular: loops (`for`, `while`), functions of its own, `new`, `this`, `eval`, `Function`, `[ ]` and
`{ }` values, template texts and regular expressions, `try`, `delete`, `typeof`, `++`, `?.`, `import`, anything reached with
square brackets (`root['x']`), `constructor`, `__proto__`, `prototype`, any other name than `root`, `$prop` and `Math`,
and a property name built from other values (`$prop('A' + 'B')`). A refusal says which script and what part.

This is a short list on purpose. It is checked by reading the code, not by guessing what it does, so a script is either on
the list or it isn't. If you need something that isn't on it, say so in an issue: the list can grow, one safe part at a time.

## Seeing it

A dash with a checked script shows **Contains a checked script** in the plugin's library and on the website, so nobody installs
one by surprise.

## For maintainers

The rules live in `tools/script_rules.mjs` (acorn, pinned in `package-lock.json`) and, for the plugin, `Usb/ScriptCheck.cs` in
the plugin repository (SimHub's own parser). Both run the same cases, `tools/tests/script_vectors.json` (the plugin keeps a copy
in `tools/UsbTest/script-vectors.json`): change one, change the other, add a case for it. The plugin's check is the one that counts.
