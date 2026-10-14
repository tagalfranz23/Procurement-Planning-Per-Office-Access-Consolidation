const fs = require('fs');

for (const filename of ['templates/index.html', 'templates/login.html']) {
  const html = fs.readFileSync(filename, 'utf8');
  const blocks = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)];
  for (const [index, block] of blocks.entries()) {
    const source = block[1];
    if (source.trim()) new Function(source);
    process.stdout.write(`${filename} inline script ${index + 1}: syntax OK\n`);
  }
}
