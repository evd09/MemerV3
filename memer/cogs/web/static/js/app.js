
// Keyboard Shortcut for Search
document.addEventListener('keydown', (e) => {
    if (e.key === '/') {
        const desktopSearch = document.getElementById('search-desktop');
        const mobileSearch = document.getElementById('search-mobile');

        const active = document.activeElement;
        if (active === desktopSearch || active === mobileSearch) return;

        e.preventDefault();

        if (desktopSearch && desktopSearch.offsetParent !== null) {
            desktopSearch.focus();
        } else if (mobileSearch && mobileSearch.offsetParent !== null) {
            mobileSearch.focus();
        }
    }
});

function filterSounds(inputId) {
    const id = inputId || 'search-desktop';
    const input = document.getElementById(id);
    if (!input) return;

    const query = input.value.toLowerCase().trim();

    let filtered = window.SOUNDS_DATA;
    if (query.length > 0) {
        filtered = window.SOUNDS_DATA.filter(s => {
            const nameMatch = s.display_name.toLowerCase().includes(query);
            const tagMatch = s.tags && s.tags.some(t => t.toLowerCase().includes(query));
            return nameMatch || tagMatch;
        });
    }

    if (window.virtualizer) {
        window.virtualizer.setItems(filtered);
    }

    if (id === 'search-desktop') {
        const mobile = document.getElementById('search-mobile');
        if (mobile) mobile.value = input.value;
    } else {
        const desktop = document.getElementById('search-desktop');
        if (desktop) desktop.value = input.value;
    }
}

async function playSound(filename, displayName) {
    const name = displayName || filename;
    try {
        const res = await fetch(`/api/play/${filename}?_=${Date.now()}`);
        if (!res.ok) {
            const txt = await res.text();
            showToast(`❌ Error: ${txt} `);
        }
    } catch (e) {
        console.error(e);
        showToast("❌ Connection failed");
    }
}

let toastTimeout;
function showToast(msg, avatarUrl = null, duration = 3000) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = "toast flex items-center gap-3 bg-zinc-900/90 backdrop-blur-md border border-white/10 px-4 py-3 rounded-xl shadow-2xl min-w-[300px]";

    let iconHtml = '<span class="text-xl">🚀</span>';
    if (avatarUrl) {
        iconHtml = `<img src="${avatarUrl}" class="w-8 h-8 rounded-full border border-white/10">`;
    }

    toast.innerHTML = `
        ${iconHtml}
        <div class="flex-1">
            <p class="text-sm font-medium text-white">${msg}</p>
        </div>
    `;

    container.appendChild(toast);

    requestAnimationFrame(() => toast.classList.add('show'));

    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 400);
    }, duration);
}

// Modal Logic
const modal = document.getElementById('uploadModal');
const modalCard = document.getElementById('uploadCard');

function openUploadModal() {
    modal.classList.remove('hidden');
    void modal.offsetWidth;
    modal.classList.remove('opacity-0');
    modalCard.classList.remove('scale-95');
    modalCard.classList.add('scale-100');
}

function closeUploadModal() {
    modal.classList.add('opacity-0');
    modalCard.classList.remove('scale-100');
    modalCard.classList.add('scale-95');
    setTimeout(() => {
        modal.classList.add('hidden');
    }, 300);
}

if (modal) {
    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeUploadModal();
    });
}

const dropArea = document.getElementById('dropArea');

if (dropArea) {
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropArea.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) { e.preventDefault(); e.stopPropagation(); }

    dropArea.addEventListener('dragover', () => {
        dropArea.classList.add('border-indigo-500', 'bg-indigo-500/10');
    });

    dropArea.addEventListener('dragleave', () => {
        dropArea.classList.remove('border-indigo-500', 'bg-indigo-500/10');
    });

    dropArea.addEventListener('drop', (e) => {
        dropArea.classList.remove('border-indigo-500', 'bg-indigo-500/10');
        handleFiles(e.dataTransfer.files);
    });
}

async function handleFiles(files) {
    if (!files.length) return;

    if (files.length > 5) {
        showToast("❌ Max 5 files at a time!");
        return;
    }

    const formData = new FormData();
    for (let i = 0; i < files.length; i++) {
        formData.append('file', files[i]);
    }

    showToast(`⏳ Uploading ${files.length} file(s)...`);
    try {
        const res = await fetch('/api/upload', { method: 'POST', body: formData });
        if (res.ok) {
            const txt = await res.text();
            showToast(`✅ ${txt} Reloading...`);
            setTimeout(() => location.reload(), 1500);
        } else {
            const txt = await res.text();
            showToast("❌ " + txt);
        }
    } catch (e) {
        showToast("❌ Upload failed");
    }
}

// Edit/Rename/Image Logic
const editModal = document.getElementById('editModal');
const editCard = document.getElementById('editCard');
const editNameInput = document.getElementById('editNameInput');
const editFilename = document.getElementById('editFilename');
const editImagePreview = document.getElementById('editImagePreview');
const editImagePlaceholder = document.getElementById('editImagePlaceholder');
const editImageInput = document.getElementById('editImageInput');

const editTagsInput = document.getElementById('editTagsInput');
const editShortcutInput = document.getElementById('editShortcutInput');

function openEditModal(filename, currentName, imageUrl, tags, shortcut) {
    editFilename.value = filename;
    editNameInput.value = currentName;
    editTagsInput.value = tags || "";
    editShortcutInput.value = shortcut || "";

    if (imageUrl) {
        editImagePreview.src = imageUrl;
        editImagePreview.classList.remove('hidden');
        editImagePlaceholder.classList.add('hidden');
    } else {
        editImagePreview.src = "";
        editImagePreview.classList.add('hidden');
        editImagePlaceholder.classList.remove('hidden');
    }

    editImageInput.value = "";

    editModal.classList.remove('hidden');
    void editModal.offsetWidth;
    editModal.classList.remove('opacity-0');
    editCard.classList.remove('scale-95');
    editCard.classList.add('scale-100');

    editNameInput.focus();
}

function closeEditModal() {
    editModal.classList.add('opacity-0');
    editCard.classList.remove('scale-100');
    editCard.classList.add('scale-95');
    setTimeout(() => {
        editModal.classList.add('hidden');
    }, 300);
}

function handleImagePreview(input) {
    if (input.files && input.files[0]) {
        const reader = new FileReader();
        reader.onload = function (e) {
            editImagePreview.src = e.target.result;
            editImagePreview.classList.remove('hidden');
            editImagePlaceholder.classList.add('hidden');
        }
        reader.readAsDataURL(input.files[0]);
    }
}

async function submitEdit() {
    const filename = editFilename.value;
    const newName = editNameInput.value;
    const tags = editTagsInput.value.split(',').map(t => t.trim()).filter(t => t);
    const shortcut = editShortcutInput.value.trim().toUpperCase().charAt(0);
    const imageFile = editImageInput.files[0];

    if (!newName.trim()) return;

    showToast("💾 Saving...");

    try {
        await fetch('/api/sound/rename', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename, new_name: newName, tags: tags, shortcut_key: shortcut })
        });

        if (imageFile) {
            const formData = new FormData();
            formData.append('filename', filename);
            formData.append('file', imageFile);
            await fetch('/api/sound/image', { method: 'POST', body: formData });
        }

        showToast("✅ Updated! Reloading...");
        setTimeout(() => location.reload(), 500);
    } catch (e) {
        showToast("❌ Error saving changes");
    }
}

async function toggleFavorite(btn, filename) {
    try {
        const res = await fetch('/api/sound/favorite', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename })
        });
        if (!res.ok) throw await res.text();
        const data = await res.json();

        const soundIndex = window.SOUNDS_DATA.findIndex(s => s.filename === filename);
        const isAdded = (data.action === 'added');

        if (soundIndex !== -1) {
            window.SOUNDS_DATA[soundIndex].is_favorite = isAdded;
        }

        if (!window.USER_FAVS) window.USER_FAVS = [];
        if (isAdded) {
            if (!window.USER_FAVS.includes(filename)) window.USER_FAVS.push(filename);
        } else {
            const favIdx = window.USER_FAVS.indexOf(filename);
            if (favIdx !== -1) window.USER_FAVS.splice(favIdx, 1);
        }

        window.SOUNDS_DATA.sort((a, b) => {
            if (a.is_favorite === b.is_favorite) {
                return a.display_name.localeCompare(b.display_name);
            }
            return a.is_favorite ? -1 : 1;
        });

        const searchInput = document.getElementById('search-desktop');
        if (searchInput && searchInput.value.trim() !== "") {
            filterSounds(searchInput.id);
        } else {
            if (window.virtualizer) {
                window.virtualizer.setItems(window.SOUNDS_DATA);
            }
        }

        showToast(data.action === 'added' ? "Added to favorites" : "Removed from favorites", null, 1000);

    } catch (e) {
        console.error(e);
        showToast("❌ Failed to toggle favorite");
    }
}

// Global Key Listener for Shortcuts
document.addEventListener('keydown', (e) => {
    if (['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) return;
    if (e.ctrlKey || e.altKey || e.metaKey) return;

    const key = e.key.toUpperCase();
    if (key.length !== 1) return;

    const editBtn = document.querySelector(`button[onclick*="'${key}')"]`) ||
        // Fallback to data attribute scan if possible, or iterate sounds
        // Actually the edit button had data-shortcut?
        // Original code: Button with data-shortcut.
        document.querySelector(`button[data-shortcut="${key}"]`);

    // Wait, the edit button markup in renderCard doesn't seem to have data-shortcut explicitly added?
    // Let's check renderCard markup in app.js

    // I need to make sure renderCard adds data-shortcut if I rely on it.
    // The original code had: const editBtn = document.querySelector(`button[data - shortcut= "${key}"]`);
    // But I don't see where I added that attribute in the markup I copied.
    // Let's fix renderCard to add it.
});


// --- Drag & Drop ---
function drag(ev) {
    ev.dataTransfer.setData("text", ev.target.dataset.filename);
    ev.dataTransfer.setData("name", ev.target.dataset.displayname);
}

// --- Virtual Scroller & Card Rendering ---
class GridVirtualizer {
    constructor(containerId, spacerId, gridId, items, renderItemFn, options = {}) {
        this.container = document.getElementById(containerId);
        this.spacer = document.getElementById(spacerId);
        this.grid = document.getElementById(gridId);
        this.items = items;
        this.renderItem = renderItemFn;

        this.options = Object.assign({
            itemMinHeight: 180,
            gap: 12,
            buffer: 15,  // Reduced buffer for better performance
        }, options);

        // Track rendered range to avoid unnecessary re-renders
        this.lastStartIndex = -1;
        this.lastEndIndex = -1;
        this.renderedElements = new Map(); // Cache DOM elements by item index

        // Debounce tracking
        this.rafPending = false;
        this.lastRenderTime = 0;

        this.onScroll = this.onScroll.bind(this);
        this.onResize = this.onResize.bind(this);

        // Listen to container scroll AND window scroll for robustness
        if (this.container) {
            this.container.addEventListener('scroll', this.onScroll, { passive: true });
        }
        window.addEventListener('scroll', this.onScroll, { passive: true });
        window.addEventListener('resize', this.onResize);

        this.init();
    }

    init() {
        this.calculateLayout();
        this.render();
    }

    calculateLayout() {
        if (!this.grid) return;
        // Use container width or window width fallback
        const width = this.grid.clientWidth || (this.container ? this.container.clientWidth : window.innerWidth);
        const w = window.innerWidth;
        if (w >= 1280) this.cols = 8;
        else if (w >= 1024) this.cols = 6;
        else if (w >= 768) this.cols = 4;
        else if (w >= 640) this.cols = 3;
        else this.cols = 2;

        this.rowHeight = (width - (this.cols - 1) * this.options.gap) / this.cols;
        this.totalRows = Math.ceil(this.items.length / this.cols);
        this.spacer.style.height = `${this.totalRows * (this.rowHeight + this.options.gap) + 400}px`;
    }

    onResize() {
        // Clear cache on resize since layout changes
        this.renderedElements.clear();
        this.lastStartIndex = -1;
        this.lastEndIndex = -1;
        this.calculateLayout();
        this.render();
    }

    onScroll() {
        // Throttle scroll events using RAF
        if (!this.rafPending) {
            this.rafPending = true;
            requestAnimationFrame(() => {
                // Additional throttling: max 60fps (16ms)
                const now = performance.now();
                if (now - this.lastRenderTime >= 16) {
                    this.render();
                    this.lastRenderTime = now;
                }
                this.rafPending = false;
            });
        }
    }

    render() {
        if (!this.container) return;

        // Robust scroll position detection
        const scrollTop = Math.max(this.container.scrollTop || 0, window.scrollY || 0);
        const viewHeight = this.container.clientHeight || window.innerHeight;

        const relativeScroll = scrollTop;

        const startRow = Math.max(0, Math.floor(relativeScroll / (this.rowHeight + this.options.gap)) - this.options.buffer);
        const endRow = Math.min(this.totalRows, Math.ceil((relativeScroll + viewHeight) / (this.rowHeight + this.options.gap)) + this.options.buffer);

        const startIndex = startRow * this.cols;
        const endIndex = Math.min(this.items.length, endRow * this.cols);

        // Smart update: only re-render if visible range changed significantly
        if (startIndex === this.lastStartIndex && endIndex === this.lastEndIndex) {
            return; // No change in visible range
        }

        this.lastStartIndex = startIndex;
        this.lastEndIndex = endIndex;

        // Update transform for positioning
        this.grid.style.transform = `translateY(${startRow * (this.rowHeight + this.options.gap)}px)`;

        // Smart DOM update: reuse existing elements when possible
        const currentChildren = Array.from(this.grid.children);
        const neededFilenames = new Set();
        const elementsToKeep = new Map();

        // Build set of files we need and map of existing elements
        for (let i = startIndex; i < endIndex; i++) {
            const item = this.items[i];
            neededFilenames.add(item.filename);

            // Find existing element if present
            const existing = currentChildren.find(child => child.dataset.filename === item.filename);
            if (existing) {
                elementsToKeep.set(item.filename, existing);
            }
        }

        // Remove only elements that are no longer in visible range
        currentChildren.forEach(child => {
            if (!neededFilenames.has(child.dataset.filename)) {
                child.remove();
            }
        });

        // Build ordered list and add missing elements
        const fragment = document.createDocumentFragment();
        for (let i = startIndex; i < endIndex; i++) {
            const item = this.items[i];

            let el = elementsToKeep.get(item.filename);
            if (!el) {
                // Create new element only if it doesn't exist
                el = this.renderItem(item);
            }

            fragment.appendChild(el);  // appendChild moves existing elements
        }

        // Append fragment (existing elements are reordered, not duplicated)
        this.grid.appendChild(fragment);
    }

    setItems(newItems) {
        this.items = newItems;
        this.renderedElements.clear();
        this.lastStartIndex = -1;
        this.lastEndIndex = -1;
        this.calculateLayout();
        this.render();
    }
}

let activePlayingFilename = null;

function renderCard(sound) {
    const div = document.createElement('div');
    const hasImage = !!sound.image_url;
    const isFav = (window.USER_FAVS || []).includes(sound.filename);
    const isPlaying = activePlayingFilename === sound.filename;
    const extraClass = isPlaying ? "party-pulse" : "";

    div.className = `group relative aspect-square bg-zinc-900/50 backdrop-blur-sm border border-white/5 rounded-2xl cursor-pointer card-hover transition-all duration-200 select-none active:scale-95 active:bg-indigo-600/20 touch-manipulation overflow-hidden glass-card ${extraClass}`;
    div.draggable = true;
    div.ondragstart = drag;
    div.dataset.filename = sound.filename;
    div.dataset.displayname = sound.display_name;

    div.innerHTML = `
         ${hasImage ?
            `<img src="${sound.image_url}" class="absolute inset-0 w-full h-full object-cover opacity-60 group-hover:opacity-40 transition-opacity duration-300 pointer-events-none" loading="lazy" decoding="async">`
            :
            `<div class="absolute inset-0 w-full h-full flex items-center justify-center pointer-events-none opacity-20 group-hover:opacity-30 transition-opacity">
                <span class="text-6xl">🎵</span>
             </div>`
        }
         <div class="absolute inset-0 bg-gradient-to-t from-black/90 via-black/40 to-transparent pointer-events-none"></div>
         
         <div class="absolute inset-0 flex items-center justify-center z-20 opacity-100 lg:opacity-0 lg:group-hover:opacity-100 transition-opacity duration-200 pointer-events-none">
            <button onclick="event.stopPropagation(); playSound('${sound.filename}', '${(sound.display_name || '').replace(/'/g, "\\'")}')"
                class="w-12 h-12 bg-white/20 hover:bg-green-500 text-white rounded-full backdrop-blur-md flex items-center justify-center shadow-lg transform active:scale-95 transition-all pointer-events-auto">
                <svg xmlns="http://www.w3.org/2000/svg" class="w-6 h-6 fill-current" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
            </button>
         </div>
         
         <div class="absolute bottom-0 inset-x-0 p-3 flex flex-col gap-1 z-10 pointer-events-none">
             <div class="flex items-center justify-between w-full">
                 <span class="font-bold text-white text-sm leading-tight text-shadow-sm neon-text break-words pr-2">${sound.display_name}</span>
             </div>
             <div class="flex gap-1 flex-wrap">
                 ${(sound.tags || []).slice(0, 3).map(t => `<span class="text-[10px] bg-white/10 px-1.5 py-0.5 rounded text-zinc-300 backdrop-blur-md">${t}</span>`).join('')}
             </div>
         </div>

         <button onclick="event.stopPropagation(); toggleFavorite(this, '${sound.filename}')" 
                 class="absolute top-2 left-2 p-1.5 rounded-full backdrop-blur-md z-20 pointer-events-auto transition ${isFav ? 'bg-red-500/20 text-red-500 opacity-100' : 'bg-black/40 text-white/30 lg:hover:text-red-400 opacity-100 lg:opacity-0 lg:group-hover:opacity-100'}"
                 data-fav="${isFav}">
             <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4 fill-current" viewBox="0 0 24 24"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>
         </button>

         <button class="absolute top-2 right-2 p-1.5 bg-black/40 hover:bg-black/60 rounded-full text-white/50 hover:text-white opacity-100 lg:opacity-0 lg:group-hover:opacity-100 transition-opacity z-20 pointer-events-auto"
            data-shortcut="${sound.shortcut || ''}"
            onclick="event.stopPropagation(); openEditModal('${sound.filename}', '${(sound.display_name || '').replace(/'/g, "\\'")}', '${sound.image_url || ''}', '${(sound.tags || []).join(',')}', '${sound.shortcut || ''}')">
            <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" /></svg>
         </button>
     `;
    return div;
}

// Global Key Listener for Shortcuts (Revised)
document.addEventListener('keydown', (e) => {
    if (['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) return;
    if (e.ctrlKey || e.altKey || e.metaKey) return;

    const key = e.key.toUpperCase();
    if (key.length !== 1) return;

    const editBtn = document.querySelector(`button[data-shortcut="${key}"]`);
    if (editBtn) {
        // Find the play button in the same group
        const card = editBtn.closest('.group');
        if (card) {
            const playBtn = card.querySelector('button[onclick*="playSound"]'); // bit hacky
            // Better: trigger playSound directly from card dataset
            const filename = card.dataset.filename;
            const displayname = card.dataset.displayname;

            playSound(filename, displayname);

            card.classList.add('playing-glow');
            setTimeout(() => card.classList.remove('playing-glow'), 200);
        }
    }
});


// WebSocket Client
const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const wsUrl = `${protocol}//${window.location.host}/ws`;
let ws;

function connectWs() {
    ws = new WebSocket(wsUrl);
    ws.onopen = () => console.log('✅ WS Connected');
    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'play_start') {
                highlightCard(msg.data.filename);

                const soundName = document.querySelector(`div[data-filename="${msg.data.filename}"]`)?.dataset?.displayname || msg.data.filename;
                if (msg.data.user_name) {
                    showToast(`${msg.data.user_name} played ${soundName}`, msg.data.user_avatar);
                }
            } else if (msg.type === 'play_end') {
                unhighlightAll();
            } else if (msg.type === 'ticker_update') {
                if (msg.data.filename) {
                    const sound = window.SOUNDS_DATA.find(s => s.filename === msg.data.filename);
                    if (sound) {
                        sound.play_count = (sound.play_count || 0) + 1;
                    }
                }
                if (msg.data.message) {
                    queueTickerMessage(msg.data.message);
                }
            }
        } catch (e) { console.error(e); }
    };
    ws.onclose = () => setTimeout(connectWs, 3000);
}
connectWs();

// Ticker
const tickerContent = document.getElementById('ticker-content');
let tickerQueue = [];
let tickerState = -1;
const BASE_MSG = `<span class="inline-block px-4 font-mono text-xs text-green-400">● LIVE</span> Connected to MemeBoard V3.2.1`;
const TICKER_SPEED_PIXELS_PER_SEC = window.TICKER_SPEED || 80;

function queueTickerMessage(text) {
    tickerQueue.push(text);
}

function getNextTickerHtml() {
    if (tickerQueue.length > 0) {
        const msg = tickerQueue.shift();
        return `<span class="inline-block px-4 font-mono text-xs text-orange-400">🔥 EVENT</span> ${msg}`;
    }

    tickerState = (tickerState + 1) % 3;

    if (tickerState === 0) {
        return BASE_MSG;
    } else if (tickerState === 1) {
        const top = [...window.SOUNDS_DATA].sort((a, b) => (b.play_count || 0) - (a.play_count || 0))[0];
        if (top && (top.play_count || 0) > 0) {
            return `<span class="inline-block px-4 font-mono text-xs text-yellow-500">🏆 TOP SOUND</span> ${top.display_name} (${top.play_count} plays)`;
        } else {
            tickerState = 2;
        }
    }

    if (tickerState === 2) {
        return `<span class="inline-block px-4 font-mono text-xs text-blue-400">💾 LIBRARY</span> ${window.SOUNDS_DATA.length} Sounds Available`;
    }
    return BASE_MSG;
}

function runTicker() {
    if (!tickerContent) return;

    const html = getNextTickerHtml();
    tickerContent.innerHTML = html;

    tickerContent.style.animation = 'none';
    tickerContent.offsetHeight;

    const totalWidth = tickerContent.scrollWidth;
    const distance = Math.max(totalWidth, window.innerWidth);
    const duration = distance / TICKER_SPEED_PIXELS_PER_SEC;

    tickerContent.style.animation = `ticker-slide ${duration}s linear forwards`;

    tickerContent.onanimationend = () => {
        tickerContent.onanimationend = null;
        runTicker();
    };
}

setTimeout(runTicker, 100);


function highlightCard(filename) {
    unhighlightAll();
    activePlayingFilename = filename;
    const card = document.querySelector(`div[data-filename="${filename}"]`);
    if (card) {
        card.classList.add('party-pulse');
    }
}

function unhighlightAll() {
    activePlayingFilename = null;
    document.querySelectorAll('.party-pulse').forEach(el => el.classList.remove('party-pulse'));
}

document.addEventListener('DOMContentLoaded', () => {
    window.intersectionObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const canvas = entry.target;
                const filename = canvas.dataset.filename;
                if (!canvas.dataset.loaded) {
                    loadWaveform(filename, canvas);
                    canvas.dataset.loaded = "true";
                    window.intersectionObserver.unobserve(canvas);
                }
            }
        });
    }, { rootMargin: "50px" });

    if (window.SOUNDS_DATA && window.SOUNDS_DATA.length > 0) {


        window.virtualizer = new GridVirtualizer(
            'virtual-scroller-container',
            'virtual-spacer',
            'virtual-grid',
            window.SOUNDS_DATA,
            renderCard
        );


    } else {
        const grid = document.getElementById('virtual-grid');
        if (grid) grid.innerHTML = '<div class="col-span-full text-center text-zinc-500 py-10">No sounds found. Upload one!</div>';
    }
});

const audioCtx = new (window.AudioContext || window.webkitAudioContext)();

async function loadWaveform(filename, canvas) {
    try {
        const url = `/sounds/${filename}`;
        const response = await fetch(url);
        const arrayBuffer = await response.arrayBuffer();
        const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);
        drawWaveform(audioBuffer, canvas);
    } catch (e) {
        // console.warn("Waveform failed", filename, e);
    }
}

function drawWaveform(audioBuffer, canvas) {
    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;
    const data = audioBuffer.getChannelData(0);
    const step = Math.ceil(data.length / width);
    const amp = height / 2;

    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "rgba(255, 255, 255, 0.6)";
    ctx.beginPath();

    for (let i = 0; i < width; i++) {
        let min = 1.0;
        let max = -1.0;
        for (let j = 0; j < step; j++) {
            const datum = data[(i * step) + j];
            if (datum < min) min = datum;
            if (datum > max) max = datum;
        }

        ctx.fillRect(i, (1 + min) * amp, 1, Math.max(1, (max - min) * amp));
    }
}

// DJ Queue
let audioQueue = [];

function toggleQueue() {
    const sb = document.getElementById('queue-sidebar');
    sb.classList.toggle('translate-x-full');
}

function addToQueue(filename, displayName) {
    audioQueue.push({ filename, displayName });
    updateQueueUI();
    showToast(`Added ${displayName || filename} to queue!`, null, 1500);

    const sb = document.getElementById('queue-sidebar');
    if (sb.classList.contains('translate-x-full')) toggleQueue();
}

function removeFromQueue(index) {
    audioQueue.splice(index, 1);
    updateQueueUI();
}

function clearQueue() {
    audioQueue = [];
    updateQueueUI();
}

function updateQueueUI() {
    const list = document.getElementById('queue-list');
    if (audioQueue.length === 0) {
        list.innerHTML = `
            <div class="text-center text-zinc-500 mt-10 text-sm">
                <p>Queue is empty</p>
                <p class="text-xs mt-2 opacity-60">Drag sounds here</p>
            </div>`;
        return;
    }

    list.innerHTML = audioQueue.map((item, idx) => `
        <div class="flex items-center justify-between bg-black/40 p-3 rounded-lg border border-white/5 group transition hover:bg-white/5">
            <div class="flex items-center gap-3 overflow-hidden">
                <span class="text-xs text-white/40 font-mono">${idx + 1}.</span>
                <span class="text-sm font-medium text-white truncate">${item.displayName || item.filename}</span>
            </div>
            <button onclick="removeFromQueue(${idx})" class="text-zinc-500 hover:text-red-400 opacity-0 group-hover:opacity-100 transition">✕</button>
        </div>
    `).join('');
}

async function playQueue() {
    if (audioQueue.length === 0) return;
    for (const item of audioQueue) {
        playSound(item.filename);
        await new Promise(r => setTimeout(r, 300));
    }
}

function allowDrop(ev) {
    ev.preventDefault();
}

function drop(ev) {
    ev.preventDefault();
    const filename = ev.dataTransfer.getData("text");
    const name = ev.dataTransfer.getData("name");
    if (filename) addToQueue(filename, name);
}

const sidebar = document.getElementById('queue-sidebar');
if (sidebar) {
    sidebar.addEventListener('dragover', allowDrop);
    sidebar.addEventListener('drop', drop);
}

// Sidebar Picker logic
function toggleSoundPicker() {
    const picker = document.getElementById('sidebar-picker');
    picker.classList.toggle('hidden');
    picker.classList.toggle('flex');

    if (!picker.classList.contains('hidden')) {
        populatePicker(window.SOUNDS_DATA);
        document.getElementById('picker-search').focus();
    }
}

function populatePicker(items) {
    const list = document.getElementById('picker-list');
    list.scrollTop = 0;

    list.innerHTML = items.slice(0, 50).map(s => `
    <button onclick="addToQueue('${s.filename}', '${(s.display_name).replace(/'/g, "\\'")}')" 
        class="w-full text-left px-2 py-1.5 hover:bg-white/10 rounded flex items-center gap-2 group">
        <span class="text-xs text-zinc-300 truncate flex-1">${s.display_name}</span>
        <span class="text-[10px] text-green-400 opacity-0 group-hover:opacity-100">+</span>
    </button>
`).join('');
}

function filterPicker() {
    const query = document.getElementById('picker-search').value.toLowerCase();
    const filtered = window.SOUNDS_DATA.filter(s => s.display_name.toLowerCase().includes(query) || (s.tags && s.tags.some(t => t.toLowerCase().includes(query))));
    populatePicker(filtered);
}

document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
        localStorage.setItem("lastVisibleTime", Date.now());
    } else {
        const lastVisible = localStorage.getItem("lastVisibleTime");
        if (lastVisible) {
            const elapsed = Date.now() - parseInt(lastVisible, 10);
            if (elapsed > 60000) {
                console.log("App was backgrounded for > 60s. Auto-refreshing...");
                window.location.reload();
            }
        }
    }
});
