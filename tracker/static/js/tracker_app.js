/**
 * Apple Design Standard — Habit Application Logic
 * Audio Chime, Precision Stopwatch, Assistant, 24h Timeline & Reminders
 */

// CSRF Token Helper
function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === (name + '=')) {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}
const csrftoken = getCookie('csrftoken');

// --- Apple Synthesized Audio Chimes (Web Audio API) ---
class iOSAudio {
  static playChime(type = 'success') {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();

      if (type === 'success') {
        // Delicate harmonic double ping
        const now = ctx.currentTime;
        [587.33, 880].forEach((freq, idx) => {
          const osc = ctx.createOscillator();
          const gain = ctx.createGain();
          osc.type = 'sine';
          osc.frequency.setValueAtTime(freq, now + idx * 0.07);
          gain.gain.setValueAtTime(0.12, now + idx * 0.07);
          gain.gain.exponentialRampToValueAtTime(0.0001, now + idx * 0.07 + 0.35);
          osc.connect(gain);
          gain.connect(ctx.destination);
          osc.start(now + idx * 0.07);
          osc.stop(now + idx * 0.07 + 0.38);
        });
      } else if (type === 'reminder') {
        // Subtle tri-tone reminder alert
        const now = ctx.currentTime;
        [523.25, 659.25, 783.99].forEach((freq, idx) => {
          const osc = ctx.createOscillator();
          const gain = ctx.createGain();
          osc.type = 'sine';
          osc.frequency.setValueAtTime(freq, now + idx * 0.09);
          gain.gain.setValueAtTime(0.15, now + idx * 0.09);
          gain.gain.exponentialRampToValueAtTime(0.0001, now + idx * 0.09 + 0.45);
          osc.connect(gain);
          gain.connect(ctx.destination);
          osc.start(now + idx * 0.09);
          osc.stop(now + idx * 0.09 + 0.5);
        });
      }
    } catch (e) {
      // Quiet fail if browser restricts audio before user interaction
    }
  }
}

// --- Toast Notification ---
function showiOSToast(message, icon = '✓') {
  let toast = document.getElementById('iosToast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'iosToast';
    toast.className = 'ios-toast';
    document.body.appendChild(toast);
  }
  toast.innerHTML = `<span>${icon}</span> <span>${message}</span>`;
  toast.classList.add('show');
  setTimeout(() => {
    toast.classList.remove('show');
  }, 2600);
}

// --- Precision Stopwatch / Habit Timer with LocalStorage Persistence ---
class HabitTimer {
  constructor() {
    this.seconds = 0;
    this.accumulated = 0;
    this.startTime = null;
    this.timerId = null;
    this.isRunning = false;

    this.display = document.getElementById('timerDigits');
    this.btn = document.getElementById('timerToggleBtn');
    this.resetBtn = document.getElementById('timerResetBtn');
    this.logBtn = document.getElementById('timerLogBtn');
    this.indicator = document.getElementById('timerIndicator');

    if (this.btn) {
      this.btn.addEventListener('click', () => this.toggle());
    }
    if (this.resetBtn) {
      this.resetBtn.addEventListener('click', () => this.reset());
    }
    if (this.logBtn) {
      this.logBtn.addEventListener('click', () => this.logSession());
    }

    this.restoreState();
  }

  saveState() {
    try {
      localStorage.setItem('habit_stopwatch_state', JSON.stringify({
        isRunning: this.isRunning,
        startTime: this.startTime,
        accumulated: this.accumulated
      }));
    } catch (e) {
      console.warn('Could not save stopwatch state', e);
    }
  }

  restoreState() {
    try {
      const saved = localStorage.getItem('habit_stopwatch_state');
      if (saved) {
        const state = JSON.parse(saved);
        this.accumulated = state.accumulated || 0;
        
        if (state.isRunning && state.startTime) {
          this.startTime = state.startTime;
          this.isRunning = true;
          const elapsedSinceStart = Math.floor((Date.now() - this.startTime) / 1000);
          this.seconds = Math.max(0, this.accumulated + elapsedSinceStart);
          this.render();
          
          if (this.btn) this.btn.innerText = 'Pause';
          if (this.indicator) {
            this.indicator.style.background = 'var(--apple-green)';
            this.indicator.style.boxShadow = '0 0 10px var(--apple-green)';
          }

          this.timerId = setInterval(() => {
            const currentElapsed = Math.floor((Date.now() - this.startTime) / 1000);
            this.seconds = Math.max(0, this.accumulated + currentElapsed);
            this.render();
          }, 1000);
        } else if (this.accumulated > 0) {
          this.seconds = this.accumulated;
          this.render();
          if (this.btn) this.btn.innerText = 'Resume';
          if (this.indicator) {
            this.indicator.style.background = 'var(--apple-orange)';
            this.indicator.style.boxShadow = 'none';
          }
        }
      }
    } catch (e) {
      console.warn('Could not restore stopwatch state', e);
    }
  }

  toggle() {
    if (this.isRunning) {
      this.stop();
    } else {
      this.start();
    }
  }

  start() {
    this.isRunning = true;
    this.startTime = Date.now();
    if (this.btn) this.btn.innerText = 'Pause';
    if (this.indicator) {
      this.indicator.style.background = 'var(--apple-green)';
      this.indicator.style.boxShadow = '0 0 10px var(--apple-green)';
    }

    this.saveState();

    if (this.timerId) clearInterval(this.timerId);
    this.timerId = setInterval(() => {
      const currentElapsed = Math.floor((Date.now() - this.startTime) / 1000);
      this.seconds = Math.max(0, this.accumulated + currentElapsed);
      this.render();
    }, 1000);
  }

  stop() {
    if (this.isRunning && this.startTime) {
      const elapsedSinceStart = Math.floor((Date.now() - this.startTime) / 1000);
      this.accumulated += Math.max(0, elapsedSinceStart);
    }
    this.seconds = this.accumulated;
    this.isRunning = false;
    this.startTime = null;

    if (this.btn) this.btn.innerText = 'Resume';
    if (this.indicator) {
      this.indicator.style.background = 'var(--apple-orange)';
      this.indicator.style.boxShadow = 'none';
    }
    clearInterval(this.timerId);
    this.saveState();
  }

  reset() {
    this.isRunning = false;
    this.seconds = 0;
    this.accumulated = 0;
    this.startTime = null;
    clearInterval(this.timerId);

    try {
      localStorage.removeItem('habit_stopwatch_state');
    } catch (e) {}

    if (this.btn) this.btn.innerText = 'Start';
    if (this.indicator) {
      this.indicator.style.background = 'var(--apple-green)';
      this.indicator.style.boxShadow = 'none';
    }
    this.render();
    showiOSToast('Stopwatch reset', '↺');
  }

  render() {
    if (!this.display) return;
    const h = Math.floor(this.seconds / 3600);
    const m = Math.floor((this.seconds % 3600) / 60);
    const s = this.seconds % 60;
    this.display.innerText = `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  }

  logSession() {
    if (this.seconds <= 0) {
      showiOSToast('Start the timer first to record elapsed time', '!');
      return;
    }
    const currentHour = new Date().getHours();
    openLogModal(currentHour, {
      title: 'Timed Focus Session',
      duration_val: this.seconds,
      unit_type: 'seconds',
      notes: `Recorded session: ${this.display.innerText}`
    });
    this.stop();
  }
}

// --- Activity Modal & Multi-Activity Logic ---
let activeHour = 0;
let selectedUnit = 'hours';
let selectedCategory = null;
let selectedEnergy = 4;
let currentSlotActivities = [];

function parseSlotActivities(element) {
  if (!element) return [];
  try {
    const raw = element.getAttribute('data-activities') || element.dataset.activities;
    return raw ? JSON.parse(raw) : [];
  } catch (e) {
    console.warn('Failed to parse slot activities', e);
    return [];
  }
}

function handleHourSlotClick(hour, element, event) {
  const activities = parseSlotActivities(element);
  if (activities.length === 0) {
    openLogModal(hour, { is_new: true }, []);
  } else {
    // Open with first activity selected, plus tabs for others & new
    openLogModal(hour, activities[0], activities);
  }
}

function handleActivityItemClick(hour, actId, element) {
  const activities = parseSlotActivities(element);
  const target = activities.find(a => a.id === actId);
  openLogModal(hour, target || { is_new: true }, activities);
}

function handleAddAnotherActivity(hour, element) {
  const activities = parseSlotActivities(element);
  openLogModal(hour, { is_new: true }, activities);
}

function openLogModal(hour, initialData = {}, allSlotActivities = []) {
  activeHour = hour;
  currentSlotActivities = allSlotActivities || [];

  const modal = document.getElementById('activityModal');
  const modalHourTitle = document.getElementById('modalHourTitle');
  const modalHourInput = document.getElementById('modalHourInput');
  const tabsContainer = document.getElementById('modalActivityTabsContainer');
  const tabsWrapper = document.getElementById('modalActivityTabs');
  const counterSpan = document.getElementById('modalActivitiesCounter');

  const period = hour < 12 ? 'AM' : 'PM';
  const displayH = hour % 12 === 0 ? 12 : hour % 12;
  const formattedHour = `${String(displayH).padStart(2, '0')}:00 ${period}`;

  if (modalHourTitle) modalHourTitle.innerText = `Hour ${formattedHour}`;
  if (modalHourInput) modalHourInput.value = hour;

  // Render Activity Tabs if this slot has existing activities
  if (currentSlotActivities.length > 0 && tabsContainer && tabsWrapper) {
    tabsContainer.style.display = 'block';
    if (counterSpan) {
      counterSpan.innerText = `${currentSlotActivities.length} active`;
    }

    tabsWrapper.innerHTML = '';

    // "+ Add Activity" tab
    const addTab = document.createElement('button');
    addTab.type = 'button';
    addTab.className = `modal-act-tab tab-add-new ${initialData.is_new ? 'active' : ''}`;
    addTab.innerHTML = '+ Add Activity';
    addTab.onclick = () => {
      loadModalActivityData({ is_new: true });
      updateTabsActive(addTab);
    };
    tabsWrapper.appendChild(addTab);

    // Existing activity tabs
    currentSlotActivities.forEach(act => {
      const tab = document.createElement('button');
      tab.type = 'button';
      const isThisActive = !initialData.is_new && initialData.id === act.id;
      tab.className = `modal-act-tab ${isThisActive ? 'active' : ''}`;
      const icon = act.category_icon || '💼';
      const spanTag = act.is_spanning ? ' (Spanned)' : '';
      tab.innerHTML = `<span>${icon}</span> <span>${act.title}${spanTag}</span>`;
      tab.onclick = () => {
        loadModalActivityData(act);
        updateTabsActive(tab);
      };
      tabsWrapper.appendChild(tab);
    });
  } else if (tabsContainer) {
    tabsContainer.style.display = 'none';
  }

  loadModalActivityData(initialData);

  if (modal) modal.classList.add('open');
}

function updateTabsActive(activeEl) {
  document.querySelectorAll('.modal-act-tab').forEach(tab => {
    tab.classList.remove('active');
  });
  if (activeEl) activeEl.classList.add('active');
}

function loadModalActivityData(data = {}) {
  const modalLogIdInput = document.getElementById('modalLogIdInput');
  const titleInput = document.getElementById('modalTitleInput');
  const durationInput = document.getElementById('modalDurationInput');
  const notesInput = document.getElementById('modalNotesInput');
  const deleteBtn = document.getElementById('modalDeleteBtn');
  const submitBtn = document.getElementById('modalSubmitBtn');
  const spannedNotice = document.getElementById('modalSpannedNotice');
  const spannedNoticeText = document.getElementById('modalSpannedNoticeText');

  const isNew = Boolean(data.is_new);
  const logId = isNew ? '' : (data.id || '');

  if (modalLogIdInput) modalLogIdInput.value = logId;
  if (titleInput) titleInput.value = isNew ? '' : (data.title || '');
  if (notesInput) notesInput.value = isNew ? '' : (data.notes || '');

  // Duration
  let durVal = 1;
  if (!isNew && data.duration_val) {
    durVal = parseFloat(data.duration_val) || 1;
  }
  if (durationInput) durationInput.value = durVal;

  setModalUnit(isNew ? 'hours' : (data.unit_type || 'hours'));
  setModalEnergy(isNew ? 4 : (data.energy || 4));

  selectedCategory = isNew ? null : (data.category_id || null);
  document.querySelectorAll('.category-tile').forEach(tile => {
    if (tile.dataset.catId == selectedCategory) {
      tile.classList.add('active');
    } else {
      tile.classList.remove('active');
    }
  });

  // Spanned Banner
  if (spannedNotice) {
    if (!isNew && data.is_spanning) {
      spannedNotice.style.display = 'flex';
      if (spannedNoticeText) {
        spannedNoticeText.innerText = `Multi-hour activity spanning from ${String(data.start_hour).padStart(2, '0')}:00 (${data.time_range || ''})`;
      }
    } else {
      spannedNotice.style.display = 'none';
    }
  }

  // Buttons
  if (submitBtn) {
    submitBtn.innerText = isNew ? 'Add Activity' : (logId ? 'Update Activity' : 'Save');
  }
  if (deleteBtn) {
    if (!isNew && logId) {
      deleteBtn.style.display = 'inline-flex';
      deleteBtn.innerText = 'Delete';
    } else {
      deleteBtn.style.display = 'none';
    }
  }
}

function closeLogModal() {
  const modal = document.getElementById('activityModal');
  if (modal) modal.classList.remove('open');
}

function setModalUnit(unit) {
  selectedUnit = unit;
  document.querySelectorAll('.segmented-option').forEach(opt => {
    if (opt.dataset.unit === unit) {
      opt.classList.add('active');
    } else {
      opt.classList.remove('active');
    }
  });
  const durLabel = document.getElementById('modalDurationLabel');
  if (durLabel) {
    durLabel.innerText = `Duration (${unit.toUpperCase()})`;
  }
}

function setModalEnergy(level) {
  selectedEnergy = level;
  document.querySelectorAll('.energy-dot').forEach(dot => {
    if (parseInt(dot.dataset.level) === level) {
      dot.classList.add('active');
    } else {
      dot.classList.remove('active');
    }
  });
}

// --- Submit Activity Log ---
async function saveActivityLog() {
  const title = document.getElementById('modalTitleInput').value.trim();
  const durationVal = parseFloat(document.getElementById('modalDurationInput').value) || 1;
  const notes = document.getElementById('modalNotesInput').value.trim();
  const dateStr = document.getElementById('currentDateStr') ? document.getElementById('currentDateStr').value : '';
  const logIdVal = document.getElementById('modalLogIdInput') ? document.getElementById('modalLogIdInput').value : '';

  const payload = {
    log_id: logIdVal ? parseInt(logIdVal) : null,
    date: dateStr,
    hour: activeHour,
    title: title,
    category_id: selectedCategory,
    unit_type: selectedUnit,
    duration_value: durationVal,
    notes: notes,
    energy_level: selectedEnergy
  };

  try {
    const res = await fetch('/api/log-hour/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrftoken
      },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.status === 'success') {
      iOSAudio.playChime('success');

      // 1. Calculate duration span for animated cascade
      let spanHours = 1;
      if (data.log && data.log.duration_seconds) {
        spanHours = Math.max(1, Math.ceil(data.log.duration_seconds / 3600.0));
      }

      // 2. Persist post-log animation event in sessionStorage
      try {
        sessionStorage.setItem('apple_post_log_event', JSON.stringify({
          hour: activeHour,
          span_hours: spanHours,
          title: data.log ? data.log.title : title,
          category_color: (data.log && data.log.category_color) ? data.log.category_color : '#0071E3'
        }));
      } catch (e) {}

      // 3. Apple tactile button feedback
      const submitBtn = document.getElementById('modalSubmitBtn');
      if (submitBtn) {
        submitBtn.innerHTML = '✓ Saved';
        submitBtn.style.background = 'var(--apple-green)';
        submitBtn.style.transform = 'scale(0.96)';
      }

      // 4. Modal smooth spring dismiss
      const modal = document.getElementById('activityModal');
      if (modal) {
        modal.classList.add('dismissing');
      }

      setTimeout(() => {
        window.location.reload();
      }, 260);
    }
  } catch (err) {
    console.error('Error logging hour:', err);
    showiOSToast('Error saving log', '✕');
  }
}

// --- Delete Activity Log ---
async function deleteActivityLog() {
  const dateStr = document.getElementById('currentDateStr') ? document.getElementById('currentDateStr').value : '';
  const logIdVal = document.getElementById('modalLogIdInput') ? document.getElementById('modalLogIdInput').value : '';

  if (!confirm(logIdVal ? 'Delete this activity entry?' : 'Clear activity for this hour?')) return;

  try {
    const res = await fetch('/api/delete-hour/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrftoken
      },
      body: JSON.stringify({
        date: dateStr,
        hour: activeHour,
        log_id: logIdVal ? parseInt(logIdVal) : null
      })
    });
    const data = await res.json();
    if (data.status === 'success') {
      try {
        sessionStorage.setItem('apple_post_delete_event', JSON.stringify({ hour: activeHour }));
      } catch (e) {}

      const modal = document.getElementById('activityModal');
      if (modal) {
        modal.classList.add('dismissing');
      }
      setTimeout(() => {
        window.location.reload();
      }, 220);
    }
  } catch (err) {
    console.error('Error deleting hour:', err);
  }
}

// --- Motivational Quotes Engine ---
async function fetchNewQuote() {
  const quoteText = document.getElementById('quoteText');
  const quoteAuthor = document.getElementById('quoteAuthor');
  const quoteTag = document.getElementById('quoteTag');

  if (quoteText) quoteText.style.opacity = '0.2';

  try {
    const res = await fetch('/api/quote/');
    const data = await res.json();
    if (data.status === 'success') {
      setTimeout(() => {
        if (quoteText) {
          quoteText.innerText = `"${data.quote.quote}"`;
          quoteText.style.opacity = '1';
        }
        if (quoteAuthor) quoteAuthor.innerText = `— ${data.quote.author}`;
        if (quoteTag) quoteTag.innerText = data.quote.tag;
      }, 160);
    }
  } catch (e) {
    console.error('Failed to fetch quote', e);
  }
}

// --- Assistant Drawer ---
class AIAssistant {
  constructor() {
    this.panel = document.getElementById('assistantPanel');
    this.backdrop = document.getElementById('assistantBackdrop');
    this.openBtn = document.getElementById('siriFloatBtn');
    this.topBarAiBtn = document.getElementById('topBarAiBtn');
    this.tabAssistantBtn = document.getElementById('tabAssistantBtn');
    this.closeBtn = document.getElementById('assistantCloseBtn');
    this.minimizeBtn = document.getElementById('assistantMinimizeBtn');
    this.maximizeBtn = document.getElementById('assistantMaximizeBtn');
    this.messagesContainer = document.getElementById('assistantMessages');
    this.input = document.getElementById('assistantInput');
    this.sendBtn = document.getElementById('assistantSendBtn');
    this.floatingDock = document.getElementById('aiFloatingDock');
    this.hideDockBtn = document.getElementById('aiDockHideBtn');

    if (this.openBtn) {
      this.openBtn.addEventListener('click', () => this.toggle());
    }
    if (this.topBarAiBtn) {
      this.topBarAiBtn.addEventListener('click', () => this.toggle());
    }
    if (this.tabAssistantBtn) {
      this.tabAssistantBtn.addEventListener('click', () => this.toggle());
    }
    if (this.closeBtn) {
      this.closeBtn.addEventListener('click', () => this.close());
    }
    if (this.minimizeBtn) {
      this.minimizeBtn.addEventListener('click', () => this.minimize());
    }
    if (this.maximizeBtn) {
      this.maximizeBtn.addEventListener('click', () => this.toggleMaximize());
    }
    if (this.backdrop) {
      this.backdrop.addEventListener('click', () => {
        if (this.panel && this.panel.classList.contains('maximized')) {
          this.toggleMaximize();
        } else {
          this.close();
        }
      });
    }
    if (this.sendBtn) {
      this.sendBtn.addEventListener('click', () => this.sendMessage());
    }
    if (this.input) {
      this.input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') this.sendMessage();
      });
    }

    // Floating Dock hide/show persistence
    if (this.hideDockBtn && this.floatingDock) {
      const isDockHidden = localStorage.getItem('ios_ai_dock_hidden') === 'true';
      if (isDockHidden) {
        this.floatingDock.classList.add('is-hidden');
      }

      this.hideDockBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.floatingDock.classList.add('is-hidden');
        localStorage.setItem('ios_ai_dock_hidden', 'true');
      });
    }

    // ESC key closes assistant
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && this.panel && this.panel.classList.contains('open')) {
        if (this.panel.classList.contains('maximized')) {
          this.toggleMaximize();
        } else {
          this.close();
        }
      }
    });

    document.querySelectorAll('.suggestion-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const text = chip.getAttribute('data-prompt') || chip.innerText;
        if (this.input) this.input.value = text;
        this.sendMessage();
      });
    });
  }

  toggle() {
    if (!this.panel) return;
    this.panel.classList.toggle('open');
    if (this.panel.classList.contains('open')) {
      if (this.input) this.input.focus();
      this.scrollToBottom();
    } else {
      if (this.backdrop) this.backdrop.classList.remove('open');
    }
  }

  toggleMaximize() {
    if (!this.panel) return;
    const isMax = this.panel.classList.toggle('maximized');
    if (this.backdrop) {
      this.backdrop.classList.toggle('open', isMax);
    }
    if (this.maximizeBtn) {
      this.maximizeBtn.setAttribute('title', isMax ? 'Restore Window' : 'Maximize Window');
      this.maximizeBtn.innerHTML = isMax
        ? `<svg class="sf-icon sf-icon-xs" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 14 10 14 10 20"></polyline><polyline points="20 10 14 10 14 4"></polyline><line x1="14" y1="10" x2="21" y2="3"></line><line x1="3" y1="21" x2="10" y2="14"></line></svg>`
        : `<svg class="sf-icon sf-icon-xs" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 3 21 3 21 9"></polyline><polyline points="9 21 3 21 3 15"></polyline><line x1="21" y1="3" x2="14" y2="10"></line><line x1="3" y1="21" x2="10" y2="14"></line></svg>`;
    }
    this.scrollToBottom();
  }

  minimize() {
    if (!this.panel) return;
    if (this.panel.classList.contains('maximized')) {
      this.toggleMaximize();
    }
    this.close();
    showiOSToast('Minimized to dock', '−');
  }

  close() {
    if (this.panel) {
      this.panel.classList.remove('open', 'maximized');
    }
    if (this.backdrop) {
      this.backdrop.classList.remove('open');
    }
  }

  scrollToBottom() {
    if (this.messagesContainer) {
      this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
    }
  }

  appendBubble(text, sender = 'user') {
    if (!this.messagesContainer) return;
    const bubble = document.createElement('div');
    bubble.className = `msg-bubble msg-${sender}`;

    let formatted = text
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/\n•/g, '<br>•')
      .replace(/\n\n/g, '<br><br>')
      .replace(/\n/g, '<br>');

    bubble.innerHTML = formatted;
    this.messagesContainer.appendChild(bubble);
    this.scrollToBottom();
  }

  async sendMessage() {
    if (!this.input) return;
    const text = this.input.value.trim();
    if (!text) return;

    this.appendBubble(text, 'user');
    this.input.value = '';

    const typingBubble = document.createElement('div');
    typingBubble.className = 'msg-bubble msg-assistant';
    typingBubble.id = 'typingBubble';
    typingBubble.innerHTML = `
      <div style="display: flex; align-items: center; gap: 8px;">
        <span style="font-size: 12px; color: var(--text-secondary); font-weight: 500;">Habit Intelligence</span>
        <div class="typing-dots">
          <div class="typing-dot"></div>
          <div class="typing-dot"></div>
          <div class="typing-dot"></div>
        </div>
      </div>
    `;
    this.messagesContainer.appendChild(typingBubble);
    this.scrollToBottom();

    // Gather live telemetry & client context for deep AI awareness
    let stopwatchSec = 0;
    let stopwatchFormatted = '00:00:00';
    if (window.habitTimer && typeof window.habitTimer.seconds === 'number') {
      stopwatchSec = window.habitTimer.seconds;
      const h = Math.floor(stopwatchSec / 3600);
      const m = Math.floor((stopwatchSec % 3600) / 60);
      const s = stopwatchSec % 60;
      stopwatchFormatted = `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    } else {
      try {
        const saved = localStorage.getItem('habit_stopwatch_state');
        if (saved) {
          const st = JSON.parse(saved);
          let s = st.accumulated || 0;
          if (st.isRunning && st.startTime) {
            s += Math.floor((Date.now() - st.startTime) / 1000);
          }
          stopwatchSec = s;
          const th = Math.floor(stopwatchSec / 3600);
          const tm = Math.floor((stopwatchSec % 3600) / 60);
          const ts = stopwatchSec % 60;
          stopwatchFormatted = `${th.toString().padStart(2, '0')}:${tm.toString().padStart(2, '0')}:${ts.toString().padStart(2, '0')}`;
        }
      } catch (e) {}
    }

    const clientContext = {
      stopwatch_seconds: stopwatchSec,
      stopwatch_formatted: stopwatchFormatted,
      current_view: localStorage.getItem('habit_schedule_view') || 'grid',
      current_page: window.location.pathname
    };

    try {
      const res = await fetch('/api/chat/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrftoken
        },
        body: JSON.stringify({
          message: text,
          client_context: clientContext
        })
      });
      const data = await res.json();
      typingBubble.remove();

      if (data.status === 'success') {
        this.appendBubble(data.reply, 'assistant');
        iOSAudio.playChime('success');

        if (data.ai_status) {
          const badge = document.getElementById('chatbotModelBadge');
          const badgeText = document.getElementById('chatbotModelBadgeText');
          if (badgeText) badgeText.textContent = data.ai_status.badge_text;
          if (badge) {
            badge.title = `Active Model: ${data.ai_status.model} (${data.ai_status.provider})`;
            badge.className = data.ai_status.is_online ? 'ai-status-pill online' : 'ai-status-pill offline';
          }
        }

        if (data.action_type) {
          this.executeAction(data.action_type, data.payload || {}, data.reply);
        }
      } else {
        this.appendBubble("Sorry, unable to process right now.", 'assistant');
      }
    } catch (e) {
      typingBubble.remove();
      this.appendBubble("Network issue. Please retry.", 'assistant');
      console.error(e);
    }
  }

  executeAction(actionType, payload = {}, reply = '') {
    switch (actionType) {
      case 'switch_view':
        if (payload.view && typeof switchScheduleView === 'function') {
          switchScheduleView(payload.view);
          showiOSToast(`Switched to ${payload.view.toUpperCase()} view`, '🔲');
        } else if (payload.view) {
          localStorage.setItem('habit_schedule_view', payload.view);
          const gridBtn = document.getElementById('viewGridBtn');
          const listBtn = document.getElementById('viewListBtn');
          if (payload.view === 'grid' && gridBtn) gridBtn.click();
          else if (payload.view === 'list' && listBtn) listBtn.click();
        }
        break;

      case 'change_theme':
        if (payload.theme && typeof applyTheme === 'function') {
          applyTheme(payload.theme);
          localStorage.setItem('ios_habit_theme', payload.theme);
          showiOSToast(`Switched to ${payload.theme} mode`, '🌓');
        }
        break;

      case 'control_timer':
        if (payload.action) {
          const timerBtn = document.getElementById('timerToggleBtn');
          const resetBtn = document.getElementById('timerResetBtn');
          if (payload.action === 'start') {
            if (timerBtn && timerBtn.innerText !== 'Pause') timerBtn.click();
            showiOSToast('Stopwatch started', '⏱️');
          } else if (payload.action === 'stop') {
            if (timerBtn && timerBtn.innerText === 'Pause') timerBtn.click();
            showiOSToast('Stopwatch paused', '⏸️');
          } else if (payload.action === 'reset') {
            if (resetBtn) resetBtn.click();
            showiOSToast('Stopwatch reset', '↺');
          }
        }
        break;

      case 'filter_schedule':
        if (payload.filter) {
          const pill = document.querySelector(`.timeline-legend-badges .cat-pill[onclick*="'${payload.filter}'"]`);
          if (pill) {
            pill.click();
          } else if (typeof filterTimeline === 'function') {
            filterTimeline(payload.filter, pill || document.body);
          }
        }
        break;

      case 'log_activity':
        if (payload.reset_stopwatch) {
          if (window.habitTimer && typeof window.habitTimer.reset === 'function') {
            window.habitTimer.reset();
          } else {
            try { localStorage.removeItem('habit_stopwatch_state'); } catch (e) {}
          }
        }
        try {
          sessionStorage.setItem('apple_post_log_event', JSON.stringify({
            hour: payload.hour,
            span_hours: payload.span_hours || 1,
            title: payload.title || 'Activity',
            category_color: payload.category_color || '#0071E3'
          }));
        } catch (e) {}
        showiOSToast(`${payload.title || 'Activity'} logged!`, '✓');
        setTimeout(() => {
          window.location.reload();
        }, 900);
        break;

      case 'delete_activity':
        try {
          sessionStorage.setItem('apple_post_delete_event', JSON.stringify({ hour: payload.hour }));
        } catch (e) {}
        showiOSToast('Hour cleared', '✓');
        setTimeout(() => {
          window.location.reload();
        }, 900);
        break;

      case 'update_profile':
        showiOSToast('Profile & Goal updated', '🎯');
        setTimeout(() => {
          window.location.reload();
        }, 900);
        break;

      case 'navigate':
        if (payload.url) {
          setTimeout(() => {
            window.location.href = payload.url;
          }, 650);
        }
        break;

      case 'set_reminder':
        showiOSToast('Reminder scheduled', '⏰');
        break;

      default:
        break;
    }
  }
}

// --- Reminders Service ---
class ReminderService {
  constructor() {
    this.interval = null;
    this.start();
  }

  start() {
    this.check();
    this.interval = setInterval(() => this.check(), 30000);
  }

  async check() {
    try {
      const res = await fetch('/api/reminders/check/');
      const data = await res.json();
      if (data.status === 'success' && data.due_reminders && data.due_reminders.length > 0) {
        data.due_reminders.forEach(r => {
          iOSAudio.playChime('reminder');
          showiOSToast(`${r.title} (${r.time_display})`, '✓');
          if ("Notification" in window && Notification.permission === "granted") {
            new Notification("Habit Reminder", {
              body: `${r.title} — Time to review your hour!`,
            });
          }
        });
      }
    } catch (e) {}
  }
}

// --- Theme Controller ---
function initTheme() {
  const savedTheme = localStorage.getItem('ios_habit_theme') || 'system';
  applyTheme(savedTheme);

  const toggleBtn = document.getElementById('themeToggleBtn');
  if (toggleBtn) {
    toggleBtn.addEventListener('click', () => {
      const current = document.documentElement.getAttribute('data-theme') || 'light';
      const next = current === 'dark' ? 'light' : 'dark';
      applyTheme(next);
      localStorage.setItem('ios_habit_theme', next);
    });
  }
}

function applyTheme(theme) {
  let effective = theme;
  if (theme === 'system') {
    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    effective = prefersDark ? 'dark' : 'light';
  }
  document.documentElement.setAttribute('data-theme', effective);

  // Smooth Apple SF Symbol morph for Sun/Moon
  const slot = document.querySelector('#themeToggleBtn .theme-icon-slot');
  if (slot) {
    if (effective === 'dark') {
      slot.innerHTML = `<svg class="sf-icon sf-icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>`;
    } else {
      slot.innerHTML = `<svg class="sf-icon sf-icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`;
    }
  }
}

// --- Apple Account Popover Menu ---
function initAccountMenu() {
  const menuWrapper = document.querySelector('.apple-account-menu-wrapper');
  const menuBtn = document.getElementById('accountMenuBtn');
  const popover = document.getElementById('accountPopover');

  if (!menuBtn || !popover) return;

  const togglePopover = (forceState) => {
    const isHidden = typeof forceState === 'boolean' ? !forceState : !popover.hidden;
    popover.hidden = isHidden;
    menuBtn.setAttribute('aria-expanded', String(!isHidden));
    if (menuWrapper) {
      menuWrapper.classList.toggle('active', !isHidden);
    }
  };

  menuBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    togglePopover();
  });

  document.addEventListener('click', (e) => {
    if (!popover.hidden && menuWrapper && !menuWrapper.contains(e.target)) {
      togglePopover(false);
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !popover.hidden) {
      togglePopover(false);
    }
  });
}

// Initialize on DOM Ready
document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  initAccountMenu();
  initTopBarLiveClock();
  initVersionHelpModal();

  const isAuthenticated = !!document.getElementById('currentDateStr') || !!document.querySelector('.ios-nav');
  if (isAuthenticated) {
    window.habitTimer = new HabitTimer();
    window.habitAssistant = new AIAssistant();
    new ReminderService();

    if ("Notification" in window && Notification.permission === "default") {
      setTimeout(() => {
        Notification.requestPermission();
      }, 4000);
    }
  }

  document.querySelectorAll('.category-tile').forEach(tile => {
    tile.addEventListener('click', () => {
      document.querySelectorAll('.category-tile').forEach(t => t.classList.remove('active'));
      tile.classList.add('active');
      selectedCategory = tile.dataset.catId;
    });
  });

  document.querySelectorAll('.segmented-option').forEach(opt => {
    opt.addEventListener('click', () => {
      setModalUnit(opt.dataset.unit);
    });
  });

  document.querySelectorAll('.energy-dot').forEach(dot => {
    dot.addEventListener('click', () => {
      setModalEnergy(parseInt(dot.dataset.level));
    });
  });

  const refreshQuoteBtn = document.getElementById('refreshQuoteBtn');
  if (refreshQuoteBtn) {
    refreshQuoteBtn.addEventListener('click', fetchNewQuote);
  }

  // Escape key closes modals
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeVersionHelpModal();
      if (typeof closeLogModal === 'function') closeLogModal();
    }
  });

  // Trigger Apple fluid post-log animation if an activity was just logged or cleared
  runApplePostLogAnimation();
});

// --- Top Bar Live Digital Clock (iPad / Tablet & Desktop Screens with Timezone Support) ---
function initTopBarLiveClock() {
  const clockContainer = document.getElementById('topBarLiveClock');
  const clockEl = document.getElementById('topBarClockText');
  if (!clockEl) return;

  const userTz = clockContainer ? (clockContainer.dataset.userTz || 'UTC') : 'UTC';

  function updateClock() {
    const now = new Date();
    try {
      const formatter = new Intl.DateTimeFormat('en-US', {
        timeZone: userTz,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: true,
        timeZoneName: 'short'
      });
      clockEl.textContent = formatter.format(now);
    } catch (err) {
      let hours = now.getHours();
      const minutes = String(now.getMinutes()).padStart(2, '0');
      const seconds = String(now.getSeconds()).padStart(2, '0');
      const ampm = hours >= 12 ? 'PM' : 'AM';
      hours = hours % 12 || 12;
      clockEl.textContent = `${String(hours).padStart(2, '0')}:${minutes}:${seconds} ${ampm}`;
    }
  }

  updateClock();
  setInterval(updateClock, 1000);
}

// --- Version & Executive Help Modal (Engineered by Leoxur Inc.) ---
function initVersionHelpModal() {
  const btn = document.getElementById('versionHelpBtn');
  const modal = document.getElementById('versionHelpModal');
  if (!btn || !modal) return;

  btn.addEventListener('click', () => {
    openVersionHelpModal();
  });

  modal.addEventListener('click', (e) => {
    if (e.target === modal) {
      closeVersionHelpModal();
    }
  });

  const tabBtns = modal.querySelectorAll('.version-tab-btn');
  tabBtns.forEach(tabBtn => {
    tabBtn.addEventListener('click', () => {
      const targetId = tabBtn.dataset.tab;
      tabBtns.forEach(b => b.classList.remove('active'));
      tabBtn.classList.add('active');

      modal.querySelectorAll('.version-tab-panel').forEach(panel => {
        panel.classList.remove('active');
      });
      const activePanel = document.getElementById(targetId);
      if (activePanel) activePanel.classList.add('active');
    });
  });
}

function openVersionHelpModal() {
  const modal = document.getElementById('versionHelpModal');
  if (modal) {
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
  }
}

function closeVersionHelpModal() {
  const modal = document.getElementById('versionHelpModal');
  if (modal) {
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
  }
}

window.openVersionHelpModal = openVersionHelpModal;
window.closeVersionHelpModal = closeVersionHelpModal;

// --- Apple Post-Log Fluid Animation Runner ---
function runApplePostLogAnimation() {
  // Check for delete event
  try {
    const delRaw = sessionStorage.getItem('apple_post_delete_event');
    if (delRaw) {
      sessionStorage.removeItem('apple_post_delete_event');
      showiOSToast('Cleared activity slot', '✓');
      return;
    }
  } catch (e) {}

  let eventData = null;
  try {
    const raw = sessionStorage.getItem('apple_post_log_event');
    if (raw) {
      eventData = JSON.parse(raw);
      sessionStorage.removeItem('apple_post_log_event');
    }
  } catch (e) {
    return;
  }

  if (!eventData) return;

  const startHour = eventData.hour;
  const spanH = eventData.span_hours || 1;
  const color = eventData.category_color || 'var(--apple-blue)';
  const title = eventData.title || 'Saved';

  // Smooth scroll target card into view if needed
  const targetCard = document.querySelector(`.grid-hour-card[data-hour="${startHour}"]`) ||
                     document.querySelector(`.hour-row[data-hour="${startHour}"]`);
  if (targetCard && targetCard.offsetParent !== null) {
    targetCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  // Animate all hours covered by this activity (start + spanned cascade)
  for (let h = startHour; h < Math.min(24, startHour + spanH); h++) {
    const delay = (h - startHour) * 70; // Wave cascade across cards!
    setTimeout(() => {
      const cards = document.querySelectorAll(`[data-hour="${h}"]`);
      cards.forEach(card => {
        card.style.setProperty('--card-accent', color);
        card.classList.add('apple-post-log-animate');

        // Animate proportional fill expanding smoothly from 0
        const fill = card.querySelector('.grid-card-fill, .row-card-fill');
        if (fill) {
          const finalWidth = fill.style.width || '100%';
          fill.style.width = '0%';
          fill.style.transition = 'width 0.85s cubic-bezier(0.16, 1, 0.3, 1), background 0.3s ease';
          requestAnimationFrame(() => {
            fill.style.width = finalWidth;
          });
        }

        // Shimmer beam sweep
        const beam = document.createElement('div');
        beam.className = 'apple-shimmer-beam';
        card.appendChild(beam);

        // Floating Apple badge on the primary hour card
        if (h === startHour && card.classList.contains('grid-hour-card')) {
          const badge = document.createElement('div');
          badge.className = 'apple-saved-badge';
          badge.innerHTML = `<span>✓</span> <span>${title}</span>`;
          card.appendChild(badge);
          setTimeout(() => badge.remove(), 1400);
        }

        setTimeout(() => {
          card.classList.remove('apple-post-log-animate');
          if (beam.parentElement) beam.remove();
        }, 1200);
      });
    }, delay);
  }

  showiOSToast(`${title} logged`, '✓');
}
