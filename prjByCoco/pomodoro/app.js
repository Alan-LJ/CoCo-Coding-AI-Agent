const PHASES = {
  work: { label: '专注中' },
  short: { label: '短休息' },
  long: { label: '长休息' },
};

const RING_CIRCUMFERENCE = 2 * Math.PI * 120;
const SETTINGS_KEY = 'pomodoro-settings';

const els = {
  body: document.body,
  phaseLabel: document.getElementById('phase-label'),
  timeDisplay: document.getElementById('time-display'),
  ringProgress: document.getElementById('ring-progress'),
  dots: document.querySelectorAll('#cycle-dots .dot'),
  taskInput: document.getElementById('task-input'),
  startBtn: document.getElementById('start-btn'),
  resetBtn: document.getElementById('reset-btn'),
  skipBtn: document.getElementById('skip-btn'),
  settingsBtn: document.getElementById('settings-btn'),
  settingsPanel: document.getElementById('settings-panel'),
  setWork: document.getElementById('set-work'),
  setShort: document.getElementById('set-short'),
  setLong: document.getElementById('set-long'),
  setNotify: document.getElementById('set-notify'),
  settingsSave: document.getElementById('settings-save'),
  settingsCancel: document.getElementById('settings-cancel'),
};

let settings = loadSettings();
let phase = 'work';
let totalSeconds = settings.work * 60;
let remainingSeconds = totalSeconds;
let completedPomodoros = 0;
let running = false;
let endTime = null;
let timerId = null;

function loadSettings() {
  try {
    const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY));
    if (saved && saved.work > 0 && saved.short > 0 && saved.long > 0) {
      return { notify: false, ...saved };
    }
  } catch (e) {
    // 忽略损坏的本地数据
  }
  return { work: 25, short: 5, long: 15, notify: false };
}

function saveSettings() {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

function phaseDuration(name) {
  return settings[name] * 60;
}

function formatTime(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function render() {
  els.body.dataset.phase = phase;
  els.phaseLabel.textContent = PHASES[phase].label;
  els.timeDisplay.textContent = formatTime(remainingSeconds);
  els.startBtn.textContent = running ? '暂停' : '开始';

  const progress = totalSeconds > 0 ? remainingSeconds / totalSeconds : 0;
  els.ringProgress.style.strokeDashoffset = String(RING_CIRCUMFERENCE * (1 - progress));

  const filled = completedPomodoros % 4;
  els.dots.forEach((dot, i) => dot.classList.toggle('filled', i < filled));

  document.title = `${formatTime(remainingSeconds)} ${PHASES[phase].label} - 番茄钟`;
}

function tick() {
  remainingSeconds = Math.max(0, Math.round((endTime - Date.now()) / 1000));
  render();
  if (remainingSeconds <= 0) {
    completePhase();
  }
}

function start() {
  running = true;
  endTime = Date.now() + remainingSeconds * 1000;
  timerId = setInterval(tick, 250);
  render();
}

function pause() {
  running = false;
  clearInterval(timerId);
  render();
}

function switchPhase(next, autoStart) {
  phase = next;
  totalSeconds = phaseDuration(next);
  remainingSeconds = totalSeconds;
  pause();
  if (autoStart) start();
  else render();
}

function completePhase() {
  clearInterval(timerId);
  running = false;
  playBeep();
  notify();
  flashRing();

  let next;
  if (phase === 'work') {
    completedPomodoros += 1;
    next = completedPomodoros % 4 === 0 ? 'long' : 'short';
  } else {
    next = 'work';
  }
  switchPhase(next, true);
}

function playBeep() {
  const AudioContext = window.AudioContext || window.webkitAudioContext;
  if (!AudioContext) return;
  const ctx = new AudioContext();
  for (let i = 0; i < 3; i++) {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.frequency.value = 880;
    const t = ctx.currentTime + i * 0.4;
    gain.gain.setValueAtTime(0.3, t);
    gain.gain.exponentialRampToValueAtTime(0.001, t + 0.3);
    osc.start(t);
    osc.stop(t + 0.3);
  }
}

function notify() {
  if (!settings.notify || !('Notification' in window) || Notification.permission !== 'granted') {
    return;
  }
  const text = phase === 'work' ? '专注结束，休息一下吧！' : '休息结束，开始下一个番茄！';
  new Notification('番茄钟', { body: text });
}

function flashRing() {
  els.body.classList.add('flash');
  setTimeout(() => els.body.classList.remove('flash'), 1600);
}

els.startBtn.addEventListener('click', () => {
  if (running) pause();
  else start();
});

els.resetBtn.addEventListener('click', () => {
  pause();
  totalSeconds = phaseDuration(phase);
  remainingSeconds = totalSeconds;
  render();
});

els.skipBtn.addEventListener('click', () => {
  const next = phase === 'work'
    ? (completedPomodoros + 1) % 4 === 0 ? 'long' : 'short'
    : 'work';
  if (phase === 'work') completedPomodoros += 1;
  switchPhase(next, false);
});

els.settingsBtn.addEventListener('click', () => {
  els.setWork.value = settings.work;
  els.setShort.value = settings.short;
  els.setLong.value = settings.long;
  els.setNotify.checked = settings.notify;
  els.settingsPanel.classList.remove('hidden');
});

els.settingsCancel.addEventListener('click', () => {
  els.settingsPanel.classList.add('hidden');
});

els.settingsSave.addEventListener('click', () => {
  const next = {
    work: Number(els.setWork.value),
    short: Number(els.setShort.value),
    long: Number(els.setLong.value),
    notify: els.setNotify.checked,
  };
  if (!(next.work > 0 && next.short > 0 && next.long > 0)) return;

  settings = next;
  saveSettings();

  if (settings.notify && 'Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission();
  }

  if (!running) {
    totalSeconds = phaseDuration(phase);
    remainingSeconds = totalSeconds;
  }
  els.settingsPanel.classList.add('hidden');
  render();
});

document.addEventListener('keydown', (e) => {
  if (e.code === 'Space' && e.target.tagName !== 'INPUT') {
    e.preventDefault();
    if (running) pause();
    else start();
  }
});

els.ringProgress.style.strokeDasharray = String(RING_CIRCUMFERENCE);
render();
