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
const layoutStorageKey = 'english-audio-reader-layout';
const speedValues = Array.from(speedSelect.options, (option) => Number(option.value));
let data;
let activeIndex = -1;
let selectedIndex = 0;
let sentenceElements = [];
let chapterElements = new Map();
let rafId;
let toastTimer;

function saveLayoutState() {
  try {
    localStorage.setItem(layoutStorageKey, JSON.stringify({
      sidebarCollapsed: document.body.classList.contains('sidebar-collapsed'),
      playerCollapsed: document.body.classList.contains('player-collapsed'),
    }));
  } catch (error) {
    console.warn('Could not save layout state', error);
  }
}

function updatePanelHandle(handle, collapsed, collapsedIcon, expandedIcon, panelName) {
  const label = `${collapsed ? '展开' : '收起'}${panelName}`;
  handle.setAttribute('aria-expanded', String(!collapsed));
  handle.title = label;
  handle.querySelector('[aria-hidden="true"]').textContent = collapsed ? expandedIcon : collapsedIcon;
  handle.querySelector('.sr-only').textContent = label;
}

function setSidebarCollapsed(collapsed, persist = true) {
  document.body.classList.toggle('sidebar-collapsed', collapsed);
  sidebar.inert = collapsed;
  sidebar.setAttribute('aria-hidden', String(collapsed));
  updatePanelHandle(sidebarHandle, collapsed, '‹', '›', '章节栏');
  if (persist) saveLayoutState();
}

function setPlayerCollapsed(collapsed, persist = true) {
  document.body.classList.toggle('player-collapsed', collapsed);
  player.inert = collapsed;
  player.setAttribute('aria-hidden', String(collapsed));
  updatePanelHandle(playerHandle, collapsed, '⌄', '⌃', '播放栏');
  if (persist) saveLayoutState();
}

function restoreLayoutState() {
  let state = {};
  try {
    state = JSON.parse(localStorage.getItem(layoutStorageKey) || '{}');
  } catch (error) {
    console.warn('Could not restore layout state', error);
  }
  setSidebarCollapsed(Boolean(state.sidebarCollapsed), false);
  setPlayerCollapsed(Boolean(state.playerCollapsed), false);
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

function togglePlayback() {
  if (audio.paused) audio.play().catch(console.error);
  else audio.pause();
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

function render() {
  $('#title').textContent = data.title;
  $('#brandTitle').textContent = data.title;
  $('#sentenceCount').textContent = `${data.sentences.length.toLocaleString()} sentences`;
  $('#alignmentStatus').textContent = data.alignment.display ||
    `Alignment ${Math.round((data.alignment.exactTokenMatchRate || 0) * 100)}% · ${data.alignment.lowConfidenceSentences} to review`;

  const grouped = new Map(data.chapters.map((chapter) => [chapter.id, []]));
  data.sentences.forEach((sentence, index) => grouped.get(sentence.chapterId)?.push({ sentence, index }));

  for (const [chapterIndex, chapter] of data.chapters.entries()) {
    const navButton = document.createElement('button');
    navButton.className = 'chapter-link';
    navButton.dataset.chapterLink = chapter.id;
    navButton.innerHTML = `<span class="chapter-number">${String(chapterIndex + 1).padStart(2, '0')}</span><span class="chapter-name"></span>`;
    navButton.querySelector('.chapter-name').textContent = chapter.title;
    navButton.addEventListener('click', () => {
      chapterElements.get(chapter.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      const first = grouped.get(chapter.id)?.[0];
      if (first) selectedIndex = first.index;
    });
    $('#chapterNav').append(navButton);

    const section = document.createElement('section');
    section.className = 'chapter';
    section.id = chapter.id;
    section.innerHTML = '<h2></h2><div class="chapter-copy"></div>';
    section.querySelector('h2').textContent = chapter.title;
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

  audio = data.mediaType === 'video' ? mediaVideo : audioFallback;
  audio.src = data.mediaUrl || data.audioUrl;
  $('#mediaStage').hidden = data.mediaType !== 'video';
  $('#loading').hidden = true;
  $('#app').hidden = false;
  player.hidden = false;
  playerHandle.hidden = false;
}

async function init() {
  try {
    const response = await fetch('data/reader.json?v=1');
    if (!response.ok) throw new Error(`reader.json: HTTP ${response.status}`);
    data = await response.json();
    render();
  } catch (error) {
    $('#loading').classList.add('error');
    $('#loading').textContent = `载入失败：${error.message}。请确认生成流程完成，并通过本地服务器打开页面。`;
  }
}

playButton.addEventListener('click', togglePlayback);
mediaElements.forEach((element) => {
  element.addEventListener('play', () => {
    playButton.textContent = '❚❚';
    playButton.setAttribute('aria-label', '暂停');
    playButton.title = '播放/暂停（空格或 K）';
    cancelAnimationFrame(rafId);
    update();
  });
  element.addEventListener('pause', () => {
    playButton.textContent = '▶';
    playButton.setAttribute('aria-label', '播放');
    playButton.title = '播放/暂停（空格或 K）';
    cancelAnimationFrame(rafId);
    update();
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

restoreLayoutState();
init();
