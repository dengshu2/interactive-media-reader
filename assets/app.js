const $ = (selector) => document.querySelector(selector);
const mediaVideo = $('#media');
const audioFallback = $('#audioFallback');
const mediaElements = [mediaVideo, audioFallback];
let audio = audioFallback;
const seek = $('#seek');
const playButton = $('#play');
const shortcutDialog = $('#shortcutDialog');
const speedSelect = $('#speed');
const sidebar = $('#sidebar');
const player = $('#player');
const sidebarHandle = $('#sidebarHandle');
const playerHandle = $('#playerHandle');
const compactLayoutQuery = window.matchMedia('(max-width: 900px)');
const layoutStorageKey = `imr-layout-v2:${window.location.pathname}`;
const themeStorageKey = 'imr-theme';
const fontStorageKey = 'imr-font-size';
const fontSizes = [16, 17.5, 19, 20.5, 22];
const speedValues = Array.from(speedSelect.options, (option) => Number(option.value));
let data;
let activeIndex = -1;
let selectedIndex = 0;
let sentenceElements = [];
let chapterElements = new Map();
let rafId;
let toastTimer;
let fontIndex = 2;
let lastProgressSave = 0;
let lastProgressLabel = '';
let measuredPlayerHeight = 0;

function readLayoutState() {
  try {
    const value = JSON.parse(localStorage.getItem(layoutStorageKey) || '{}');
    return value && typeof value === 'object' ? value : {};
  } catch (error) {
    console.warn('Could not read layout state', error);
    return {};
  }
}

function layoutMode() {
  return compactLayoutQuery.matches ? 'compact' : 'desktop';
}

function saveLayoutState() {
  try {
    const state = readLayoutState();
    state[layoutMode()] = {
      sidebarCollapsed: document.body.classList.contains('sidebar-collapsed'),
      playerCollapsed: document.body.classList.contains('player-collapsed'),
    };
    localStorage.setItem(layoutStorageKey, JSON.stringify(state));
  } catch (error) {
    console.warn('Could not save layout state', error);
  }
}

function updatePanelHandle(handle, collapsed, panelName) {
  const label = `${collapsed ? '展开' : '收起'}${panelName}`;
  handle.setAttribute('aria-expanded', String(!collapsed));
  handle.title = label;
  handle.querySelector('.sr-only').textContent = label;
}

function setSidebarCollapsed(collapsed, persist = true) {
  document.body.classList.toggle('sidebar-collapsed', collapsed);
  sidebar.inert = collapsed;
  sidebar.setAttribute('aria-hidden', String(collapsed));
  updatePanelHandle(sidebarHandle, collapsed, '章节栏');
  if (persist) saveLayoutState();
}

function setPlayerCollapsed(collapsed, persist = true) {
  document.body.classList.toggle('player-collapsed', collapsed);
  player.inert = collapsed;
  player.setAttribute('aria-hidden', String(collapsed));
  updatePanelHandle(playerHandle, collapsed, '播放栏');
  if (persist) saveLayoutState();
}

function restoreLayoutState() {
  const state = readLayoutState()[layoutMode()] || {};
  setSidebarCollapsed(Boolean(state.sidebarCollapsed), false);
  setPlayerCollapsed(Boolean(state.playerCollapsed), false);
}

function updatePlayerHeight() {
  if (player.hidden) return;
  const height = Math.ceil(player.getBoundingClientRect().height);
  if (height > 0 && height !== measuredPlayerHeight) {
    measuredPlayerHeight = height;
    document.documentElement.style.setProperty('--player-height', `${height}px`);
  }
}

function formatTime(seconds) {
  if (!Number.isFinite(seconds)) return '00:00';
  const value = Math.max(0, Math.floor(seconds));
  const h = Math.floor(value / 3600);
  const m = Math.floor((value % 3600) / 60);
  const s = value % 60;
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`;
}

function findSentenceIndex(time) {
  if (time < data.sentences[0].start - 0.03) return -1;
  let low = 0;
  let high = data.sentences.length - 1;
  let answer = 0;
  while (low <= high) {
    const middle = (low + high) >> 1;
    if (data.sentences[middle].start <= time + 0.03) {
      answer = middle;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  const sentence = data.sentences[answer];
  const following = data.sentences[answer + 1];
  if (time > sentence.end + 0.35 && (!following || time < following.start - 0.03)) return -1;
  return answer;
}

function setActive(index) {
  if (index === activeIndex) return;
  const previousElement = sentenceElements[activeIndex];
  previousElement?.classList.remove('active');
  if (index < 0) {
    activeIndex = -1;
    return;
  }
  if (previousElement) previousElement.tabIndex = -1;
  activeIndex = index;
  selectedIndex = index;
  const element = sentenceElements[index];
  if (element) {
    element.classList.add('active');
    element.tabIndex = 0;
  }

  const sentence = data.sentences[index];
  document.querySelectorAll('.chapter-link.active').forEach((item) => item.classList.remove('active'));
  document.querySelector(`[data-chapter-link="${sentence.chapterId}"]`)?.classList.add('active');

  if ($('#autoScroll').checked && !audio.paused && element) {
    const rect = element.getBoundingClientRect();
    if (rect.top < 100 || rect.bottom > window.innerHeight - 170) {
      element.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }
}

function update() {
  const duration = audio.duration || data.duration || 0;
  const current = audio.currentTime || 0;
  seek.max = duration;
  if (!seek.matches(':active')) seek.value = current;
  $('#time').textContent = `${formatTime(current)} / ${formatTime(duration)}`;

  if (!audio.paused && Math.abs(current - lastProgressSave) >= 5) saveProgress(current);
  const progressText = duration
    ? `已听 ${Math.min(100, Math.round((current / duration) * 100))}% · ${formatTime(current)}`
    : '';
  if (progressText !== lastProgressLabel) {
    lastProgressLabel = progressText;
    $('#listenProgress').textContent = progressText;
  }

  if ($('#repeat').checked && activeIndex >= 0) {
    const sentence = data.sentences[activeIndex];
    if (current >= sentence.end) {
      audio.currentTime = sentence.start;
      if (!audio.paused) rafId = requestAnimationFrame(update);
      return;
    }
  }
  setActive(findSentenceIndex(current));
  if (!audio.paused) rafId = requestAnimationFrame(update);
}

async function togglePlayback() {
  if (!audio.paused && !audio.ended) {
    audio.pause();
    setPlayIcon(false);
    return;
  }
  if (audio.ended) audio.currentTime = 0;
  try {
    await audio.play();
    setPlayIcon(!audio.paused && !audio.ended);
  } catch (error) {
    setPlayIcon(false);
    console.error(error);
  }
}

function showToast(message) {
  const toast = $('#toast');
  clearTimeout(toastTimer);
  toast.textContent = message;
  toast.hidden = false;
  toastTimer = setTimeout(() => { toast.hidden = true; }, 1500);
}

function seekAudio(offset, notify = false) {
  const duration = audio.duration || data?.duration || 0;
  audio.currentTime = Math.max(0, Math.min(duration, audio.currentTime + offset));
  if (notify) showToast(offset < 0 ? '后退 5 秒' : '前进 5 秒');
}

function setSpeed(value, notify = true) {
  const speed = speedValues.reduce((best, item) => Math.abs(item - value) < Math.abs(best - value) ? item : best);
  audio.playbackRate = speed;
  speedSelect.value = String(speed);
  if (notify) showToast(`播放速度：${speed}×`);
}

function changeSpeed(direction) {
  const currentIndex = speedValues.indexOf(Number(speedSelect.value));
  const nextIndex = Math.max(0, Math.min(speedValues.length - 1, currentIndex + direction));
  setSpeed(speedValues[nextIndex]);
}

function toggleOption(selector, label) {
  const input = $(selector);
  input.checked = !input.checked;
  showToast(`${label}：${input.checked ? '已开启' : '已关闭'}`);
}

function playSentence(index, focus = false) {
  if (!data?.sentences?.length) return;
  const safeIndex = Math.max(0, Math.min(data.sentences.length - 1, index));
  const sentence = data.sentences[safeIndex];
  selectedIndex = safeIndex;
  audio.currentTime = Math.max(0, sentence.start - 0.06);
  audio.play().catch(console.error);
  setActive(safeIndex);
  if (focus) sentenceElements[safeIndex]?.focus({ preventScroll: true });
}

function moveSentence(delta, focus = false) {
  playSentence(selectedIndex + delta, focus);
}

const themeQuery = window.matchMedia('(prefers-color-scheme: dark)');

function storedTheme() {
  try {
    return localStorage.getItem(themeStorageKey);
  } catch (error) {
    return null;
  }
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $('#iconMoon').hidden = theme === 'dark';
  $('#iconSun').hidden = theme !== 'dark';
  document.querySelector('meta[name="theme-color"]')
    .setAttribute('content', theme === 'dark' ? '#161c23' : '#f4efe4');
}

function applyFontSize(size, notify = false) {
  document.body.style.setProperty('--copy-size', `${size}px`);
  if (notify) showToast(`正文字号 ${size}px`);
}

function changeFontSize(direction) {
  const next = Math.max(0, Math.min(fontSizes.length - 1, fontIndex + direction));
  if (next === fontIndex) {
    showToast(direction > 0 ? '已是最大字号' : '已是最小字号');
    return;
  }
  fontIndex = next;
  applyFontSize(fontSizes[fontIndex], true);
  try {
    localStorage.setItem(fontStorageKey, String(fontSizes[fontIndex]));
  } catch (error) {
    console.warn('Could not save font size', error);
  }
}

function progressKey() {
  return `imr-progress:${data.title}:${Math.round(data.duration || 0)}`;
}

function saveProgress(current) {
  lastProgressSave = current;
  try {
    localStorage.setItem(progressKey(), JSON.stringify({ t: Math.round(current * 100) / 100, at: Date.now() }));
  } catch (error) {
    console.warn('Could not save progress', error);
  }
}

function restoreProgress() {
  let saved = null;
  try {
    saved = JSON.parse(localStorage.getItem(progressKey()) || 'null');
  } catch (error) {
    saved = null;
  }
  const duration = audio.duration || data.duration || 0;
  if (!saved || !(saved.t > 20) || saved.t > duration - 20) return;
  audio.currentTime = saved.t;
  lastProgressSave = saved.t;
  setActive(findSentenceIndex(saved.t));
  update();
  showToast(`已恢复到上次位置 ${formatTime(saved.t)}`);
}

function render() {
  document.title = `${data.title} · Interactive Media Reader`;
  $('#title').textContent = data.title;
  $('#brandTitle').textContent = data.title;
  $('#heroMeta').textContent = [
    formatTime(data.duration),
    `${data.chapters.length} 章`,
    `${data.sentences.length.toLocaleString()} 句`,
    (data.sourceLanguage || '').toUpperCase(),
  ].filter(Boolean).join(' · ');
  $('#sentenceCount').textContent = `${data.sentences.length.toLocaleString()} 句`;
  $('#alignmentStatus').textContent = data.alignment.display ||
    `Alignment ${Math.round((data.alignment.exactTokenMatchRate || 0) * 100)}% · ${data.alignment.lowConfidenceSentences} to review`;

  const grouped = new Map(data.chapters.map((chapter) => [chapter.id, []]));
  data.sentences.forEach((sentence, index) => grouped.get(sentence.chapterId)?.push({ sentence, index }));

  for (const [chapterIndex, chapter] of data.chapters.entries()) {
    const navButton = document.createElement('button');
    navButton.className = 'chapter-link';
    navButton.dataset.chapterLink = chapter.id;
    navButton.innerHTML = `<span class="chapter-number">${String(chapterIndex + 1).padStart(2, '0')}</span><span class="chapter-body"><span class="chapter-name"></span><span class="chapter-time"></span></span>`;
    navButton.querySelector('.chapter-name').textContent = chapter.title;
    navButton.querySelector('.chapter-time').textContent = formatTime(chapter.start);
    navButton.addEventListener('click', () => {
      chapterElements.get(chapter.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      const first = grouped.get(chapter.id)?.[0];
      if (first) selectedIndex = first.index;
    });
    $('#chapterNav').append(navButton);

    const section = document.createElement('section');
    section.className = 'chapter';
    section.id = chapter.id;
    section.innerHTML = '<h2></h2><p class="chapter-meta"></p><div class="chapter-copy"></div>';
    section.querySelector('h2').textContent = chapter.title;
    const chapterEnd = data.chapters[chapterIndex + 1]?.start ?? (data.duration || chapter.start);
    section.querySelector('.chapter-meta').textContent =
      `${formatTime(chapter.start)} 起 · 时长 ${formatTime(Math.max(0, chapterEnd - chapter.start))} · ${chapter.sentenceCount} 句`;
    chapterElements.set(chapter.id, section);
    const copy = section.querySelector('.chapter-copy');
    let paragraph;
    let previousSentence;
    let paragraphSize = 0;

    for (const { sentence, index } of grouped.get(chapter.id) || []) {
      const hasLongPause = previousSentence && sentence.start - previousSentence.end > 1.35;
      if (!paragraph || hasLongPause || paragraphSize >= 8) {
        paragraph = document.createElement('p');
        copy.append(paragraph);
        paragraphSize = 0;
      }
      const span = document.createElement('span');
      span.className = `sentence${sentence.confidence < 0.65 ? ' low-confidence' : ''}`;
      span.dataset.index = index;
      span.textContent = sentence.text;
      span.tabIndex = index === 0 ? 0 : -1;
      span.setAttribute('role', 'button');
      span.setAttribute('aria-label', `从这里播放：${sentence.text}`);
      span.title = `${formatTime(sentence.start)} · 识别置信度 ${Math.round(sentence.confidence * 100)}%`;
      span.addEventListener('click', () => playSentence(index));
      span.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          playSentence(index);
        }
      });
      sentenceElements[index] = span;
      paragraph.append(span, ' ');
      previousSentence = sentence;
      paragraphSize += 1;
    }
    $('#reader').append(section);
  }

  const totalDuration = data.duration || 0;
  if (totalDuration > 0) {
    for (const chapter of data.chapters.slice(1)) {
      const tick = document.createElement('span');
      tick.className = 'seek-tick';
      tick.style.left = `${(chapter.start / totalDuration) * 100}%`;
      $('#seekTicks').append(tick);
    }
  }

  audio = data.mediaType === 'video' ? mediaVideo : audioFallback;
  audio.src = data.mediaUrl || data.audioUrl;
  setPlayIcon(false);
  audio.addEventListener('loadedmetadata', restoreProgress, { once: true });
  $('#mediaStage').hidden = data.mediaType !== 'video';
  $('#loading').hidden = true;
  $('#app').hidden = false;
  player.hidden = false;
  playerHandle.hidden = false;
  requestAnimationFrame(updatePlayerHeight);
}

async function init() {
  try {
    const response = await fetch('data/reader.json?v=3');
    if (!response.ok) throw new Error(`reader.json: HTTP ${response.status}`);
    data = await response.json();
    render();
  } catch (error) {
    $('#loading').classList.add('error');
    $('#loading').textContent = `载入失败：${error.message}。请确认生成流程完成，并通过本地服务器打开页面。`;
  }
}

function setPlayIcon(playing) {
  playButton.classList.toggle('is-playing', playing);
  playButton.dataset.state = playing ? 'playing' : 'paused';
  playButton.setAttribute('aria-label', playing ? '暂停' : '播放');
  playButton.title = `${playing ? '暂停' : '播放'}（空格或 K）`;
}

playButton.addEventListener('click', togglePlayback);
mediaElements.forEach((element) => {
  const syncPlaying = () => {
    if (element !== audio) return;
    setPlayIcon(!element.paused && !element.ended);
    cancelAnimationFrame(rafId);
    update();
  };
  const syncPaused = () => {
    if (element !== audio) return;
    setPlayIcon(false);
    if (data) saveProgress(audio.currentTime);
    cancelAnimationFrame(rafId);
    update();
  };
  element.addEventListener('play', syncPlaying);
  element.addEventListener('playing', syncPlaying);
  element.addEventListener('pause', syncPaused);
  element.addEventListener('ended', syncPaused);
  element.addEventListener('emptied', () => {
    if (element === audio) setPlayIcon(false);
  });
  element.addEventListener('loadedmetadata', update);
  element.addEventListener('seeked', update);
});
seek.addEventListener('input', () => { audio.currentTime = Number(seek.value); update(); });
$('#previous').addEventListener('click', () => moveSentence(-1));
$('#next').addEventListener('click', () => moveSentence(1));
$('#back').addEventListener('click', () => seekAudio(-5));
$('#forward').addEventListener('click', () => seekAudio(5));
speedSelect.addEventListener('change', (event) => setSpeed(Number(event.target.value)));
$('#repeat').addEventListener('change', (event) => showToast(`循环当前句：${event.target.checked ? '已开启' : '已关闭'}`));
$('#autoScroll').addEventListener('change', (event) => showToast(`自动跟随：${event.target.checked ? '已开启' : '已关闭'}`));

sidebarHandle.addEventListener('click', () => {
  setSidebarCollapsed(!document.body.classList.contains('sidebar-collapsed'));
});
playerHandle.addEventListener('click', () => {
  setPlayerCollapsed(!document.body.classList.contains('player-collapsed'));
});

$('#shortcuts').addEventListener('click', () => shortcutDialog.showModal());
$('#closeShortcuts').addEventListener('click', () => shortcutDialog.close());
shortcutDialog.addEventListener('click', (event) => {
  if (event.target === shortcutDialog) shortcutDialog.close();
});

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && shortcutDialog.open) {
    event.preventDefault();
    shortcutDialog.close();
    return;
  }
  if (event.isComposing || event.metaKey || event.ctrlKey || event.altKey) return;

  const target = event.target;
  if (target.closest('input, textarea, select, button, [contenteditable="true"]')) return;
  if (target.closest('[role="button"]') && (event.code === 'Space' || event.key === 'Enter')) return;

  const wantsHelp = event.key === '?' || (event.code === 'Slash' && event.shiftKey);
  if (wantsHelp) {
    event.preventDefault();
    if (!shortcutDialog.open) shortcutDialog.showModal();
    return;
  }
  if (!data) return;

  let handled = true;
  switch (event.code) {
    case 'Space':
    case 'KeyK':
      togglePlayback();
      break;
    case 'ArrowLeft':
      if (event.shiftKey) moveSentence(-1, true);
      else seekAudio(-5, true);
      break;
    case 'ArrowRight':
      if (event.shiftKey) moveSentence(1, true);
      else seekAudio(5, true);
      break;
    case 'KeyR':
      toggleOption('#repeat', '循环当前句');
      break;
    case 'KeyA':
      toggleOption('#autoScroll', '自动跟随');
      break;
    case 'Minus':
    case 'NumpadSubtract':
      changeSpeed(-1);
      break;
    case 'Equal':
    case 'NumpadAdd':
      changeSpeed(1);
      break;
    case 'Digit0':
    case 'Numpad0':
      setSpeed(1);
      break;
    default:
      handled = false;
  }
  if (handled) event.preventDefault();
});

applyTheme(storedTheme() || (themeQuery.matches ? 'dark' : 'light'));
themeQuery.addEventListener('change', (event) => {
  if (!storedTheme()) applyTheme(event.matches ? 'dark' : 'light');
});
$('#themeToggle').addEventListener('click', () => {
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  try {
    localStorage.setItem(themeStorageKey, next);
  } catch (error) {
    console.warn('Could not save theme', error);
  }
  applyTheme(next);
  showToast(next === 'dark' ? '已切换到深色模式' : '已切换到浅色模式');
});

try {
  const savedFontSize = Number(localStorage.getItem(fontStorageKey));
  if (fontSizes.includes(savedFontSize)) fontIndex = fontSizes.indexOf(savedFontSize);
} catch (error) {
  console.warn('Could not restore font size', error);
}
if (fontIndex !== 2) applyFontSize(fontSizes[fontIndex]);
$('#fontSmaller').addEventListener('click', () => changeFontSize(-1));
$('#fontLarger').addEventListener('click', () => changeFontSize(1));

seek.addEventListener('pointermove', (event) => {
  const duration = audio.duration || data?.duration || 0;
  if (!duration) return;
  const rect = seek.getBoundingClientRect();
  const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
  const bubble = $('#seekBubble');
  bubble.hidden = false;
  bubble.style.left = `${ratio * 100}%`;
  bubble.textContent = formatTime(ratio * duration);
});
seek.addEventListener('pointerleave', () => { $('#seekBubble').hidden = true; });

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden' && data) saveProgress(audio.currentTime);
});
window.addEventListener('pagehide', () => {
  if (data) saveProgress(audio.currentTime);
});
window.addEventListener('resize', updatePlayerHeight);
compactLayoutQuery.addEventListener('change', () => {
  restoreLayoutState();
  requestAnimationFrame(updatePlayerHeight);
});
if ('ResizeObserver' in window) {
  new ResizeObserver(updatePlayerHeight).observe(player);
}

restoreLayoutState();
init();
