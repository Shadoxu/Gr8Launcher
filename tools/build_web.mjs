/** Dependency-free static build; all source pages and artwork live in web/. */
import { cp, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('../', import.meta.url));
const source = path.join(root, 'web');
const output = path.join(root, 'dist', 'web');
const configured = process.env.SITE_URL || process.env.VERCEL_PROJECT_PRODUCTION_URL || process.env.VERCEL_URL || 'http://localhost:3000';
const site = new URL(configured.includes('://') ? configured : `https://${configured}`);
if (!['http:', 'https:'].includes(site.protocol) || site.username || site.password || site.pathname !== '/' || site.search || site.hash) throw new Error('SITE_URL must be a plain HTTP(S) origin, for example https://launcher.example.com');
const origin = site.origin;
await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });
for (const item of await readdir(source, { withFileTypes: true })) {
    if (['api', 'vercel.json'].includes(item.name)) continue;
    await cp(path.join(source, item.name), path.join(output, item.name), { recursive: true });
}
let pages = 0;
async function finish(directory) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
        const file = path.join(directory, entry.name);
        if (entry.isDirectory()) await finish(file);
        else if (/\.(html|xml|txt)$/.test(entry.name)) {
            let content = (await readFile(file, 'utf8')).replaceAll('__SITE_URL__', origin);
            if (entry.name.endsWith('.html')) {
                pages++;
                if (entry.name === 'index.html' && directory === output) {
                    const structuredData = { '@context': 'https://schema.org', '@type': 'SoftwareApplication', name: 'Wisc Launcher', applicationCategory: 'GameApplication', operatingSystem: 'Windows; Linux; macOS', url: `${origin}/`, downloadUrl: `${origin}/download`, license: 'https://www.gnu.org/licenses/gpl-3.0.html', offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD' } };
                    content = content.replace('</head>', `<script type="application/ld+json">${JSON.stringify(structuredData).replaceAll('<', '\\u003c')}</script></head>`);
                }
            }
            await writeFile(file, content);
        }
    }
}
await finish(output);
console.log(`Built ${pages} Wisc pages in dist/web for ${origin}`);
