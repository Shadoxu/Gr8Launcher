'use strict';

function downloadText(filename, content, type = 'text/plain;charset=utf-8') {
    const url = URL.createObjectURL(new Blob([content], { type }));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const releaseStatus = document.querySelector('[data-release-status]');
if (releaseStatus) {
    fetch('/api/release', { signal: AbortSignal.timeout(10000) }).then(response => {
        if (!response.ok) throw new Error('Release unavailable');
        return response.json();
    }).then(release => {
        for (const button of document.querySelectorAll('[data-download]')) {
            const asset = release.assets[button.dataset.download];
            if (asset && /^https:\/\/github\.com\/wisc-launcher\/wisc\/releases\/download\//.test(asset.url)) {
                button.href = asset.url;
                if (button.dataset.download === 'installer') button.textContent = 'Download installer ↗';
                if (button.dataset.download === 'portable') button.textContent = 'Download portable ZIP ↗';
                if (button.dataset.download === 'checksums') button.textContent = 'Download checksums ↗';
            }
        }
        releaseStatus.textContent = `Latest published release: ${release.tag}. Files are hosted on GitHub.`;
    }).catch(() => {
        releaseStatus.textContent = 'Live release details are unavailable. Use the buttons to view the latest published files on GitHub.';
    });
}

const doctorForm = document.getElementById('doctor-form');
if (doctorForm) {
    let checklist = '';
    doctorForm.addEventListener('submit', event => {
        event.preventDefault();
        const answers = new FormData(doctorForm);
        const selectedJava = Number(answers.get('java'));
        const requirement = answers.get('game');
        const steps = [];
        if (requirement === 'custom') steps.push('Check the exact Java requirement published for your Minecraft release and loader.');
        else if (selectedJava !== Number(requirement)) steps.push(`Your selected Java ${selectedJava} differs from the usual Java ${requirement} requirement. Check the exact game and loader requirements, then select the appropriate executable in Options → Java.`);
        else steps.push(`Java ${selectedJava} matches this release group’s usual requirement. Confirm that Wisc selects this executable in Options → Java.`);
        if (!answers.has('files')) steps.push('Install the game and loader files before trying an offline launch.');
        if (!answers.has('space')) steps.push('Check free space and write access on the instance drive.');
        if (!answers.has('compatible')) steps.push('Match every mod and its dependencies to the selected Minecraft version and loader.');
        if (!answers.has('network')) steps.push('Connect to the internet if game, loader, mod, or account files still need to be fetched.');
        steps.push('If the launch still fails, inspect game output for the first error and use the troubleshooting guide. Redact credentials before sharing logs.');
        const list = document.getElementById('doctor-steps');
        list.replaceChildren(...steps.map(step => {
            const item = document.createElement('li');
            item.textContent = step;
            return item;
        }));
        document.getElementById('doctor-result').hidden = false;
        checklist = `Wisc Launcher — launch checklist\n\n${steps.map((step, index) => `${index + 1}. ${step}`).join('\n')}\n`;
    });
    document.getElementById('doctor-export').addEventListener('click', () => downloadText('wisc-launch-checklist.txt', checklist));
}

const benchForm = document.getElementById('bench-form');
if (benchForm) {
    const storageKey = 'wisc-bench-v1';
    const status = document.getElementById('bench-status');
    let runs = [];
    function validRun(run) {
        return run && typeof run.label === 'string' && run.label.trim().length > 0 && run.label.length <= 80 && Number.isFinite(run.seconds) && run.seconds > 0 && run.seconds <= 86400 && [run.fps, run.memory].every(value => value === null || (Number.isFinite(value) && value >= 0 && value <= 1000000));
    }
    try {
        const saved = JSON.parse(localStorage.getItem(storageKey) || '[]');
        if (Array.isArray(saved)) runs = saved.filter(validRun).slice(-1000);
    } catch { status.textContent = 'Saved runs could not be loaded. You can still enter and export measurements in this tab.'; }
    function save() {
        try { localStorage.setItem(storageKey, JSON.stringify(runs)); }
        catch { status.textContent = 'Browser storage is unavailable. Export your runs before leaving this tab.'; }
    }
    function average(group, key) {
        const values = group.map(run => run[key]).filter(value => value !== null);
        return values.length ? (values.reduce((sum, value) => sum + value, 0) / values.length).toFixed(2) : '—';
    }
    function render() {
        const tbody = document.getElementById('bench-runs');
        tbody.replaceChildren();
        runs.forEach((run, index) => {
            const tr = document.createElement('tr');
            for (const value of [run.label, run.seconds.toFixed(2), run.fps ?? '—', run.memory ?? '—']) {
                const td = document.createElement('td');
                td.textContent = String(value);
                tr.append(td);
            }
            const td = document.createElement('td');
            const remove = document.createElement('button');
            remove.type = 'button';
            remove.className = 'btn';
            remove.textContent = 'Remove';
            remove.setAttribute('aria-label', `Remove ${run.label} run ${index + 1}`);
            remove.addEventListener('click', () => { runs.splice(index, 1); save(); render(); });
            td.append(remove);
            tr.append(td);
            tbody.append(tr);
        });
        const summary = document.getElementById('bench-summary');
        summary.replaceChildren();
        const groups = new Map();
        for (const run of runs) {
            if (!groups.has(run.label)) groups.set(run.label, []);
            groups.get(run.label).push(run);
        }
        for (const [label, group] of groups) {
            const article = document.createElement('article');
            article.className = 'info-card';
            const heading = document.createElement('h2');
            heading.textContent = label;
            const detail = document.createElement('p');
            detail.textContent = `${group.length} run${group.length === 1 ? '' : 's'} · Average launch: ${average(group, 'seconds')} s · FPS: ${average(group, 'fps')} · Peak memory: ${average(group, 'memory')} MB`;
            article.append(heading, detail);
            summary.append(article);
        }
        if (!runs.length) {
            const empty = document.createElement('p');
            empty.className = 'muted';
            empty.textContent = 'Add a run to start comparing setups.';
            summary.append(empty);
        }
        document.getElementById('bench-export').disabled = !runs.length;
        document.getElementById('bench-clear').disabled = !runs.length;
    }
    benchForm.addEventListener('submit', event => {
        event.preventDefault();
        if (runs.length >= 1000) { status.textContent = 'Export or remove some runs before adding more. This notebook holds up to 1,000 runs.'; return; }
        const data = new FormData(benchForm);
        const label = String(data.get('profile')).trim();
        const optional = key => data.get(key) === '' ? null : Number(data.get(key));
        const run = { label, seconds: Number(data.get('seconds')), fps: optional('fps'), memory: optional('memory') };
        if (!validRun(run)) { status.textContent = 'Enter a setup name and valid measurements.'; return; }
        runs.push(run);
        status.textContent = 'Measured run added.';
        save();
        render();
    });
    document.getElementById('bench-clear').addEventListener('click', () => {
        runs = [];
        status.textContent = 'All benchmark runs cleared.';
        save();
        render();
    });
    document.getElementById('bench-export').addEventListener('click', () => {
        const cell = value => {
            let text = value === null ? '' : String(value);
            // Prevent a user-entered label from becoming a spreadsheet formula.
            if (/^[\s]*[=+\-@]/.test(text)) text = `'${text}`;
            return `"${text.replaceAll('"', '""')}"`;
        };
        const lines = ['setup,launch_seconds,average_fps,peak_memory_mb', ...runs.map(run => [run.label, run.seconds, run.fps, run.memory].map(cell).join(','))];
        downloadText('wisc-bench.csv', lines.join('\r\n') + '\r\n', 'text/csv;charset=utf-8');
    });
    render();
}
