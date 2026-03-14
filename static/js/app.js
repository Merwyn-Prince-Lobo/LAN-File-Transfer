// app.js - frontend logic for LAN Transfer
// nothing too fancy, just fetch calls and dom stuff

// selected file + peer tracking
let selectedFile = null;
let selectedPeer = null;

// ---- Peer discovery (poll every 3s) ----

async function loadPeers() {
    try {
        const res = await fetch("/peers");
        const data = await res.json();
        renderPeers(data.peers);
    } catch (e) {
        console.log("Couldn't load peers:", e); // network error probably
    }
}

function renderPeers(peers) {
    const list = document.getElementById("peers-list");
    const count = document.getElementById("peer-count");
    const select = document.getElementById("target-select");

    count.textContent = peers.length;

    if (peers.length === 0) {
        list.innerHTML = '<div class="empty-state">No peers found. Are they running the app?</div>';
        select.innerHTML = '<option value="">-- no peers found --</option>';
        selectedPeer = null;
        updateSendBtn();
        return;
    }

    // Rebuild peer list
    list.innerHTML = "";
    select.innerHTML = '<option value="">-- select a peer --</option>';

    for (const peer of peers) {
        // Peer card
        const div = document.createElement("div");
        div.className = "peer-item" + (selectedPeer?.ip === peer.ip ? " selected" : "");
        div.innerHTML = `
            <div class="peer-dot"></div>
            <div>
                <div class="peer-name">${escapeHtml(peer.name)}</div>
                <div class="peer-ip">${peer.ip}:${peer.port}</div>
            </div>
        `;
        div.onclick = () => selectPeer(peer, div);
        list.appendChild(div);

        // Dropdown option
        const opt = document.createElement("option");
        opt.value = peer.ip;
        opt.dataset.port = peer.port;
        opt.textContent = `${peer.name} (${peer.ip})`;
        if (selectedPeer?.ip === peer.ip) opt.selected = true;
        select.appendChild(opt);
    }
}

function selectPeer(peer, element) {
    // Deselect old
    document.querySelectorAll(".peer-item").forEach(el => el.classList.remove("selected"));
    element.classList.add("selected");

    selectedPeer = peer;

    // Also update the dropdown
    const select = document.getElementById("target-select");
    select.value = peer.ip;

    updateSendBtn();
}

// Also handle dropdown change (user might use that instead of clicking cards)
document.getElementById("target-select")?.addEventListener("change", function () {
    const ip = this.value;
    const port = this.options[this.selectedIndex]?.dataset.port;
    if (ip) {
        selectedPeer = { ip, port };
        // Highlight matching card
        document.querySelectorAll(".peer-item").forEach(el => {
            el.classList.toggle("selected", el.querySelector(".peer-ip")?.textContent.startsWith(ip));
        });
    } else {
        selectedPeer = null;
    }
    updateSendBtn();
});

// ---- File selection ----

const dropZone = document.getElementById("drop-zone");
const fileInput = document.getElementById("file-input");

dropZone?.addEventListener("click", () => fileInput.click());

dropZone?.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
});

dropZone?.addEventListener("dragleave", () => {
    dropZone.classList.remove("dragover");
});

dropZone?.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    const file = e.dataTransfer.files[0];
    if (file) setFile(file);
});

fileInput?.addEventListener("change", () => {
    if (fileInput.files[0]) setFile(fileInput.files[0]);
});

function setFile(file) {
    selectedFile = file;
    document.getElementById("file-name").textContent = file.name;
    document.getElementById("file-size").textContent = formatBytes(file.size);
    document.getElementById("selected-file").classList.remove("hidden");
    updateSendBtn();
}

function updateSendBtn() {
    const btn = document.getElementById("send-btn");
    if (btn) btn.disabled = !(selectedFile && selectedPeer);
}

// ---- Sending ----

document.getElementById("send-btn")?.addEventListener("click", async () => {
    if (!selectedFile || !selectedPeer) return;

    const btn = document.getElementById("send-btn");
    const progressContainer = document.getElementById("progress-container");
    const progressFill = document.getElementById("progress-fill");
    const progressText = document.getElementById("progress-text");
    const progressPercent = document.getElementById("progress-percent");
    const statusDiv = document.getElementById("send-status");

    btn.disabled = true;
    statusDiv.classList.add("hidden");
    progressContainer.classList.remove("hidden");

    // Fake progress because XHR upload progress doesn't show encryption time well
    // encryption is fast but transfer takes time - fake steps look better honestly
    progressText.textContent = "Encrypting file...";
    progressFill.style.width = "10%";
    progressPercent.textContent = "10%";

    const formData = new FormData();
    formData.append("file", selectedFile);
    formData.append("target_ip", selectedPeer.ip);
    formData.append("target_port", selectedPeer.port || 5000);

    try {
        // Use XMLHttpRequest so we can track upload progress
        const xhr = new XMLHttpRequest();

        xhr.upload.onprogress = (e) => {
            if (e.lengthComputable) {
                // Map upload progress to 20%-95% range (0-20 = encryption, 95-100 = peer side)
                const pct = Math.round(20 + (e.loaded / e.total) * 75);
                progressFill.style.width = pct + "%";
                progressPercent.textContent = pct + "%";
                progressText.textContent = "Uploading & sending...";
            }
        };

        xhr.onload = () => {
            progressFill.style.width = "100%";
            progressPercent.textContent = "100%";

            const resp = JSON.parse(xhr.responseText);

            setTimeout(() => {
                progressContainer.classList.add("hidden");
                statusDiv.classList.remove("hidden");

                if (xhr.status === 200 && resp.success) {
                    progressText.textContent = "Done!";
                    statusDiv.className = "status-msg success";
                    statusDiv.textContent = `✅ Sent to ${selectedPeer.ip}!`;
                    selectedFile = null;
                    document.getElementById("selected-file").classList.add("hidden");
                    fileInput.value = "";
                    loadFiles(); // refresh received files list
                } else {
                    statusDiv.className = "status-msg error";
                    statusDiv.textContent = `❌ Error: ${resp.error || "Something went wrong"}`;
                }

                btn.disabled = !(selectedFile && selectedPeer);
            }, 500);
        };

        xhr.onerror = () => {
            progressContainer.classList.add("hidden");
            statusDiv.classList.remove("hidden");
            statusDiv.className = "status-msg error";
            statusDiv.textContent = "❌ Network error. Is the peer still up?";
            btn.disabled = false;
        };

        xhr.open("POST", "/send");
        xhr.send(formData);

        // Fake progress jumping to 20% quickly to show encryption happened
        setTimeout(() => {
            progressFill.style.width = "20%";
            progressPercent.textContent = "20%";
            progressText.textContent = "Transferring...";
        }, 300);

    } catch (e) {
        progressContainer.classList.add("hidden");
        statusDiv.classList.remove("hidden");
        statusDiv.className = "status-msg error";
        statusDiv.textContent = `❌ ${e.message}`;
        btn.disabled = false;
    }
});

// ---- Received Files ----

async function loadFiles() {
    try {
        const res = await fetch("/files");
        const data = await res.json();
        renderFiles(data.files);
    } catch (e) {
        console.log("Couldn't load files:", e);
    }
}

function renderFiles(files) {
    const list = document.getElementById("files-list");
    if (!files || files.length === 0) {
        list.innerHTML = '<div class="empty-state">No files received yet</div>';
        return;
    }

    list.innerHTML = "";
    for (const file of files) {
        const div = document.createElement("div");
        div.className = "file-item";
        div.innerHTML = `
            <div class="file-item-left">
                <span class="file-emoji">${getFileEmoji(file.name)}</span>
                <div class="file-info">
                    <div class="file-item-name" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</div>
                    <div class="file-item-meta">${formatBytes(file.size)}</div>
                </div>
            </div>
            <div class="file-actions">
                <a href="/download/${encodeURIComponent(file.name)}" class="btn-icon" title="Download">⬇️</a>
                <button class="btn-icon danger" onclick="deleteFile('${escapeHtml(file.name)}')" title="Delete">🗑️</button>
            </div>
        `;
        list.appendChild(div);
    }
}

async function deleteFile(filename) {
    if (!confirm(`Delete "${filename}"?`)) return;
    try {
        const res = await fetch(`/delete/${encodeURIComponent(filename)}`, { method: "DELETE" });
        const data = await res.json();
        if (data.success) loadFiles();
        else alert("Delete failed: " + data.error);
    } catch (e) {
        alert("Error: " + e.message);
    }
}

// ---- Helpers ----

function formatBytes(bytes) {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}

function getFileEmoji(name) {
    const ext = name.split(".").pop().toLowerCase();
    const map = {
        pdf: "📄", png: "🖼️", jpg: "🖼️", jpeg: "🖼️", gif: "🖼️", webp: "🖼️",
        mp4: "🎬", mkv: "🎬", avi: "🎬", mov: "🎬",
        mp3: "🎵", wav: "🎵", flac: "🎵",
        zip: "📦", rar: "📦", "7z": "📦", tar: "📦",
        py: "🐍", js: "📜", html: "🌐", css: "🎨",
        txt: "📝", md: "📝", docx: "📝", doc: "📝",
        exe: "⚙️", apk: "📱",
        xlsx: "📊", csv: "📊",
    };
    return map[ext] || "📁";
}

function escapeHtml(str) {
    // basic xss prevention, not that anyone on LAN would do that... hopefully
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

// ---- Init ----

loadPeers();
loadFiles();
setInterval(loadPeers, 3000);   // refresh peers every 3s
setInterval(loadFiles, 10000);  // refresh files every 10s

// ---- Manual peer add ----

function toggleManualAdd() {
    const form = document.getElementById("manual-add-form");
    const arrow = document.getElementById("manual-arrow");
    const hidden = form.classList.toggle("hidden");
    arrow.textContent = hidden ? "▼" : "▲";
}

async function addPeerManually() {
    const ip = document.getElementById("manual-ip").value.trim();
    const port = document.getElementById("manual-port").value || "5000";
    const statusDiv = document.getElementById("manual-status");

    if (!ip) {
        statusDiv.className = "status-msg error";
        statusDiv.textContent = "Enter an IP address first";
        statusDiv.classList.remove("hidden");
        return;
    }

    statusDiv.className = "status-msg";
    statusDiv.textContent = `Pinging ${ip}:${port}...`;
    statusDiv.classList.remove("hidden");

    try {
        const res = await fetch("/add_peer", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ip, port: parseInt(port) })
        });
        const data = await res.json();

        if (data.success) {
            statusDiv.className = "status-msg success";
            statusDiv.textContent = `✅ Added ${data.name || ip}!`;
            loadPeers(); // refresh peer list immediately
        } else {
            statusDiv.className = "status-msg error";
            statusDiv.textContent = `❌ ${data.error}`;
        }
    } catch (e) {
        statusDiv.className = "status-msg error";
        statusDiv.textContent = `❌ ${e.message}`;
    }
}
