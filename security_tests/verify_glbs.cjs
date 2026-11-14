#!/usr/bin/env node
// Independent format validation, using the installed Khronos package directly.
const fs = require('node:fs');
const path = require('node:path');
const validator = require('../frontend/node_modules/gltf-validator');

async function main() {
  const directory = path.resolve(process.argv[2] || path.join(__dirname, 'generated'));
  const cases = [
    ['GLB01_valid.glb', false],
    ['GLB02_broken.glb', true],
    ['GLB03_external.glb', false],
    ['GLB04_invalid_accessor.glb', true],
  ];
  let failed = false;
  for (const [filename, expectsErrors] of cases) {
    const report = await validator.validateBytes(
      new Uint8Array(fs.readFileSync(path.join(directory, filename))),
      {
        format: 'glb', maxIssues: 0, writeTimestamp: false,
        externalResourceFunction: () => Promise.reject(new Error('External resource denied')),
      },
    );
    fs.writeFileSync(path.join(directory, `${filename}.validation.json`), JSON.stringify(report, null, 2) + '\n');
    const messages = report.issues.messages;
    let matches = !report.issues.truncated && (report.issues.numErrors > 0) === expectsErrors;
    if (filename === 'GLB04_invalid_accessor.glb') {
      matches = matches && messages.some(issue => issue.code === 'ACCESSOR_INVALID_FLOAT' && issue.severity === 0);
    }
    console.log(`${matches ? 'PASS' : 'FAIL'} ${filename}: ${report.issues.numErrors} errors, ${report.issues.numWarnings} warnings`);
    for (const issue of messages) console.log(`  ${issue.code}: ${issue.message}`);
    failed ||= !matches;
  }
  if (failed) process.exitCode = 1;
}

main().catch(error => {
  console.error(`Verification could not finish: ${error.message}`);
  process.exitCode = 1;
});
