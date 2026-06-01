function $(id) {
    return document.getElementById(id);
}

function setStatus(el, msg, ok) {
    el.textContent = msg;
    el.className = `status ${ok ? 'ok' : 'err'}`;
}

async function api(path, options) {
    const res = await fetch(path, {
        headers: { 'Content-Type': 'application/json' },
        ...options,
    });

    const text = await res.text();
    let data;
    try {
        data = text ? JSON.parse(text) : null;
    } catch {
        data = { raw: text };
    }

    if (!res.ok) {
        const detail = data?.detail || data?.error || `HTTP ${res.status}`;
        throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }

    return data;
}

function toIsoWithOffset(dayStr, timeStr) {
    // dayStr: YYYY-MM-DD, timeStr: HH:MM
    // Retorna ISO com offset local (ex.: 2026-06-10T10:00:00-03:00)
    const [y, m, d] = dayStr.split('-').map(Number);
    const [hh, mm] = timeStr.split(':').map(Number);
    const dt = new Date(y, m - 1, d, hh, mm, 0);

    const pad = (n) => String(n).padStart(2, '0');
    const yyyy = dt.getFullYear();
    const MM = pad(dt.getMonth() + 1);
    const DD = pad(dt.getDate());
    const HH = pad(dt.getHours());
    const Min = pad(dt.getMinutes());
    const SS = pad(dt.getSeconds());

    const tzMin = dt.getTimezoneOffset(); // minutos para somar ao local e obter UTC
    const sign = tzMin > 0 ? '-' : '+';
    const abs = Math.abs(tzMin);
    const offH = pad(Math.floor(abs / 60));
    const offM = pad(abs % 60);

    return `${yyyy}-${MM}-${DD}T${HH}:${Min}:${SS}${sign}${offH}:${offM}`;
}

async function loadContent() {
    const content = await api('/content');
    $('institutional').textContent = content.institutional_info || '';
    $('rules').textContent = content.rules || '';
    return content;
}

async function loadHealth() {
    const healthEl = $('health');
    const h = await api('/health');
    if (h.ok) {
        healthEl.textContent = `API ok • Banco: ${h.db} (${h.database})`;
    } else {
        healthEl.textContent = `API ok • Banco indisponível: ${h.error}`;
    }
}

async function loadAvailabilityForDay(dayStr) {
    const timeSelect = $('time');
    timeSelect.innerHTML = '';

    if (!dayStr) return;

    const av = await api(`/availability?day=${encodeURIComponent(dayStr)}`);
    const slots = av.slots || [];
    const open = av.open;

    if (!open) {
        const opt = document.createElement('option');
        opt.value = '';
        opt.textContent = 'Museu fechado neste dia';
        timeSelect.appendChild(opt);
        timeSelect.disabled = true;
        return;
    }

    const available = slots.filter((s) => (s.remaining || 0) > 0);
    if (available.length === 0) {
        const opt = document.createElement('option');
        opt.value = '';
        opt.textContent = 'Sem horários disponíveis';
        timeSelect.appendChild(opt);
        timeSelect.disabled = true;
        return;
    }

    for (const s of available) {
        const start = new Date(s.start);
        const hh = String(start.getHours()).padStart(2, '0');
        const mm = String(start.getMinutes()).padStart(2, '0');

        const opt = document.createElement('option');
        opt.value = `${hh}:${mm}`;
        opt.textContent = `${hh}:${mm} (vagas: ${s.remaining})`;
        timeSelect.appendChild(opt);
    }

    timeSelect.disabled = false;
}

async function createAppointment() {
    const statusEl = $('createStatus');
    const outEl = $('createResult');
    outEl.style.display = 'none';

    try {
        setStatus(statusEl, 'Enviando…', true);

        const day = $('day').value;
        const time = $('time').value;
        if (!day || !time) throw new Error('Selecione data e horário.');

        const payload = {
            start: toIsoWithOffset(day, time),
            visitor: {
                name: $('name').value.trim(),
                email: $('email').value.trim(),
                phone: $('phone').value.trim(),
            },
            group: {
                size: Number($('groupSize').value),
                institution: $('institution').value.trim() || null,
                city: $('city').value.trim() || null,
                state: $('state').value.trim().toUpperCase() || null,
            },
            purpose: $('purpose').value.trim(),
            notes: $('notes').value.trim() || null,
            accessibility_needs: $('accessibility').value.trim() || null,
        };

        const created = await api('/appointments', {
            method: 'POST',
            body: JSON.stringify(payload),
        });

        setStatus(statusEl, 'Solicitação registrada com sucesso.', true);
        outEl.style.display = 'block';
        outEl.textContent = JSON.stringify(created, null, 2);

        if (created?.id) {
            $('fbAppointmentId').value = created.id;
        }

        // Atualiza disponibilidade após reservar
        await loadAvailabilityForDay(day);
    } catch (e) {
        setStatus(statusEl, e.message || 'Erro ao criar agendamento.', false);
    }
}

async function sendFeedback() {
    const statusEl = $('fbStatus');
    try {
        setStatus(statusEl, 'Enviando…', true);

        const payload = {
            appointment_id: $('fbAppointmentId').value.trim(),
            rating: Number($('fbRating').value),
            comment: $('fbComment').value.trim() || null,
            suggestions: $('fbSuggestions').value.trim() || null,
        };

        await api('/feedback', {
            method: 'POST',
            body: JSON.stringify(payload),
        });

        setStatus(statusEl, 'Avaliação enviada. Obrigado!', true);
        $('fbComment').value = '';
        $('fbSuggestions').value = '';
    } catch (e) {
        setStatus(statusEl, e.message || 'Erro ao enviar avaliação.', false);
    }
}

async function init() {
    await loadHealth();
    await loadContent();

    const dayEl = $('day');
    const base = new Date();
    base.setDate(base.getDate() + 1); // regra padrão: 1 dia de antecedência
    const yyyy = base.getFullYear();
    const mm = String(base.getMonth() + 1).padStart(2, '0');
    const dd = String(base.getDate()).padStart(2, '0');
    dayEl.value = `${yyyy}-${mm}-${dd}`;

    dayEl.addEventListener('change', async () => {
        try {
            await loadAvailabilityForDay(dayEl.value);
        } catch (e) {
            const timeSelect = $('time');
            timeSelect.innerHTML = '';
            const opt = document.createElement('option');
            opt.value = '';
            opt.textContent = e.message || 'Erro ao carregar horários';
            timeSelect.appendChild(opt);
            timeSelect.disabled = true;
        }
    });

    $('btnCreate').addEventListener('click', (ev) => {
        ev.preventDefault();
        createAppointment();
    });

    $('btnFeedback').addEventListener('click', (ev) => {
        ev.preventDefault();
        sendFeedback();
    });

    await loadAvailabilityForDay(dayEl.value);
}

init().catch((e) => {
    const healthEl = $('health');
    healthEl.textContent = `Erro ao inicializar: ${e.message || e}`;
});
