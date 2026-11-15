/** Local static preview with the same public release handler used by Vercel. */
import http from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import release from '../web/api/release.mjs';

const root = fileURLToPath(new URL('../dist/web/', import.meta.url));
const port = Number(process.env.PORT || 3000);
const mime = { '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.json': 'application/json; charset=utf-8', '.xml': 'application/xml; charset=utf-8', '.txt': 'text/plain; charset=utf-8', '.png': 'image/png', '.ico': 'image/x-icon', '.ttf': 'font/ttf' };
const aliases = { '/home': '/', '/index.html': '/', '/skins': '/cosmetics', '/support': '/help', '/cubeon-bench': '/benchmarks', '/cubeon-bench/': '/benchmarks', '/cubeon-bench/index.html': '/benchmarks' };
http.createServer(async (req, res) => {
    try {
        const pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
        if (pathname === '/api/release') return await release(req, res);
        if (req.method !== 'GET' && req.method !== 'HEAD') { res.writeHead(405, { Allow: 'GET, HEAD' }); return res.end(); }
        if (aliases[pathname]) { res.writeHead(308, { Location: aliases[pathname] }); return res.end(); }
        let file = path.resolve(root, `.${pathname}`);
        if (file !== path.resolve(root) && !file.startsWith(`${path.resolve(root)}${path.sep}`)) { res.writeHead(403); return res.end(); }
        if (pathname.endsWith('/')) file = path.join(file, 'index.html');
        else if (!path.extname(file)) file += '.html';
        let status = 200;
        try { if (!(await stat(file)).isFile()) throw new Error('Not a file'); }
        catch { file = path.join(root, '404.html'); status = 404; }
        const content = await readFile(file);
        res.writeHead(status, { 'Content-Type': mime[path.extname(file)] || 'application/octet-stream', 'X-Content-Type-Options': 'nosniff' });
        res.end(req.method === 'HEAD' ? undefined : content);
    } catch { res.writeHead(400); res.end('Bad request'); }
}).listen(port, '127.0.0.1', () => console.log(`Wisc preview: http://localhost:${port}`));
