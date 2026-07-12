import sharp from 'sharp';
import { copyFile, mkdir } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const brand = (f) => join(root, 'src/assets/brand', f);

const jobs = [
  { src: brand('app-icon.svg'), out: join(root, '../build/icon.png'), width: 1024, height: 1024 },
  { src: brand('app-icon-flat.svg'), out: join(root, 'public/favicon-32.png'), width: 32, height: 32 },
  { src: brand('app-icon-flat.svg'), out: join(root, 'public/favicon-16.png'), width: 16, height: 16 },
  { src: brand('hero.svg'), out: join(root, '../docs/assets/logo.png'), width: 800, height: 680 },
];

for (const { src, out, width, height } of jobs) {
  await mkdir(dirname(out), { recursive: true });
  await sharp(src, { density: 600 }).resize(width, height).png().toFile(out);
  const meta = await sharp(out).metadata();
  if (meta.width !== width || meta.height !== height) {
    console.error(`FAIL ${out}: ${meta.width}x${meta.height}, expected ${width}x${height}`);
    process.exit(1);
  }
  console.log(`OK ${out} ${width}x${height}`);
}

await copyFile(brand('app-icon-flat.svg'), join(root, 'public/favicon.svg'));
console.log('OK public/favicon.svg (copy)');
