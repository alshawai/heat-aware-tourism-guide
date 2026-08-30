import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { join } from "node:path";

const root = process.cwd();
const windowsPython = join(root, ".venv", "Scripts", "python.exe");
const unixPython = join(root, ".venv", "bin", "python");
const python = existsSync(windowsPython) ? windowsPython : unixPython;

if (!existsSync(python)) {
  console.error("Repository virtualenv Python was not found in .venv");
  process.exit(1);
}

const result = spawnSync(python, ["-m", ...process.argv.slice(2)], {
  cwd: root,
  stdio: "inherit",
});

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}

process.exit(result.status ?? 1);
